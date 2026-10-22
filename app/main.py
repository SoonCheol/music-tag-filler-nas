import os, json, re, uuid, time, threading
from pathlib import Path
from typing import List, Dict, Optional, Literal
import requests, musicbrainzngs
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field, ConfigDict
import mutagen
from functools import wraps
from collections import OrderedDict
from concurrent.futures import Future
import io
from . import storage, search_service, job_service, preferences
from .upstream import tags as original_tags, match as original_match, search_lyrics as original_lyrics

MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_FILE = DATA_ROOT / "jobs.json"
BACKUP_ROOT = DATA_ROOT / "backups"
BACKUP_ROOT.mkdir(exist_ok=True)

musicbrainzngs.set_useragent("music-tag-filler-nas", "2.0.0", "https://github.com/microhan1/music-tag-filler")

app = FastAPI(title="음악 정보 채우기 NAS Web", version="2.0.0")

# --- job store ---
jobs: Dict[str, dict] = {}
job_store_error = None
if JOBS_FILE.exists():
    try:
        raw = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        jobs = job_service.normalize_jobs(raw)
    except (OSError, ValueError, TypeError):
        job_store_error = "jobs.json 읽기/검증 실패. 원본 상태 파일을 보존하며 새 작업 기록을 차단합니다"

def save_jobs():
    with storage.OPERATION_LOCK:
        if job_store_error:
            raise OSError(job_store_error)
        storage._replace_file(JOBS_FILE, json.dumps(jobs, ensure_ascii=False, indent=2).encode("utf-8"))

def parse_filename(p: Path):
    return original_match.guess_from_filename(str(p))

def search_itunes(artist: str, title: str, country=None):
    query = original_match.build_query(title, artist)
    return search_service.search_itunes.search(query, country or search_service.configuration(DATA_ROOT).country)


def search_musicbrainz(artist: str, title: str):
    return search_service.search_mb.search(original_match.base_title(title), artist,
                                          original_match.build_query(title, artist))


def read_tags(path: Path):
    try:
        if original_tags.format_of(str(path)) is not None:
            return storage.describe(path)
        audio = mutagen.File(str(path), easy=False)
        if audio is None:
            return {}
        info = {"duration": getattr(audio.info, "length", 0) if hasattr(audio, "info") else 0}
        try:
            easy = mutagen.File(str(path), easy=True)
            if easy:
                info["title"] = easy.get("title",[""])[0] if easy.get("title") else ""
                info["artist"] = easy.get("artist",[""])[0] if easy.get("artist") else ""
                info["album"] = easy.get("album",[""])[0] if easy.get("album") else ""
                info["albumartist"] = easy.get("albumartist",[""])[0] if easy.get("albumartist") else ""
                info["date"] = easy.get("date",[""])[0] if easy.get("date") else ""
                info["genre"] = easy.get("genre",[""])[0] if easy.get("genre") else ""
                info["tracknumber"] = easy.get("tracknumber",[""])[0] if easy.get("tracknumber") else ""
        except:
            pass
        return info
    except:
        return {}

def candidate_id(candidate):
    return search_service.candidate_id(candidate)


def score_candidates(candidates, artist, title, duration):
    return search_service.rank(candidates, title, artist, duration)


def automatic_candidate(result):
    hint = result.get("parsed", {})
    artist = result.get("query_artist", result.get("original", {}).get("artist") or hint.get("artist", ""))
    title = result.get("query_title", result.get("original", {}).get("title") or hint.get("title", ""))
    return search_service.auto_pick(result.get("candidates", []), title, artist,
                                    result.get("original", {}).get("duration", 0))

class ScanCancellation:
    def __init__(self, job):
        self.job = job

    def is_set(self):
        return bool(self.job.get("cancel_requested"))


