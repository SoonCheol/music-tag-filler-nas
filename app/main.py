import os, json, re, uuid, time, threading, logging
from pathlib import Path
from typing import Dict, Optional
import requests, musicbrainzngs
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
import mutagen
from functools import wraps
from collections import OrderedDict
import io
import inspect
import hmac
from pydantic import BaseModel, Field
from .request_models import (
    ScanRequest, DeleteJobsRequest, SaveItem, SaveRequest, LyricsSearchRequest,
    RevertRequest, SearchRequest, RenameRequest, CandidateLyricsRequest, MaSearchRequest,
)
from . import storage, search_service, job_service, preferences, rename_service, job_store, scan_service, lyrics_service
from .lyrics_service import lyric_response
from .scan_service import ScanCancellation
from .upstream import tags as original_tags, match as original_match, search_lyrics as original_lyrics

APP_VERSION = os.getenv("APP_VERSION", "v2.0.0")
if not re.fullmatch(r"v\d+\.\d+\.\d+", APP_VERSION):
    APP_VERSION = "v2.0.0"

MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_FILE = DATA_ROOT / "jobs.json"
BACKUP_ROOT = DATA_ROOT / "backups"
BACKUP_ROOT.mkdir(exist_ok=True)

musicbrainzngs.set_useragent("music-tag-filler-nas", APP_VERSION[1:], "https://github.com/microhan1/music-tag-filler")

app = FastAPI(title="음악 정보 채우기 NAS Web", version=APP_VERSION[1:])

# --- job store ---
jobs: Dict[str, dict] = {}
job_store_error = None
_scan_clocks = {}
try:
    jobs = job_store.load(DATA_ROOT)
except (OSError, ValueError, TypeError) as exc:
    raise RuntimeError("작업 기록을 안전하게 열 수 없습니다: " + str(exc)) from exc


def save_jobs(job_id=None):
    with storage.OPERATION_LOCK:
        if job_store_error:
            raise OSError(job_store_error)
        scan_service.update_scan_timing(jobs, _scan_clocks, job_id)
        job_store.save(JOBS_FILE.parent, jobs, [job_id] if job_id else None)


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


def scan_job(job_id: str, sub_path: str, opts: dict, resume: bool = False):
    context = scan_service.ScanContext(
        jobs=jobs, scan_clocks=_scan_clocks, music_root=MUSIC_ROOT, data_root=DATA_ROOT,
        save_jobs=save_jobs, operation_lock=storage.OPERATION_LOCK,
        parse_filename=parse_filename, prepare_result=prepare_result, file_state=file_state,
    )
    return scan_service.scan_job(context, job_id, sub_path, opts, resume)

_activity_lock = threading.RLock()
_activity = {}


def begin_activity(label, path=""):
    token = uuid.uuid4().hex
    with _activity_lock:
        _activity[token] = {"id": token, "label": label, "path": path, "state": "running"}
        rename_service.active[label] = rename_service.active.get(label, 0) + 1
    return token


def end_activity(token):
    with _activity_lock:
        entry = _activity.pop(token, None)
        if entry:
            label = entry["label"]
            rename_service.active[label] = max(0, rename_service.active.get(label, 0) - 1)


