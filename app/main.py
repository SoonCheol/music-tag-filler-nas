import os, json, re, uuid, time
from pathlib import Path
from typing import List, Dict, Optional
import requests, musicbrainzngs
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import mutagen

MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_FILE = DATA_ROOT / "jobs.json"
BACKUP_ROOT = DATA_ROOT / "backups"
BACKUP_ROOT.mkdir(exist_ok=True)

musicbrainzngs.set_useragent("music-tag-filler-nas", "0.4.0", "https://github.com/microhan1/music-tag-filler")

app = FastAPI(title="음악 정보 채우기 NAS Web")

# --- job store ---
jobs: Dict[str, dict] = {}
if JOBS_FILE.exists():
    try:
        raw = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        # 이전 실행 중이던 작업은 interrupted로 표시 (이어하기 가능)
        for j in raw.values():
            if j.get("status") in ("scanning", "queued"):
                j["status"] = "interrupted"
                j["interrupted_at"] = time.time()
        jobs = raw
    except:
        jobs = {}

def save_jobs():
    try:
        JOBS_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    except:
        pass

def parse_filename(p: Path):
    name = p.stem
    if " - " in name:
        artist, title = name.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", name.strip()

def search_itunes(artist: str, title: str):
    try:
        term = f"{artist} {title}".strip()
        if not term:
            return []
        r = requests.get("https://itunes.apple.com/search", params={"term": term, "media": "music", "limit": 10, "country": "KR"}, timeout=10)
        j = r.json()
        results = []
        for item in j.get("results", []):
            art = item.get("artworkUrl100", "").replace("100x100bb", "1000x1000bb")
            score = 0
            if title.lower() in item.get("trackName","").lower():
                score += 50
            if artist.lower() in item.get("artistName","").lower():
                score += 30
            results.append({
                "source": "iTunes",
                "title": item.get("trackName"),
                "artist": item.get("artistName"),
                "album": item.get("collectionName"),
                "year": (item.get("releaseDate","")[:4]),
                "track": item.get("trackNumber"),
                "cover_url": art,
                "score": score,
            })
        return results
    except:
        return []

def search_musicbrainz(artist: str, title: str):
    try:
        query = f"{title} AND artist:{artist}" if artist else title
        res = musicbrainzngs.search_recordings(query=query, limit=10)
        out = []
        for rec in res.get("recording-list", []):
            r_title = rec.get("title","")
            r_artist = rec.get("artist-credit", [{}])[0].get("artist",{}).get("name","") if rec.get("artist-credit") else ""
            r_album = rec.get("release-list", [{}])[0].get("title","") if rec.get("release-list") else ""
            r_date = rec.get("release-list", [{}])[0].get("date","") if rec.get("release-list") else ""
            score = rec.get("ext:score", "0")
            try:
                score_int = int(score)
            except:
                score_int = 0
            cover_url = f"https://coverartarchive.org/release/{rec.get('release-list',[{}])[0].get('id')}/front-500" if rec.get("release-list") else ""
            out.append({
                "source": "MusicBrainz",
                "title": r_title,
                "artist": r_artist,
                "album": r_album,
                "year": r_date[:4] if r_date else "",
                "track": None,
                "cover_url": cover_url,
                "score": score_int,
                "mbid": rec.get("id"),
            })
        return out
    except:
        return []