def scan_job(job_id: str, sub_path: str, opts: dict, resume: bool = False):
    job = jobs.get(job_id)
    if not job:
        return
    cancelled = ScanCancellation(job)
    try:
        files = job_service.collect(MUSIC_ROOT, opts.get("paths") or [sub_path], opts.get("recurse", True), cancel=cancelled)
        previous = job.get("results", []) if resume else []
        retained, pending, missing = job_service.retained_results(MUSIC_ROOT, files, previous, cancel=cancelled)
        with storage.OPERATION_LOCK:
            if job.get("cancel_requested"):
                job.update(status="cancelled", finished_at=time.time(), current_file="", search_wait_seconds=0, diagnostic="중지 완료")
                save_jobs()
                return
            job.update(status="scanning", total=len(files), results=retained, scanned=len(retained),
                       missing_paths=missing, diagnostic="", search_wait_seconds=0)
            save_jobs()
        for path in pending:
            if cancelled.is_set():
                break
            relative = path.relative_to(MUSIC_ROOT.resolve()).as_posix()
            with storage.OPERATION_LOCK:
                if cancelled.is_set():
                    break
                job["current_file"] = relative
                job["search_wait_seconds"] = 0
            try:
                original = storage.describe(path)
                if cancelled.is_set():
                    break
                artist, title = parse_filename(path)
                artist, title = original.get("artist") or artist, original.get("title") or title
                found = search_service.search(path, original_match.build_query(title, artist), opts.get("country"),
                                              original.get("duration", 0), DATA_ROOT,
                                              use_fingerprint=opts.get("use_fingerprint", True), cancel=cancelled,
                                              on_wait=lambda seconds: job.update(search_wait_seconds=seconds))
                if cancelled.is_set():
                    break
                result = {**found, "path": relative, "original": original,
                          "parsed": {"artist": artist, "title": title}, "lyrics": None,
                          "lyrics_status": "skipped"}
                prepare_result(result)
            except Exception as exc:
                result = {"path": relative, "error": str(exc), "candidates": [], "original": {}}
            with storage.OPERATION_LOCK:
                if cancelled.is_set():
                    break
                job["results"].append(result)
                job["scanned"] = len(job["results"])
                save_jobs()
        with storage.OPERATION_LOCK:
            job.update(status="cancelled" if cancelled.is_set() else "done", finished_at=time.time(),
                       current_file="", search_wait_seconds=0,
                       diagnostic="중지 완료" if cancelled.is_set() else "")
            save_jobs()
    except job_service.ScanCancelled:
        with storage.OPERATION_LOCK:
            job.update(status="cancelled", finished_at=time.time(), current_file="", search_wait_seconds=0, diagnostic="중지 완료")
            save_jobs()
    except Exception as exc:
        with storage.OPERATION_LOCK:
            job.update(status="failed", error=str(exc), diagnostic="작업 상태 기록 또는 파일 탐색 실패")
            try:
                save_jobs()
            except OSError:
                job["state_error"] = "작업 기록 실패. 기존 디스크 기록은 보존했습니다"

class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_path: str = ""
    paths: List[str] = Field(default_factory=list, max_length=200)
    recurse: bool = True
    only_empty: bool = True
    fill_lyrics: bool = False
    rename: bool = False
    use_fingerprint: bool = True
    force: bool = False
    country: Optional[Literal["KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR"]] = None

def get_active_job():
    for j in jobs.values():
        if j.get("status") in job_service.ACTIVE:
            return j
    return None


def job_locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with storage.OPERATION_LOCK:
            return function(*args, **kwargs)
    return wrapped

@app.get("/api/folders")
def list_folders():
    root = MUSIC_ROOT.resolve()
    if not root.is_dir():
        raise HTTPException(404, "음악 폴더를 찾을 수 없습니다")
    folders = []
    try:
        for parent, dirs, _ in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()]
            folders.extend((Path(parent) / name).relative_to(root).as_posix() for name in dirs)
    except OSError as exc:
        raise HTTPException(500, "음악 폴더 목록을 읽을 수 없습니다") from exc
    return {"folders": sorted(folders, key=str.casefold)}


@app.post("/api/scan")
@job_locked
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    root = MUSIC_ROOT.resolve()
    target = (root / req.sub_path).resolve()
    if not req.paths and (not target.is_relative_to(root) or not target.is_dir()):
        raise HTTPException(400, "유효한 음악 폴더를 선택하세요")
    try:
        job_service.collect(root, req.paths or [req.sub_path], req.recurse)
    except (storage.StorageError, OSError) as exc:
        raise HTTPException(400, str(exc))
    # 중복 방지
    active = get_active_job()
    if active:
        # 같은 경로면 차단
        if active.get("sub_path","") == req.sub_path:
            raise HTTPException(status_code=409, detail={"message": "이미 같은 폴더를 스캔 중입니다", "active_job_id": active["id"], "active_path": active.get("sub_path")})
        # 다른 경로라도 병렬 스캔 방지 (NAS 리소스 보호)
        raise HTTPException(status_code=409, detail={"message": f"다른 스캔이 진행 중입니다 ({active.get('sub_path') or '전체'} - {active['scanned']}/{active['total']})", "active_job_id": active["id"]})

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "total": 0,
        "scanned": 0,
        "sub_path": req.sub_path,
        "options": req.model_dump(),
        "created_at": time.time(),
        "current_file": "",
        "results": [],
        "cancel_requested": False
    }
    try:
        save_jobs()
    except OSError as exc:
        del jobs[job_id]
        raise HTTPException(503, str(exc))
    background_tasks.add_task(scan_job, job_id, req.sub_path, req.model_dump(), False)
    return {"job_id": job_id}

def public_job(job):
    # Legacy job files may still contain lyrics: never include bodies in list data.
    results = []
    for row in job.get("results", []):
        original = row.get("original", {})
        compact = {key: value for key, value in original.items() if key != "lyrics"}
        if "lyrics" in original:
            text = original.get("lyrics") or ""
            compact.setdefault("has_lyrics", bool(text.strip()))
            compact.setdefault("lyrics_lines", len(text.splitlines()) if text.strip() else 0)
        results.append({**{key: value for key, value in row.items() if key not in ("lyrics", "original")}, "original": compact})
    return {**job, "results": results}


@app.get("/api/jobs")
@job_locked
def list_jobs():
    for job in jobs.values():
        for result in job.get("results", []):
            prepare_result(result)
    return [public_job(job) for job in sorted(jobs.values(), key=lambda x: x.get("created_at",0), reverse=True)]

