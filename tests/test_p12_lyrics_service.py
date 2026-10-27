"""Service policy tests: isolated memory and temporary paths only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.lyrics_service import LyricsService
from app.upstream import search_lyrics as upstream
from app import storage


class LyricsServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.service = LyricsService(lambda: self.root, lambda c: c['id'])

    def test_status_ttl_and_expired_token(self):
        for status, text, ttl in [(upstream.FOUND, 'Verified lyric text', 86400),
                                  (upstream.NOT_FOUND, '', 1800),
                                  (upstream.NO_LYRICS, '', 1800),
                                  (upstream.INSTRUMENTAL, '', 1800),
                                  (upstream.BUSY, '', 60),
                                  (upstream.CONFLICT, '', 60)]:
            with self.subTest(status=status), patch('app.lyrics_service.time.monotonic', return_value=100):
                self.service = LyricsService(lambda: self.root, lambda c: c['id'])
                with patch.object(upstream, 'find', return_value=upstream.LyricsResult(status, text)):
                    entry = self.service.lookup_lyrics('job', 'a.mp3', 'rev', 'Song', 'Singer', 10, force=True)
                self.assertEqual(entry['expires'], 100 + ttl)
                self.assertEqual(next(iter(self.service._lyrics_results.values()))[0], 100 + ttl)
            with patch('app.lyrics_service.time.monotonic', return_value=100 + ttl):
                with self.assertRaises(storage.StorageError):
                    self.service.selected_lyrics('job', 'a.mp3', 'rev', entry['lyrics_id'], 'Song', 'Singer')

    def test_legacy_retry_and_batch_busy_policy(self):
        busy = upstream.LyricsResult(upstream.BUSY)
        context = {'busy_streak': 4}
        with patch.object(upstream, 'find', return_value=busy) as find:
            self.assertTrue(self.service.legacy_lookup('Song', 'Singer', 10, context)[1])
            self.assertEqual(find.call_count, 2)
            self.assertEqual(context['busy_streak'], 5)
            self.assertFalse(self.service.legacy_lookup('Song', 'Singer', 10, context)[1])
            self.assertEqual(find.call_count, 2)
        context['busy_streak'] = 0
        found = upstream.LyricsResult(upstream.FOUND, 'Verified lyric')
        with patch.object(upstream, 'find', side_effect=[busy, found]) as find:
            self.assertIs(self.service.legacy_lookup('Song', 'Singer', 10, context)[0], found)
            self.assertEqual(context['busy_streak'], 0)

    def test_provider_error_message_survives_service_mapping(self):
        failure = upstream.LyricsResult(upstream.BUSY, message='LRCLIB API 오류 (HTTP 502).')
        with patch.object(upstream, 'find', return_value=failure):
            entry = self.service.lookup_lyrics('job', 'a.mp3', 'rev', 'Song', 'Singer', 180, force=True)
        self.assertEqual(entry['status'], 'error')
        self.assertEqual(entry['message'], 'LRCLIB API 오류 (HTTP 502).')

    def test_instance_isolation_and_root_binding(self):
        key = (str(self.root.resolve()), 'job', 'a.mp3', 'rev', 'Song', 'Singer')
        entry = self.service.remember_lyrics(key, upstream.LyricsResult(upstream.FOUND, 'Verified lyric'))
        other = LyricsService(lambda: self.root, lambda c: c['id'])
        self.assertFalse(other._lyrics_tokens)
        self.root = self.root / 'other'
        with self.assertRaises(storage.StorageError):
            self.service.selected_lyrics('job', 'a.mp3', 'rev', entry['lyrics_id'], 'Song', 'Singer')
