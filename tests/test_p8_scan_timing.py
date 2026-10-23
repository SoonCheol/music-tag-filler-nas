"""Scan timing and rate-limit regression: generated audio and mocked HTTP only."""
import json
import threading
import unittest
from unittest.mock import Mock, patch
import requests
import test_p0_storage as p0
from app import main, search_service, job_store
from app.upstream import net


class ThrottleTests(unittest.TestCase):
    def test_wait_rechecks_penalty_and_preserves_minimum_interval(self):
        clock = [1000.0]
        limiter = net._Throttle()
        limiter.set_interval('example', 1.05)
        applied = []
        def sleep(seconds):
            clock[0] += seconds
            if not applied:
                applied.append(True)
                limiter.slow_down('example', 5)
        with patch.object(net.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(net.time, 'sleep', side_effect=sleep):
            limiter.wait('example')
            first = clock[0]
            limiter.wait('example')
            second = clock[0]
            limiter.wait('example')
            self.assertGreaterEqual(second - first, 5)
            self.assertGreaterEqual(clock[0] - second, 2.075 - 1e-8)

    def test_cancel_does_not_reserve_future_request(self):
        limiter = net._Throttle()
        limiter.set_interval('example', 1.05)
        cancel = threading.Event()
        with patch.object(net.time, 'monotonic', return_value=1000), patch.object(net.time, 'sleep', side_effect=lambda _: cancel.set()):
            limiter.wait('example')
            before = dict(limiter._next_ok)
            limiter.wait('example', cancel)
        self.assertEqual(limiter._next_ok, before)

    def test_successful_recovery_requires_quiet_period_and_three_successes(self):
        limiter = net._Throttle()
        limiter.set_interval('musicbrainz.org', 1.05)
        with patch.object(net.time, 'monotonic', return_value=1000):
            for _ in range(5):
                limiter.slow_down('musicbrainz.org', 2)
            self.assertEqual(limiter._intervals['musicbrainz.org'], 10)
            for _ in range(3):
                limiter.succeeded('musicbrainz.org')
            self.assertEqual(limiter._intervals['musicbrainz.org'], 10)
        with patch.object(net.time, 'monotonic', return_value=1031):
            limiter.succeeded('musicbrainz.org')
            self.assertEqual(limiter._intervals['musicbrainz.org'], 1.05)
            limiter.slow_down('musicbrainz.org', 60)
        with patch.object(net.time, 'monotonic', return_value=1062):
            for _ in range(3):
                limiter.succeeded('musicbrainz.org')
            self.assertGreater(limiter._intervals['musicbrainz.org'], 1.05)

    def test_sliding_window_never_exceeds_original_limit(self):
        limiter = net._Throttle()
        limiter.set_window('example', 2, 60)
        clock = [1000.0]
        starts = []
        with patch.object(net.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(net.time, 'sleep', side_effect=lambda value: clock.__setitem__(0, clock[0] + value)):
            for _ in range(5):
                limiter.wait('example')
                starts.append(clock[0])
        self.assertEqual(starts, [1000, 1000, 1060, 1060, 1120])

    def test_network_metrics_retry_and_timeout(self):
        metrics = {}
        with patch.object(net, 'session') as session, patch.object(net.throttle, 'wait'), patch.object(net.throttle, 'slow_down'), patch.object(net.throttle, 'succeeded'), patch.object(net, '_sleep'):
            session.return_value.request.side_effect = [Mock(status_code=503, headers={}), Mock(status_code=200)]
            with net.measure_network(metrics):
                net.request('GET', 'https://musicbrainz.org/test')
            session.return_value.request.side_effect = requests.Timeout('test timeout')
            with net.measure_network(metrics), self.assertRaises(net.NetworkError):
                net.request('GET', 'https://musicbrainz.org/test')
        row = metrics['musicbrainz.org']
        self.assertEqual((row['requests'], row['retries'], row['timeouts']), (3, 1, 1))
        self.assertIn('http_seconds', row)
        self.assertIn('rate_wait_seconds', row)


class DurationTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job

    def test_pause_resume_excludes_idle_and_survives_json_reload(self):
        self.job([self.copy()])
        main.jobs['test'].update(status='queued', results=[], scanned=0, cancel_requested=False)
        clock = [100.0]
        def stop(*args, **kwargs):
            clock[0] += 3
            main.cancel_job('test')
            return {'candidates': [], 'search_status': 'cancelled'}
        with patch.object(main.time, 'perf_counter', side_effect=lambda: clock[0]), patch.object(search_service, 'search', side_effect=stop):
            main.scan_job('test', '', {'use_fingerprint': False})
        self.assertEqual(main.jobs['test']['scan_elapsed_seconds'], 3)
        clock[0] += 1000  # User leaves the stopped task idle for 1000 seconds.
        main.jobs['test'].update(status='queued', cancel_requested=False)
        def complete(*args, **kwargs):
            clock[0] += 2
            return {'candidates': [], 'search_status': 'not_found', '_timing': {'fake': True}}
        with patch.object(main.time, 'perf_counter', side_effect=lambda: clock[0]), patch.object(search_service, 'search', side_effect=complete):
            main.scan_job('test', '', {'use_fingerprint': False}, resume=True)
        job = main.jobs['test']
        self.assertEqual((job['scan_elapsed_seconds'], job['scan_segment_seconds']), (5, 2))
        persisted = json.loads(job_store.record_path(self.data, 'test').read_text())
        self.assertEqual(persisted['scan_elapsed_seconds'], 5)
        self.assertNotIn('_timing', persisted['results'][0])
        self.assertNotIn('test', main._scan_clocks)


if __name__ == '__main__':
    unittest.main(verbosity=2)