@app.get("/api/jobs/{job_id}")
@job_locked
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    for result in jobs[job_id].get("results", []):
        prepare_result(result)
    return public_job(jobs[job_id])

@app.post("/api/jobs/{job_id}/cancel")
@job_locked
def cancel_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    job = jobs[job_id]
    # scanning/queued는 정상 취소, interrupted는 즉시 cancelled로 변경 (중지 버튼)
    if job.get("status") in job_service.ACTIVE:
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        job["diagnostic"] = "중지 요청됨. 진행 중 HTTP 응답/지문 생성의 제한 시간까지 기다릴 수 있습니다"
    elif job.get("status") in ("interrupted", "failed", "cancelled"):
        job["status"] = "cancelled"
        job["cancelled_at"] = time.time()
    else:
        raise HTTPException(400, "중지할 수 없는 상태입니다")
    save_jobs()
    return {"status": job["status"], "id": job_id}

@app.delete("/api/jobs/{job_id}")
@job_locked
def delete_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    job = jobs[job_id]
    if job.get("status") in ("scanning", "queued", "cancelling"):
        raise HTTPException(400, "진행 중인 작업은 먼저 중지하세요")
    del jobs[job_id]
    try:
        save_jobs()
    except OSError as exc:
        jobs[job_id] = job
        raise HTTPException(503, "삭제 기록 실패: " + str(exc))
    return {"deleted": job_id}

@app.post("/api/jobs/{job_id}/resume")
@job_locked
def resume_job(job_id: str, background_tasks: BackgroundTasks):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    job = jobs[job_id]
    if job.get("status") not in ("cancelled", "interrupted", "failed", "done"):
        # scanning 중이면 resume 불가
        if job.get("status") in ("scanning", "queued", "cancelling"):
            raise HTTPException(400, "이미 진행 중인 작업입니다")
    # 이미 done인데 전체가 끝났으면 resume 의미 없음 -> 그래도 허용 (재스캔)
    if job.get("scanned",0) >= job.get("total",0) and job.get("total",0) > 0:
        # 전체 스캔 완료된 경우, 새로 스캔으로 처리할지? 여기서는 중단된 것만 이어하기이므로
        # 만약 done이면 처음부터 다시 스캔하도록 total 리셋
        if job.get("status") == "done":
            raise HTTPException(400, "이미 완료된 작업입니다. 새로 스캔을 시작하세요")

    # active job 체크
    active = get_active_job()
    if active and active["id"] != job_id:
        raise HTTPException(409, detail={"message": "다른 작업이 진행 중입니다", "active_job_id": active["id"]})

    if job.get("status") not in ("cancelled", "interrupted", "failed"):
        raise HTTPException(400, "중단된 작업만 이어할 수 있습니다")
    previous_status, previous_cancel = job.get("status"), job.get("cancel_requested", False)
    job["status"] = "queued"
    job["cancel_requested"] = False
    try:
        save_jobs()
    except OSError as exc:
        job.update(status=previous_status, cancel_requested=previous_cancel)
        raise HTTPException(503, "이어하기 기록 실패: " + str(exc))
    background_tasks.add_task(scan_job, job_id, job.get("sub_path",""), job.get("options",{}), True)
    return {"status": "resumed", "id": job_id}

TagField = Literal["title", "artist", "album", "albumartist", "track", "year", "genre"]


class SaveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: Literal["auto", "manual", "edit", "none"]
    candidate_id: Optional[str] = None
    values: Dict[TagField, str] = Field(default_factory=dict)
    fields: List[TagField] = Field(default_factory=list)
    include_cover: bool = False
    cover_id: Optional[str] = None
    include_ids: bool = False
    lyrics_id: Optional[str] = None


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["current", "selected", "all"]
    paths: List[str]
    checked_paths: List[str] = Field(default_factory=list)
    items: List[SaveItem]
    save_cover: bool = True
    save_lyrics: bool = True
    only_empty: bool = True
    fill_lyrics: bool = False
    rename: bool = False
    cover_max_px: Optional[int] = Field(default=None, ge=100, le=1000)
    artist_name_preference: Literal["original", "latin"] = "original"


class LyricsSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(max_length=4096)
    artist: str = Field(max_length=4096)


_lyrics_cache = OrderedDict()
_lyrics_pending = {}
_lyrics_lock = threading.Lock()


def lyric_response(entry):
    return {key: entry[key] for key in ("lyrics_id", "status", "searched", "lyrics", "message")}


def remember_lyrics(key, found, searched=True):
    text = original_lyrics.clean_text(found.text) if found.status == original_lyrics.FOUND else ""
    status = "found" if text else "not_found" if found.status in (original_lyrics.FOUND, original_lyrics.NOT_FOUND, original_lyrics.NO_LYRICS, original_lyrics.INSTRUMENTAL) else "error"
    messages = {original_lyrics.BUSY: "가사 서버에 연결할 수 없습니다. 다시 시도해 주세요.",
                original_lyrics.CONFLICT: "검색된 가사가 서로 일치하지 않아 사용할 수 없습니다.",
                original_lyrics.NEED_TAGS: "가사 검색에 제목과 가수가 필요합니다."}
    entry = {"key": key, "lyrics_id": uuid.uuid4().hex, "status": status, "searched": searched,
             "lyrics": text, "message": messages.get(found.status, "가사 검색 오류가 발생했습니다.") if status == "error" else "",
             "expires": time.monotonic() + (3600 if status == "found" else 30 if status == "not_found" else 5)}
    with _lyrics_lock:
        _lyrics_cache[key] = entry
        _lyrics_cache.move_to_end(key)
        while len(_lyrics_cache) > 64:
            _lyrics_cache.popitem(last=False)
    return entry


