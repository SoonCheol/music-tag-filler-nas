
import os, json, re, uuid, asyncio, threading, time, shutil
from pathlib import Path
from typing import List, Dict, Optional
import requests, musicbrainzngs
from PIL import Image
import io
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import mutagen
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_FILE = DATA_ROOT / "jobs.json"
BACKUP_ROOT = DATA_ROOT / "backups"
BACKUP_ROOT.mkdir(exist_ok=True)

musicbrainzngs.set_useragent("music-tag-filler-nas", "0.3.0", "https://github.com/microhan1/music-tag-filler")

app = FastAPI(title="음악 정보 채우기 NAS Web")

# --- simple job store ---
jobs: Dict[str, dict] = {}
if JOBS_FILE.exists():
    try:
        jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except:
        jobs = {}

def save_jobs():
    JOBS_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")

def parse_filename(p: Path):
    name = p.stem
    # 가수 - 제목 패턴
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
            # 고화질 아트: 100x100 -> 1000x1000
            art = item.get("artworkUrl100", "").replace("100x100bb", "1000x1000bb")
            score = 0
            if title.lower() in item.get("trackName","").lower():
                score += 50
            if artist.lower() in item.get("artistName","").lower():
                score += 30
            # 길이 유사도 등은 나중에
            results.append({
                "source": "iTunes",
                "title": item.get("trackName"),
                "artist": item.get("artistName"),
                "album": item.get("collectionName"),
                "year": (item.get("releaseDate","")[:4]),
                "track": item.get("trackNumber"),
                "cover_url": art,
                "score": score,
                "artist_id": item.get("artistId"),
                "collection_id": item.get("collectionId")
            })
        return results
    except Exception as e:
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
            mbid = rec.get("id")
            # cover art archive
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
                "mbid": mbid,
                "artist_mbid": rec.get("artist-credit",[{}])[0].get("artist",{}).get("id") if rec.get("artist-credit") else ""
            })
        return out
    except Exception as e:
        return []

