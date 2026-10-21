"""Search/cover orchestration over pinned upstream logic; no music writes."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields
import io
import json
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace

from PIL import Image
from . import storage
from .upstream import match, net, pipeline, search_acoustid, search_itunes, search_mb, search_lyrics, tags

COUNTRIES = search_itunes.COUNTRIES
_CANDIDATE_FIELDS = {field.name for field in fields(match.Candidate)}
_cover_cache = OrderedDict()
_cover_lock = threading.Lock()
_COVER_CACHE_BYTES = 32 * 1024 * 1024


def error(source, code, message, **extra):
    return {"source": source, "code": code, "message": message, **extra}


def configuration(data_root):
    problems = []
    path = Path(data_root) / "settings.json"
    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(settings, dict):
                raise ValueError("settings must be an object")
        except (OSError, ValueError):
            settings = {}
            problems.append(error("configuration", "invalid_configuration", "/data/settings.json을 읽을 수 없거나 올바른 JSON 객체가 아닙니다"))
    def text(name, default=""):
        value = settings.get(name, default)
        if not isinstance(value, str):
            problems.append(error("configuration", "invalid_configuration", name + " 설정은 문자열이어야 합니다"))
            return default
        return value.strip()
    country = os.getenv("SEARCH_COUNTRY", "").strip().upper() or text("country", "KR").upper()
    if country not in COUNTRIES:
        problems.append(error("configuration", "invalid_country", "지원하지 않는 기본 국가입니다. KR/US/JP/CN/TW/HK/GB/DE/FR 중 지정하세요"))
        country = "KR"
    key = os.getenv("ACOUSTID_API_KEY", "").strip() or text("acoustid_key")
    if not key:
        try:
            key = (Path(data_root) / "acoustid_key.txt").read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            pass
        except OSError:
            problems.append(error("AcoustID", "configuration_unreadable", "AcoustID 키 파일을 읽을 권한이 없습니다"))
    fpcalc = os.getenv("FPCALC_PATH", "").strip() or text("fpcalc_path")
    return SimpleNamespace(country=country, acoustid_key=key, fpcalc_path=fpcalc,
                           cover_max_px=1000, rename=False, problems=problems)


def capabilities(data_root):
    config = configuration(data_root)
    return {"countries": list(COUNTRIES), "default_country": config.country,
            "acoustid_key_configured": bool(config.acoustid_key),
            "fpcalc_available": bool(search_acoustid.find_fpcalc(config.fpcalc_path or None)),
            "errors": config.problems}


def candidate_model(value):
    source = value.get("sources") or [s for s in (value.get("source") or "").split("+") if s]
    data = {key: value[key] for key in _CANDIDATE_FIELDS if key in value}
    data.update(sources=source, album_artist=value.get("albumartist") or value.get("album_artist") or "",
                mb_recording_id=value.get("mbid") or value.get("mb_recording_id"))
    return match.Candidate(**data)


def candidate_dict(candidate):
    value = asdict(candidate)
    value.update(source=candidate.source_label(), albumartist=candidate.album_artist,
                 mbid=candidate.mb_recording_id)
    value["id"] = candidate_id(value)
    return value


def candidate_id(value):
    identifying = {name: value.get(name) for name in
                   ("source", "title", "artist", "album", "year", "track", "cover_url", "mbid")}
    return storage.digest(json.dumps(identifying, sort_keys=True, ensure_ascii=False).encode("utf-8"))[:24]


def rank(values, title, artist, duration):
    candidates = [value if isinstance(value, match.Candidate) else candidate_model(value) for value in values]
    unique, seen = [], set()
    for candidate in candidates:
        key = (tuple(candidate.sources), candidate.itunes_id, candidate.mb_recording_id, candidate.mb_release_id,
               match.normalize(candidate.title), match.normalize(candidate.artist), match.normalize(candidate.album),
               candidate.year, candidate.track, candidate.length)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return [candidate_dict(candidate) for candidate in match.rank(unique, title, artist, duration)]


def _versions(title):
    value = (title or "").casefold()
    return (search_lyrics.version_flags(value),
            tuple(bool(re.search(pattern, value)) for pattern in
                  (r"\blive\b", r"\bremix\b", r"\bacoustic\b", r"\bdemo\b", r"\bremaster(?:ed)?\b")))


def auto_pick(values, title, artist, duration):
    candidates = rank(values, title, artist, duration)
    if not candidates or candidates[0]["score"] < 90:
        return None
    best = candidates[0]
    strong_sound = (best.get("acoustid_score") or 0) >= 0.95 and "AcoustID" in best["sources"]
    if match.is_generic_name(title, artist) and not strong_sound:
        return None
    if duration and best.get("length") and abs(duration - best["length"]) > 5:
        return None
    if not strong_sound:
        if _versions(title) != _versions(best["title"]):
            return None
        if title and match.similarity(best["title"], title) < 0.9:
            return None
        if artist and match.similarity(best["artist"], artist) < 0.8:
            return None
    for runner in candidates[1:]:
        if best["score"] - runner["score"] > 3:
            break
        if (match.normalize(best["title"]) != match.normalize(runner["title"])
                or match.normalize(best["artist"]) != match.normalize(runner["artist"])):
            # A clearly stronger acoustic hit can distinguish otherwise ambiguous text hits.
            if not strong_sound or (runner.get("acoustid_score") or 0) >= best["acoustid_score"] - 0.02:
                return None
    return best


def network_error(source, exc):
    if isinstance(exc, net.RateLimited):
        return error(source, "rate_limited", "API 요청 제한/서버 혼잡 재시도 후에도 실패했습니다", retry_after=exc.wait)
    if isinstance(exc, net.NetworkError):
        code = "invalid_response" if "bad json" in str(exc) else "api_error" if str(exc).startswith("HTTP ") else "network_error"
        return error(source, code, {"invalid_response": "API 응답 형식 오류", "api_error": "API HTTP 오류", "network_error": "네트워크 연결/DNS/시간 초과"}[code])
    return error(source, "invalid_response", "검색 응답 처리 중 오류가 발생했습니다")


def sound(path, config, query, duration, cancel=None, on_wait=None):
    errors = []
    if not config.acoustid_key:
        errors.append(error("AcoustID", "missing_api_key", "AcoustID API 키가 없습니다. /data/acoustid_key.txt에 발급받은 키를 설정하세요"))
    if not search_acoustid.find_fpcalc(config.fpcalc_path or None):
        errors.append(error("AcoustID", "missing_fpcalc", "fpcalc 실행 파일을 찾을 수 없습니다"))
    if errors:
        return [], errors
    try:
        result = pipeline.search_sound(str(path), config, query, duration, on_wait=on_wait, cancel=cancel)
    except (net.NetworkError, net.RateLimited, ValueError, TypeError, KeyError, AttributeError) as exc:
        return [], [network_error("AcoustID", exc)]
    mapping = {pipeline.ERR_NETWORK: "network_error", pipeline.ERR_RATE_LIMIT: "rate_limited",
               pipeline.ERR_FPCALC: "missing_fpcalc", pipeline.ERR_ACOUSTID_KEY: "invalid_api_key",
               pipeline.ERR_FINGERPRINT: "fingerprint_failed"}
    for code in result.errors:
        mapped = mapping.get(code, "search_error")
        errors.append(error("AcoustID", mapped, "음향 검색 실패: " + mapped))
    return result.candidates, errors


def search(path, query, country, duration, data_root, mode="text", use_fingerprint=True,
           previous=None, cancel=None, on_wait=None):
    config = configuration(data_root)
    country = country or config.country
    if country not in COUNTRIES:
        raise ValueError("지원하지 않는 검색 국가입니다")
    artist, title = match.split_query(query)
    found, errors = [], list(config.problems)
    used_sound = mode == "sound"
    if mode == "text":
        def guarded(source, fn):
            if cancel and cancel.is_set():
                return [], []
            try:
                return fn(), []
            except (net.NetworkError, net.RateLimited, ValueError, TypeError, KeyError, AttributeError) as exc:
                return [], [network_error(source, exc)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(guarded, "iTunes", lambda: search_itunes.search(query, country, on_wait=on_wait, cancel=cancel)),
                     pool.submit(guarded, "MusicBrainz", lambda: search_mb.search(match.base_title(title), artist, query, on_wait=on_wait, cancel=cancel))]
            for call in calls:
                candidates, problems = call.result()
                found.extend(candidates)
                errors.extend(problems)
    if mode == "sound" or (not found and use_fingerprint and not (cancel and cancel.is_set())):
        used_sound = True
        candidates, problems = sound(path, config, query, duration, cancel, on_wait)
        found.extend(candidates)
        errors.extend(problems)
    if mode == "sound" and previous:
        found.extend(candidate_model(value) for value in previous)
    ranked = rank(found, title, artist, duration)[:20]
    status = "cancelled" if cancel and cancel.is_set() else "partial" if ranked and errors else "matched" if ranked else "error" if errors else "not_found"
    return {"candidates": ranked, "search_errors": errors, "search_status": status,
            "query": query, "query_title": title, "query_artist": artist, "country": country,
            "used_fingerprint": used_sound, "weak_query": match.is_generic_name(title, artist)}


def prepare_image(data):
    if not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("이미지가 없거나 20MB 제한을 초과했습니다")
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 25_000_000:
            raise ValueError("이미지 픽셀 제한 초과")
        image.verify()
    return tags.prepare_cover(data)[0]


def fetch_cover(value, country="US", cancel=None, on_wait=None):
    candidate = candidate_model(value)
    key = (candidate_id(value), country)
    with _cover_lock:
        cached = _cover_cache.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            _cover_cache.move_to_end(key)
            return cached[1], []
    urls = [candidate.cover_url]
    if candidate.mb_release_group_id:
        urls.append(search_mb.CAA_RELEASE_GROUP.format(id=candidate.mb_release_group_id, size=500))
    errors = []
    def attempt(url):
        if not url or (cancel and cancel.is_set()):
            return None
        try:
            data = net.get_bytes(url, on_wait=on_wait, cancel=cancel)
            if not data:
                return None
            prepared = prepare_image(data)
            with _cover_lock:
                _cover_cache[key] = (time.monotonic(), prepared)
                _cover_cache.move_to_end(key)
                while len(_cover_cache) > 32 or sum(len(entry[1]) for entry in _cover_cache.values()) > _COVER_CACHE_BYTES:
                    _cover_cache.popitem(last=False)
            return prepared
        except (net.NetworkError, net.RateLimited) as exc:
            errors.append(network_error("cover", exc))
        except Exception:
            errors.append(error("cover", "invalid_image", "유효하지 않거나 손상된 표지 이미지입니다"))
        return None
    for url in urls:
        data = attempt(url)
        if data:
            return data, []
    if candidate.album and not (cancel and cancel.is_set()):
        try:
            url = search_itunes.album_artwork(candidate.album, candidate.album_artist or candidate.artist, country,
                                              cancel=cancel, on_wait=on_wait)
            data = attempt(url)
            if data:
                return data, []
        except (net.NetworkError, net.RateLimited) as exc:
            errors.append(network_error("iTunes cover", exc))
    return None, errors or [error("cover", "cover_not_found", "사용할 수 있는 표지를 찾지 못했습니다")]