@app.post("/api/jobs/{job_id}/lyrics-search")
def search_file_lyrics(job_id: str, request: LyricsSearchRequest):
    with storage.OPERATION_LOCK:
        job = jobs.get(job_id)
        row = next((r for r in (job or {}).get("results", []) if r["path"] == request.path), None)
        if row is None:
            raise HTTPException(404, "이 작업의 파일이 아닙니다")
        try:
            target = storage.resolve_music(MUSIC_ROOT, request.path)
            if storage.revision(target) != request.expected_revision:
                raise HTTPException(409, "파일이 변경되었습니다. 다시 확인하세요")
        except (storage.StorageError, OSError) as exc:
            raise HTTPException(400, str(exc))
        duration = row.get("original", {}).get("duration", 0)
    key = (str(MUSIC_ROOT.resolve()), job_id, request.path, request.expected_revision, request.title, request.artist)
    with _lyrics_lock:
        entry = _lyrics_cache.get(key)
        if entry and entry["expires"] > time.monotonic():
            return lyric_response(entry)
        pending = _lyrics_pending.get(key)
        owner = pending is None
        if owner:
            pending = Future()
            _lyrics_pending[key] = pending
    if not owner:
        return lyric_response(pending.result())
    try:
        searched = bool(request.title.strip() and request.artist.strip())
        found = original_lyrics.find(request.title, request.artist, duration) if searched else original_lyrics.LyricsResult(original_lyrics.NEED_TAGS)
        entry = remember_lyrics(key, found, searched)
        pending.set_result(entry)
        return lyric_response(entry)
    except Exception:
        entry = remember_lyrics(key, original_lyrics.LyricsResult(original_lyrics.BUSY))
        pending.set_result(entry)
        return lyric_response(entry)
    finally:
        with _lyrics_lock:
            _lyrics_pending.pop(key, None)


def selected_lyrics(job_id, path, revision, lyrics_id, title, artist):
    with _lyrics_lock:
        entry = next((value for value in _lyrics_cache.values() if value["lyrics_id"] == lyrics_id), None)
        if not entry or entry["expires"] <= time.monotonic() or entry["key"] != (str(MUSIC_ROOT.resolve()), job_id, path, revision, title, artist):
            raise storage.StorageError("가사 검색 결과가 만료되었거나 태그가 변경되었습니다. 다시 검색하세요")
        return entry


class RevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    query: str = Field(default="", max_length=500)
    mode: Literal["text", "sound"] = "text"
    country: Optional[Literal["KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR"]] = None
    use_fingerprint: bool = True
    expected_revision: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@app.get("/api/capabilities")
def capabilities():
    return search_service.capabilities(DATA_ROOT)


@app.get("/api/preferences")
def get_preferences():
    try:
        return preferences.read(DATA_ROOT).model_dump()
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "설정 읽기 실패: " + str(exc))


@app.put("/api/preferences")
def put_preferences(value: preferences.Preferences):
    try:
        preferences.write(DATA_ROOT, value)
        return value.model_dump()
    except (OSError, ValueError):
        raise HTTPException(503, "설정 저장 실패. 기존 설정 파일을 보존했습니다")


@app.get("/api/diagnostics")
def diagnostics(check_network: bool = False):
    return {"job_store_error": job_store_error, "capabilities": capabilities(),
            "supported_formats": ["MP3", "FLAC", "M4A", "OGG"],
            "network_reachable": search_service.net.online() if check_network else None,
            "cancellation": "HTTP 응답/지문 실행은 제한 시간까지 기다릴 수 있습니다"}


@app.post("/api/jobs/{job_id}/cover-upload")
async def upload_cover(job_id: str, request: Request):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    data = bytearray()
    async for block in request.stream():
        data.extend(block)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "커버는 20MB 이하여야 합니다")
    try:
        return {"cover_id": preferences.put_cover(job_id, bytes(data)), "expires_in": 3600}
    except Exception:
        raise HTTPException(400, "검증할 수 없는 이미지입니다")


@app.get("/api/jobs/{job_id}/uploaded-cover/{cover_id}")
def uploaded_cover(job_id: str, cover_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    try:
        return Response(preferences.get_cover(job_id, cover_id), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})
    except storage.StorageError as exc:
        raise HTTPException(410, str(exc))