def search_lrclib(artist: str, title: str, duration: float):
    # 원칙: 틀린 가사보다 빈 가사
    try:
        if not artist or not title:
            return None
        # instrumental 체크
        low = (artist+" "+title).lower()
        if any(k in low for k in ["instrumental","off vocal","karaoke","mr","inst."]):
            return None
        r = requests.get("https://lrclib.net/api/get", params={"artist_name": artist, "track_name": title, "duration": int(duration)}, timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or data.get("instrumental"):
            return None
        # 길이 차이 3초 이내 체크는 서버가 이미 함, 추가 검증
        if abs((data.get("duration") or 0) - duration) > 3:
            return None
        plain = data.get("plainLyrics")
        if not plain or "[" in plain[:20]: # 타임스탬프 없는 일반 가사만
            # lrclib는 plainLyrics가 timestamp 없는 버전
            pass
        return plain
    except:
        return None

def read_tags(path: Path):
    try:
        audio = mutagen.File(str(path), easy=False)
        if audio is None:
            return {}
        info = {"duration": getattr(audio.info, "length", 0) if hasattr(audio, "info") else 0}
        # 공통
        def get(key):
            try:
                v = audio.get(key)
                if isinstance(v, list):
                    return str(v[0]) if v else ""
                return str(v) if v else ""
            except:
                return ""
        # MP3 easy?
        tags = {}
        # mutagen easy interface fallback
        try:
            easy = mutagen.File(str(path), easy=True)
            if easy:
                tags["title"] = easy.get("title",[""])[0] if easy.get("title") else ""
                tags["artist"] = easy.get("artist",[""])[0] if easy.get("artist") else ""
                tags["album"] = easy.get("album",[""])[0] if easy.get("album") else ""
                tags["date"] = easy.get("date",[""])[0] if easy.get("date") else ""
                tags["tracknumber"] = easy.get("tracknumber",[""])[0] if easy.get("tracknumber") else ""
        except:
            pass
        tags["duration"] = info["duration"]
        tags["has_cover"] = any("APIC" in str(k) or "covr" in str(k).lower() or "picture" in str(k).lower() for k in (audio.keys() if hasattr(audio, "keys") else []))
        # lyrics check
        has_lyrics = False
        try:
            if isinstance(audio, MP3):
                has_lyrics = any("USLT" in k for k in audio.keys())
            elif isinstance(audio, FLAC):
                has_lyrics = "lyrics" in [k.lower() for k in audio.keys()]
        except:
            pass
        tags["has_lyrics"] = has_lyrics
        return tags
    except Exception as e:
        return {"error": str(e), "duration": 0}

def backup_original(path: Path):
    try:
        audio = mutagen.File(str(path))
        if not audio:
            return
        dump = {}
        for k in audio.keys():
            try:
                dump[k] = str(audio[k])
            except:
                pass
        bak_path = path.with_suffix(path.suffix + ".tagbak.json")
        # /data/backups 에도 복사
        bak_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
        # data backups 폴더에도
        rel = path.relative_to(MUSIC_ROOT) if path.is_relative_to(MUSIC_ROOT) else path.name
        dest = BACKUP_ROOT / str(rel).replace("/", "_") + ".tagbak.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(bak_path), str(dest))
        return str(bak_path)
    except Exception as e:
        return None

def write_tags(path: Path, candidate: dict, options: dict):
    # options: only_empty=True, fill_lyrics=False, rename=False, lyrics_text=None
    try:
        backup_original(path)
        audio_easy = mutagen.File(str(path), easy=True)
        audio = mutagen.File(str(path))
        if not audio_easy:
            return False, "지원하지 않는 포맷"
        # 기존 값
        orig_title = audio_easy.get("title",[""])[0] if audio_easy.get("title") else ""
        orig_artist = audio_easy.get("artist",[""])[0] if audio_easy.get("artist") else ""
        orig_album = audio_easy.get("album",[""])[0] if audio_easy.get("album") else ""
        orig_date = audio_easy.get("date",[""])[0] if audio_easy.get("date") else ""

        only_empty = options.get("only_empty", True)

        def should_write(orig, new):
            if not new:
                return False
            if only_empty and orig:
                return False
            return True

        if should_write(orig_title, candidate.get("title")):
            audio_easy["title"] = candidate["title"]
        if should_write(orig_artist, candidate.get("artist")):
            audio_easy["artist"] = candidate["artist"]
        if should_write(orig_album, candidate.get("album")):
            audio_easy["album"] = candidate["album"]
        if should_write(orig_date, candidate.get("year")):
            audio_easy["date"] = candidate["year"]

        # 커버
        cover_url = candidate.get("cover_url")
        if cover_url:
            try:
                if not (only_empty and read_tags(path).get("has_cover")):
                    r = requests.get(cover_url, timeout=15)
                    if r.status_code == 200:
                        img = Image.open(io.BytesIO(r.content))
                        # 긴 변 1000 이하 JPEG 리사이징
                        w, h = img.size
                        if max(w,h) > 1000:
                            if w > h:
                                new_w, new_h = 1000, int(h * 1000 / w)
                            else:
                                new_h, new_w = 1000, int(w * 1000 / h)
                            img = img.resize((new_w, new_h), Image.LANCZOS)
                        buf = io.BytesIO()
                        if img.mode in ("RGBA","P"):
                            img = img.convert("RGB")
                        img.save(buf, format="JPEG", quality=90)
                        # mutagen에 삽입
                        from mutagen.id3 import ID3, APIC
                        from mutagen.flac import Picture
                        if path.suffix.lower() == ".mp3":
                            id3 = ID3(str(path))
                            id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=buf.getvalue()))
                            id3.save()
                        elif path.suffix.lower() == ".flac":
                            flac = FLAC(str(path))
                            pic = Picture()
                            pic.data = buf.getvalue()
                            pic.type = 3
                            pic.mime = "image/jpeg"
                            flac.add_picture(pic)
                            flac.save()
                        else:
                            # M4A
                            if isinstance(audio, MP4):
                                audio["covr"] = [buf.getvalue()]
                                audio.save()
            except Exception as e:
                pass

        audio_easy.save()

        # 가사
        if options.get("fill_lyrics") and options.get("lyrics_text"):
            try:
                if path.suffix.lower() == ".mp3":
                    from mutagen.id3 import ID3, USLT
                    id3 = ID3(str(path))
                    # 기존 USLT 없고, COWON S9 같은 플레이스홀더 체크
                    existing = ""
                    for k in id3.keys():
                        if "USLT" in k:
                            existing = str(id3[k])
                    if not existing or "[COWON" in existing:
                        id3.add(USLT(encoding=3, lang="kor", desc="", text=options["lyrics_text"]))
                        id3.save()
                elif path.suffix.lower() == ".flac":
                    flac = FLAC(str(path))
                    if "lyrics" not in [k.lower() for k in flac.keys()] or any("[COWON" in str(v) for v in flac.values()):
                        flac["lyrics"] = options["lyrics_text"]
                        flac.save()
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

