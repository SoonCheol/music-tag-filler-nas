"""Focused provider-selection checks using mocked APIs and no music files."""
from pathlib import Path
import unittest
from unittest.mock import patch

from app import search_service
from app.request_models import ScanRequest, SearchRequest
from app.upstream import match, net


DATA_ROOT = Path(__file__).parent


class SearchModeTests(unittest.TestCase):
    def search(self, search_mode, itunes_rows=None, mb_rows=None, itunes_error=None):
        with patch.object(search_service.search_itunes, "search", return_value=itunes_rows or []) as itunes, \
                patch.object(search_service.search_mb, "search", return_value=mb_rows or []) as musicbrainz:
            if itunes_error:
                itunes.side_effect = itunes_error
            result = search_service.search(
                "unused.mp3", "Singer - Song", "US", 180, DATA_ROOT,
                search_mode=search_mode)
        return result, itunes, musicbrainz

    def test_four_modes_target_the_expected_providers(self):
        checks = {
            "integrated": (1, 1),
            "itunes": (1, 0),
            "musicbrainz": (0, 1),
        }
        for mode, counts in checks.items():
            with self.subTest(mode=mode):
                _, itunes, musicbrainz = self.search(mode)
                self.assertEqual((itunes.call_count, musicbrainz.call_count), counts)

        good = match.Candidate(title="Song", artist="Singer", length=180, sources=["iTunes"])
        result, itunes, musicbrainz = self.search("quick", [good])
        self.assertEqual((itunes.call_count, musicbrainz.call_count), (1, 0))
        self.assertTrue(result["musicbrainz_skipped"])

    def test_quick_search_falls_through_when_existing_auto_pick_rejects_candidate(self):
        candidates = [
            match.Candidate(title="Song", artist="Someone Else", length=180, sources=["iTunes"]),
            match.Candidate(title="Song", artist="Singer", length=190, sources=["iTunes"]),
            match.Candidate(title="Song Live", artist="Singer", length=180, sources=["iTunes"]),
        ]
        for candidate in candidates:
            with self.subTest(candidate=(candidate.title, candidate.artist, candidate.length)):
                result, itunes, musicbrainz = self.search("quick", [candidate])
                self.assertEqual((itunes.call_count, musicbrainz.call_count), (1, 1))
                self.assertFalse(result["musicbrainz_skipped"])

    def test_quick_search_falls_through_on_no_candidate_or_itunes_error(self):
        for error in (None, net.NetworkError("HTTP 503")):
            with self.subTest(error=error):
                result, itunes, musicbrainz = self.search("quick", itunes_error=error)
                self.assertEqual((itunes.call_count, musicbrainz.call_count), (1, 1))
                self.assertFalse(result["musicbrainz_skipped"])

    def test_job_and_manual_search_default_to_integrated_and_accept_all_modes(self):
        self.assertEqual(ScanRequest().search_mode, "integrated")
        self.assertEqual(SearchRequest(path="song.mp3").search_mode, "integrated")
        for mode in ("integrated", "itunes", "musicbrainz", "quick"):
            self.assertEqual(ScanRequest(search_mode=mode).model_dump()["search_mode"], mode)
            self.assertEqual(SearchRequest(path="song.mp3", search_mode=mode).search_mode, mode)
        with self.assertRaises(ValueError):
            ScanRequest(search_mode="unknown")


if __name__ == "__main__":
    unittest.main()