@app.post("/api/jobs/{job_id}/search")
def research_file(job_id: str, request: SearchRequest):
    with storage.OPERATION_LOCK:
        if job_id not in jobs:
            raise HTTPException(404, "job not found")
        job = jobs[job_id]
        if job.get("status") in ("queued", "scanning", "cancelling"):
            raise HTTPException(409, "스캔을 완료하거나 중지한 후 재검색하세요")
        result = next((r for r in job.get("results", []) if r.get("path") == request.path), None)
        if result is None:
            raise HTTPException(400, "이 작업에 속한 파일이 아닙니다")
        try:
            path = storage.resolve_music(MUSIC_ROOT, request.path)
            original = storage.describe(path)
        except (storage.StorageError, OSError, original_tags.UnsupportedFile) as exc:
            raise HTTPException(400, str(exc))
        if request.expected_revision and request.expected_revision != original["revision"]:
            raise HTTPException(409, "파일이 변경되었습니다. 다시 스캔하세요")
        generation = uuid.uuid4().hex
        result["search_generation"] = generation
    artist, title = parse_filename(path)
    query = request.query.strip() or original_match.build_query(original.get("title") or title, original.get("artist") or artist)
    found = search_service.search(path, query, request.country, original["duration"], DATA_ROOT,
                                  mode=request.mode, use_fingerprint=request.use_fingerprint,
                                  previous=result.get("candidates") if request.mode == "sound" else None,
                                  on_wait=lambda seconds: result.update(search_wait_seconds=seconds))
    with storage.OPERATION_LOCK:
        if result.get("search_generation") != generation or storage.revision(path) != original["revision"]:
            raise HTTPException(409, "파일 또는 검색 요청이 변경되어 오래된 결과를 적용하지 않았습니다")
        result.update(found, original=original)
        prepare_result(result)
        save_jobs()
        return result