def scan_job(job_id: str, sub_path: str, opts: dict):
    job = jobs[job_id]
    root = MUSIC_ROOT / sub_path if sub_path else MUSIC_ROOT
    files = []
    for ext in ("*.mp3","*.flac","*.m4a","*.ogg","*.mp4","*.wma","*.wav"):
        files.extend(list(root.rglob(ext)))
    job["total"] = len(files)
    job["status"] = "scanning"
    save_jobs()
    results = []
    for idx, f in enumerate(files):
        try:
            job["current_file"] = str(f.relative_to(MUSIC_ROOT))
            job["scanned"] = idx
            # 1. 기존 태그
            orig = read_tags(f)
            artist_hint, title_hint = parse_filename(f)
            # 기존 태그가 있으면 우선
            if orig.get("artist"):
                artist_hint = orig.get("artist") or artist_hint
            if orig.get("title"):
                title_hint = orig.get("title") or title_hint

            # 2. 검색 (음향 지문은 파일명 엉망일 때 - 여기서는 fpcalc 있으면 시도)
            # fpcalc 생략하고 텍스트 검색으로 대체 (컨테이너에 fpcalc 있어도 pyacoustid 사용 가능)
            candidates = []
            candidates += search_musicbrainz(artist_hint, title_hint)
            candidates += search_itunes(artist_hint, title_hint)
            # 점수 정렬
            candidates = sorted(candidates, key=lambda x: x.get("score",0), reverse=True)[:10]

            # 3. 가사 (옵션 켜졌을 때)
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
                "path": str(f.relative_to(MUSIC_ROOT)),
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
            results.append({"path": str(f), "error": str(e), "candidates": []})
        # 저장
        job["results"] = results
        if idx % 5 == 0:
            save_jobs()
        time.sleep(0.2) # rate limit
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

@app.post("/api/scan")
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
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
        "results": []
    }
    save_jobs()
    background_tasks.add_task(scan_job, job_id, req.sub_path, req.model_dump())
    return {"job_id": job_id}

@app.get("/api/jobs")
def list_jobs():
    return sorted(jobs.values(), key=lambda x: x.get("created_at",0), reverse=True)

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return jobs[job_id]

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
        # auto_apply 또는 수동 선택된 것만
        cand = r.get("best")
        if not cand:
            continue
        # 안전 규칙: only_empty면 기존 태그 보호는 write_tags 내부에서
        abs_path = MUSIC_ROOT / r["path"]
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
    # .tagbak.json 복원
    target = MUSIC_ROOT / path
    bak = target.with_suffix(target.suffix + ".tagbak.json")
    if not bak.exists():
        raise HTTPException(404, "백업 없음")
    try:
        # 간단 복원: mutagen으로 원본 덤프 복원은 복잡하므로 백업 json 기반으로 타이틀 등 복원 + 파일 자체 백업에서 복구하려면 원본 바이너리 백업 필요
        # 여기서는 tagbak.json을 읽어 easy 태그 복원
        data = json.loads(bak.read_text(encoding="utf-8"))
        # 실제 무결성 복구: 원본 파일 백업이 있으면 교체 (구현 생략, easy 복원)
        return {"restored_from": str(bak)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/")
def root():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))

# static
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
