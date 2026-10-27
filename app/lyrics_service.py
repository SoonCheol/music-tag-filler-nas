"""In-memory lyrics lookup and save-token ownership.

One LyricsService is owned by main. Root/candidate callbacks observe the current
application configuration without importing main. Network calls never acquire the
storage operation lock; the service RLock protects caches, tokens and pending work.
"""
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future

from . import storage
from .upstream import search_lyrics as original_lyrics


def lyric_response(entry):
    return {**{key: entry[key] for key in ("lyrics_id", "status", "searched", "lyrics", "synced", "message")}, "query_title": entry["key"][4], "query_artist": entry["key"][5]}


class LyricsService:
    def __init__(self, music_root, candidate_id):
        self.music_root = music_root
        self.candidate_id = candidate_id
        self._lyrics_cache = OrderedDict()
        self._lyrics_tokens = OrderedDict()
        self._lyrics_results = OrderedDict()
        self._lyrics_results_pending = {}
        self._lyrics_lock = threading.RLock()
        self.LYRICS_CACHE_LIMIT = 2000
        self.LYRICS_CACHE_TTL = 86400

    def remember_lyrics(self, key, found, searched=True, candidate_key=None):
        text = original_lyrics.clean_text(found.text) if found.status == original_lyrics.FOUND else ""
        status = "found" if text else "not_found" if found.status in (original_lyrics.FOUND, original_lyrics.NOT_FOUND, original_lyrics.NO_LYRICS, original_lyrics.INSTRUMENTAL) else "error"
        messages = {original_lyrics.BUSY: "가사 서버에 연결할 수 없습니다. 다시 시도해 주세요.",
                    original_lyrics.CONFLICT: "검색된 가사가 서로 일치하지 않아 사용할 수 없습니다.",
                    original_lyrics.NEED_TAGS: "가사 검색에 제목과 가수가 필요합니다."}
        entry = {"key": key, "candidate_id": candidate_key, "lyrics_id": uuid.uuid4().hex, "status": status, "searched": searched,
                 "lyrics": text, "synced": getattr(found, "synced", "") if text else "", "message": (getattr(found, "message", "") or messages.get(found.status, "가사 검색 오류가 발생했습니다.")) if status == "error" else "",
                 "expires": time.monotonic() + (self.LYRICS_CACHE_TTL if status == "found" else 1800 if status == "not_found" else 60)}
        with self._lyrics_lock:
            self._lyrics_cache[key] = entry
            self._lyrics_tokens[entry["lyrics_id"]] = entry
            while len(self._lyrics_tokens) > self.LYRICS_CACHE_LIMIT:
                _, old = self._lyrics_tokens.popitem(last=False)
                if self._lyrics_cache.get(old["key"]) is old:
                    self._lyrics_cache.pop(old["key"])
            self._lyrics_cache.move_to_end(key)
            while len(self._lyrics_cache) > self.LYRICS_CACHE_LIMIT:
                self._lyrics_cache.popitem(last=False)
        return entry


    def lookup_lyrics(self, job_id, path, revision, title, artist, duration, candidate=None, force=False):
        """Shared content lookup; save tokens stay bound to file, revision and candidate.

        The network runs outside OPERATION_LOCK. Exact query/version/length keys avoid
        sharing a lyric across different artists or editions. No disk cache is used.
        """
        key = (str(self.music_root().resolve()), job_id, path, revision, title, artist)
        candidate_key = self.candidate_id(candidate) if candidate else None
        edition = tuple(str((candidate or {}).get(k) or "") for k in ("title", "artist", "album", "duration"))
        content_key = (title, artist, float(duration or 0), edition)
        with self._lyrics_lock:
            existing = self._lyrics_cache.get(key)
            if not force and existing and existing["expires"] > time.monotonic() and existing.get("candidate_id") == candidate_key:
                self._lyrics_cache.move_to_end(key)
                self._lyrics_tokens.move_to_end(existing["lyrics_id"])
                if content_key in self._lyrics_results:
                    self._lyrics_results.move_to_end(content_key)
                return existing
            cached = self._lyrics_results.get(content_key)
            if cached and cached[0] <= time.monotonic():
                self._lyrics_results.pop(content_key, None)
                cached = None
            future = self._lyrics_results_pending.get(content_key)
            owner = future is None
            if cached and not force:
                self._lyrics_results.move_to_end(content_key)
                found = cached[1]
                owner = False
                future = None
            elif owner:
                future = Future()
                self._lyrics_results_pending[content_key] = future
        if future is not None:
            if owner:
                try:
                    found = original_lyrics.find(title, artist, duration) if title.strip() and artist.strip() else original_lyrics.LyricsResult(original_lyrics.NEED_TAGS)
                except Exception:
                    found = original_lyrics.LyricsResult(original_lyrics.BUSY)
                ttl = self.LYRICS_CACHE_TTL if found.status == original_lyrics.FOUND else 1800 if found.status in (original_lyrics.NOT_FOUND, original_lyrics.NO_LYRICS, original_lyrics.INSTRUMENTAL) else 60
                with self._lyrics_lock:
                    self._lyrics_results[content_key] = (time.monotonic() + ttl, found)
                    self._lyrics_results.move_to_end(content_key)
                    while len(self._lyrics_results) > self.LYRICS_CACHE_LIMIT:
                        self._lyrics_results.popitem(last=False)
                    self._lyrics_results_pending.pop(content_key, None)
                    future.set_result(found)
            else:
                found = future.result()
        # Keep a previously valid draft token usable when a refresh finds nothing/errors.
        valid = found.status == original_lyrics.FOUND and bool(found.text.strip())
        if not valid and existing and existing["expires"] > time.monotonic():
            entry = dict(existing)
            entry.update(status="not_found" if found.status in (original_lyrics.NOT_FOUND, original_lyrics.NO_LYRICS, original_lyrics.INSTRUMENTAL) else "error",
                         lyrics="", synced="", message=getattr(found, "message", "") or "가사를 찾지 못했거나 조회에 실패했습니다.")
            return entry
        with self._lyrics_lock:
            latest = self._lyrics_cache.get(key)
            if latest and latest is not existing and latest["expires"] > time.monotonic() and latest.get("candidate_id") == candidate_key:
                return latest
            return self.remember_lyrics(key, found, bool(title.strip() and artist.strip()), candidate_key)


    def selected_lyrics(self, job_id, path, revision, lyrics_id, title, artist):
        with self._lyrics_lock:
            entry = self._lyrics_tokens.get(lyrics_id)
            if not entry or entry["expires"] <= time.monotonic() or entry["key"] != (str(self.music_root().resolve()), job_id, path, revision, title, artist):
                raise storage.StorageError("가사 검색 결과가 만료되었거나 태그가 변경되었습니다. 다시 검색하세요")
            self._lyrics_tokens.move_to_end(lyrics_id)
            return entry


    def rekey_lyrics(self, event):
        remaps = []
        with self._lyrics_lock:
            for token, entry in list(self._lyrics_tokens.items()):
                key = entry["key"]
                if key[0] == str(self.music_root().resolve()) and key[2] == event["old_path"]:
                    self._lyrics_tokens.pop(token)
                    if self._lyrics_cache.get(key) is entry:
                        self._lyrics_cache.pop(key)
                    if key[3] != event["revision"]:
                        continue
                    new_key = (*key[:2], event["new_path"], *key[3:])
                    entry = {**entry, "key": new_key, "lyrics_id": uuid.uuid4().hex}
                    self._lyrics_cache[new_key] = entry
                    self._lyrics_tokens[entry["lyrics_id"]] = entry
                    remaps.append({"job_id": key[1], "old_id": token, "new_id": entry["lyrics_id"]})
        return remaps


    def legacy_lookup(self, title, artist, duration, lyric_context=None):
        context = lyric_context if lyric_context is not None else {"busy_streak": 0}
        actually_searched = context["busy_streak"] < 5
        if not actually_searched:
            found = original_lyrics.LyricsResult(original_lyrics.BUSY)
        else:
            found = original_lyrics.find(title, artist, duration)
            if found.status == original_lyrics.BUSY:
                found = original_lyrics.find(title, artist, duration)
        context["busy_streak"] = context["busy_streak"] + 1 if found.status == original_lyrics.BUSY else 0
        return found, actually_searched