@app.get("/api/jobs/{job_id}/cover/{selection_id}")
def candidate_cover(job_id: str, selection_id: str, path: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    result = next((r for r in jobs[job_id].get("results", []) if r.get("path") == path), None)
    if result is None:
        raise HTTPException(400, "이 작업에 속한 파일이 아닙니다")
    candidate = next((c for c in result.get("candidates", []) if candidate_id(c) == selection_id), None)
    if candidate is None:
        raise HTTPException(404, "이 파일의 검색 후보가 아닙니다")
    data, errors = search_service.fetch_cover(candidate, result.get("country") or search_service.configuration(DATA_ROOT).country)
    if data is None:
        raise HTTPException(404, detail={"message": "표지 조회 실패", "errors": errors})
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


def file_state(result):
    stored = result.get("stored_saved", result.get("last_save", {}).get("status") in ("saved", "partial"))
    return "saved" if stored else "auto" if result.get("scan_auto_selected", result.get("auto_apply", False)) else "review"


def prepare_result(result):
    hint = result.get("parsed", {})
    artist = result.get("query_artist", result.get("original", {}).get("artist") or hint.get("artist", ""))
    title = result.get("query_title", result.get("original", {}).get("title") or hint.get("title", ""))
    result["candidates"] = score_candidates(result.get("candidates", []), artist, title,
                                            result.get("original", {}).get("duration", 0))
    result["best"] = automatic_candidate(result)
    result["auto_apply"] = result["best"] is not None
    result.setdefault("scan_auto_selected", result["auto_apply"])
    result.setdefault("stored_saved", result.get("last_save", {}).get("status") in ("saved", "partial"))
    result["file_state"] = file_state(result)
    return result


def save_one(result, item, request, lyric_context=None):
    path = storage.resolve_music(MUSIC_ROOT, item.path)
    if storage.revision(path) != item.expected_revision:
        raise storage.StorageError("확인 이후 파일이 변경되었습니다. 다시 스캔하세요")
    if item.selection == "none":
        if not item.cover_id and not request.rename and not (request.save_lyrics and item.lyrics_id):
            return {"path": item.path, "status": "skipped", "reason": "no_selection"}
        # Explicit cover/rename-only operation must not import unchecked text or IDs.
        item = item.model_copy(update={"fields": [], "values": {}, "include_ids": False, "include_cover": False})
    if len(set(item.fields)) != len(item.fields) or not set(item.fields).issubset(item.values):
        raise storage.StorageError("체크된 항목의 저장값이 누락되었거나 중복되었습니다")
    if any(len(value) > 4096 for value in item.values.values()):
        raise storage.StorageError("태그 값이 너무 깁니다")
    candidate = None
    if item.selection == "auto":
        candidate = automatic_candidate(result)
        if candidate is None or item.candidate_id != candidate["id"]:
            raise storage.StorageError("90점 미만이거나 유효하지 않은 자동 후보입니다. 직접 확인하고 선택하세요")
    elif item.candidate_id:
        candidate = next((c for c in result.get("candidates", []) if candidate_id(c) == item.candidate_id), None)
        if candidate is None:
            raise storage.StorageError("이 파일의 검색 후보가 아닙니다")
    elif item.selection == "manual":
        raise storage.StorageError("선택한 후보가 없습니다")
    current = original_tags.read_file(str(path))
    only_empty = request.only_empty
    values = dict(item.values)
    if item.selection == "auto":
        # The automatic payload cannot substitute untrusted browser values.
        values = {field: str(candidate.get(field) or "") for field in item.fields}
        if request.artist_name_preference == "latin":
            for field, alias in (("artist", "artist_latin"), ("albumartist", "album_artist_latin")):
                if field in item.fields and candidate.get(alias):
                    values[field] = str(candidate[alias])
    final = current.tags.as_dict()
    for field in item.fields:
        key = storage.FIELDS[field]
        if not only_empty or not final[key]:
            final[key] = values.get(field, "")
    needs_text = original_tags.Tags.from_dict(final) != current.tags
    ids = None
    if item.include_ids and candidate:
        model = search_service.candidate_model(candidate)
        ids = search_service.pipeline.ids_from_candidate(model)
        def matches(field, key, *expected):
            return field in item.fields and bool(final[key]) and final[key] in expected
        artist_matches = matches("artist", "artist", model.artist, model.artist_latin)
        if not artist_matches:
            ids.mb_artist_ids, ids.artist_sort, ids.itunes_artist_id = [], "", ""
        if not matches("albumartist", "album_artist", model.album_artist, model.album_artist_latin):
            ids.mb_album_artist_ids, ids.album_artist_sort = [], ""
        if not matches("album", "album", model.album):
            ids.mb_album_id = ""
        if not artist_matches or not matches("title", "title", model.title):
            ids.mb_recording_id = ""
    wants_cover = bool(request.save_cover and item.include_cover and candidate and (candidate.get("cover_url") or candidate.get("album"))
                       and not (only_empty and current.cover is not None))
    uploaded = preferences.get_cover(result.get("job_id", ""), item.cover_id) if request.save_cover and item.cover_id else None
    if uploaded is not None:
        wants_cover = not (only_empty and current.cover is not None)
    has_real_lyrics = bool(current.lyrics.strip() and not original_lyrics.marker_only(current.lyrics))
    choice = selected_lyrics(result.get("job_id", ""), item.path, item.expected_revision, item.lyrics_id, final["title"], final["artist"]) if request.save_lyrics and item.lyrics_id else None
    # New UI sends an explicit checkbox: only previously searched lyrics may save.
    # Old API clients without that control retain their automatic missing-lyrics option.
    wants_lyrics = bool("save_lyrics" not in request.model_fields_set and request.save_lyrics and item.selection != "none" and request.fill_lyrics and not choice and not has_real_lyrics and final["title"] and final["artist"])
    manual_lyrics = choice["lyrics"] if choice and choice["status"] == "found" and not (only_empty and has_real_lyrics) else None
    if needs_text or wants_cover or wants_lyrics or manual_lyrics or request.rename or (ids and not ids.is_empty()):
        storage.writable(path)  # fail before network lookups or backup creation on /music:ro
    cover = None
    asset_errors = []
    if wants_cover:
        if uploaded is not None:
            cover = uploaded
        else:
            cover, asset_errors = search_service.fetch_cover(candidate, result.get("country") or search_service.configuration(DATA_ROOT).country)
        # Normalize missing/empty downloads before reaching the transactional writer.
        cover = storage.prepare_cover_change(cover, current.cover, request.cover_max_px if request.cover_max_px is not None else preferences.read(DATA_ROOT).cover_max_px)
    lyrics = manual_lyrics
    lyrics_status = choice["status"] if choice else "preserved" if has_real_lyrics else "skipped"
    if wants_lyrics:
        context = lyric_context if lyric_context is not None else {"busy_streak": 0}
        actually_searched = context["busy_streak"] < 5
        if not actually_searched:
            found = original_lyrics.LyricsResult(original_lyrics.BUSY)
        else:
            found = original_lyrics.find(final["title"], final["artist"], current.length)
            if found.status == original_lyrics.BUSY:
                found = original_lyrics.find(final["title"], final["artist"], current.length)
        context["busy_streak"] = context["busy_streak"] + 1 if found.status == original_lyrics.BUSY else 0
        lyrics_status = found.status
        if found.status == original_lyrics.FOUND:
            lyrics = found.text
        choice = remember_lyrics((str(MUSIC_ROOT.resolve()), result.get("job_id", ""), item.path, item.expected_revision, final["title"], final["artist"]), found, actually_searched)
    outcome = storage.save(path, MUSIC_ROOT.resolve(), BACKUP_ROOT, values, item.fields,
                           only_empty, item.expected_revision, cover, lyrics, request.rename, ids, replace_lyrics=bool(manual_lyrics))
    if choice:
        outcome["lyrics_search"] = lyric_response(choice)
    outcome["lyrics_status"] = lyrics_status
    outcome["asset_errors"] = asset_errors
    if asset_errors:
        outcome["warning"] = "; ".join(problem["message"] for problem in asset_errors)
        outcome["status"] = "partial" if outcome["status"] in ("saved", "partial") else "failed"
        if outcome["status"] == "failed":
            outcome["message"] = outcome["warning"]
    if wants_lyrics and lyrics_status == original_lyrics.BUSY:
        outcome["warning"] = (outcome.get("warning", "") + "; 가사 서버 응답 실패: 가사는 추가하지 않았습니다").lstrip("; ")
        if outcome["status"] == "saved":
            outcome["status"] = "partial"
    return outcome


# Progress has its own lock: polling must not wait for the music mutation lock.
save_tasks = {}
save_tasks_lock = threading.Lock()


def update_save_task(task_id, **values):
    with save_tasks_lock:
        save_tasks[task_id].update(values)


@app.get("/api/save-tasks")
def list_save_tasks():
    with save_tasks_lock:
        return sorted([dict(task) for task in save_tasks.values()],
                      key=lambda task: task["created_at"], reverse=True)


@app.delete("/api/save-tasks/{task_id}")
def delete_save_task(task_id: str):
    with save_tasks_lock:
        task = save_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "save task not found")
        if task["status"] in ("queued", "saving"):
            raise HTTPException(409, "저장 중인 작업은 삭제할 수 없습니다")
        del save_tasks[task_id]
    return {"status": "deleted"}


