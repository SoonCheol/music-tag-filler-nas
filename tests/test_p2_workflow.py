"""P2 tests use generated audio and isolated runtime paths only."""
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.parse
import urllib.error
from fastapi import BackgroundTasks, HTTPException
import test_p0_storage as p0
from app import main, storage, preferences, job_service, search_service


class P2Tests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    http = p0.P0Tests.http

    def raw_http(self, route, data=None, method="GET", expected=200):
        request = urllib.request.Request("http://127.0.0.1:" + str(self.port) + route,
                                         data=data, method=method,
                                         headers={"Content-Type": "application/octet-stream"})
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            response = exc
        self.assertEqual(response.code, expected)
        with response:
            return response.read()

    def test_multipath_dedup_nonrecursive_case_and_escape(self):
        first = self.copy("Album/A.MP3")
        child = self.copy("Album/Nested/b.flac")
        self.assertEqual(job_service.collect(self.root, ["Album", "Album/A.MP3"], False), [first])
        self.assertEqual(set(job_service.collect(self.root, ["Album", "Album/Nested"], True)), {first, child})
        (self.root / "Album/ignore.wav").write_bytes(b"unsupported")
        self.assertEqual(len(job_service.collect(self.root, ["Album"])), 2)
        for value in ["../outside", str(self.fixtures), "missing"]:
            with self.assertRaises(storage.StorageError):
                job_service.collect(self.root, [value])
        (self.root / "escape").symlink_to(self.fixtures, target_is_directory=True)
        with self.assertRaises(storage.StorageError):
            job_service.collect(self.root, ["escape/seed.mp3"])

    def test_detailed_info_and_ids_four_formats(self):
        for ext in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(ext=ext):
                value = storage.describe(self.copy("detail." + ext))
                self.assertTrue(value["format"])
                self.assertGreater(value["sample_rate"], 0)
                self.assertGreater(value["bitrate"], 0)
                self.assertEqual(value["ids"]["mb_artist_ids"], self.ids.mb_artist_ids)

    def test_resume_path_revision_insertion_removal_and_change(self):
        old = self.copy("z.mp3")
        changed = self.copy("changed.mp3")
        missing = self.copy("missing.mp3")
        results = self.job([old, changed, missing])
        missing.unlink()
        p0.tags.write_file(str(changed), p0.tags.Tags(title="Revised", artist="Singer"))
        added = self.copy("a.mp3")
        main.jobs["test"].update(status="queued", cancel_requested=False)
        with patch.object(search_service, "search", return_value={"candidates": [], "search_status": "not_found"}) as search:
            main.scan_job("test", "", {"use_fingerprint": False}, resume=True)
        job = main.jobs["test"]
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["scanned"], 3)
        self.assertEqual(job["missing_paths"], ["missing.mp3"])
        self.assertEqual({c.args[0] for c in search.call_args_list}, {added, changed})
        self.assertEqual(len({r["path"] for r in job["results"]}), 3)
        self.assertEqual(next(r for r in job["results"] if r["path"] == "z.mp3")["candidates"], results[0]["candidates"])

    def test_cancel_during_search_does_not_publish_partial_result(self):
        self.job([self.copy()])
        main.jobs["test"].update(status="queued", results=[], cancel_requested=False)
        def cancel(*args, **kwargs):
            main.cancel_job("test")
            return {"candidates": [], "search_status": "cancelled"}
        with patch.object(search_service, "search", side_effect=cancel):
            main.scan_job("test", "", {}, False)
        self.assertEqual(main.jobs["test"]["status"], "cancelled")
        self.assertEqual(len(main.jobs["test"]["results"]), 1)
        self.assertEqual(main.jobs["test"]["results"][0]["search_phase"], "waiting")
        self.assertEqual(main.jobs["test"]["results"][0]["candidates"], [])

    def test_force_cannot_bypass_cancelling_and_concurrent_start(self):
        self.copy()
        main.jobs["busy"] = {"id": "busy", "status": "cancelling", "sub_path": ""}
        self.http({"force": True}, "/api/scan", expected=409)
        main.jobs.clear()
        results = []
        barrier = threading.Barrier(2)
        def start():
            barrier.wait()
            try:
                results.append(main.start_scan(main.ScanRequest(), BackgroundTasks())["job_id"])
            except HTTPException as exc:
                results.append(exc.status_code)
        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(main.jobs), 1)
        self.assertIn(409, results)

    def test_restart_normalizes_all_active_states(self):
        for state in ("queued", "scanning", "cancelling"):
            self.assertEqual(job_service.normalize_jobs({"j": {"status": state, "results": []}})["j"]["status"], "interrupted")
        for malformed in ([], {"j": []}, {"j": {"results": {}}}):
            with self.assertRaises(ValueError):
                job_service.normalize_jobs(malformed)

    def test_corrupt_store_blocks_new_jobs_without_overwriting(self):
        self.copy()
        main.JOBS_FILE.write_text("corrupt original")
        with patch.object(main, "job_store_error", "invalid existing jobs"):
            self.http({}, "/api/scan", expected=503)
        self.assertEqual(main.jobs, {})
        self.assertEqual(main.JOBS_FILE.read_text(), "corrupt original")

    def test_worker_persistence_failure_is_not_done(self):
        self.job([self.copy()])
        with patch.object(main, "save_jobs", side_effect=OSError("disk full")):
            main.scan_job("test", "", {}, True)
        self.assertEqual(main.jobs["test"]["status"], "failed")
        self.assertIn("state_error", main.jobs["test"])

    def test_resume_delete_persistence_failure_rolls_back_state(self):
        self.job([self.copy()])
        main.jobs["test"]["status"] = "interrupted"
        with patch.object(main, "save_jobs", side_effect=OSError("disk full")):
            with self.assertRaises(HTTPException):
                main.resume_job("test", BackgroundTasks())
            self.assertEqual(main.jobs["test"]["status"], "interrupted")
            with self.assertRaises(HTTPException):
                with patch.object(main.job_store,"delete",side_effect=OSError("disk full")):
                    main.delete_job("test")
            self.assertIn("test", main.jobs)

    def test_delete_only_record_and_reject_active(self):
        path = self.copy()
        before = path.read_bytes()
        self.job([path])
        self.raw_http("/api/jobs/test", method="DELETE")
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("test", main.jobs)
        self.job([path])
        main.jobs["test"]["status"] = "cancelling"
        self.raw_http("/api/jobs/test", method="DELETE", expected=409)

    def test_preferences_persist_keep_secrets_and_reject_invalid(self):
        path = self.data / "settings.json"
        path.write_text(json.dumps({"acoustid_key": "private-fixture", "extra": 42}))
        value = preferences.Preferences(country="JP", rename=True, artist_name_preference="latin")
        preferences.write(self.data, value)
        self.assertEqual(preferences.read(self.data), value)
        stored = json.loads(path.read_text())
        self.assertEqual(stored["acoustid_key"], "private-fixture")
        self.assertEqual(stored["extra"], 42)
        self.assertNotIn("private-fixture", self.raw_http("/api/preferences").decode())
        self.http({"country": "XX"}, "/api/preferences", expected=405)
        with self.assertRaises(ValueError):
            preferences.Preferences(cover_max_px=2000)
        path.write_text("broken")
        with self.assertRaises(ValueError):
            preferences.write(self.data, value)
        self.assertEqual(path.read_text(), "broken")

    def test_ids_checked_scope_multiple_values_and_exact_restore(self):
        for ext in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(ext=ext):
                path = self.copy("ids." + ext)
                before = path.read_bytes()
                result = self.job([path])[0]
                candidate = {"source": "MusicBrainz", "title": "New Title", "artist": "New Singer", "album": "New Album",
                             "mb_artist_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"],
                             "artist_sort": "Singer, New", "mbid": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                             "mb_release_id": "dddddddd-dddd-dddd-dddd-dddddddddddd"}
                result["candidates"] = [candidate]
                main.prepare_result(result)
                candidate = result["candidates"][0]
                item = self.item(result, selection="manual", candidate_id=candidate["id"], include_ids=True,
                                 values={"title": candidate["title"], "artist": candidate["artist"]}, fields=["title", "artist"])
                self.assertEqual(self.http(self.request([item]))["saved"], 1)
                ids = p0.tags.read_file(str(path)).ids
                self.assertEqual(ids.mb_artist_ids, candidate["mb_artist_ids"])
                self.assertEqual(ids.artist_sort, "Singer, New")
                self.assertEqual(ids.mb_recording_id, candidate["mbid"])
                self.assertEqual(ids.mb_album_id, "")  # unchecked album cannot import its ID
                self.http({"expected_revision": storage.revision(path)}, "/api/revert/" + path.name)
                self.assertEqual(path.read_bytes(), before)

    def test_ids_only_empty_and_manual_mismatch_protected(self):
        path = self.copy()
        extra = p0.tags.Ids(mb_artist_ids=["new"], mb_recording_id="recording")
        storage.save(path, self.root, self.backups, {}, [], True, storage.revision(path), ids=extra)
        self.assertEqual(p0.tags.read_file(str(path)).ids.mb_artist_ids, self.ids.mb_artist_ids)
        result = self.job([path])[0]
        candidate = result["candidates"][0]
        candidate["mb_artist_ids"] = ["wrong-artist"]
        item = self.item(result, selection="edit", candidate_id=candidate["id"], include_ids=True)
        self.http(self.request([item]))
        self.assertEqual(p0.tags.read_file(str(path)).ids.mb_artist_ids, self.ids.mb_artist_ids)

    def test_rename_only_collision_sidecar_and_restore(self):
        for ext in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(ext=ext):
                path = self.copy("rename." + ext)
                before = path.read_bytes()
                collision = self.copy("Original singer - Original song." + ext)
                result = storage.save(path, self.root, self.backups, {}, [], False, storage.revision(path), rename=True)
                self.assertEqual(result["status"], "saved")
                self.assertIn("(2)", result["path"])
                renamed = self.root / result["path"]
                self.assertFalse(path.exists())
                self.assertTrue(Path(p0.tags.backup_path(str(renamed))).exists())
                storage.restore(renamed, self.root, self.backups, storage.revision(renamed))
                self.assertEqual(renamed.read_bytes(), before)
                self.assertTrue(collision.exists())

    def test_http_rename_only_no_candidate_ignores_unselected_values(self):
        path = self.copy()
        before = path.read_bytes()
        result = self.job([path])[0]
        item = self.item(result, selection="none", values={"title": "Must not write"}, fields=["title"])
        response = self.http(self.request([item], rename=True))
        self.assertEqual(response["saved"], 1)
        relative = response["results"][0]["path"]
        renamed = self.root / relative
        self.assertEqual(p0.tags.read_file(str(renamed)).tags.title, "Original song")
        self.http({"expected_revision": storage.revision(renamed)}, "/api/revert/" + urllib.parse.quote(relative))
        self.assertEqual(renamed.read_bytes(), before)

    def test_uploaded_cover_subset_save_no_implicit_writes_and_undo(self):
        first, second = self.copy("one.mp3", blank=True), self.copy("two.mp3", blank=True)
        before = first.read_bytes(), second.read_bytes()
        results = self.job([first, second])
        token = json.loads(self.raw_http("/api/jobs/test/cover-upload", p0.image_bytes("green"), "POST"))["cover_id"]
        self.assertEqual(first.read_bytes(), before[0])
        self.assertEqual(second.read_bytes(), before[1])
        self.assertTrue(self.raw_http("/api/jobs/test/uploaded-cover/" + token).startswith(b"\xff\xd8"))
        item = self.item(results[0], selection="none", fields=[], values={}, cover_id=token, include_cover=True)
        self.assertEqual(self.http(self.request([item]))["saved"], 1)
        self.assertEqual(second.read_bytes(), before[1])
        self.assertTrue(p0.tags.read_cover(str(first))[0])
        self.http({"expected_revision": storage.revision(first)}, "/api/revert/one.mp3")
        self.assertEqual(first.read_bytes(), before[0])

    def test_auto_latin_uses_verified_candidate_and_preserves_existing(self):
        path = self.copy("auto-latin.mp3", blank=True)
        result = self.job([path])[0]
        candidate = {"source": "iTunes", "title": "Song", "artist": "原文", "artist_latin": "Latin Singer",
                     "album_artist": "原文", "album_artist_latin": "Latin Album", "album": "Album"}
        result["candidates"] = [candidate]
        main.prepare_result(result)
        candidate = result["candidates"][0]
        with patch.object(main, "automatic_candidate", return_value=candidate):
            item = self.item(result, selection="auto", candidate_id=candidate["id"],
                             fields=["title", "artist", "albumartist"],
                             values={"title": "forged", "artist": "forged", "albumartist": "forged"})
            response = self.http(self.request([item], artist_name_preference="latin"))
        self.assertEqual(response["saved"], 1)
        info = p0.tags.read_file(str(path))
        self.assertEqual(info.tags.artist, "Latin Singer")
        self.assertEqual(info.tags.album_artist, "Latin Album")
        self.assertEqual(info.tags.title, "Song")

    def test_auto_manual_overwrite_matrix_and_all_scope(self):
        for selection in ("auto", "manual"):
            for only_empty in (True, False):
                for checked in (True, False):
                    with self.subTest(selection=selection, only_empty=only_empty, checked=checked):
                        path = self.copy("matrix.mp3")
                        p0.tags.write_file(str(path), p0.tags.Tags(title="Song", artist="빅뱅"))
                        result = self.job([path])[0]
                        result["candidates"] = [{"source": "iTunes", "title": "Song", "artist": "BIGBANG"}]
                        main.prepare_result(result)
                        candidate = result["candidates"][0]
                        item = self.item(result, selection=selection, candidate_id=candidate["id"],
                                         values={"artist": "BIGBANG"}, fields=["artist"] if checked else [])
                        with patch.object(main, "automatic_candidate", return_value=candidate):
                            self.http(self.request([item], only_empty=only_empty))
                        expected = "BIGBANG" if checked and not only_empty else "빅뱅"
                        self.assertEqual(p0.tags.read_file(str(path)).tags.artist, expected)
        paths = [self.copy("all1.mp3"), self.copy("all2.mp3")]
        results = self.job(paths)
        items = []
        for result in results:
            candidate = result["candidates"][0]
            items.append(self.item(result, selection="auto", candidate_id=candidate["id"],
                                   fields=["artist"], values={"artist": candidate["artist"]}))
        def verified(result):
            return result["candidates"][0]
        with patch.object(main, "automatic_candidate", side_effect=verified):
            response = self.http(self.request(items, scope="all", only_empty=False))
        self.assertEqual(response["saved"], 2)
        for path, item in zip(paths, items):
            self.assertEqual(p0.tags.read_file(str(path)).tags.artist, item["values"]["artist"])

    def test_option_defaults_and_bounds(self):
        value = preferences.Preferences().model_dump()
        self.assertEqual(value, {"country": "KR", "recurse": True, "only_empty": True,
                                 "fill_lyrics": False, "save_synced": False, "create_lrc": False, "rename": False, "include_ids": False,
                                 "artist_name_preference": "original", "cover_max_px": 1000})
        for country in ("KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR"):
            self.assertEqual(preferences.Preferences(country=country).country, country)
        for maximum in (100, 1000):
            self.assertEqual(preferences.Preferences(cover_max_px=maximum).cover_max_px, maximum)
        for kwargs in ({"cover_max_px": 99}, {"cover_max_px": 1001}, {"country": "XX"},
                       {"artist_name_preference": "invalid"}, {"only_empty": "false"}):
            with self.assertRaises(ValueError):
                preferences.Preferences(**kwargs)

    def test_request_cover_size_without_remembering_preferences(self):
        import io
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 600), "green").save(buffer, "PNG")
        preferences.write(self.data, preferences.Preferences(cover_max_px=800))
        settings_before = (self.data / "settings.json").read_bytes()
        for maximum in (240, 400):
            path = self.copy("sized" + str(maximum) + ".mp3", blank=True)
            result = self.job([path])[0]
            token = preferences.put_cover("test", buffer.getvalue())
            item = self.item(result, selection="edit", cover_id=token, include_cover=True)
            response = self.http(self.request([item], cover_max_px=maximum))
            self.assertEqual(response["saved"], 1)
            data = p0.tags.read_file(str(path)).cover
            with Image.open(io.BytesIO(data)) as cover:
                self.assertEqual(max(cover.size), maximum)
        self.assertEqual((self.data / "settings.json").read_bytes(), settings_before)
        legacy = main.SaveRequest(**self.request([item]))
        self.assertIsNone(legacy.cover_max_px)
        for maximum in (99, 1001):
            self.http(self.request([item], cover_max_px=maximum), expected=422)

    def test_manual_overwrite_option_and_unchecked_field(self):
        path = self.copy("options.mp3")
        result = self.job([path])[0]
        candidate = result["candidates"][0]
        item = self.item(result, selection="manual", candidate_id=candidate["id"],
                         values={"title": candidate["title"], "artist": "Unchecked"}, fields=["title"])
        before = path.read_bytes()
        self.assertEqual(self.http(self.request([item], only_empty=True))["skipped"], 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.http(self.request([item], only_empty=False))["saved"], 1)
        info = p0.tags.read_file(str(path))
        self.assertEqual(info.tags.title, candidate["title"])
        self.assertEqual(info.tags.artist, "Original singer")

    def test_cover_invalid_scoped_expired_and_bounded(self):
        self.job([self.copy()])
        self.raw_http("/api/jobs/test/cover-upload", b"invalid", "POST", expected=400)
        token = preferences.put_cover("test", p0.image_bytes("green"))
        with self.assertRaises(storage.StorageError):
            preferences.get_cover("other", token)
        with patch.object(preferences.time, "monotonic", return_value=10**12):
            with self.assertRaises(storage.StorageError):
                preferences.get_cover("test", token)
        for _ in range(34):
            preferences.put_cover("test", p0.image_bytes("blue"))
        self.assertLessEqual(len(preferences._covers), 32)

    def test_diagnostics_offline_and_lyrics_original_script(self):
        with patch.object(search_service.net, "online", return_value=False):
            self.assertFalse(json.loads(self.raw_http("/api/diagnostics?check_network=true"))["network_reachable"])
        rows = [{"plainLyrics": "桜の花が咲く季節にあなたを思い出す"}, {"plainLyrics": "sakura no hana ga saku kisetsu ni anata wo omoidasu " * 3}]
        preferred = main.original_lyrics._prefer_original_script(rows)
        self.assertEqual(preferred, [rows[0]])

    def test_save_progress_is_live_independent_and_counts_real_outcomes(self):
        paths=[self.copy(str(i)+'.mp3') for i in range(4)]
        rows=self.job(paths)
        main.jobs["test"]["sub_path"]="DANCE/Temporary"
        request=main.SaveRequest(**self.request([self.item(row) for row in rows]))
        entered,release=threading.Event(),threading.Event()
        responses,errors=[],[]
        original_save=main.save_one
        def save(result,item,request,context):
            if item.path=='0.mp3':
                return original_save(result,item,request,context)
            if item.path=='1.mp3':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test timed out')
                return {'status':'skipped','reason':'unchanged','changed':False}
            if item.path=='2.mp3':
                return {'status':'partial','changed':True}
            raise RuntimeError('simulated file failure')
        def run(value):
            try:responses.append(main.save_job('test',value))
            except Exception as exc:errors.append(exc)
        with main.save_tasks_lock:main.save_tasks.clear()
        with patch.object(main,'save_one',side_effect=save):
            worker=threading.Thread(target=run,args=(request,));worker.start()
            try:
                self.assertTrue(entered.wait(5))
                # Real HTTP polling stays responsive while music operation lock is held.
                tasks=json.loads(self.raw_http('/api/save-tasks'))
                task=tasks[0]
                self.assertEqual(task['sub_path'],'DANCE/Temporary')
                self.assertEqual((task['saved'],task['processed'],task['total'],task['current_file']),(1,1,4,'1.mp3'))
                self.assertEqual(task['current_path'],str(self.root/'1.mp3'))
                other=main.SaveRequest(**self.request([self.item(rows[3])]))
                queued=threading.Thread(target=run,args=(other,));queued.start()
                import time
                for _ in range(100):
                    tasks=main.list_save_tasks()
                    if len(tasks)==2:break
                    time.sleep(.01)
                self.assertEqual(len(tasks),2)
                self.assertEqual(len({t['id'] for t in tasks}),2)
                waiting=next(t for t in tasks if t['id']!=task['id'])
                self.assertEqual((waiting['status'],waiting['saved'],waiting['processed']),('queued',0,0))
                with self.assertRaises(HTTPException):main.delete_save_task(task['id'])
            finally:
                release.set();worker.join(5)
                if 'queued' in locals():queued.join(5)
        self.assertFalse(errors)
        finished=next(t for t in main.list_save_tasks() if t['id']==task['id'])
        self.assertEqual((finished['status'],finished['saved'],finished['failed'],finished['skipped'],finished['partial'],finished['processed']),('done',2,1,1,1,4))
        self.assertEqual(finished['current_file'],'')
        main.delete_save_task(task['id'])
        self.assertFalse(any(t['id']==task['id'] for t in main.list_save_tasks()))

    def test_unchecked_album_preserved_for_all_save_scopes_and_candidates(self):
        for scope in ('current','selected','all'):
            for selection in ('auto','manual'):
                with self.subTest(scope=scope,selection=selection):
                    paths=[self.copy(scope+'-'+selection+'-'+str(i)+'.mp3') for i in range(1 if scope=='current' else 2)]
                    rows=self.job(paths)
                    items=[]
                    for row in rows:
                        row['candidates']=[{'source':'iTunes','title':'Original song','artist':'Original singer','album':'Replace album','genre':'New genre'}]
                        candidate=main.automatic_candidate(row)
                        self.assertIsNotNone(candidate)
                        candidate_id=candidate['id'] if selection=='auto' else main.candidate_id(row['candidates'][0])
                        items.append(self.item(row,selection=selection,candidate_id=candidate_id,values={'genre':'New genre','album':'Replace album'},fields=['genre']))
                    result=self.http(self.request(items,scope=scope,only_empty=False))
                    self.assertEqual(result['failed'],0)
                    self.assertEqual(result['saved'],len(paths))
                    for path in paths:
                        info=storage.describe(path)
                        self.assertEqual(info['album'],'Original album')
                        self.assertEqual(info['genre'],'New genre')

    def test_cover_disabled_preserves_existing_and_missing_covers_for_every_scope(self):
        for scope in ('current','selected','all'):
            for blank in (False,True):
                for source in ('candidate','uploaded'):
                    with self.subTest(scope=scope,blank=blank,source=source):
                        paths=[self.copy(scope+'-'+str(blank)+'-'+source+'-'+str(i)+'.mp3',blank=blank) for i in range(1 if scope=='current' else 2)]
                        before=[p0.tags.read_cover(str(path)) for path in paths]
                        rows=self.job(paths)
                        token=preferences.put_cover('test',p0.image_bytes('blue')) if source=='uploaded' else None
                        items=[self.item(row,selection='manual',candidate_id=main.candidate_id(row['candidates'][0]),include_cover=True,cover_id=token) for row in rows]
                        with patch.object(search_service,'fetch_cover',side_effect=AssertionError('cover download must be disabled')):
                            result=self.http(self.request(items,scope=scope,save_cover=False,only_empty=False))
                        self.assertEqual(result['failed'],0)
                        self.assertEqual(result['saved'],len(paths))
                        self.assertEqual(before,[p0.tags.read_cover(str(path)) for path in paths])

    def test_disabled_uploaded_cover_without_tag_changes_does_not_touch_file(self):
        path=self.copy()
        row=self.job([path])[0]
        before=path.read_bytes(),path.stat().st_mtime_ns
        token=preferences.put_cover('test',p0.image_bytes('blue'))
        item=self.item(row,selection='edit',values={'title':'Original song'},fields=['title'],cover_id=token,include_cover=True)
        outcome=self.http(self.request([item],save_cover=False,only_empty=False))
        self.assertEqual(outcome['unchanged'],1)
        self.assertEqual(before,(path.read_bytes(),path.stat().st_mtime_ns))

    def test_cover_enabled_keeps_fill_empty_rule(self):
        for blank in (False,True):
            for only_empty in (False,True):
                for source in ('candidate','uploaded'):
                    with self.subTest(blank=blank,only_empty=only_empty,source=source):
                        path=self.copy('enabled-'+str(blank)+'-'+str(only_empty)+'-'+source+'.mp3',blank=blank)
                        row=self.job([path])[0]
                        before=p0.tags.read_cover(str(path))
                        token=preferences.put_cover('test',p0.image_bytes('blue')) if source=='uploaded' else None
                        item=self.item(row,selection='manual',candidate_id=main.candidate_id(row['candidates'][0]),fields=[],values={},cover_id=token,include_cover=True)
                        with patch.object(search_service,'fetch_cover',return_value=(p0.image_bytes('blue'),[])):
                            result=self.http(self.request([item],only_empty=only_empty))
                        self.assertEqual(result['failed'],0)
                        after=p0.tags.read_cover(str(path))
                        if only_empty and not blank:self.assertEqual(before,after)
                        else:self.assertTrue(after[0]);self.assertNotEqual(before,after)

    def test_empty_cover_payload_never_removes_embedded_image(self):
        for ext in ('mp3', 'flac', 'm4a', 'ogg'):
            for empty in (None, b'', ''):
                with self.subTest(ext=ext, empty=empty):
                    path = self.copy('empty-' + str(type(empty).__name__) + '.' + ext)
                    before = p0.tags.read_cover(str(path))
                    # Exercise the lowest writer too: no empty APIC/PICTURE/covr.
                    info = p0.tags.read_file(str(path))
                    p0.tags.write_file(str(path), info.tags, empty, fields=set())
                    self.assertEqual(p0.tags.read_cover(str(path)), before)
                    result = storage.save(path, self.root, self.backups, {'title': 'Edited'}, ['title'],
                                          False, storage.revision(path), cover=empty)
                    self.assertEqual(result['status'], 'saved')
                    self.assertEqual(p0.tags.read_cover(str(path)), before)

    def test_invalid_new_cover_is_rejected_before_existing_bytes_change(self):
        from PIL import UnidentifiedImageError
        for ext in ('mp3', 'flac', 'm4a', 'ogg'):
            path = self.copy('invalid-cover.' + ext)
            before = path.read_bytes(), path.stat().st_mtime_ns
            info = p0.tags.read_file(str(path))
            with self.assertRaises(UnidentifiedImageError):
                p0.tags.write_file(str(path), info.tags, b'not an image')
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            with self.assertRaises(UnidentifiedImageError):
                storage.save(path, self.root, self.backups, {'title': 'Edited'}, ['title'],
                             False, storage.revision(path), cover=b'not an image')
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_cover_save_matrix_four_formats_and_all_scopes(self):
        cases = ((True, None, True, False), (True, None, False, False),
                 (True, 'new', True, False), (True, 'new', False, False),
                 (True, 'new', True, True), (False, 'new', True, False))
        for ext in ('mp3', 'flac', 'm4a', 'ogg'):
            for scope in ('current', 'selected', 'all'):
                for index, (existing, source, checked, only_empty) in enumerate(cases):
                    with self.subTest(ext=ext, scope=scope, case=index + 1):
                        paths = [self.copy(f'{scope}-{index}-{i}.{ext}', blank=not existing)
                                 for i in range(1 if scope == 'current' else 2)]
                        before = [p0.tags.read_cover(str(path)) for path in paths]
                        rows = self.job(paths)
                        items = [self.item(row, selection="manual", candidate_id=main.candidate_id(row["candidates"][0]), include_cover=source is not None) for row in rows]
                        new = p0.image_bytes('blue')
                        with patch.object(search_service, 'fetch_cover', return_value=(new, [])):
                            result = self.http(self.request(items, scope=scope, save_cover=checked,
                                                            only_empty=only_empty))
                        self.assertEqual(result['failed'], 0)
                        self.assertEqual(result['partial'], 0)
                        replace = source is not None and checked and not (only_empty and existing)
                        for path, old in zip(paths, before):
                            after = p0.tags.read_cover(str(path))
                            self.assertEqual(after[0], new if replace else old[0])
                        tasks = list(main.save_tasks.values())
                        self.assertEqual(tasks[-1]['status'], 'done')

    def test_blank_candidate_response_preserves_cover_and_saves_text(self):
        for empty in (None, b'', ''):
            path = self.copy('blank-' + str(type(empty).__name__) + '.mp3')
            before = p0.tags.read_cover(str(path))
            row = self.job([path])[0]
            item = self.item(row, selection="manual", candidate_id=main.candidate_id(row["candidates"][0]), include_cover=True)
            with patch.object(search_service, 'fetch_cover', return_value=(empty, [])):
                result = self.http(self.request([item]))
            self.assertEqual(result['failed'], 0)
            self.assertEqual(result['saved'], 1)
            self.assertEqual(p0.tags.read_cover(str(path)), before)

    def test_list_media_flags_reuse_scan_read_and_never_send_lyrics_body(self):
        for blank in (False, True):
            path = self.copy('flags-' + str(blank) + '.mp3', blank=blank)
            with patch.object(p0.tags, 'read_file', wraps=p0.tags.read_file) as read:
                info = storage.describe(path)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(info['has_cover'], not blank)
            self.assertEqual(info['has_lyrics'], not blank)
            self.assertNotIn('lyrics', info)
        row = self.job([self.copy('legacy.mp3')])[0]
        row['original']['lyrics'] = 'PRIVATE STORED LYRICS'
        row['lyrics'] = 'ONLINE LYRICS MUST NOT APPEAR IN LIST'
        with patch.object(p0.tags, 'read_file', side_effect=AssertionError('list must not reread music')):
            listed = self.raw_http('/api/jobs')
            detail = self.raw_http('/api/jobs/test')
        self.assertNotIn(b'PRIVATE STORED LYRICS', listed + detail)
        self.assertNotIn(b'ONLINE LYRICS', listed + detail)
        self.assertEqual(row['original']['lyrics'], 'PRIVATE STORED LYRICS')

    def test_file_thumbnails_four_formats_cached_and_individually_invalidated(self):
        import io
        from PIL import Image
        main._thumbnail_cache.clear()
        paths = [self.copy('thumb.' + ext) for ext in ('mp3', 'flac', 'm4a', 'ogg')]
        original_bytes = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        def route(path):
            return '/api/thumbnail/' + urllib.parse.quote(path.name)
        with patch.object(search_service.net, 'get_bytes', side_effect=AssertionError('no external images')):
            with patch.object(p0.tags, 'read_file', wraps=p0.tags.read_file) as read:
                for path in paths:
                    image = Image.open(io.BytesIO(self.raw_http(route(path))))
                    self.assertEqual(image.size, (24, 24))
                    self.raw_http(route(path))
                self.assertEqual(read.call_count, 4)
            for path, before in zip(paths, original_bytes):
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            info = p0.tags.read_file(str(paths[0]))
            p0.tags.write_file(str(paths[0]), info.tags, p0.image_bytes('blue'))
            with patch.object(p0.tags, 'read_file', wraps=p0.tags.read_file) as read:
                self.raw_http(route(paths[1]))
                self.raw_http(route(paths[0]))
                self.assertEqual(read.call_count, 1)
            response = urllib.request.urlopen('http://127.0.0.1:' + str(self.port) + route(paths[0]))
            request = urllib.request.Request(response.url, headers={'If-None-Match': response.headers['ETag']})
            response.close()
            with self.assertRaises(urllib.error.HTTPError) as unchanged:
                urllib.request.urlopen(request)
            self.assertEqual(unchanged.exception.code, 304)
            unchanged.exception.close()
            blank = self.copy('no-cover.mp3', blank=True)
            with patch.object(p0.tags, 'read_file', wraps=p0.tags.read_file) as read:
                self.raw_http(route(blank), expected=404)
                self.raw_http(route(blank), expected=404)
                self.assertEqual(read.call_count, 1)

    def test_thumbnail_cache_bound_concurrent_requests_and_path_validation(self):
        from fastapi import Request
        from concurrent.futures import ThreadPoolExecutor
        main._thumbnail_cache.clear()
        paths = [self.copy(str(i) + '.mp3') for i in range(3)]
        with patch.object(main, '_THUMBNAIL_LIMIT', 2):
            with patch.object(p0.tags, 'read_file', wraps=p0.tags.read_file) as read:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    list(pool.map(lambda _: main.file_thumbnail(paths[0].name, Request({'type':'http','headers':[]})), range(3)))
                self.assertEqual(read.call_count, 1)
            for path in paths[1:]:
                main.file_thumbnail(path.name, Request({'type':'http','headers':[]}))
            self.assertEqual(len(main._thumbnail_cache), 2)
        self.raw_http('/api/thumbnail/..%2Foutside.mp3', expected=400)
        self.raw_http('/api/thumbnail/%2Foutside.mp3', expected=400)
        (self.root / 'link.mp3').symlink_to(paths[0])
        self.raw_http('/api/thumbnail/link.mp3', expected=400)

    def test_existing_lyric_viewer_reads_only_on_explicit_request(self):
        path = self.copy('lyrics.mp3')
        with patch.object(p0.tags, 'read_file', wraps=p0.tags.read_file) as read:
            value = json.loads(self.raw_http('/api/lyrics/lyrics.mp3'))
            self.assertEqual(value['lyrics'], self.lyrics)
            self.assertEqual(read.call_count, 1)
        self.raw_http('/api/lyrics/..%2Foutside.mp3', expected=400)

    def lyrics_search(self, row, **changes):
        value = {'path': row['path'], 'expected_revision': row['original']['revision'],
                 'title': row['original']['title'], 'artist': row['original']['artist']}
        value.update(changes)
        return self.http(value, route='/api/jobs/test/lyrics-search')

    def test_lyrics_search_states_cache_and_read_only(self):
        states = ((main.original_lyrics.FOUND, 'New line one\nNew line two', 'found'),
                  (main.original_lyrics.NOT_FOUND, '', 'not_found'),
                  (main.original_lyrics.FOUND, '', 'not_found'),
                  (main.original_lyrics.BUSY, '', 'error'),
                  (main.original_lyrics.CONFLICT, '', 'error'))
        for index, (status, text, expected) in enumerate(states):
            path = self.copy('search-state-' + str(index) + '.mp3')
            row = self.job([path])[0]
            before = path.read_bytes(), path.stat().st_mtime_ns
            job_before = copy.deepcopy(main.jobs['test'])
            found = main.original_lyrics.LyricsResult(status, text)
            with patch.object(main.original_lyrics, 'find', return_value=found) as find:
                first = self.lyrics_search(row)
                again = self.lyrics_search(row)
                self.assertEqual(find.call_count, 1)
            self.assertEqual(first['status'], expected)
            self.assertEqual(first['lyrics'], text)
            self.assertTrue(first['searched'])
            self.assertEqual(first['lyrics_id'], again['lyrics_id'])
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertEqual(main.jobs['test'], job_before)
            self.assertFalse(self.backups.exists())
        missing = self.lyrics_search(row, title='', artist='')
        self.assertEqual(missing['status'], 'error')
        self.assertFalse(missing['searched'])

    def test_lyrics_search_duplicate_requests_share_one_lookup(self):
        from concurrent.futures import ThreadPoolExecutor
        path = self.copy('concurrent-lyrics.mp3')
        row = self.job([path])[0]
        request = main.LyricsSearchRequest(path=row['path'], expected_revision=row['original']['revision'],
                                           title=row['original']['title'], artist=row['original']['artist'])
        entered, release = threading.Event(), threading.Event()
        def lookup(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return main.original_lyrics.LyricsResult(main.original_lyrics.FOUND, 'Concurrent lyrics')
        with patch.object(main.original_lyrics, 'find', side_effect=lookup) as find:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(main.search_file_lyrics, 'test', request)
                self.assertTrue(entered.wait(5))
                second = pool.submit(main.search_file_lyrics, 'test', request)
                release.set()
                self.assertEqual(first.result(5)['lyrics_id'], second.result(5)['lyrics_id'])
            self.assertEqual(find.call_count, 1)

    def test_manual_lyrics_save_options_all_formats_and_scopes(self):
        new_text = 'Verified new lyric line one\nVerified new lyric line two'
        for ext in ('mp3', 'flac', 'm4a', 'ogg'):
            for scope in ('current', 'selected', 'all'):
                for existing in (False, True):
                    for checked in (False, True):
                        for only_empty in (False, True):
                            with self.subTest(ext=ext, scope=scope, existing=existing, checked=checked, only_empty=only_empty):
                                stem = f'lyric-{scope}-{existing}-{checked}-{only_empty}'
                                paths = [self.copy(stem + str(i) + '.' + ext, blank=not existing)
                                         for i in range(1 if scope == 'current' else 2)]
                                if not existing:
                                    for path in paths:
                                        p0.tags.write_file(str(path), p0.tags.Tags(title='Temporary song', artist='Singer'))
                                rows = self.job(paths)
                                before = [(path.read_bytes(), path.stat().st_mtime_ns, p0.tags.read_cover(str(path))) for path in paths]
                                items = []
                                with patch.object(main.original_lyrics, 'find', return_value=main.original_lyrics.LyricsResult(main.original_lyrics.FOUND, new_text)):
                                    for row in rows:
                                        found = self.lyrics_search(row)
                                        items.append(self.item(row, fields=[], values={}, lyrics_id=found['lyrics_id']))
                                with patch.object(main.original_lyrics, 'find', side_effect=AssertionError('save must reuse searched lyric')):
                                    response = self.http(self.request(items, scope=scope, save_lyrics=checked, only_empty=only_empty))
                                self.assertEqual(response['failed'], 0)
                                self.assertEqual(response['partial'], 0)
                                replace = checked and not (only_empty and existing)
                                for path, old in zip(paths, before):
                                    self.assertEqual(p0.tags.read_file(str(path)).lyrics, new_text if replace else self.lyrics if existing else '')
                                    self.assertEqual(p0.tags.read_cover(str(path)), old[2])
                                    if not replace:
                                        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), old[:2])
                                self.assertEqual(list(main.save_tasks.values())[-1]['status'], 'done')

    def test_unsearched_empty_or_not_found_lyrics_always_preserve_file(self):
        for existing in (False, True):
            for mode in ('missing', 'null', 'empty', 'not_found'):
                path = self.copy(f'preserve-{existing}-{mode}.mp3', blank=not existing)
                if not existing:
                    p0.tags.write_file(str(path), p0.tags.Tags(title='Song', artist='Singer'))
                row = self.job([path])[0]
                item = self.item(row, fields=[], values={})
                if mode == 'null': item['lyrics_id'] = None
                if mode == 'empty': item['lyrics_id'] = ''
                if mode == 'not_found':
                    with patch.object(main.original_lyrics, 'find', return_value=main.original_lyrics.LyricsResult(main.original_lyrics.NOT_FOUND)):
                        item['lyrics_id'] = self.lyrics_search(row)['lyrics_id']
                before = path.read_bytes(), path.stat().st_mtime_ns
                with patch.object(main.original_lyrics, 'find', side_effect=AssertionError('option alone must not search')):
                    response = self.http(self.request([item], save_lyrics=True, fill_lyrics=True, only_empty=False))
                self.assertEqual(response['failed'], 0)
                self.assertEqual(response['saved'], 0)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_lyrics_choice_is_bound_to_file_job_revision_and_query(self):
        paths = [self.copy('bound-a.mp3'), self.copy('bound-b.mp3')]
        rows = self.job(paths)
        with patch.object(main.original_lyrics, 'find', return_value=main.original_lyrics.LyricsResult(main.original_lyrics.FOUND, 'Bound lyrics')):
            token = self.lyrics_search(rows[0])['lyrics_id']
        before = [path.read_bytes() for path in paths]
        wrong_file = self.item(rows[1], fields=[], values={}, lyrics_id=token)
        self.assertEqual(self.http(self.request([wrong_file], save_lyrics=True))['failed'], 1)
        changed_query = self.item(rows[0], values={'title':'Another title'}, fields=['title'], lyrics_id=token)
        self.assertEqual(self.http(self.request([changed_query], save_lyrics=True))['failed'], 1)
        main.jobs['other'] = copy.deepcopy(main.jobs['test'])
        wrong_job = self.item(rows[0], fields=[], values={}, lyrics_id=token)
        self.assertEqual(self.http(self.request([wrong_job], save_lyrics=True), route='/api/jobs/other/save')['failed'], 1)
        entry = next(e for e in main._lyrics_cache.values() if e['lyrics_id'] == token)
        entry['expires'] = 0
        self.assertEqual(self.http(self.request([wrong_job], save_lyrics=True))['failed'], 1)
        self.assertEqual(self.http(self.request([wrong_job], save_lyrics=False))['failed'], 0)
        self.assertEqual(before, [path.read_bytes() for path in paths])
        self.http({'path': rows[0]['path'], 'expected_revision': '0'*64, 'title':'Song','artist':'Singer'}, route='/api/jobs/test/lyrics-search', expected=409)
        self.http({'path':'../outside.mp3', 'expected_revision':'0'*64,'title':'Song','artist':'Singer'}, route='/api/jobs/test/lyrics-search', expected=404)

    def test_explicit_lyrics_replacement_retains_first_backup_and_ignores_blank(self):
        for ext in ('mp3', 'flac', 'm4a', 'ogg'):
            path = self.copy('lyrics-restore.' + ext)
            original = path.read_bytes()
            result = storage.save(path, self.root, self.backups, {}, [], False, storage.revision(path),
                                  lyrics='New actual embedded lyrics\nSecond line', replace_lyrics=True)
            self.assertEqual(result['status'], 'saved')
            self.assertEqual(p0.tags.read_file(str(path)).lyrics, 'New actual embedded lyrics\nSecond line')
            storage.restore(path, self.root, self.backups, storage.revision(path))
            self.assertEqual(path.read_bytes(), original)
            for blank in (None, '', '   '):
                before = path.read_bytes(), path.stat().st_mtime_ns
                result = storage.save(path, self.root, self.backups, {}, [], False, storage.revision(path), lyrics=blank, replace_lyrics=True)
                self.assertEqual(result['status'], 'skipped')
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_audio_stream_ranges_head_and_read_only(self):
        def stream(path,range_value=None,method='GET'):
            request=urllib.request.Request('http://127.0.0.1:'+str(self.port)+'/api/audio/'+urllib.parse.quote(path,safe=''),method=method,headers={'Range':range_value} if range_value else {})
            try:response=urllib.request.urlopen(request,timeout=3)
            except urllib.error.HTTPError as exc:response=exc
            with response:return response.code,dict(response.headers),response.read()
        for ext,mime in [('mp3','audio/mpeg'),('flac','audio/flac'),('m4a','audio/mp4'),('ogg','audio/ogg')]:
            path=self.copy('stream.'+ext);before=path.read_bytes(),path.stat().st_mtime_ns
            code,headers,data=stream(path.name)
            self.assertEqual(code,200);self.assertEqual(data,before[0]);self.assertEqual(headers['content-type'],mime)
            self.assertEqual(headers['accept-ranges'],'bytes')
            for value,start,end in [('bytes=0-15',0,15),('bytes=20-',20,len(data)-1),('bytes=-12',len(data)-12,len(data)-1),('bytes=0-999999',0,len(data)-1)]:
                code,h,part=stream(path.name,value);self.assertEqual(code,206);self.assertEqual(part,data[start:end+1]);self.assertEqual(h['content-range'],f'bytes {start}-{end}/{len(data)}')
            for value in ['bytes=999999-','bytes=12-2','bytes=-0','bytes=','bytes=0-1,3-4','bytes='+'9'*200+'-']:
                code,h,_=stream(path.name,value);self.assertEqual(code,416);self.assertEqual(h['content-range'],f'bytes */{len(data)}')
            code,h,body=stream(path.name,'bytes=0-15','HEAD');self.assertEqual(code,206);self.assertEqual(body,b'');self.assertEqual(h['content-length'],'16')
            self.assertEqual(before,(path.read_bytes(),path.stat().st_mtime_ns))

    def test_audio_stream_rejects_escape_unsupported_and_symlink(self):
        valid=self.copy()
        (self.root/'bad.txt').write_text('not audio')
        (self.root/'linked.mp3').symlink_to(valid)
        for path in ['../outside.mp3',str(valid.resolve()),'missing.mp3','bad.txt','linked.mp3']:
            request=urllib.request.Request('http://127.0.0.1:'+str(self.port)+'/api/audio/'+urllib.parse.quote(path,safe=''))
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,400)
    def test_candidate_cover_only_no_text_fields_and_identical_skip(self):
        for ext in ('mp3', 'flac', 'm4a', 'ogg'):
            for scope in ('current', 'selected'):
                with self.subTest(ext=ext, scope=scope):
                    paths=[self.copy('cover-only-'+scope+'-'+str(i)+'.'+ext) for i in range(1 if scope=='current' else 2)]
                    original=[path.read_bytes() for path in paths]
                    infos=[p0.tags.read_file(str(path)) for path in paths]
                    rows=self.job(paths);blue=p0.image_bytes('blue')
                    items=[self.item(row,selection='manual',candidate_id=main.candidate_id(row['candidates'][0]),fields=[],values={},include_cover=True,include_ids=False) for row in rows]
                    with patch.object(search_service,'fetch_cover',return_value=(blue,[])) as fetch:
                        result=self.http(self.request(items,scope=scope,save_cover=True,save_lyrics=False,only_empty=False,rename=False))
                    self.assertEqual(result['saved'],len(paths));self.assertEqual(result['failed'],0);self.assertEqual(fetch.call_count,len(paths))
                    for path,row,before,first in zip(paths,rows,infos,original):
                        after=p0.tags.read_file(str(path))
                        self.assertEqual(after.cover,blue);self.assertNotEqual(after.cover,before.cover)
                        self.assertEqual(after.tags,before.tags);self.assertEqual(after.ids,before.ids);self.assertEqual(after.lyrics,before.lyrics)
                        unchanged=path.read_bytes(),path.stat().st_mtime_ns
                        sidecar=p0.tags.backup_path(str(path));backup=Path(sidecar).read_bytes()
                        same=self.item(row,selection='manual',candidate_id=main.candidate_id(row['candidates'][0]),fields=[],values={},include_cover=True,include_ids=False)
                        with patch.object(search_service,'fetch_cover',return_value=(blue,[])):
                            second=self.http(self.request([same],save_cover=True,save_lyrics=False,only_empty=False,rename=False))
                        self.assertEqual(second['unchanged'],1);self.assertEqual(second['saved'],0)
                        self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),unchanged)
                        self.assertEqual(Path(sidecar).read_bytes(),backup)
                        storage.restore(path,self.root,self.backups,storage.revision(path));self.assertEqual(path.read_bytes(),first)

    def test_candidate_cover_only_still_respects_cover_and_empty_options(self):
        for checked,only_empty in ((False,False),(True,True)):
            path=self.copy('protected-'+str(checked)+'.mp3');row=self.job([path])[0]
            before=path.read_bytes(),path.stat().st_mtime_ns
            item=self.item(row,selection='manual',candidate_id=main.candidate_id(row['candidates'][0]),fields=[],values={},include_cover=True)
            with patch.object(search_service,'fetch_cover') as fetch:
                result=self.http(self.request([item],save_cover=checked,save_lyrics=False,only_empty=only_empty,rename=False))
            fetch.assert_not_called();self.assertEqual(result['unchanged'],1)
            self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)
