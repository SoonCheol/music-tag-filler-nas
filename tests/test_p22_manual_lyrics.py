"""Manual-only lyric policy, using generated audio and temporary runtime roots."""
import copy
import unittest
from unittest.mock import patch
import test_p0_storage as p0
from app import main, storage
from app.upstream import search_lyrics as lyrics, net


class ManualLyricsTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    http = p0.P0Tests.http

    def records(self):
        base = {"trackName": "Edited Song", "artistName": "Edited Singer", "albumName": "Fixture"}
        return [{**base, "id": 1, "duration": 241, "plainLyrics": "Flowers blossom gently underneath the golden summer sunshine", "syncedLyrics": "[04:00.00]Flowers blossom gently"},
                {**base, "id": 2, "duration": 300, "plainLyrics": "Zigzag quartz rhythms explode beyond mysterious purple galaxies"}]

    def search(self, row, **changes):
        body = {"path": row["path"], "expected_revision": row["original"]["revision"],
                "title": "Edited Song", "artist": "Edited Singer", "force": True}
        body.update(changes)
        return self.http(body, "/api/jobs/test/lyrics-search")

    def test_manual_choices_ignore_file_length_and_keep_music_and_job_unchanged(self):
        path = self.copy("manual.mp3")
        row = self.job([path])[0]
        before = path.read_bytes(), path.stat().st_mtime_ns, copy.deepcopy(main.jobs)
        with patch.object(lyrics, "_search", side_effect=[self.records(), []]) as search:
            result = self.search(row)
        self.assertEqual(result["status"], "found")
        self.assertEqual([c["record_id"] for c in result["choices"]], [1, 2])
        self.assertEqual(search.call_args_list[0].args[0], {"track_name": "Edited Song", "artist_name": "Edited Singer"})
        self.assertEqual(search.call_args_list[1].args[0], {"q": "EditedSinger Edited Song"})
        self.assertNotIn("duration", search.call_args_list[0].args[0])
        self.assertEqual((result["query_title"], result["query_artist"]), ("Edited Song", "Edited Singer"))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, main.jobs), before)
        self.assertFalse(self.backups.exists())
        for choice in result["choices"]:
            entry = main.selected_lyrics("test", row["path"], row["original"]["revision"], choice["lyrics_id"], "Edited Song", "Edited Singer")
            self.assertEqual(entry["lyrics"], choice["lyrics"])
            with self.assertRaises(storage.StorageError):
                main.selected_lyrics("test", row["path"], row["original"]["revision"], choice["lyrics_id"], "Original song", "Edited Singer")

    def test_manual_retains_title_artist_version_and_text_validation(self):
        records = self.records()
        invalid = [{**records[0], "id": 3, "artistName": "Other"}, {**records[0], "id": 4, "trackName": "Different"},
                   {**records[0], "id": 5, "trackName": "Edited Song (Instrumental)"},
                   {**records[0], "id": 6, "plainLyrics": "", "syncedLyrics": ""}]
        with patch.object(lyrics, "_search", side_effect=[records + invalid, []]):
            found = lyrics.find("Edited Song", "Edited Singer", 0, manual=True)
        self.assertEqual([c["record_id"] for c in found.choices], [1, 2])
        self.assertEqual(lyrics.pick(records, "Edited Song", "Edited Singer", 180)[0], lyrics.NOT_FOUND)
        matching = [{**record, "duration": 180, "syncedLyrics": ""} for record in records]
        self.assertEqual(lyrics.pick(matching, "Edited Song", "Edited Singer", 180)[0], lyrics.CONFLICT)
        self.assertEqual(lyrics.pick([matching[0]], "Edited Song", "Edited Singer", 180)[0], lyrics.FOUND)
        self.assertEqual(lyrics.pick([{**matching[0], "syncedLyrics": "[04:00.00]Too late"}], "Edited Song", "Edited Singer", 180)[0], lyrics.NOT_FOUND)

    def test_manual_and_automatic_cache_policies_are_separate(self):
        service = main._lyrics_service
        args = ("test", "a.mp3", "revision", "Edited Song", "Edited Singer", 180)
        with patch.object(lyrics, "_search", side_effect=[self.records(), [], self.records(), [], self.records(), []]) as search:
            manual = service.lookup_lyrics(*args, manual=True)
            automatic = service.lookup_lyrics(*args)
            manual_again = service.lookup_lyrics(*args, manual=True)
        self.assertEqual((manual["status"], automatic["status"], manual_again["status"]), ("found", "not_found", "found"))
        self.assertEqual(search.call_count, 4)
        with patch.object(lyrics, "find", return_value=lyrics.LyricsResult(lyrics.NOT_FOUND)) as find:
            service.legacy_lookup("Edited Song", "Edited Singer", 180)
        find.assert_called_once_with("Edited Song", "Edited Singer", 180)

    def test_no_results_api_errors_and_network_errors_are_distinct(self):
        path = self.copy("states.mp3")
        row = self.job([path])[0]
        cases = [([[], []], "not_found", ""), ([net.NetworkError("HTTP 502")], "error", "API 오류"),
                 ([net.NetworkError("timeout")], "error", "연결 오류")]
        for responses, status, message in cases:
            with patch.object(lyrics, "_search", side_effect=responses):
                result = self.search(row)
            self.assertEqual(result["status"], status)
            self.assertIn(message, result["message"])

    def test_choice_tokens_follow_existing_rename_rekey(self):
        args = ("test", "before.mp3", "revision", "Edited Song", "Edited Singer", 0)
        with patch.object(lyrics, "_search", side_effect=[self.records(), []]):
            found = main._lyrics_service.lookup_lyrics(*args, manual=True)
        remaps = main._lyrics_service.rekey_lyrics({"old_path": "before.mp3", "new_path": "after.mp3", "revision": "revision"})
        mapping = {r["old_id"]: r["new_id"] for r in remaps}
        first = main.selected_lyrics("test", "after.mp3", "revision", mapping[found["lyrics_id"]], "Edited Song", "Edited Singer")
        for choice in first["choices"]:
            main.selected_lyrics("test", "after.mp3", "revision", choice["lyrics_id"], "Edited Song", "Edited Singer")