@app.post("/api/jobs/{job_id}/save")
def save_job(job_id: str, request: SaveRequest):
    task_id = str(uuid.uuid4())
    with save_tasks_lock:
        save_tasks[task_id] = {"id": task_id, "job_id": job_id, "status": "queued",
                               "sub_path": jobs.get(job_id, {}).get("sub_path", ""),
                               "created_at": time.time(), "total": len(request.paths),
                               "saved": 0, "failed": 0, "skipped": 0, "partial": 0,
                               "processed": 0, "current_file": "", "current_path": ""}
    try:
        response = perform_save_job(job_id, request, task_id)
        update_save_task(task_id, status="done", finished_at=time.time(),
                         current_file="", current_path="")
        response["save_task_id"] = task_id
        return response
    except Exception as exc:
        update_save_task(task_id, status="failed", finished_at=time.time(),
                         current_file="", current_path="", error=str(exc))
        raise


def perform_save_job(job_id: str, request: SaveRequest, task_id: str):
    with storage.OPERATION_LOCK:
        if job_id not in jobs:
            raise HTTPException(404, "job not found")
        job = jobs[job_id]
        if job.get("status") in ("queued", "scanning", "cancelling"):
            raise HTTPException(409, "스캔을 완료하거나 중지한 후 저장하세요")
        results = {r["path"]: r for r in job.get("results", [])}
        paths = request.paths
        items = {item.path: item for item in request.items}
        if (not paths or len(set(paths)) != len(paths) or len(items) != len(request.items)
                or set(paths) != set(items) or not set(paths).issubset(results)):
            raise HTTPException(400, "저장 대상 경로와 파일별 요청을 명시적으로 지정하세요")
        if request.scope == "current":
            if len(paths) != 1 or request.checked_paths:
                raise HTTPException(400, "현재 곡 저장은 한 곡만 지정해야 합니다")
        elif (len(set(request.checked_paths)) != len(request.checked_paths)
              or set(paths) != set(request.checked_paths)
              or any(file_state(results[path]) != "auto" for path in paths)):
            raise HTTPException(400, "일괄 저장은 체크된 자동선택 곡만 지정해야 합니다")
        update_save_task(task_id, status="saving")
        outcomes = []
        counts = {"saved": 0, "failed": 0, "skipped": 0, "partial": 0}
        lyric_context = {"busy_streak": 0}
        for relative in paths:
            update_save_task(task_id, current_file=Path(relative).name,
                             current_path=str(MUSIC_ROOT / relative))
            result = results[relative]
            result.setdefault("stored_saved", file_state(result) == "saved")
            try:
                result["job_id"] = job_id
                outcome = save_one(result, items[relative], request, lyric_context)
                outcome["request_path"] = relative
                outcome.setdefault("path", relative)
                if outcome.get("original"):
                    result["original"] = outcome["original"]
                    result["path"] = outcome["path"]
                    result["abs_path"] = str(MUSIC_ROOT / outcome["path"])
                if outcome.get("changed"):
                    result["stored_saved"] = True
                result["file_state"] = file_state(result)
                outcome["file_state"] = result["file_state"]
                result["last_save"] = {k: v for k, v in outcome.items() if k not in ("original", "lyrics_search")}
            except Exception as exc:
                outcome = {"path": relative, "status": "failed", "message": str(exc)}
                result["last_save"] = outcome
            outcomes.append(outcome)
            if outcome["status"] in ("saved", "partial"):
                counts["saved"] += 1
            if outcome["status"] in ("failed", "skipped", "partial"):
                counts[outcome["status"]] += 1
            update_save_task(task_id, processed=len(outcomes), **counts)
        saved = sum(o["status"] in ("saved", "partial") for o in outcomes)
        skipped = sum(o["status"] == "skipped" for o in outcomes)
        failed = sum(o["status"] == "failed" for o in outcomes)
        partial = sum(o["status"] == "partial" for o in outcomes)
        status = "partial" if partial or (failed and saved) else "failed" if failed else "saved" if saved else "unchanged"
        job["save_status"], job["saved_count"] = status, saved
        response = {"status": status, "scope": request.scope, "requested": len(paths),
                    "saved": saved, "skipped": skipped, "failed": failed, "partial": partial,
                    "unchanged": sum(o.get("reason") == "unchanged" for o in outcomes),
                    "unselected": sum(o.get("reason") == "no_selection" for o in outcomes),
                    "results": outcomes,
                    "errors": [o for o in outcomes if o["status"] in ("failed", "partial")]}
        try:
            save_jobs()
        except OSError as exc:
            response["state_error"] = "파일 처리 결과는 위와 같으나 작업 상태 기록 실패: " + str(exc)
        return response


