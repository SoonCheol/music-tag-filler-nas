"""HTTP helpers shared by the search modules.

One session with the app's User-Agent, a per-host minimum interval between
requests, and retry on 429/503 with the wait reported through a callback so
the UI can show it. Only query strings and fingerprints ever leave the
machine; no audio file is uploaded anywhere.
"""
from __future__ import annotations

import collections
import copy
import json
from concurrent.futures import Future, TimeoutError as FutureTimeout
from contextlib import contextmanager
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import requests

APP_NAME = "music-tag-filler"
APP_VERSION = "2.0.0"  # sent in the User-Agent; MusicBrainz asks for the real version — bump with each release
APP_URL = "https://github.com/microhan1/music-tag-filler"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} ( {APP_URL} )"

TIMEOUT = 15
MAX_RETRIES = 3

WaitCallback = Callable[[float], None]


class NetworkError(Exception):
    """No connection, DNS failure, timeout: the caller should say 'offline'."""


class RateLimited(Exception):
    """Gave up after repeated 429 responses."""

    def __init__(self, wait: float) -> None:
        super().__init__(f"rate limited, wait {wait:.0f}s")
        self.wait = wait


class _Throttle:
    """Per-host rate limiting. A host has either a fixed interval between
    requests, or a sliding window ("at most N requests in any S seconds"), which
    lets a single search go out immediately and only paces long batches."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_ok: dict[str, float] = {}
        self._intervals: dict[str, float] = {}
        self._windows: dict[str, tuple[int, float]] = {}
        self._history: dict[str, collections.deque] = {}
        self._base_intervals: dict[str, float] = {}
        self._base_windows: dict[str, tuple[int, float]] = {}
        self._recover_after: dict[str, float] = {}
        self._successes: dict[str, int] = {}

    def set_interval(self, host: str, seconds: float) -> None:
        self._intervals[host] = seconds
        self._base_intervals[host] = seconds

    def set_window(self, host: str, count: int, seconds: float) -> None:
        self._windows[host] = (count, seconds)
        self._base_windows[host] = (count, seconds)
        self._history[host] = collections.deque()

    def _reserve(self, host: str) -> float:
        """Book the next slot for host and return how long to sleep before using it."""
        now = time.monotonic()
        start = max(now, self._next_ok.get(host, 0.0))  # a 429 penalty pushes everything out
        if host in self._windows:
            count, seconds = self._windows[host]
            hist = self._history[host]
            start = max(start, hist[-1] if hist else start)
            while hist and hist[0] <= start - seconds:
                hist.popleft()
            while len(hist) >= count:
                start = max(start, hist[0] + seconds)
                while hist and hist[0] <= start - seconds:
                    hist.popleft()
            hist.append(start)
        else:
            start += 0.0
            self._next_ok[host] = start + self._intervals.get(host, 0.0)
        return start - now

    def wait(self, host: str, cancel: threading.Event | None = None) -> None:
        # Book actual starts, not future slots. A Retry-After received while
        # another worker sleeps must delay that worker too; cancelled workers
        # must not consume future slots. Recheck under the short host-state lock.
        while cancel is None or not cancel.is_set():
            with self._lock:
                now = time.monotonic()
                delay = self._next_ok.get(host, 0.0) - now
                if host in self._windows:
                    count, span = self._windows[host]
                    hist = self._history[host]
                    while hist and hist[0] <= now - span:
                        hist.popleft()
                    if len(hist) >= count:
                        delay = max(delay, hist[0] + span - now)
                if delay <= 0:
                    self._reserve(host)
                    return
            time.sleep(min(delay, 0.2))

    def succeeded(self, host: str) -> None:
        with self._lock:
            if host not in self._recover_after:
                return
            self._successes[host] = self._successes.get(host, 0) + 1
            # Recovery requires successful traffic AND a quiet period, never a
            # new scan, so repeated scan clicks cannot reset server backoff.
            if self._successes[host] < 3 or time.monotonic() < self._recover_after[host]:
                return
            if host in self._base_intervals:
                self._intervals[host] = self._base_intervals[host]
            if host in self._base_windows:
                self._windows[host] = self._base_windows[host]
            del self._recover_after[host]
            self._successes.pop(host, None)

    def slow_down(self, host: str, seconds: float) -> None:
        """After a 429, hold the host for `seconds` and pace it more conservatively."""
        with self._lock:
            self._recover_after[host] = time.monotonic() + max(seconds, 60.0 if host in self._windows else 30.0)
            self._successes[host] = 0
            self._next_ok[host] = max(self._next_ok.get(host, 0.0), time.monotonic() + seconds)
            if host in self._windows:
                count, span = self._windows[host]
                self._windows[host] = (max(1, count - count // 4), span)
            else:
                self._intervals[host] = min(10.0, self._intervals.get(host, 0.0) * 1.5 + 0.5)


throttle = _Throttle()
throttle.set_window("itunes.apple.com", 20, 60.0)  # Apple: about 20 requests per minute
throttle.set_interval("musicbrainz.org", 1.05)  # 1 request per second
throttle.set_interval("api.acoustid.org", 0.35)  # 3 requests per second
throttle.set_interval("lrclib.net", 0.3)  # docs: one request at a time, 200-500 ms apart

# Hosts whose 503 means "busy right now" (Retry-After: 1), not "you are too fast".
# MusicBrainz answers 503 when a client exceeds its rate, so there a 503 slows the
# host down; LRCLIB answers 503 under load whatever the pace (measured: the same
# 17-47% at 0.3 s and 1 s gaps), and slowing down for good only made a batch crawl.
OVERLOAD_503_HOSTS = {"lrclib.net"}
# coverartarchive.org has no published limit; thumbnails are fetched in parallel

_session: requests.Session | None = None
_session_lock = threading.Lock()


def session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            s.headers["User-Agent"] = USER_AGENT
            s.headers["Accept"] = "application/json, image/*;q=0.8, */*;q=0.5"
            _session = s
        return _session


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()



_timing = threading.local()


@contextmanager
def measure_network(metrics):
    previous = getattr(_timing, "metrics", None)
    _timing.metrics = metrics
    try:
        yield
    finally:
        _timing.metrics = previous


def _metric(host, name, value):
    metrics = getattr(_timing, "metrics", None)
    if metrics is not None:
        row = metrics.setdefault(host, {})
        row[name] = row.get(name, 0) + value


def request(method: str, url: str, *, params: dict | None = None, data: dict | None = None,
            on_wait: WaitCallback | None = None, cancel: threading.Event | None = None,
            stream: bool = False) -> requests.Response:
    """GET/POST with throttling and 429/503 retry. Raises NetworkError or RateLimited."""
    host = _host(url)
    last_wait = 0.0
    for attempt in range(MAX_RETRIES + 1):
        if cancel is not None and cancel.is_set():
            raise NetworkError("cancelled")
        tick = time.perf_counter()
        throttle.wait(host, cancel)
        _metric(host, "rate_wait_seconds", time.perf_counter() - tick)
        if cancel is not None and cancel.is_set():
            raise NetworkError("cancelled")
        tick = time.perf_counter()
        _metric(host, "requests", 1)
        try:
            resp = session().request(method, url, params=params, data=data, timeout=TIMEOUT, stream=stream)
        except requests.RequestException as exc:
            _metric(host, "errors", 1)
            _metric(host, "timeouts", int(isinstance(exc, requests.Timeout)))
            raise NetworkError(str(exc)) from exc
        finally:
            _metric(host, "http_seconds", time.perf_counter() - tick)
        _metric(host, "status_" + str(resp.status_code), 1)
        if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
            _metric(host, "retries", 1)
            resp.close()
            if resp.status_code == 503 and host in OVERLOAD_503_HOSTS:
                # back off 1, 2, 4 s for this request only; the host keeps its pace
                wait = max(_retry_after(resp, default=1.0), float(2 ** attempt))
                last_wait = wait
                tick = time.perf_counter()
                _sleep(wait, cancel)
                _metric(host, "retry_sleep_seconds", time.perf_counter() - tick)
                continue
            wait = _retry_after(resp, default=2.0 * (attempt + 1))
            last_wait = wait
            throttle.slow_down(host, wait)
            if on_wait is not None:
                on_wait(wait)
            tick = time.perf_counter()
            _sleep(wait, cancel)
            _metric(host, "retry_sleep_seconds", time.perf_counter() - tick)
            continue
        if resp.status_code in (429, 503):
            raise RateLimited(last_wait or 5.0)
        if resp.status_code < 400:
            throttle.succeeded(host)
        return resp
    raise RateLimited(last_wait or 5.0)  # pragma: no cover - loop always returns or raises


def get_json(url: str, params: dict | None = None, *, on_wait: WaitCallback | None = None,
             cancel: threading.Event | None = None) -> dict:
    resp = request("GET", url, params=params, on_wait=on_wait, cancel=cancel)
    if resp.status_code >= 400:
        raise NetworkError(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise NetworkError("bad json") from exc
    return data if isinstance(data, dict) else {}



class _SearchFlight:
    def __init__(self):
        self.future = Future()
        self.cancel = threading.Event()
        self.users = 0
        self.started = time.monotonic()


class _SearchCache:
    """Bounded raw-response LRU with independent subscribers and fresh generations."""
    def __init__(self, max_entries=500, ttl=86400.0, empty_ttl=60.0, wait_timeout=600.0):
        self.max_entries, self.ttl, self.empty_ttl = max_entries, ttl, empty_ttl
        self.wait_timeout = wait_timeout
        self._lock = threading.Lock()
        self._values = collections.OrderedDict()
        self._pending = {}

    def get(self, key, loader, *, empty, host, cancel=None, force=False):
        if cancel is not None and cancel.is_set():
            raise NetworkError("cancelled")
        _metric(host, "cache_lookups", 1)
        if force:
            _metric(host, "cache_forced", 1)
        with self._lock:
            cached = self._values.get(key)
            if not force and cached is not None:
                if cached[0] > time.monotonic():
                    self._values.move_to_end(key)
                    _metric(host, "cache_hits", 1)
                    return copy.deepcopy(cached[1])
                del self._values[key]
            # A refresh must never join an older ordinary request. Its flight
            # replaces the publication token; old flights can finish for their
            # own subscribers but cannot overwrite newer cache generations.
            flight = None if force else self._pending.get(key)
            if flight is not None and flight.future.done():
                flight = None
            owner = flight is None
            if owner:
                flight = _SearchFlight()
                self._pending[key] = flight
            flight.users += 1
        if owner:
            _metric(host, "cache_misses", 1)
            metrics = getattr(_timing, "metrics", None)
            def fetch():
                try:
                    with measure_network(metrics):
                        value = loader(flight.cancel)
                    lifetime = self.empty_ttl if empty(value) else self.ttl
                    with self._lock:
                        if flight.cancel.is_set():
                            raise NetworkError("cancelled")
                        if self._pending.get(key) is flight:
                            self._values[key] = (time.monotonic() + lifetime, copy.deepcopy(value))
                            self._values.move_to_end(key)
                            while len(self._values) > self.max_entries:
                                self._values.popitem(last=False)
                    flight.future.set_result(value)
                except BaseException as exc:
                    flight.future.set_exception(exc)
                finally:
                    with self._lock:
                        if self._pending.get(key) is flight:
                            del self._pending[key]
            threading.Thread(target=fetch, name="search-response", daemon=True).start()
        else:
            _metric(host, "shared_requests", 1)
        started = time.perf_counter()
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise NetworkError("cancelled")
                if time.monotonic() - flight.started >= self.wait_timeout:
                    raise NetworkError("shared search timeout")
                try:
                    return copy.deepcopy(flight.future.result(timeout=0.1))
                except FutureTimeout:
                    if flight.future.done():
                        return copy.deepcopy(flight.future.result())
                    continue
        finally:
            if not owner:
                _metric(host, "shared_wait_seconds", time.perf_counter() - started)
            with self._lock:
                flight.users -= 1
                if not flight.users and not flight.future.done():
                    flight.cancel.set()
                    if self._pending.get(key) is flight:
                        del self._pending[key]


_search_caches = {host: _SearchCache() for host in ("itunes.apple.com", "musicbrainz.org")}


def search_json(url: str, params: dict, *, on_wait=None, cancel=None, force=False):
    """Cache only validated song-search JSON, before parsing/scoring candidates.

    No normalization: query punctuation, Live/Remix/Remaster text, storefront,
    limits and every other actual request parameter remain part of the key.
    Covers, lyrics and fingerprint requests continue through their own paths.
    """
    host = _host(url)
    key = (url, json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    field = "results" if host == "itunes.apple.com" else "recordings"
    def waiting(seconds):
        if on_wait is not None and (cancel is None or not cancel.is_set()):
            on_wait(seconds)
    def load(shared_cancel):
        value = get_json(url, params, on_wait=waiting if on_wait else None, cancel=shared_cancel)
        if not isinstance(value.get(field), list) or any(not isinstance(row, dict) for row in value[field]):
            raise NetworkError("bad json search results")
        return value
    return _search_caches[host].get(key, load, empty=lambda value: not value[field],
                                     host=host, cancel=cancel, force=force)


def get_bytes(url: str, *, max_bytes: int = 20 * 1024 * 1024, on_wait: WaitCallback | None = None,
              cancel: threading.Event | None = None) -> bytes | None:
    """Download a small binary (cover art). None on 404 or when too large."""
    resp = request("GET", url, on_wait=on_wait, cancel=cancel, stream=True)
    if resp.status_code != 200:
        resp.close()
        return None
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(64 * 1024):
        if cancel is not None and cancel.is_set():
            resp.close()
            return None
        total += len(chunk)
        if total > max_bytes:
            resp.close()
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def online(timeout: float = 4.0) -> bool:
    """Cheap connectivity probe against a search host (HEAD, no throttle)."""
    for url in ("https://itunes.apple.com/", "https://musicbrainz.org/"):
        try:
            session().head(url, timeout=timeout, allow_redirects=False)
            return True
        except requests.RequestException:
            continue
    return False


def _retry_after(resp: requests.Response, default: float) -> float:
    value = resp.headers.get("Retry-After")
    if value:
        try:
            return min(60.0, max(0.5, float(value)))
        except ValueError:
            pass
    return default


def _sleep(seconds: float, cancel: threading.Event | None) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel is not None and cancel.is_set():
            return
        time.sleep(min(0.2, end - time.monotonic()))
