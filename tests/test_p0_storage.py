"""Generated audio only. Never mounts or addresses the real NAS library.

Run in the isolated validation container documented in P0_VALIDATION.md.
Uses stdlib unittest/urllib so the production dependency list stays unchanged.
"""
import dataclasses
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

SCRATCH = tempfile.TemporaryDirectory(prefix="music-tag-p0-")
os.environ["MUSIC_ROOT"] = str(Path(SCRATCH.name) / "music")
os.environ["DATA_ROOT"] = str(Path(SCRATCH.name) / "data")

from PIL import Image
import uvicorn
from app import main, storage
from app.upstream import tags


def image_bytes(color):
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), color).save(buffer, "JPEG")
    return buffer.getvalue()


class P0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = Path(SCRATCH.name) / ("fixtures-" + cls.__name__)
        cls.fixtures.mkdir()
        cls.cover = image_bytes("red")
        cls.lyrics = "Original lyrics\nKeep these words unchanged."
        cls.ids = tags.Ids(mb_artist_ids=["11111111-1111-1111-1111-111111111111"], artist_sort="Original, Singer")
        for extension, codec in (("mp3", "libmp3lame"), ("flac", "flac"), ("m4a", "aac"), ("ogg", "libvorbis")):
            path = cls.fixtures / ("seed." + extension)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=0.4", "-c:a", codec, str(path)], check=True)
            tags.write_file(str(path), tags.Tags(title="Original song", artist="Original singer", album="Original album",
                                                album_artist="Original album artist", year="2001", track="1/3", genre="Test"),
                            cls.cover, ids=cls.ids, lyrics=cls.lyrics)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.02)
        if not cls.server.started:
            raise RuntimeError("Test HTTP server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=SCRATCH.name, prefix="case-")
        self.root = Path(self.case.name) / "music"
        self.root.mkdir()
        self.backups = Path(self.case.name) / "backups"
        self.data = Path(self.case.name) / "data"
        self.data.mkdir()
        main.MUSIC_ROOT = self.root
        main.DATA_ROOT = self.data
        main.BACKUP_ROOT = self.backups
        main.JOBS_FILE = self.data / "jobs.json"
        main.jobs.clear()

    def tearDown(self):
        self.case.cleanup()

    def copy(self, name="song.mp3", blank=False):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.fixtures / ("seed" + path.suffix.lower()), path)
        if blank:
            tags.write_file(str(path), tags.Tags(), lyrics="")
            # Remove cover only on generated test files.
            tags._remove_cover(str(path))
        return path

    def save(self, path, title="Changed", **kwargs):
        return storage.save(path, self.root, self.backups, {"title": title, "artist": "MUST NOT WRITE"},
                            ["title"], kwargs.pop("only_empty", False), storage.revision(path), **kwargs)

    def job(self, paths):
        results = []
        for path in paths:
            original = storage.describe(path)
            candidates = [{"source": "MusicBrainz", "title": "First candidate", "artist": "Singer One", "album": "One"},
                          {"source": "iTunes", "title": "Second candidate", "artist": "Singer Two", "album": "Two"}]
            result = {"path": str(path.relative_to(self.root)), "original": original,
                      "parsed": {"title": original["title"], "artist": original["artist"]}, "candidates": candidates}
            main.prepare_result(result)
            result["scan_auto_selected"] = True  # Base fixtures permit explicit bulk selection tests.
            results.append(result)
        main.jobs["test"] = {"id": "test", "status": "done", "options": {}, "results": results}
        return results

    def item(self, result, selection="edit", **kwargs):
        data = {"path": result["path"], "expected_revision": result["original"]["revision"],
                "selection": selection, "values": {"title": "Hand edited title", "artist": "Unchecked artist"},
                "fields": ["title"], "include_cover": False}
        data.update(kwargs)
        return data

    def request(self, items, scope=None, **kwargs):
        scope = scope or ("current" if len(items) == 1 else "selected")
        value = {"scope": scope, "paths": [item["path"] for item in items],
                 "checked_paths": [] if scope == "current" else [item["path"] for item in items], "items": items,
                 "only_empty": False, "fill_lyrics": False}
        value.update(kwargs)
        return value

    def http(self, value, route="/api/jobs/test/save", expected=200):
        request = urllib.request.Request("http://127.0.0.1:" + str(self.port) + route,
                                         data=json.dumps(value).encode(), headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        self.assertEqual(response.code, expected)
        return json.load(response)

    def test_four_formats_first_backup_preserved_and_exact_undo(self):
        for extension in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(extension=extension):
                path = self.copy("original." + extension)
                original = path.read_bytes()
                info = tags.read_file(str(path))
                self.assertEqual(self.save(path)["status"], "saved")
                sidecar = Path(tags.backup_path(str(path)))
                first_backup = sidecar.read_bytes()
                updated = tags.read_file(str(path))
                self.assertEqual(updated.tags.title, "Changed")
                self.assertEqual(updated.tags.artist, info.tags.artist)
                self.assertEqual(updated.cover, info.cover)
                self.assertEqual(updated.lyrics, info.lyrics)
                self.assertEqual(updated.ids, info.ids)
                self.save(path, title="Second edit")
                self.assertEqual(sidecar.read_bytes(), first_backup)
                result = storage.restore(path, self.root, self.backups, storage.revision(path))
                self.assertTrue(result["exact"])
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(sidecar.read_bytes(), first_backup)

    def test_unchanged_and_only_empty_do_not_write_or_create_backup(self):
        path = self.copy()
        before, modified = path.read_bytes(), path.stat().st_mtime_ns
        result = self.save(path, only_empty=True, cover=image_bytes("blue"), lyrics="Replacement words")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertFalse(Path(tags.backup_path(str(path))).exists())
        self.assertFalse(self.backups.exists())

    def test_complete_noop_and_rename_only_do_not_rewrite(self):
        for extension in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(extension=extension):
                path = self.copy("Original singer - Original song." + extension)
                info = tags.read_file(str(path))
                values = {field: info.tags.as_dict()[key] for field, key in storage.FIELDS.items()}
                before, modified = path.read_bytes(), path.stat().st_mtime_ns
                with patch.object(tags, "write_file", side_effect=AssertionError("no-op must not write")):
                    outcome = storage.save(path, self.root, self.backups, values, list(values), False,
                                           storage.revision(path), cover=info.cover, lyrics=info.lyrics,
                                           rename=True, ids=info.ids)
                self.assertEqual((outcome["status"], outcome["reason"]), ("skipped", "unchanged"))
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(path.stat().st_mtime_ns, modified)
                self.assertFalse(Path(tags.backup_path(str(path))).exists())
                other = self.copy("rename-only." + extension)
                before, modified = other.read_bytes(), other.stat().st_mtime_ns
                with patch.object(tags, "write_file", side_effect=AssertionError("rename-only must not write")):
                    outcome = storage.save(other, self.root, self.backups, {}, [], False,
                                           storage.revision(other), rename=True)
                target = self.root / outcome["path"]
                self.assertEqual(outcome["status"], "saved")
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(target.stat().st_mtime_ns, modified)
                storage.restore(target, self.root, self.backups, storage.revision(target))
                self.assertEqual(target.read_bytes(), before)

    def test_http_same_and_unselected_are_separate_without_writes(self):
        paths = [self.copy("same.mp3"), self.copy("no-result.mp3")]
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        results = self.job(paths)
        info = tags.read_file(str(paths[0]))
        values = {field: info.tags.as_dict()[key] for field, key in storage.FIELDS.items()}
        results[1]["candidates"] = []
        items = [self.item(results[0], values=values, fields=list(values)),
                 self.item(results[1], selection="none")]
        with patch.object(tags, "write_file", side_effect=AssertionError("unchanged HTTP must not write")):
            response = self.http(self.request(items, scope="all", rename=False))
        self.assertEqual((response["saved"], response["skipped"], response["unchanged"], response["unselected"]), (0, 2, 1, 1))
        for path, (data, modified) in zip(paths, before):
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, modified)
        self.assertFalse(self.backups.exists())

    def test_same_png_cover_is_not_reencoded(self):
        buffer = io.BytesIO()
        Image.new("RGB", (24, 24), "blue").save(buffer, "PNG")
        image = buffer.getvalue()
        path = self.copy("same-png.mp3")
        info = tags.read_file(str(path))
        tags.write_file(str(path), info.tags, image, "image/png")
        before, modified = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(tags, "write_file", side_effect=AssertionError("identical PNG must not write")):
            outcome = storage.save(path, self.root, self.backups, {}, [], False,
                                   storage.revision(path), cover=image)
        self.assertEqual(outcome["reason"], "unchanged")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_new_lyrics_and_cover_write_for_each_format_then_exact_undo(self):
        for extension in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(extension=extension):
                path = self.copy("blank." + extension, blank=True)
                original = path.read_bytes()
                result = self.save(path, cover=self.cover, lyrics="New lyrics\nOnly test words.")
                info = tags.read_file(str(path))
                self.assertEqual(result["status"], "saved")
                self.assertEqual(info.cover, self.cover)
                self.assertEqual(info.lyrics, "New lyrics\nOnly test words.")
                storage.restore(path, self.root, self.backups, storage.revision(path))
                self.assertEqual(path.read_bytes(), original)

    def test_corrupted_backups_block_save_and_restore(self):
        for file in ("sidecar", "original.bin", "tags.json", "manifest.json", "manifest.sha256"):
            with self.subTest(file=file):
                path = self.copy(file.replace(".", "-") + ".mp3")
                self.save(path)
                sidecar = Path(tags.backup_path(str(path)))
                folder = self.backups / json.loads(sidecar.read_bytes())["nas_backup_id"]
                target = sidecar if file == "sidecar" else folder / file
                target.write_bytes(b"corrupted")
                before = path.read_bytes()
                with self.assertRaises(storage.StorageError):
                    self.save(path, title="Must not write")
                with self.assertRaises(storage.StorageError):
                    storage.restore(path, self.root, self.backups, storage.revision(path))
                self.assertEqual(path.read_bytes(), before)

    def test_backup_and_staged_write_failures_preserve_music(self):
        path = self.copy()
        before = path.read_bytes()
        with patch.object(storage, "ensure_backup", side_effect=OSError("backup disk full")):
            with self.assertRaises(OSError):
                self.save(path)
        self.assertEqual(path.read_bytes(), before)
        with patch.object(tags, "write_file", side_effect=OSError("staged save failed")):
            with self.assertRaises(OSError):
                self.save(path)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_backup_is_not_overwritten(self):
        path = self.copy()
        sidecar = Path(tags.backup_path(str(path)))
        legacy = b'{"title":"legacy"}'
        sidecar.write_bytes(legacy)
        before = path.read_bytes()
        with self.assertRaises(storage.StorageError):
            self.save(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sidecar.read_bytes(), legacy)

    def test_failed_sidecar_publish_can_resume_only_with_verified_original(self):
        path = self.copy()
        before = path.read_bytes()
        with patch.object(storage, "_new_file", side_effect=OSError("sidecar disk full")):
            with self.assertRaises(storage.StorageError):
                self.save(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.save(path)["status"], "saved")
        storage.restore(path, self.root, self.backups, storage.revision(path))
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_central_backup_without_sidecar_is_not_treated_as_new_original(self):
        path = self.copy()
        self.backups.mkdir()
        legacy = self.backups / (path.name + ".tagbak.json")
        legacy.write_bytes(b'{"original":{"title":"older original"}}')
        before = path.read_bytes()
        with self.assertRaises(storage.StorageError):
            self.save(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(legacy.read_bytes(), b'{"original":{"title":"older original"}}')

    def test_revision_conflict_and_readonly_fail_before_backup(self):
        path = self.copy()
        before = path.read_bytes()
        with self.assertRaises(storage.StorageError):
            storage.save(path, self.root, self.backups, {"title": "Bad"}, ["title"], False, "0" * 64)
        with patch.object(storage.os, "statvfs", return_value=type("ReadOnly", (), {"f_flag": 1})()):
            with self.assertRaises(storage.StorageError):
                self.save(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.backups.exists())

    def test_actual_readonly_validation_mount_rejected(self):
        path = Path(__file__).resolve()
        if not hasattr(os, "statvfs") or not (os.statvfs(path.parent).f_flag & 1):
            self.skipTest("requires the documented read-only validation mount")
        with self.assertRaises(storage.StorageError):
            storage.writable(path)

    def test_rename_moves_sidecar_and_exact_undo_remains_available(self):
        path = self.copy()
        before = path.read_bytes()
        result = self.save(path, title="Renamed song", rename=True)
        renamed = self.root / result["path"]
        self.assertFalse(path.exists())
        self.assertTrue(Path(tags.backup_path(str(renamed))).is_file())
        storage.restore(renamed, self.root, self.backups, storage.revision(renamed))
        self.assertEqual(renamed.read_bytes(), before)

    def test_changed_audio_content_blocks_undo_even_with_current_revision(self):
        path = self.copy()
        self.save(path)
        with path.open("ab") as output:
            output.write(b"different audio content")
        before = path.read_bytes()
        with self.assertRaises(storage.StorageError):
            storage.restore(path, self.root, self.backups, storage.revision(path))
        self.assertEqual(path.read_bytes(), before)

    def test_real_http_second_candidate_manual_values_and_checked_mask(self):
        path = self.copy()
        result = self.job([path])[0]
        candidate = result["candidates"][1]
        item = self.item(result, selection="manual", candidate_id=candidate["id"],
                         values={"title": candidate["title"], "artist": candidate["artist"]})
        response = self.http(self.request([item]))
        self.assertEqual(response["saved"], 1)
        info = tags.read_file(str(path))
        self.assertEqual(info.tags.title, candidate["title"])
        self.assertEqual(info.tags.artist, "Original singer")
        result = main.jobs["test"]["results"][0]
        response = self.http(self.request([self.item(result)]))
        self.assertEqual(tags.read_file(str(path)).tags.title, "Hand edited title")
        response = self.http({"expected_revision": storage.revision(path)}, "/api/revert/song.mp3")
        self.assertTrue(response["exact"])
        self.assertEqual(path.read_bytes(), (self.fixtures / "seed.mp3").read_bytes())

    def test_http_empty_unchecked_and_explicit_scope(self):
        paths = [self.copy(name) for name in ("one.mp3", "two.mp3", "hidden.mp3")]
        results = self.job(paths)
        before_hidden = paths[2].read_bytes()
        self.http(self.request([]), expected=400)
        self.http([], expected=422)  # old empty-list payload must never mean all
        self.http(self.request([self.item(results[0])], scope="all", checked_paths=[r["path"] for r in results]), expected=400)
        request = self.request([self.item(results[0], fields=[])])
        self.assertEqual(self.http(request)["skipped"], 1)
        response = self.http(self.request([self.item(results[0])]))
        self.assertEqual(response["requested"], 1)
        self.assertEqual(paths[1].read_bytes(), before_hidden)
        self.assertEqual(paths[2].read_bytes(), before_hidden)
        all_items = [self.item(result, selection="none") for result in main.jobs["test"]["results"] if main.file_state(result) == "auto"]
        self.assertEqual(self.http(self.request(all_items, scope="all"))["skipped"], 2)

    def test_batch_state_boundaries_and_current_save_transitions(self):
        paths = [self.copy(name) for name in ("auto.mp3", "review.mp3", "saved.mp3")]
        results = self.job(paths)
        results[1]["scan_auto_selected"] = False
        results[2]["stored_saved"] = True
        before = [path.read_bytes() for path in paths]
        for index in (1, 2):
            for scope in ("selected", "all"):
                self.http(self.request([self.item(results[index])], scope=scope), expected=400)
        self.http(self.request([self.item(results[0])], scope="all", checked_paths=[]), expected=400)
        self.http(self.request([self.item(results[0]), self.item(results[1])], scope="current"), expected=400)
        self.assertEqual([path.read_bytes() for path in paths], before)
        unchanged = self.item(results[0], values={"title": "Original song"})
        response = self.http(self.request([unchanged], scope="all"))
        self.assertEqual(response["skipped"], 1)
        self.assertEqual(main.file_state(results[0]), "auto")
        response = self.http(self.request([self.item(results[0])], scope="selected"))
        self.assertEqual(response["saved"], 1)
        self.assertEqual(response["results"][0]["file_state"], "saved")
        self.http(self.request([self.item(results[0])], scope="all"), expected=400)
        for index in (1, 2):
            response = self.http(self.request([self.item(results[index])], scope="current"))
            self.assertEqual(response["saved"], 1)
            self.assertEqual(main.file_state(results[index]), "saved")
        same = self.item(results[1])
        response = self.http(self.request([same], scope="current"))
        self.assertEqual(response["skipped"], 1)
        self.assertEqual(main.file_state(results[1]), "saved")

    def test_http_low_score_generic_and_forged_candidate_rejected(self):
        path = self.copy()
        result = self.job([path])[0]
        item = self.item(result, selection="auto", candidate_id=result["candidates"][0]["id"])
        before = path.read_bytes()
        self.assertEqual(self.http(self.request([item]))["failed"], 1)
        forged = self.item(result, selection="manual", candidate_id="foreign-candidate")
        self.assertEqual(self.http(self.request([forged]))["failed"], 1)
        self.assertEqual(path.read_bytes(), before)
        blank = self.copy("track01.mp3", blank=True)
        generic = self.job([blank])[0]
        generic["parsed"] = {"title": "track01", "artist": ""}
        generic["candidates"][0].update(title="track01", artist="", score=100)
        self.assertIsNone(main.automatic_candidate(generic))

    def test_http_auto_90_boundary_and_browser_value_substitution(self):
        path = self.copy()
        result = self.job([path])[0]
        result["candidates"] = [{"source": "iTunes", "title": "Original song", "artist": "Original singer",
                                  "album": "Wrong overwrite", "length": None}]
        candidate = main.automatic_candidate(result)
        self.assertEqual(candidate["score"], 90)
        item = self.item(result, selection="auto", candidate_id=candidate["id"], values={"title": "Forged browser value"})
        before = path.read_bytes()
        self.assertEqual(self.http(self.request([item]))["skipped"], 1)
        self.assertEqual(path.read_bytes(), before)
        result["candidates"][0]["source"] = "MusicBrainz"
        self.assertIsNone(main.automatic_candidate(result))  # 88, not 90

    def test_http_partial_failure_and_state_record_failure_reported(self):
        paths = [self.copy("one.mp3"), self.copy("two.mp3")]
        results = self.job(paths)
        items = [self.item(result) for result in results]
        items[1]["expected_revision"] = "0" * 64
        response = self.http(self.request(items))
        self.assertEqual((response["status"], response["saved"], response["failed"]), ("partial", 1, 1))
        self.assertEqual(tags.read_file(str(paths[1])).tags.title, "Original song")
        with patch.object(main, "save_jobs", side_effect=OSError("state disk full")):
            current = main.jobs["test"]["results"][0]
            response = self.http(self.request([self.item(current, values={"title": "Next edit"})]))
        self.assertEqual(response["saved"], 1)
        self.assertIn("state_error", response)

    def test_http_all_failed_is_not_saved_and_backup_failure_blocks_save(self):
        path = self.copy()
        result = self.job([path])[0]
        with patch.object(storage, "ensure_backup", side_effect=OSError("backup refused")):
            response = self.http(self.request([self.item(result)]))
        self.assertEqual((response["status"], response["saved"], response["failed"]), ("failed", 0, 1))
        self.assertEqual(main.jobs["test"]["save_status"], "failed")
        self.assertEqual(path.read_bytes(), (self.fixtures / "seed.mp3").read_bytes())

    def test_concurrent_http_saves_allow_only_one_revision(self):
        path = self.copy()
        result = self.job([path])[0]
        payload = self.request([self.item(result)])
        barrier = threading.Barrier(2)
        responses = []
        def worker():
            barrier.wait()
            responses.append(self.http(payload))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(responses), 2)
        self.assertEqual(sorted((r["saved"], r["failed"]) for r in responses), [(0, 1), (1, 0)])

    def test_http_existing_lyrics_cover_protected_and_new_lyrics_use_final_values(self):
        path = self.copy()
        result = self.job([path])[0]
        with patch.object(main.requests, "get", side_effect=AssertionError("must not fetch protected cover")), \
             patch.object(main.original_lyrics, "find", side_effect=AssertionError("must not replace existing lyrics")):
            response = self.http(self.request([self.item(result)], only_empty=True, fill_lyrics=True))
        self.assertEqual(response["skipped"], 1)
        blank = self.copy("blank.m4a", blank=True)
        result = self.job([blank])[0]
        found = main.original_lyrics.LyricsResult(main.original_lyrics.FOUND, "Safe test lyrics\nFinal tags only.")
        item = self.item(result, fields=["title", "artist"], values={"title": "Final song", "artist": "Final singer"})
        with patch.object(main.original_lyrics, "find", return_value=found) as lookup:
            response = self.http(self.request([item], fill_lyrics=True))
        self.assertEqual(response["saved"], 1)
        self.assertEqual(lookup.call_args.args[:2], ("Final song", "Final singer"))
        self.assertEqual(tags.read_file(str(blank)).lyrics, found.text)

    def test_http_path_escape_and_active_scan_rejected(self):
        path = self.copy()
        result = self.job([path])[0]
        self.http(self.request([self.item(result, path="../outside.mp3")]), expected=400)
        main.jobs["test"]["status"] = "scanning"
        self.http(self.request([self.item(result)]), expected=409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