@app.api_route("/api/audio/{path:path}", methods=["GET", "HEAD"])
def stream_audio(path: str, request: Request):
    source = None
    try:
        target = storage.resolve_music(MUSIC_ROOT, path)
        source = target.open("rb")
        size = os.fstat(source.fileno()).st_size
    except (storage.StorageError, OSError) as exc:
        if source is not None:
            source.close()
        raise HTTPException(400, str(exc))
    start, end, status = 0, size - 1, 200
    range_header = None if request.headers.get("if-range") else request.headers.get("range")
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if len(range_header)>128 or not match or not any(match.groups()) or size == 0:
            source.close()
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            suffix = int(last)
            start, end = max(0, size - suffix), size - 1
        if start >= size or end < start:
            source.close()
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
        status = 206
    length = max(0, end - start + 1)
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length),
               "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    media_type = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}[target.suffix.lower()]
    if request.method == "HEAD":
        source.close()
        return Response(status_code=status, headers=headers, media_type=media_type)

    async def chunks():
        try:
            source.seek(start)
            remaining = length
            while remaining:
                data = await run_in_threadpool(source.read, min(65536, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
        finally:
            source.close()
    return StreamingResponse(chunks(), status_code=status, headers=headers, media_type=media_type, background=BackgroundTask(source.close))


@app.get("/api/files/{path:path}")
def file_info(path: str):
    try:
        return storage.describe(storage.resolve_music(MUSIC_ROOT, path))
    except (storage.StorageError, OSError) as exc:
        raise HTTPException(400, str(exc))


# One bounded entry per file; a revision/stat change replaces only that entry.
_thumbnail_cache = OrderedDict()
_thumbnail_lock = threading.Lock()
_THUMBNAIL_LIMIT = 256


@app.get("/api/thumbnail/{path:path}")
def file_thumbnail(path: str, request: Request, v: Optional[str] = None):
    try:
        target = storage.resolve_music(MUSIC_ROOT, path)
        stat = target.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        key = str(target)
        with _thumbnail_lock:
            cached = _thumbnail_cache.get(key)
            if cached is None or cached[0] != signature:
                info = original_tags.read_file(str(target))
                thumbnail = None
                if info.cover:
                    from PIL import Image
                    with Image.open(io.BytesIO(info.cover)) as image:
                        image.thumbnail((24, 24))
                        output = io.BytesIO()
                        image.convert("RGB").save(output, "JPEG", quality=80)
                        thumbnail = output.getvalue()
                after = target.stat()
                if signature != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise HTTPException(409, "파일이 변경되었습니다. 다시 불러오세요")
                cached = (signature, thumbnail, storage.digest(repr((key, signature)).encode()))
                _thumbnail_cache[key] = cached
            _thumbnail_cache.move_to_end(key)
            while len(_thumbnail_cache) > _THUMBNAIL_LIMIT:
                _thumbnail_cache.popitem(last=False)
        if not cached[1]:
            raise HTTPException(404, "표지 없음")
        headers = {"ETag": '"' + cached[2] + '"',
                   "Cache-Control": "private, max-age=86400" if v else "private, max-age=0, must-revalidate"}
        if request.headers.get("if-none-match") == headers["ETag"]:
            return Response(status_code=304, headers=headers)
        return Response(cached[1], media_type="image/jpeg", headers=headers)
    except (storage.StorageError, OSError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/lyrics/{path:path}")
def file_lyrics(path: str, v: Optional[str] = None):
    # Read the selected song only; never populate list data with lyric bodies.
    try:
        target = storage.resolve_music(MUSIC_ROOT, path)
        if v and storage.revision(target) != v:
            raise HTTPException(409, "파일이 변경되었습니다. 다시 확인하세요")
        info = original_tags.read_file(str(target))
        return {"lyrics": info.lyrics}
    except (storage.StorageError, OSError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/cover/{path:path}")
def file_cover(path: str):
    try:
        info = original_tags.read_file(str(storage.resolve_music(MUSIC_ROOT, path)))
        if not info.cover:
            raise HTTPException(404, "표지 없음")
        return Response(info.cover, media_type=info.cover_mime or "image/jpeg")
    except (storage.StorageError, OSError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/revert/{path:path}")
def revert_file(path: str, request: RevertRequest):
    with storage.OPERATION_LOCK:
        try:
            target = storage.resolve_music(MUSIC_ROOT, path)
            outcome = storage.restore(target, MUSIC_ROOT.resolve(), BACKUP_ROOT, request.expected_revision)
            for job in jobs.values():
                for result in job.get("results", []):
                    if result.get("path") == path:
                        result["original"] = outcome["original"]
                        result["stored_saved"] = False
                        result["file_state"] = file_state(result)
                        result["last_save"] = {"status": outcome["status"]}
            try:
                save_jobs()
            except OSError as exc:
                outcome["state_error"] = str(exc)
            return outcome
        except (storage.StorageError, OSError, original_tags.UnsupportedFile) as exc:
            raise HTTPException(400, str(exc))

@app.get("/")
def root():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