def path_operation(label):
    """Register under the mutation lock; status reads/cleanup use a separate lock."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs).arguments
            request = bound.get("request")
            path = bound.get("path") or getattr(request, "path", "")
            with storage.OPERATION_LOCK:
                try:
                    rename_service.check_ready(DATA_ROOT)
                except storage.StorageError as exc:
                    raise HTTPException(409, str(exc))
                token = begin_activity(label, path)
            try:
                return function(*args, **kwargs)
            finally:
                end_activity(token)
        return wrapped
    return decorate


def get_active_job():
    for j in jobs.values():
        if j.get("status") in job_service.ACTIVE:
            return j
    return None


def job_locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with storage.OPERATION_LOCK:
            if function.__name__ in ("start_scan", "resume_job"):
                try:
                    rename_service.check_ready(DATA_ROOT, MUSIC_ROOT)
                    if function.__name__ == "resume_job":
                        rename_service.reconcile_jobs(MUSIC_ROOT.resolve(), rename_service.records(DATA_ROOT), jobs, save_jobs)
                except storage.StorageError as exc:
                    raise HTTPException(409, str(exc))
                except OSError as exc:
                    raise HTTPException(503, "이어하기 경로 기록 실패: " + str(exc))
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



# MA searches are read-only; the file is always reopened and SHA256 checked by
# the existing save path. Never trust an MA URI as a filesystem write target.
@app.post("/api/ma/search")
def search_ma_library(request: MaSearchRequest):
    from urllib.parse import unquote
    url = os.getenv("MA_API_URL", "").rstrip("/")
    token = os.getenv("MA_API_TOKEN", "").strip()
    if not url or not token:
        raise HTTPException(503, "MA_API_URL 및 MA_API_TOKEN 서버 설정이 필요합니다")
    if not re.fullmatch(r"https?://[^/]+(?::[0-9]+)?", url):
        raise HTTPException(503, "MA_API_URL 설정을 확인하세요")
    try:
        response = requests.post(url + "/api",
            json={"message_id": uuid.uuid4().hex, "command": "music/tracks/library_items",
                  "args": {"search": request.query, "limit": request.limit, "offset": 0}},
            headers={"Authorization": "Bearer " + token}, timeout=20)
        response.raise_for_status()
        packet = response.json()
    except (requests.RequestException, ValueError) as exc:
        logging.getLogger("uvicorn.error").warning("MA library lookup failed: %s", type(exc).__name__)
        raise HTTPException(502, "MA 서버 검색 요청에 실패했습니다") from exc
    if isinstance(packet, dict) and (packet.get("error") or packet.get("error_code")):
        raise HTTPException(502, "MA 서버가 검색 오류를 반환했습니다")
    tracks = packet.get("result") if isinstance(packet, dict) else packet
    if isinstance(tracks, dict):
        tracks = tracks.get("items") or tracks.get("tracks")
    if not isinstance(tracks, list):
        raise HTTPException(502, "MA 검색 결과 형식을 확인할 수 없습니다")

    root = MUSIC_ROOT.resolve()
    results = []
    seen = set()
    term = request.query.casefold()
    for track in tracks:
        if not isinstance(track, dict):
            continue
        artists = ", ".join(str(a.get("name", "")) for a in track.get("artists", []) if isinstance(a, dict))
        album = track.get("album") or {}
        album = album if isinstance(album, dict) else {}
        album_artists = ", ".join(str(a.get("name", "")) for a in album.get("artists", []) if isinstance(a, dict))
        mappings = track.get("provider_mappings") or []
        candidates = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            provider = str(mapping.get("provider_domain") or mapping.get("provider_instance") or "")
            if not provider.startswith("filesystem"):
                continue
            candidates.append(str(mapping.get("item_id") or ""))
        for raw in candidates:
            raw = unquote(raw)
            if raw.startswith("/music/"):
                relative = raw[len("/music/"):]
            elif raw.startswith("/"):
                continue
            else:
                relative = raw
            try:
                target = storage.resolve_music(root, relative)
            except (storage.StorageError, OSError):
                continue
            relative = target.relative_to(root).as_posix()
            if relative in seen:
                continue
            fields = {"title": str(track.get("name") or ""), "artist": artists,
                      "albumartist": album_artists, "filename": target.name}
            # MA's library search may match broadly. Filter field-specific queries here.
            if request.field != "all" and term not in fields[request.field].casefold():
                continue
            try:
                original = storage.describe(target)
            except (storage.StorageError, OSError, original_tags.UnsupportedFile):
                continue
            artist, title = parse_filename(target)
            seen.add(relative)
            results.append({"path": relative, "original": original,
                            "parsed": {"artist": original.get("artist") or artist,
                                       "title": original.get("title") or title},
                            "candidates": [], "search_phase": "complete",
                            "search_status": "ma_library", "scan_auto_selected": False,
                            "file_state": "review", "ma_source": True})
            break
    with storage.OPERATION_LOCK:
        job_id = uuid.uuid4().hex[:8]
        jobs[job_id] = {"id": job_id, "status": "done", "total": len(results),
                        "scanned": len(results), "sub_path": "",
                        "options": {"search_mode": "integrated"},
                        "created_at": time.time(), "finished_at": time.time(),
                        "ma_search": True, "ma_query": request.query,
                        "view_revision": 1, "current_file": "", "results": results,
                        "cancel_requested": False}
        try:
            save_jobs(job_id)
        except OSError as exc:
            del jobs[job_id]
            raise HTTPException(503, "검색 결과를 작업 목록에 저장하지 못했습니다") from exc
        return public_job(jobs[job_id])


@app.get("/api/musicbrainz/artists")
def search_musicbrainz_artists(query: str):
    if not query.strip() or len(query) > 160:
        raise HTTPException(400, "가수 이름을 1~160자로 입력하세요")
    try:
        data = search_service.net.get_json(
            "https://musicbrainz.org/ws/2/artist",
            {"query": query.strip(), "fmt": "json", "limit": 15})
        if not isinstance(data.get("artists"), list):
            raise ValueError("unexpected artist response")
    except Exception as exc:
        logging.getLogger("uvicorn.error").warning("MusicBrainz artist lookup failed: %s", type(exc).__name__)
        raise HTTPException(502, "MusicBrainz 가수 검색에 실패했습니다") from exc
    return {"artists": [{"id": str(a.get("id") or ""), "name": str(a.get("name") or ""),
                         "disambiguation": str(a.get("disambiguation") or ""),
                         "country": str(a.get("country") or ""),
                         "type": str(a.get("type") or ""),
                         "sort_name": str(a.get("sort-name") or "")}
                        for a in data.get("artists", []) if isinstance(a, dict) and a.get("id")]}


@app.post("/api/scan")
@job_locked
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    root = MUSIC_ROOT.resolve()
    target = (root / req.sub_path).resolve()
    if not req.paths and (not target.is_relative_to(root) or not target.is_dir()):
        raise HTTPException(400, "유효한 음악 폴더를 선택하세요")
    for value in req.paths or [req.sub_path]:
        selected = root / value
        if Path(value).is_absolute() or ".." in Path(value).parts or selected.is_symlink() or not selected.resolve().is_relative_to(root) or not selected.exists():
            raise HTTPException(400, "유효한 음악 파일/폴더를 선택하세요")
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
        save_jobs(job_id)
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
def list_jobs(summary: bool = False):
    priority = {"scanning": 0, "cancelling": 0, "queued": 1, "interrupted": 2,
                "cancelled": 2, "failed": 3, "partial": 3, "done": 4}
    ordered = sorted(jobs.values(), key=lambda x: (priority.get(x.get("status"), 3),
                                                    -x.get("record_version", x.get("created_at", 0))),)
    if summary:
        return [{k:v for k,v in job.items() if k not in ("results", "options")} for job in ordered]
    for job in ordered:
        for result in job.get("results", []):
            if not result.get("ranking_version"):
                prepare_result(result)
    return [public_job(job) for job in ordered]

@app.get("/api/jobs/{job_id}")
@job_locked
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    for result in jobs[job_id].get("results", []):
        if not result.get("ranking_version"):
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
    save_jobs(job_id)
    return {"status": job["status"], "id": job_id}

def remove_job_records(ids):
    if not ids or len(ids)!=len(set(ids)):
        raise HTTPException(400,"삭제할 작업을 중복 없이 선택하세요")
    for key in ids:
        if key not in jobs:raise HTTPException(404,"job not found")
        if jobs[key].get("status") in job_service.ACTIVE:
            raise HTTPException(409,"진행 중인 작업은 삭제할 수 없습니다")
    with save_tasks_lock:
        if any(task.get("job_id") in ids and task.get("status") in ("queued","saving") for task in save_tasks.values()):
            raise HTTPException(409,"태그 저장 대기 또는 진행 중인 작업 기록은 삭제할 수 없습니다")
    removed=[]
    for key in ids:
        try:
            job_store.delete(JOBS_FILE.parent,[key])
        except OSError as exc:
            raise HTTPException(503,{"message":"작업 기록 삭제 실패: "+str(exc),"deleted":removed})
        del jobs[key];removed.append(key)
    return {"deleted":removed}


@app.post("/api/jobs/delete")
@job_locked
def delete_jobs(request: DeleteJobsRequest):
    return remove_job_records(request.ids)


@app.delete("/api/jobs/{job_id}")
@job_locked
def delete_job(job_id: str):
    remove_job_records([job_id])
    return {"deleted":job_id}


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
        save_jobs(job_id)
    except OSError as exc:
        job.update(status=previous_status, cancel_requested=previous_cancel)
        raise HTTPException(503, "이어하기 기록 실패: " + str(exc))
    background_tasks.add_task(scan_job, job_id, job.get("sub_path",""), job.get("options",{}), True)
    return {"status": "resumed", "id": job_id}


_lyrics_service = lyrics_service.LyricsService(lambda: MUSIC_ROOT, lambda candidate: candidate_id(candidate))


def remember_lyrics(key, found, searched=True, candidate_key=None):
    return _lyrics_service.remember_lyrics(key, found, searched, candidate_key)


@app.post("/api/jobs/{job_id}/lyrics-search")
@path_operation("가사 검색")
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
    candidate = None
    if request.candidate_id:
        candidate = next((c for c in row.get("candidates", []) if candidate_id(c) == request.candidate_id), None)
        if candidate is None:
            raise HTTPException(404, "이 파일의 후보가 아닙니다")
    # A candidate-specific re-search shares its verified token/cache with the
    # candidate lyrics pane; free-text search remains a separate manual query.
    duration = (row.get("original", {}).get("duration") or candidate.get("duration", 0)) if candidate else 0
    return lyric_response(lookup_lyrics(job_id, request.path, request.expected_revision,
                                      request.title, request.artist, duration, candidate, request.force,
                                      manual=candidate is None))


def lookup_lyrics(job_id, path, revision, title, artist, duration, candidate=None, force=False, *, manual=False):
    return _lyrics_service.lookup_lyrics(job_id, path, revision, title, artist, duration, candidate, force, manual=manual)


def selected_lyrics(job_id, path, revision, lyrics_id, title, artist, approve_manual_mismatch=False):
    return _lyrics_service.selected_lyrics(job_id, path, revision, lyrics_id, title, artist, approve_manual_mismatch)


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
@path_operation("태그 검색")
def research_file(job_id: str, request: SearchRequest):
    with storage.OPERATION_LOCK:
        if job_id not in jobs:
            raise HTTPException(404, "job not found")
        job = jobs[job_id]
        result = next((r for r in job.get("results", []) if r.get("path") == request.path), None)
        if result is None:
            raise HTTPException(400, "이 작업에 속한 파일이 아닙니다")
        try:
            path = storage.resolve_music(MUSIC_ROOT, request.path)
            original = storage.describe(path)
        except (storage.StorageError, OSError, original_tags.UnsupportedFile) as exc:
            raise HTTPException(400, str(exc))
        if result.get("search_phase") in ("waiting", "running"):
            raise HTTPException(409, "이 곡의 검색이 끝난 후 재검색하세요")
        if request.expected_revision and request.expected_revision != original["revision"]:
            raise HTTPException(409, "파일이 변경되었습니다. 다시 스캔하세요")
        generation = uuid.uuid4().hex
        result["search_generation"] = generation
        preserved_candidate = next((candidate for candidate in result.get("candidates", [])
                                    if candidate_id(candidate) == request.preserve_candidate_id), None)
    artist, title = parse_filename(path)
    query = request.query.strip() or original_match.build_query(original.get("title") or title, original.get("artist") or artist)
    found = search_service.search(path, query, request.country, original["duration"], DATA_ROOT,
                                  mode=request.mode, use_fingerprint=request.use_fingerprint, force=True,
                                  previous=result.get("candidates") if request.mode == "sound" else None,
                                  search_mode=request.search_mode,
                                  on_wait=lambda seconds: result.update(search_wait_seconds=seconds))
    if preserved_candidate and not any(candidate_id(candidate) == request.preserve_candidate_id
                                       for candidate in found.get("candidates", [])):
        found["candidates"].append(preserved_candidate)
    timing = found.pop("_timing", {})
    with storage.OPERATION_LOCK:
        if result.get("search_generation") != generation or storage.revision(path) != original["revision"]:
            raise HTTPException(409, "파일 또는 검색 요청이 변경되어 오래된 결과를 적용하지 않았습니다")
        result.update(found, original=original)
        prepare_result(result)
        save_jobs(job_id)
        timing.update(event="research", job_id=job_id, path=request.path)
        logging.getLogger("uvicorn.error").info("scan_timing %s", json.dumps(timing))
        return result


@app.get("/api/jobs/{job_id}/cover/{selection_id}")
@path_operation("앨범 이미지 검색")
def candidate_cover(job_id: str, selection_id: str, path: str, force: bool = False):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    result = next((r for r in jobs[job_id].get("results", []) if r.get("path") == path), None)
    if result is None:
        raise HTTPException(400, "이 작업에 속한 파일이 아닙니다")
    candidate = next((c for c in result.get("candidates", []) if candidate_id(c) == selection_id), None)
    if candidate is None:
        raise HTTPException(404, "이 파일의 검색 후보가 아닙니다")
    data, errors = search_service.fetch_cover(candidate, result.get("country") or search_service.configuration(DATA_ROOT).country, force=force)
    if data is None:
        raise HTTPException(404, detail={"message": "표지 조회 실패", "errors": errors,
                                            "state": "none" if all(e.get("code") == "cover_not_found" for e in errors) else "error"})
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store" if force else "private, max-age=600"})


def file_state(result):
    stored = result.get("stored_saved", result.get("last_save", {}).get("status") in ("saved", "partial"))
    if not stored and result.get("search_phase") in ("waiting", "running", "error"):
        return result["search_phase"]
    return "saved" if stored else "auto" if result.get("scan_auto_selected", result.get("auto_apply", False)) else "review"


def prepare_result(result):
    result["ranking_version"] = 1
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
        if not item.cover_id and not request.rename and not (request.save_lyrics and (item.lyrics_id or item.lyrics_text)):
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
    original_values = current.tags.as_dict()
    requested_fields = [field for field in item.fields if final[storage.FIELDS[field]] != original_values[storage.FIELDS[field]]]
    ids = None
    if item.include_ids and candidate and item.manual_artist_ids is None and item.manual_album_artist_ids is None:
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
    if item.manual_artist_ids is not None or item.manual_album_artist_ids is not None:
        if not item.include_ids or item.selection != "edit":
            raise storage.StorageError("수동 식별자는 직접 편집으로 선택한 경우에만 저장할 수 있습니다")
        for values in (item.manual_artist_ids, item.manual_album_artist_ids):
            if values is not None and any(not re.fullmatch(
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", v)
                    for v in values):
                raise storage.StorageError("MusicBrainz Artist ID는 UUID 형식이어야 합니다")
        if ids is None:
            ids = original_tags.Ids()
        if item.manual_artist_ids is not None:
            ids.mb_artist_ids = item.manual_artist_ids
        if item.manual_album_artist_ids is not None:
            ids.mb_album_artist_ids = item.manual_album_artist_ids
    wants_cover = bool(request.save_cover and item.include_cover and candidate and (candidate.get("cover_url") or candidate.get("album"))
                       and not (only_empty and current.cover is not None))
    uploaded = preferences.get_cover(result.get("job_id", ""), item.cover_id) if request.save_cover and item.cover_id else None
    if uploaded is not None:
        wants_cover = not (only_empty and current.cover is not None)
    has_real_lyrics = bool(current.synced or (current.lyrics.strip() and (only_empty or not original_lyrics.marker_only(current.lyrics))))
    choice = selected_lyrics(result.get("job_id", ""), item.path, item.expected_revision, item.lyrics_id, final["title"], final["artist"], item.approve_manual_lyrics_mismatch) if request.save_lyrics and item.lyrics_id else None
    edited_lyrics = original_lyrics.clean_text(item.lyrics_text) if request.save_lyrics and item.lyrics_text is not None else None
    # New UI explicitly requests searched or directly entered lyrics.
    # Old API clients without that control retain their automatic missing-lyrics option.
    wants_lyrics = bool("save_lyrics" not in request.model_fields_set and request.save_lyrics and item.selection != "none" and request.fill_lyrics and edited_lyrics is None and not choice and not has_real_lyrics and final["title"] and final["artist"])
    if choice and choice.get("candidate_id") and choice["candidate_id"] != item.candidate_id:
        raise storage.StorageError("가사 후보가 변경되었습니다. 다시 검색하세요")
    manual_lyrics = (edited_lyrics if edited_lyrics is not None else choice["lyrics"] if choice and choice["status"] == "found" else None) if not (only_empty and has_real_lyrics) else None
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
    lyrics_status = "found" if manual_lyrics else choice["status"] if choice else "preserved" if has_real_lyrics else "skipped"
    if wants_lyrics:
        found, actually_searched = _lyrics_service.legacy_lookup(final["title"], final["artist"], current.length, lyric_context)
        lyrics_status = found.status
        if found.status == original_lyrics.FOUND:
            lyrics = found.text
        choice = remember_lyrics((str(MUSIC_ROOT.resolve()), result.get("job_id", ""), item.path, item.expected_revision, final["title"], final["artist"]), found, actually_searched)
    synced = choice.get("synced") if choice and choice["status"] == "found" and request.save_lyrics and not (only_empty and (has_real_lyrics or current.synced)) else None
    if edited_lyrics is not None and (not choice or edited_lyrics != choice["lyrics"]):
        synced = None  # Edited plain lyrics have no verified timestamps; preserve existing SYLT/LRC.
    requested_assets = []
    if cover is not None:
        requested_assets.append("cover")
    if manual_lyrics:
        requested_assets.append("lyrics")
    if synced and request.save_synced:
        requested_assets.append("synced")
    if synced and request.create_lrc:
        requested_assets.append("lrc")
    outcome = storage.save(path, MUSIC_ROOT.resolve(), BACKUP_ROOT, values, item.fields,
                           only_empty, item.expected_revision, cover, lyrics, False, ids, replace_lyrics=bool(manual_lyrics),
                           synced=synced if request.save_synced else None, lrc=synced if request.create_lrc else None,
                           asset_root=DATA_ROOT, rename_context=(jobs, save_jobs, result.get("job_id", "")))
    actual = outcome.get("original") or {}
    outcome["saved_fields"] = [field for field in requested_fields
                                if actual.get({"title": "title", "artist": "artist", "album": "album",
                                               "albumartist": "albumartist", "year": "date",
                                               "track": "tracknumber", "genre": "genre"}[field]) == final[storage.FIELDS[field]]
                                and outcome.get("status") in ("saved", "partial")]
    outcome["failed_fields"] = [field for field in requested_fields if field not in outcome["saved_fields"]]
    saved_assets = list(requested_assets) if outcome.get("status") in ("saved", "partial") and outcome.get("music_saved") else []
    if asset_errors:
        saved_assets = [asset for asset in saved_assets if asset != "cover"]
    if any(error.get("stage", "").startswith("LRC") for error in outcome.get("postprocess_errors", [])):
        saved_assets = [asset for asset in saved_assets if asset != "lrc"]
    outcome["saved_assets"] = saved_assets
    outcome["failed_assets"] = [asset for asset in requested_assets if asset not in saved_assets]
    try:
        if choice:
            outcome["lyrics_search"] = lyric_response(choice)
        outcome["lyrics_status"] = lyrics_status
        outcome["asset_errors"] = asset_errors
        if asset_errors:
            outcome["warning"] = "; ".join(filter(None, [outcome.get("warning")] + [problem["message"] for problem in asset_errors]))
            outcome["status"] = "partial" if outcome["status"] in ("saved", "partial") else "failed"
            if outcome["status"] == "failed":
                outcome["message"] = outcome["warning"]
        if wants_lyrics and lyrics_status == original_lyrics.BUSY:
            outcome["warning"] = (outcome.get("warning", "") + "; 가사 서버 응답 실패: 가사는 추가하지 않았습니다").lstrip("; ")
            if outcome["status"] == "saved":
                outcome["status"] = "partial"
    except Exception as exc:
        storage.postprocess_error(outcome, "저장 응답 생성", exc)
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
        tasks = [dict(task) for task in save_tasks.values()]
    def order(task):
        state = task.get("status")
        group = 0 if state == "saving" else 1 if state == "queued" else 3 if state == "failed" or task.get("failed") or task.get("partial") else 4
        return group, -task.get("finished_at", task.get("created_at", 0))
    return sorted(tasks, key=order)


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
        try:
            rename_service.check_ready(DATA_ROOT)
        except storage.StorageError as exc:
            raise HTTPException(409, str(exc))
        if rename_service.renaming:
            raise HTTPException(409, "파일명 변경 중입니다. 완료 후 다시 시도하세요")
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
        with save_tasks_lock:
            task = dict(save_tasks[task_id])
        outcomes = task.get("results", [])
        if outcomes and task["processed"] == task["total"]:
            # All file outcomes are known even if final response construction failed.
            response = {k: task[k] for k in ("saved", "failed", "skipped", "partial")}
            response.update(status="partial" if task["saved"] else "failed" if task["failed"] else "unchanged", scope=request.scope,
                            requested=len(request.paths), results=outcomes,
                            unchanged=sum(o.get("reason") == "unchanged" for o in outcomes),
                            unselected=sum(o.get("reason") == "no_selection" for o in outcomes),
                            errors=[o for o in outcomes if o["status"] in ("failed", "partial")],
                            state_error="파일 처리 후 응답/상태 기록 오류: " + str(exc), save_task_id=task_id)
            update_save_task(task_id, status="done", finished_at=time.time(),
                             current_file="", current_path="", error=str(exc))
            return response
        update_save_task(task_id, status="partial" if task["saved"] else "failed", finished_at=time.time(),
                         current_file="", current_path="", error=str(exc))
        raise


def perform_save_job(job_id: str, request: SaveRequest, task_id: str):
    lock_started = time.perf_counter()
    with storage.OPERATION_LOCK:
        logging.getLogger("uvicorn.error").info("save_timing %s", json.dumps({
            "task_id": task_id, "phase": "lock_wait", "seconds": round(time.perf_counter() - lock_started, 6),
            "thread": threading.get_ident()}))
        try:
            rename_service.check_ready(DATA_ROOT, MUSIC_ROOT)
        except storage.StorageError as exc:
            raise HTTPException(409, str(exc))
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
            outcome = None
            try:
                rename_service.check_ready(DATA_ROOT, MUSIC_ROOT)
                result["job_id"] = job_id
                save_started = time.perf_counter()
                try:
                    outcome = save_one(result, items[relative], request, lyric_context)
                finally:
                    logging.getLogger("uvicorn.error").info("save_timing %s", json.dumps({
                        "task_id": task_id, "phase": "file_save", "seconds": round(time.perf_counter() - save_started, 6),
                        "thread": threading.get_ident()}))
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
                if outcome is not None and outcome.get("status") in ("saved", "partial"):
                    storage.postprocess_error(outcome, "작업 결과 갱신", exc)
                else:
                    outcome = {"path": result["path"], "request_path": relative,
                               "status": "failed", "message": str(exc)}
                result["last_save"] = {k: v for k, v in outcome.items() if k not in ("original", "lyrics_search")}
            update_save_task(task_id, sub_path=job.get("sub_path", ""),
                             current_file=Path(outcome["path"]).name,
                             current_path=str(MUSIC_ROOT / outcome["path"]))
            outcomes.append(outcome)
            if outcome["status"] in ("saved", "partial"):
                counts["saved"] += 1
            if outcome["status"] in ("failed", "skipped", "partial"):
                counts[outcome["status"]] += 1
            update_save_task(task_id, processed=len(outcomes), results=list(outcomes), **counts)
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
        record_started = time.perf_counter()
        try:
            save_jobs(job_id)
        except Exception as exc:
            response["state_error"] = "파일 처리 결과는 위와 같으나 작업 상태 기록 실패: " + str(exc)
        finally:
            logging.getLogger("uvicorn.error").info("save_timing %s", json.dumps({
                "task_id": task_id, "phase": "job_record", "seconds": round(time.perf_counter() - record_started, 6),
                "thread": threading.get_ident()}))
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
@path_operation("파일 정보")
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
@path_operation("썸네일 조회")
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
@path_operation("가사 읽기")
def file_lyrics(path: str, v: Optional[str] = None):
    # Read the selected song only; never populate list data with lyric bodies.
    try:
        target = storage.resolve_music(MUSIC_ROOT, path)
        if v and storage.revision(target) != v:
            raise HTTPException(409, "파일이 변경되었습니다. 다시 확인하세요")
        info = original_tags.read_file(str(target))
        return {"lyrics": info.lyrics or "\n".join(text for text, _ in info.synced)}
    except (storage.StorageError, OSError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/cover/{path:path}")
@path_operation("커버 읽기")
def file_cover(path: str):
    try:
        info = original_tags.read_file(str(storage.resolve_music(MUSIC_ROOT, path)))
        if not info.cover:
            raise HTTPException(404, "표지 없음")
        return Response(info.cover, media_type=info.cover_mime or "image/jpeg")
    except (storage.StorageError, OSError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/revert/{path:path}")
@path_operation("백업 복원")
def revert_file(path: str, request: RevertRequest):
    with storage.OPERATION_LOCK:
        try:
            rename_service.check_ready(DATA_ROOT, MUSIC_ROOT)
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

@app.get("/api/version")
def app_version():
    return {"version": APP_VERSION}


# Proxy the reusable update agent. The music app NEVER receives Portainer/GitHub tokens.
class UpdateApplyPayload(BaseModel):
    expected_current: str = Field(min_length=1, max_length=255)
    expected_latest: str = Field(pattern=r"^[0-9a-f]{40}$")


def updater_config():
    endpoint = os.getenv("NAS_UPDATER_URL", "").rstrip("/")
    app_id = os.getenv("NAS_UPDATER_APP_ID", "music-tag-filler")
    key = os.getenv("NAS_UPDATER_KEY", "")
    if not endpoint.startswith(("http://", "https://")) or not key or not re.fullmatch(r"[A-Za-z0-9_.-]+", app_id):
        raise HTTPException(503, "업데이트 서비스가 연결되지 않았습니다.")
    return endpoint, app_id, key


def update_work_busy():
    if get_active_job():
        return "스캔/검색 진행 중에는 업데이트할 수 없습니다."
    with save_tasks_lock:
        if any(t.get("status") in ("queued", "saving") for t in save_tasks.values()):
            return "태그 저장 중에는 업데이트할 수 없습니다."
        if rename_service.renaming:
            return "파일명 변경 중에는 업데이트할 수 없습니다."
    with _activity_lock:
        if any(rename_service.active.values()):
            return "파일 작업 진행 중에는 업데이트할 수 없습니다."
    return ""


@app.get("/api/updater/safety")
def updater_safety(request: Request):
    _, _, key = updater_config()
    supplied = request.headers.get("x-updater-key", "")
    if not supplied or not hmac.compare_digest(key, supplied):
        raise HTTPException(403, "인증되지 않은 업데이트 요청입니다.")
    busy = update_work_busy()
    return {"safe": not bool(busy), "reason": busy}


def call_updater(method, action, *, payload=None):
    endpoint, app_id, key = updater_config()
    headers = {"X-App-Key": key}
    try:
        response = requests.request(method, endpoint + "/v1/apps/" + app_id + action,
                                    headers=headers, json=payload, timeout=25)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(503, "업데이트 서비스 응답을 받지 못했습니다.") from exc
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        raise HTTPException(response.status_code, detail if isinstance(detail, str) else "업데이트 요청 실패")
    if not isinstance(data, dict):
        raise HTTPException(502, "업데이트 서비스 응답 형식이 올바르지 않습니다.")
    return data


@app.get("/api/updater/status")
def updater_status():
    return call_updater("GET", "")


@app.post("/api/updater/apply", status_code=202)
def updater_apply(payload: UpdateApplyPayload, request: Request):
    # JSON + explicit custom header block cross-origin form submissions.
    if request.headers.get("x-requested-with") != "NAS-Updater":
        raise HTTPException(403, "허용되지 않은 업데이트 요청입니다.")
    busy = update_work_busy()
    if busy:
        raise HTTPException(409, busy)
    return call_updater("POST", "/update",
                        payload={"expected_current": payload.expected_current,
                                 "expected_latest": payload.expected_latest})


@app.get("/")
def root():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def rekey_lyrics(event):
    return _lyrics_service.rekey_lyrics(event)


_rename_tokens = {}


def public_rename(event):
    return {**{key: event[key] for key in ("seq", "old_path", "new_path", "revision")},
            "lyrics_tokens": _rename_tokens.get(event["id"], [])}


@app.get("/api/path-changes")
@job_locked
def path_changes(after: int = 0):
    try:
        events = rename_service.changes(DATA_ROOT, after)
        return {"changes": [public_rename(e) for e in events]}
    except (storage.StorageError, OSError, ValueError) as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/jobs/{job_id}/rename")
def rename_file(job_id: str, request: RenameRequest):
    if not storage.OPERATION_LOCK.acquire(blocking=False):
        raise HTTPException(409, rename_conflict())
    activity_token = None
    try:
        if get_active_job():
            raise HTTPException(409, rename_conflict())
        with _activity_lock:
            busy = [label for label, count in rename_service.active.items() if count]
        with save_tasks_lock:
            if any(t["status"] in ("queued", "saving") for t in save_tasks.values()):
                busy.extend("태그 저장 대기" if t["status"] == "queued" else "태그 저장" for t in save_tasks.values() if t["status"] in ("queued", "saving"))
            if busy:
                raise HTTPException(409, rename_conflict(busy, include_saves=False))
            rename_service.renaming = True
        activity_token = begin_activity("파일명 변경", request.path)
        event = rename_service.rename(MUSIC_ROOT.resolve(), DATA_ROOT, BACKUP_ROOT, jobs, save_jobs,
                                      job_id, request.path, request.stem, request.expected_revision)
        if event["status"] == "unchanged":
            return event
        _rename_tokens[event["id"]] = rekey_lyrics(event)
        with _thumbnail_lock:
            _thumbnail_cache.pop(str(MUSIC_ROOT / request.path), None)
        return {"status": "renamed", "change": public_rename(event)}
    except (storage.StorageError, OSError, ValueError) as exc:
        raise HTTPException(409, str(exc))
    finally:
        if activity_token:
            end_activity(activity_token)
        with save_tasks_lock:
            rename_service.renaming = False
        storage.OPERATION_LOCK.release()


def reconcile_saved_results():
    """Rebuild save state only from journals whose published music still verifies."""
    renames, lyrics = rename_service.recovery_records(DATA_ROOT, MUSIC_ROOT)
    confirmed = {}
    for _, record in renames:
        if record["status"] not in ("pending", "complete"):
            continue
        old, target = MUSIC_ROOT / record["old_path"], MUSIC_ROOT / record["new_path"]
        if (not old.exists() and not old.is_symlink() and target.is_file() and not target.is_symlink()
                and rename_service.identity(target) == record["identity"]
                and storage.revision(target) == record["revision"]):
            confirmed.setdefault(record["new_path"], []).append(record)
    for _, record in lyrics:
        target = MUSIC_ROOT / record["music"]
        if (record["status"] in ("pending", "complete") and target.is_file() and not target.is_symlink()
                and storage.revision(target) == record["after"]):
            confirmed.setdefault(record["music"], []).append(record)
    changed = False
    for job in jobs.values():
        job_changed = False
        for row in job.get("results", []):
            evidence = confirmed.get(row["path"])
            if not evidence:
                continue
            pending = [r for r in evidence if r["status"] == "pending"]
            last = row.get("last_save", {})
            if row.get("stored_saved") and not last.get("recovery_pending"):
                continue
            outcome = {**last, "path": row["path"], "status": "partial" if pending else "saved",
                       "music_saved": True, "changed": True, "recovery_pending": bool(pending)}
            for key in ("warning", "message", "rename_error", "postprocess_errors"):
                outcome.pop(key, None)
            if last.get("asset_errors"):
                outcome["status"] = "partial"
                outcome["warning"] = "; ".join(problem["message"] for problem in last["asset_errors"])
            if pending:
                outcome["warning"] = "음악 저장 완료, 후속 처리 복구 필요: " + "; ".join(r.get("error", "미완료 저널") for r in pending)
            row.update(original=storage.describe(MUSIC_ROOT / row["path"]), stored_saved=True,
                       file_state="saved", last_save=outcome)
            changed = job_changed = True
        if job_changed:
            statuses = [r.get("last_save", {}).get("status") for r in job.get("results", [])]
            saved = sum(status in ("saved", "partial") for status in statuses)
            failed = statuses.count("failed")
            job["saved_count"] = saved
            job["save_status"] = "partial" if "partial" in statuses or (saved and failed) else "failed" if failed else "saved" if saved else "unchanged"
    if changed:
        save_jobs()


@app.on_event("startup")
def recover_filename_changes():
    with storage.OPERATION_LOCK:
        try:
            rename_service.recover(MUSIC_ROOT.resolve(), DATA_ROOT, BACKUP_ROOT, jobs, save_jobs)
            from . import lyric_assets
            lyric_assets.recover(MUSIC_ROOT.resolve(), DATA_ROOT)
            reconcile_saved_results()
        except (storage.StorageError, OSError, ValueError) as exc:
            rename_service.blocked[str(DATA_ROOT.resolve())] = str(exc)
            # Reads remain available; path-changing operations fail closed until repaired.
            pass


def operation_snapshot(include_saves=True):
    # Never acquire OPERATION_LOCK here: save/restore/rename hold it across file I/O.
    with _activity_lock:
        entries = [dict(value) for value in _activity.values()]
    for key, job in list(jobs.items()):
        state = job.get("status")
        if state in ("queued", "scanning", "cancelling"):
            entries.append({"id": "scan:" + key, "label": "파일 스캔", "state": state,
                            "path": job.get("current_file") or job.get("sub_path") or ""})
    if include_saves:
        with save_tasks_lock:
            for key, task in save_tasks.items():
                if task.get("status") in ("queued", "saving"):
                    entries.append({"id": "save:" + key, "label": "태그 저장", "state": task["status"],
                                    "path": task.get("current_path") or task.get("current_file") or task.get("sub_path") or ""})
    for entry in entries:
        phase = " 대기 중..." if entry["state"] == "queued" else " 중지 중..." if entry["state"] == "cancelling" else " 중..."
        entry["message"] = entry["label"] + phase
        entry["file"] = Path(entry["path"]).name if entry["path"] else ""
    return entries


def rename_conflict(fallback=None, include_saves=True):
    names = list(dict.fromkeys(e["message"].removesuffix("...") for e in operation_snapshot(include_saves)))
    if not names:
        names = [label + " 중" for label in fallback or []]
    return (", ".join(names) + "이어서 파일명을 변경할 수 없습니다. 작업 완료 후 다시 시도하세요."
            if names else "다른 파일 작업이 진행 중이어서 파일명을 변경할 수 없습니다. 완료 후 다시 시도하세요.")


@app.get("/api/background-operations")
def background_operations():
    return {"operations": operation_snapshot()}


@app.post("/api/jobs/{job_id}/candidate-lyrics")
@path_operation("가사 검색")
def candidate_lyrics(job_id: str, request: CandidateLyricsRequest):
    with storage.OPERATION_LOCK:
        row = next((r for r in jobs.get(job_id, {}).get("results", []) if r.get("path") == request.path), None)
        if row is None or row.get("original", {}).get("revision") != request.expected_revision:
            raise HTTPException(409, "파일 또는 작업 정보가 변경되었습니다")
        candidate = next((c for c in row.get("candidates", []) if candidate_id(c) == request.candidate_id), None)
        if candidate is None:
            raise HTTPException(404, "이 파일의 후보가 아닙니다")
        title, artist = candidate.get("title", ""), candidate.get("artist", "")
        length = row.get("original", {}).get("duration") or candidate.get("duration", 0)
    entry = lookup_lyrics(job_id, request.path, request.expected_revision, title, artist,
                          length, candidate, request.force)
    return {**lyric_response(entry), "has_lyrics": entry["status"] == "found"}
