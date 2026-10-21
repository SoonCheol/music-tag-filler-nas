"""P2 tests use generated audio and isolated runtime paths only."""
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import urllib.request
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
        self.assertEqual(main.jobs["test"]["results"], [])

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
        self.raw_http("/api/jobs/test", method="DELETE", expected=400)

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
                                 "fill_lyrics": False, "rename": False, "include_ids": False,
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
