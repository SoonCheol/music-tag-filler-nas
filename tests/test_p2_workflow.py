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