def search_lrclib(artist: str, title: str, duration: float):
    try:
        if not artist or not title:
            return None
        low = (artist+" "+title).lower()
        if any(k in low for k in ["instrumental","off vocal","karaoke","mr","inst."]):
            return None
        r = requests.get("https://lrclib.net/api/get", params={"artist_name": artist, "track_name": title, "duration": int(duration)}, timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or data.get("instrumental"):
            return None
        if abs((data.get("duration") or 0) - duration) > 3:
            return None
        return data.get("plainLyrics")
    except:
        return None

def read_tags(path: Path):
    try:
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

def write_tags(path: Path, candidate: dict, options: dict):
    try:
        # 백업
        orig = read_tags(path)
        bak_path = path.with_suffix(path.suffix + ".tagbak.json")
        try:
            bak_path.write_text(json.dumps(orig, ensure_ascii=False, indent=2), encoding="utf-8")
            (BACKUP_ROOT / f"{path.name}.tagbak.json").write_text(json.dumps({"path": str(path), "original": orig, "candidate": candidate}, ensure_ascii=False, indent=2), encoding="utf-8")
        except:
            pass

        only_empty = options.get("only_empty", True)
        audio_easy = mutagen.File(str(path), easy=True)
        if audio_easy is None:
            return False, "지원하지 않는 포맷"

        def set_if(key, value):
            if not value:
                return
            if only_empty and audio_easy.get(key):
                return
            audio_easy[key] = [str(value)]

        set_if("title", candidate.get("title"))
        set_if("artist", candidate.get("artist"))
        set_if("album", candidate.get("album"))
        if candidate.get("year"):
            set_if("date", candidate.get("year"))
        if candidate.get("track"):
            set_if("tracknumber", str(candidate.get("track")))

        # 가사
        if options.get("fill_lyrics") and options.get("lyrics_text"):
            try:
                audio_easy["lyrics"] = [options.get("lyrics_text")]
            except:
                pass

        audio_easy.save()

        # 커버
        if candidate.get("cover_url"):
            try:
                r = requests.get(candidate["cover_url"], timeout=15)
                if r.status_code == 200:
                    # mutagen으로 커버 삽입 (간단 버전)
                    from mutagen.id3 import ID3, APIC
                    from mutagen.mp3 import MP3
                    if path.suffix.lower() == ".mp3":
                        try:
                            audio = MP3(str(path), ID3=ID3)
                            if audio.tags is None:
                                audio.add_tags()
                            audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=r.content))
                            audio.save()
                        except:
                            pass
            except:
                pass

        # 파일명 바꾸기
        if options.get("rename"):
            new_artist = audio_easy.get("artist",[""])[0] if audio_easy.get("artist") else candidate.get("artist","")
            new_title = audio_easy.get("title",[""])[0] if audio_easy.get("title") else candidate.get("title","")
            if new_artist and new_title:
                new_name = f"{new_artist} - {new_title}{path.suffix}"
                new_name = re.sub(r'[\\/:*?\"<>|]', "_", new_name)
                new_path = path.parent / new_name
                if new_path != path and not new_path.exists():
                    path.rename(new_path)
        return True, "ok"
    except Exception as e:
        return False, str(e)

def scan_job(job_id: str, sub_path: str, opts: dict, resume: bool = False):
    job = jobs.get(job_id)
    if not job:
        return
    root = MUSIC_ROOT / sub_path if sub_path else MUSIC_ROOT
    if not root.exists():
        job["status"] = "failed"
        job["error"] = f"경로 없음: {root}"
        save_jobs()
        return

    # 파일 목록
    files = []
    for ext in ("*.mp3","*.flac","*.m4a","*.ogg","*.mp4","*.wma","*.wav"):
        files.extend(list(root.rglob(ext)))
    files = sorted(files)

    # 이어하기: 이미 처리된 파일 제외
    existing_results = job.get("results", []) if resume else []
    existing_paths = set(r.get("path") for r in existing_results) if resume else set()
    start_idx = len(existing_results) if resume else 0

    if not resume:
        job["total"] = len(files)
        job["results"] = []
        job["scanned"] = 0
    else:
        # total은 그대로, results는 유지
        job["total"] = len(files)

    job["status"] = "scanning"
    job["cancel_requested"] = False
    save_jobs()

    results = existing_results if resume else []

    for idx in range(start_idx, len(files)):
        # 중지 체크
        cur_job = jobs.get(job_id)
        if not cur_job or cur_job.get("cancel_requested"):
            job["status"] = "cancelled"
            job["cancelled_at"] = time.time()
            save_jobs()
            return

        f = files[idx]
        try:
            rel = str(f.relative_to(MUSIC_ROOT))
            job["current_file"] = rel
            job["scanned"] = idx
            orig = read_tags(f)
            artist_hint, title_hint = parse_filename(f)
            if orig.get("artist"):
                artist_hint = orig.get("artist") or artist_hint
            if orig.get("title"):
                title_hint = orig.get("title") or title_hint

            candidates = []
            candidates += search_musicbrainz(artist_hint, title_hint)
            candidates += search_itunes(artist_hint, title_hint)
            candidates = sorted(candidates, key=lambda x: x.get("score",0), reverse=True)[:10]

            lyrics_text = None
            if opts.get("fill_lyrics") and candidates:
                best = candidates[0]
                dur = orig.get("duration",0) or 0
                lyrics_text = search_lrclib(best.get("artist","") or artist_hint, best.get("title","") or title_hint, dur)

            best_candidate = candidates[0] if candidates else None
            auto_apply = False
            if best_candidate and best_candidate.get("score",0) >= 90:
                auto_apply = True

            results.append({
                "path": rel,
                "abs_path": str(f),
                "original": orig,
                "parsed": {"artist": artist_hint, "title": title_hint},
                "candidates": candidates,
                "best": best_candidate,
                "auto_apply": auto_apply,
                "lyrics": lyrics_text,
                "lyrics_status": "found" if lyrics_text else "not_found" if opts.get("fill_lyrics") else "skipped"
            })
        except Exception as e:
            try:
                results.append({"path": str(f.relative_to(MUSIC_ROOT)), "error": str(e), "candidates": [], "original": {}})
            except:
                results.append({"path": str(f), "error": str(e), "candidates": [], "original": {}})

        job["results"] = results
        job["scanned"] = idx + 1
        if idx % 3 == 0:
            save_jobs()
        time.sleep(0.25)

    job["results"] = results
    job["scanned"] = len(files)
    job["status"] = "done"
    job["finished_at"] = time.time()
    save_jobs()

