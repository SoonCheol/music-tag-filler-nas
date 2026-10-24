"""Mocked search HTTP and generated files only; no production music writes."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_p0_storage as p0
from app import main, preferences, search_service
from app.upstream import net, search_itunes, search_mb

URL = search_itunes.SEARCH_URL
PARAMS = {'term': 'Elvis - Song (Live)', 'country': 'US', 'entity': 'song', 'limit': 20}


class SearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = net._SearchCache()
        replacement = {host: net._SearchCache() for host in net._search_caches}
        replacement['itunes.apple.com'] = self.cache
        self.patcher = patch.dict(net._search_caches, replacement)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_raw_response_copies_and_parameter_keys(self):
        raw = {'results': [{'trackName': 'Song', 'nested': ['original']}]}
        with patch.object(net, 'get_json', return_value=raw) as fetch:
            first = net.search_json(URL, PARAMS)
            first['results'][0]['nested'].append('edited')
            second = net.search_json(URL, dict(reversed(list(PARAMS.items()))))
            self.assertEqual(second, raw)
            for params in ({**PARAMS, 'country': 'JP'}, {**PARAMS, 'limit': 10},
                           {**PARAMS, 'term': 'Elvis - Song'},
                           {**PARAMS, 'term': 'Elvis - Song (Remaster)'},
                           {**PARAMS, 'term': 'Elvis - Song (Remix)'}):
                net.search_json(URL, params)
            self.assertEqual(fetch.call_count, 6)
        self.assertEqual(self.cache.max_entries, 500)
        self.assertEqual(self.cache.ttl, 86400)

    def test_expiry_empty_expiry_and_lru(self):
        cache = net._SearchCache(max_entries=2)
        clock = [1000.0]
        calls = []
        def get(key, value):
            return cache.get(key, lambda cancel: calls.append(key) or value,
                             empty=lambda row: not row['results'], host='test')
        with patch.object(net.time, 'monotonic', side_effect=lambda: clock[0]):
            get('a', {'results': [1]}); get('b', {'results': [2]})
            get('a', {'results': [99]}); get('c', {'results': [3]})
            get('b', {'results': [2]})  # b was least recently used.
            self.assertEqual(calls, ['a', 'b', 'c', 'b'])
            get('empty', {'results': []})
            clock[0] += 59
            get('empty', {'results': []})
            self.assertEqual(calls.count('empty'), 1)
            clock[0] += 2
            get('empty', {'results': []})
            self.assertEqual(calls.count('empty'), 2)
            get('full', {'results': [1]})
            clock[0] += 86399
            get('full', {'results': [1]})
            self.assertEqual(calls.count('full'), 1)
            clock[0] += 2
            get('full', {'results': [1]})
            self.assertEqual(calls.count('full'), 2)

    def test_errors_not_cached_and_failed_refresh_keeps_good_cache(self):
        good = {'results': [{'trackName': 'Good'}]}
        with patch.object(net, 'get_json', return_value=good) as fetch:
            net.search_json(URL, PARAMS)
            for failure in (net.RateLimited(2), net.NetworkError('timeout'),
                            net.NetworkError('HTTP 429'), net.NetworkError('HTTP 503')):
                fetch.side_effect = failure
                with self.assertRaises(type(failure)):
                    net.search_json(URL, PARAMS, force=True)
                self.assertEqual(net.search_json(URL, PARAMS), good)
            fetch.side_effect = None
            fetch.return_value = {'results': [{'trackName': 'Latest'}]}
            self.assertEqual(net.search_json(URL, PARAMS, force=True)['results'][0]['trackName'], 'Latest')
            count = fetch.call_count
            net.search_json(URL, PARAMS)
            self.assertEqual(fetch.call_count, count)
            fetch.side_effect = net.NetworkError('timeout')
            for _ in range(2):
                with self.assertRaises(net.NetworkError):
                    net.search_json(URL, {**PARAMS, 'term': 'missing'})
            self.assertEqual(fetch.call_count, count + 2)

    def test_invalid_response_is_not_cached(self):
        with patch.object(net, 'get_json', return_value={'error': 'unavailable'}) as fetch:
            for _ in range(2):
                with self.assertRaises(net.NetworkError):
                    net.search_json(URL, PARAMS)
            self.assertEqual(fetch.call_count, 2)

    def test_same_requests_share_and_owner_cancel_does_not_cancel_follower(self):
        entered, release, owner_cancel = threading.Event(), threading.Event(), threading.Event()
        observed_cancel = []
        callbacks = []
        stats = [{}, {}, {}]
        def load(url, params, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            observed_cancel.append(kwargs['cancel'].is_set())
            kwargs['on_wait'](2)
            return {'results': [{'trackName': 'Shared'}]}
        def search(index):
            with net.measure_network(stats[index]):
                return net.search_json(URL, PARAMS, cancel=owner_cancel if index == 0 else None, on_wait=lambda seconds: callbacks.append(index))
        with patch.object(net, 'get_json', side_effect=load) as fetch, ThreadPoolExecutor(max_workers=3) as pool:
            owner = pool.submit(search, 0)
            self.assertTrue(entered.wait(2))
            followers = [pool.submit(search, i) for i in (1, 2)]
            deadline = time.monotonic() + 2
            while sum(row.get('itunes.apple.com', {}).get('shared_requests', 0) for row in stats) < 2 and time.monotonic() < deadline:
                time.sleep(.001)
            owner_cancel.set()
            try:
                with self.assertRaises(net.NetworkError):
                    owner.result(timeout=2)
            finally:
                release.set()
            values = [f.result(timeout=2) for f in followers]
            values[0]['results'][0]['trackName'] = 'Edited'
            self.assertEqual(values[1]['results'][0]['trackName'], 'Shared')
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(observed_cancel, [False])
        self.assertEqual(callbacks, [])
        self.assertEqual(sum(row.get('itunes.apple.com', {}).get('shared_requests', 0) for row in stats), 2)

    def test_different_queries_run_in_parallel(self):
        barrier = threading.Barrier(2)
        def load(url, params, **kwargs):
            barrier.wait(timeout=2)
            return {'results': [{'trackName': params['term']}]}
        with patch.object(net, 'get_json', side_effect=load), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(net.search_json, URL, {**PARAMS, 'term': title}) for title in ('A', 'B')]
            self.assertEqual({f.result(timeout=3)['results'][0]['trackName'] for f in futures}, {'A', 'B'})

    def test_late_old_response_cannot_replace_new_refresh(self):
        entered, release = threading.Event(), threading.Event()
        def load(url, params, **kwargs):
            if not entered.is_set():
                entered.set()
                self.assertTrue(release.wait(3))
                return {'results': [{'trackName': 'Old'}]}
            return {'results': [{'trackName': 'New'}]}
        with patch.object(net, 'get_json', side_effect=load) as fetch, ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(net.search_json, URL, PARAMS)
            self.assertTrue(entered.wait(2))
            try:
                self.assertEqual(net.search_json(URL, PARAMS, force=True)['results'][0]['trackName'], 'New')
            finally:
                release.set()
            self.assertEqual(old.result(timeout=2)['results'][0]['trackName'], 'Old')
            self.assertEqual(net.search_json(URL, PARAMS)['results'][0]['trackName'], 'New')
            self.assertEqual(fetch.call_count, 2)

    def test_shared_wait_has_deadline_and_can_be_cancelled(self):
        cache = net._SearchCache(wait_timeout=.02)
        def load(cancel):
            cancel.wait(2)
            raise net.NetworkError('cancelled')
        with self.assertRaisesRegex(net.NetworkError, 'timeout'):
            cache.get('key', load, empty=lambda value: False, host='test')

    def test_loader_timeout_is_propagated_without_repeated_waiting(self):
        def load(cancel):
            raise TimeoutError("loader timeout")
        with self.assertRaisesRegex(TimeoutError, "loader timeout"):
            self.cache.get('timeout', load, empty=lambda value: False, host='test')

    def test_raw_candidates_are_scored_independently_and_no_fingerprint_when_off(self):
        raw = {'results': [{'trackName': 'Song', 'artistName': 'Singer', 'trackTimeMillis': 180000, 'trackId': 1}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(net, 'get_json', return_value=raw) as fetch, patch.object(search_mb, 'search', return_value=[]), patch.object(search_service, 'sound') as sound:
            first = search_service.search(Path('unused.mp3'), 'Singer - Song', 'US', 180, folder)
            second = search_service.search(Path('unused.mp3'), 'Singer - Song', 'US', 300, folder)
            self.assertEqual(fetch.call_count, 1)
            self.assertNotEqual(first['candidates'][0]['score'], second['candidates'][0]['score'])
            self.assertNotIn('score', raw['results'][0])
            sound.assert_not_called()
        with tempfile.TemporaryDirectory() as folder, patch.object(search_itunes, 'search', return_value=[]), patch.object(search_mb, 'search', return_value=[]), patch.object(search_service, 'sound', return_value=([], [])) as sound:
            search_service.search(Path('unused.mp3'), 'Singer - Unknown', 'US', 180, folder)
            sound.assert_not_called()
            search_service.search(Path('unused.mp3'), 'Singer - Unknown', 'US', 180, folder, mode='sound')
            sound.assert_called_once()

    def test_fingerprint_default_and_saved_true_preserved(self):
        self.assertFalse(main.ScanRequest().use_fingerprint)
        self.assertFalse(main.SearchRequest(path='song.mp3').use_fingerprint)
        self.assertFalse(preferences.Preferences().use_fingerprint)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({'use_fingerprint': True, 'fill_lyrics': True}))
            self.assertTrue(preferences.read(folder).use_fingerprint)
            self.assertTrue(preferences.read(folder).fill_lyrics)


if __name__ == '__main__':
    unittest.main(verbosity=2)