class ScanRequest(BaseModel):
    sub_path: str = ""
    only_empty: bool = True
    fill_lyrics: bool = False
    rename: bool = False
    use_fingerprint: bool = True
    force: bool = False

def get_active_job():
    for j in jobs.values():
        if j.get("status") in ("queued", "scanning"):
            return j
    return None

@app.post("/api/scan")
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    # 중복 방지
    active = get_active_job()
    if active and not req.force:
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
    save_jobs()
    background_tasks.add_task(scan_job, job_id, req.sub_path, req.model_dump(), False)
    return {"job_id": job_id}

@app.get("/api/jobs")
def list_jobs():
    return sorted(jobs.values(), key=lambda x: x.get("created_at",0), reverse=True)

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return jobs[job_id]

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    job = jobs[job_id]
    # scanning/queued는 정상 취소, interrupted는 즉시 cancelled로 변경 (중지 버튼)
    if job.get("status") in ("scanning", "queued"):
        job["cancel_requested"] = True
        job["status"] = "cancelling"
    elif job.get("status") in ("interrupted", "failed", "cancelled"):
        job["status"] = "cancelled"
        job["cancelled_at"] = time.time()
    else:
        raise HTTPException(400, "중지할 수 없는 상태입니다")
    save_jobs()
    return {"status": job["status"], "id": job_id}

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    job = jobs[job_id]
    if job.get("status") in ("scanning", "queued", "cancelling"):
        raise HTTPException(400, "진행 중인 작업은 먼저 중지하세요")
    del jobs[job_id]
    save_jobs()
    return {"deleted": job_id}

@app.post("/api/jobs/{job_id}/resume")
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

    job["status"] = "queued"
    job["cancel_requested"] = False
    save_jobs()
    background_tasks.add_task(scan_job, job_id, job.get("sub_path",""), job.get("options",{}), True)
    return {"status": "resumed", "id": job_id}

@app.post("/api/jobs/{job_id}/save")
def save_job(job_id: str, selected: List[str] = None):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    job = jobs[job_id]
    opts = job["options"]
    results = job["results"]
    saved = 0
    errors = []
    for r in results:
        p = r.get("path")
        if selected and p not in selected:
            continue
        cand = r.get("best")
        if not cand:
            continue
        abs_path = MUSIC_ROOT / r["path"]
        if not abs_path.exists():
            # rename으로 이미 옮겨졌을 수도 있음
            continue
        ok, msg = write_tags(abs_path, cand, {"only_empty": opts.get("only_empty", True), "fill_lyrics": opts.get("fill_lyrics"), "rename": opts.get("rename"), "lyrics_text": r.get("lyrics")})
        if ok:
            saved += 1
        else:
            errors.append(f"{p}: {msg}")
    job["status"] = "saved"
    job["saved_count"] = saved
    save_jobs()
    return {"saved": saved, "errors": errors}

@app.post("/api/revert/{path:path}")
def revert_file(path: str):
    target = MUSIC_ROOT / path
    bak = target.with_suffix(target.suffix + ".tagbak.json")
    if not bak.exists():
        raise HTTPException(404, "백업 없음")
    try:
        data = json.loads(bak.read_text(encoding="utf-8"))
        return {"restored_from": str(bak)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/")
def root():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
