"""NAS transactions around the pinned upstream format-specific tag implementation.

The first original is immutable. Full original bytes supplement upstream's tag
layout backup so exact undo is available even when a format needs its fallback.
All callers must hold OPERATION_LOCK across revision checks and mutations.
"""
import functools
import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path

from .upstream import tags, search_lyrics

OPERATION_LOCK = threading.RLock()
FIELDS = {"title": "title", "artist": "artist", "album": "album",
          "albumartist": "album_artist", "year": "year", "track": "track", "genre": "genre"}


class StorageError(Exception):
    pass


def postprocess_error(outcome, stage, exc):
    """Keep a confirmed file result when reporting an ancillary failure."""
    message = ("음악 저장 완료; " if outcome.get("music_saved") else "") + stage + ": " + str(exc)
    outcome.setdefault("postprocess_errors", []).append({"stage": stage, "message": str(exc)})
    outcome["status"] = "partial"
    outcome["warning"] = "; ".join(filter(None, (outcome.get("warning"), message)))
    return outcome


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _trace_slow_storage(fn):
    @functools.wraps(fn)
    def measured(*args, **kwargs):
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            if elapsed >= 0.25:
                target = str(args[0]) if args else ""
                if fn.__name__ == "_fsync":
                    try:
                        target = os.readlink("/proc/self/fd/" + target)
                    except OSError:
                        target = "file descriptor " + target
                logging.getLogger("uvicorn.error").info("save_storage_timing %s", json.dumps({
                    "phase": fn.__name__, "seconds": round(elapsed, 6),
                    "thread": threading.get_ident(), "target": target}))
    return measured


@_trace_slow_storage
def _fsync(fd):
    os.fsync(fd)


@_trace_slow_storage
def revision(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolve_music(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageError("음악 폴더 밖의 경로는 처리할 수 없습니다")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise StorageError("유효한 음악 파일이 아닙니다")
    if tags.format_of(str(path)) is None:
        raise StorageError("안전한 저장/복원을 지원하지 않는 형식입니다 (MP3/FLAC/M4A/OGG만 지원)")
    return path


def describe(path):
    before = revision(path)
    info = tags.read_file(str(path))
    after = revision(path)
    if before != after:
        raise StorageError("정보를 읽는 도중 파일이 변경되었습니다. 다시 스캔하세요")
    return {"title": info.tags.title, "artist": info.tags.artist, "album": info.tags.album,
            "albumartist": info.tags.album_artist, "date": info.tags.year,
            "tracknumber": info.tags.track, "genre": info.tags.genre,
            "duration": info.length, "format": info.fmt, "bitrate": info.bitrate,
            "sample_rate": info.sample_rate, "ids": info.ids.as_dict(), "has_cover": bool(info.cover),
            "has_synced": bool(info.synced), "has_lyrics": bool(info.lyrics.strip() or info.synced), "lyrics_lines": len(info.lyrics.splitlines()) if info.lyrics.strip() else 0,
            "lyrics_marker": search_lyrics.marker_only(info.lyrics),
            "revision": after}


def writable(path):
    if not os.access(path, os.W_OK) or not os.access(path.parent, os.W_OK):
        raise StorageError("파일 또는 폴더에 쓰기 권한이 없습니다")
    if hasattr(os, "statvfs") and os.statvfs(path.parent).f_flag & getattr(os, "ST_RDONLY", 1):
        raise StorageError("음악 폴더가 읽기 전용입니다. 저장/복원하지 않았습니다")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@_trace_slow_storage
def _sync_dir(path):
    from . import rename_service
    rename_service.sync_dir(path)


@_trace_slow_storage
def _new_file(path, data):
    """Publish a fully written file without replacing an existing first backup."""
    fd, name = tempfile.mkstemp(prefix=".tagbak-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            _fsync(output.fileno())
        os.link(name, path)  # fails closed if the destination already exists
        _sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


@_trace_slow_storage
def _replace_file(path, data):
    fd, name = tempfile.mkstemp(prefix=".tagtxn-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            _fsync(output.fileno())
        if path.exists():
            os.chmod(name, stat.S_IMODE(path.stat().st_mode))
        os.replace(name, path)
        _sync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _verify_backup(path, root, backup_root, allow_missing=False):
    sidecar = Path(tags.backup_path(str(path)))
    try:
        if allow_missing and not sidecar.exists():
            key = digest(str(path.relative_to(Path(root).resolve())).encode("utf-8"))
            sidecar_bytes = (Path(backup_root) / key / "tags.json").read_bytes()
        else:
            sidecar_bytes = sidecar.read_bytes()
        record = json.loads(sidecar_bytes)
        key = record["nas_backup_id"]
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("invalid backup id")
        folder = Path(backup_root) / key
        manifest_bytes = (folder / "manifest.json").read_bytes()
        if digest(manifest_bytes) != (folder / "manifest.sha256").read_text().strip():
            raise ValueError("manifest checksum")
        manifest = json.loads(manifest_bytes)
        relative = str(path.relative_to(Path(root).resolve()))
        if manifest.get("version") != 2:
            raise ValueError("backup version")
        if relative not in manifest["paths"]:
            alias = json.loads((folder / ("alias-" + digest(relative.encode("utf-8")) + ".json")).read_bytes())
            checksum = digest((relative + key + manifest["tags_sha256"]).encode("utf-8"))
            if alias != {"path": relative, "checksum": checksum}:
                raise ValueError("backup path mismatch")
        original = folder / "original.bin"
        if original.stat().st_size != manifest["size"] or revision(original) != manifest["sha256"]:
            raise ValueError("original checksum")
        central_tags = (folder / "tags.json").read_bytes()
        if digest(central_tags) != manifest["tags_sha256"] or sidecar_bytes != central_tags:
            raise ValueError("tag backup checksum")
        if record["sha256"] != manifest["sha256"] or not isinstance(record["tags"], dict):
            raise ValueError("upstream backup metadata")
        return folder, manifest
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StorageError("백업 무결성 검사 실패 또는 기존 백업 형식 불일치: 원본을 변경하지 않았습니다") from exc


def _sync_backup(folder, music):
    _sync_dir(folder)
    _sync_dir(folder.parent)
    _sync_dir(folder.parent.parent)
    _sync_dir(music.parent)


@_trace_slow_storage
def ensure_backup(path, root, backup_root, expected):
    sidecar = Path(tags.backup_path(str(path)))
    if sidecar.exists():
        folder, manifest = _verify_backup(path, root, backup_root)
        _sync_backup(folder, path)
        return folder, manifest
    if (Path(backup_root) / (path.name + ".tagbak.json")).exists():
        raise StorageError("이전 형식의 중앙 백업이 있습니다. 최초 원본을 확인할 수 없어 새 백업/저장을 차단했습니다")
    relative = str(path.relative_to(Path(root).resolve()))
    key = digest(relative.encode("utf-8"))
    destination = Path(backup_root) / key
    if destination.exists():
        folder, manifest = _verify_backup(path, root, backup_root, allow_missing=True)
        if manifest["sha256"] != expected:
            raise StorageError("원본 백업은 있으나 sidecar가 없고 파일이 변경되어 안전하게 재개할 수 없습니다")
        _sync_backup(folder, path)
        _new_file(sidecar, (folder / "tags.json").read_bytes())
        return _verify_backup(path, root, backup_root)
    Path(backup_root).mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".backup-", dir=backup_root))
    try:
        original = temporary / ("source" + path.suffix)
        shutil.copyfile(path, original)
        if revision(original) != expected or revision(path) != expected:
            raise StorageError("백업 도중 파일이 변경되었습니다")
        upstream_backup = Path(tags.make_backup(str(original)))
        record = json.loads(upstream_backup.read_text(encoding="utf-8"))
        record["file"] = path.name
        record["nas_backup_id"] = key
        tag_bytes = _json_bytes(record)
        manifest = {"version": 2, "paths": [relative], "sha256": expected,
                    "size": original.stat().st_size, "tags_sha256": digest(tag_bytes)}
        original.rename(temporary / "original.bin")
        upstream_backup.unlink()
        (temporary / "tags.json").write_bytes(tag_bytes)
        manifest_bytes = _json_bytes(manifest)
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        (temporary / "manifest.sha256").write_text(digest(manifest_bytes), encoding="ascii")
        for child in temporary.iterdir():
            with child.open("rb") as stream:
                _fsync(stream.fileno())
        _sync_dir(temporary)
        temporary.rename(destination)
        _sync_dir(backup_root)
        _sync_dir(backup_root.parent)
        _new_file(sidecar, tag_bytes)
        return _verify_backup(path, root, backup_root)
    except Exception as exc:
        if isinstance(exc, StorageError):
            raise
        raise StorageError("원본 백업 실패: 음악 파일을 저장하지 않았습니다") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def prepare_cover_change(data, current, max_px=1000):
    """Empty means keep; only a validated new image can replace embedded bytes."""
    if data is None or data == b"" or data == "":
        return None
    if data == current:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) <= max_px:
                return None
    prepared, _ = tags.prepare_cover(data, max_px)
    return None if prepared == current else prepared


@_trace_slow_storage
def save(path, root, backup_root, values, fields, only_empty, expected,
         cover=None, lyrics=None, rename=False, ids=None, replace_lyrics=False, synced=None, lrc=None, asset_root=None, rename_context=None):
    # Direct callers use the same lock and recovery gate as the HTTP save path.
    from . import rename_service
    with OPERATION_LOCK:
        rename_service.check_ready(asset_root or Path(backup_root).parent, root)
        return _save_locked(path, root, backup_root, values, fields, only_empty, expected,
                            cover, lyrics, rename, ids, replace_lyrics, synced, lrc, asset_root, rename_context)


def _save_locked(path, root, backup_root, values, fields, only_empty, expected,
                 cover, lyrics, rename, ids, replace_lyrics, synced, lrc, asset_root, rename_context):
    if revision(path) != expected:
        raise StorageError("스캔/확인 이후 파일이 변경되었습니다. 다시 스캔하세요")
    info = tags.read_file(str(path))
    final = info.tags.as_dict()
    for field in fields:
        key = FIELDS[field]
        if not only_empty or not final[key]:
            final[key] = values.get(field, "")
    new_tags = tags.Tags.from_dict(final)
    final_ids = info.ids
    if ids is not None:
        # Nonempty IDs survive empty-only saves, including multi-artist lists.
        final_ids = info.ids.merged_over(ids) if only_empty else ids.merged_over(info.ids)
    prepared = None
    if cover is not None and not (only_empty and info.cover is not None):
        prepared = prepare_cover_change(cover, info.cover)
    # Empty input never deletes lyrics. Replacement requires explicit verified consent.
    existing_lyrics = bool(info.synced or (info.lyrics.strip() and (only_empty or not search_lyrics.marker_only(info.lyrics))))
    if (existing_lyrics and (only_empty or not replace_lyrics)) or not lyrics or not lyrics.strip() or lyrics.strip() == info.lyrics.strip():
        lyrics = None
    from . import lyric_assets
    if synced and (info.fmt != "MP3" or (only_empty and (info.synced or info.lyrics.strip())) or search_lyrics.synced_lines(synced) == info.synced):
        synced = None
    if only_empty and (info.synced or info.lyrics.strip()):
        lrc = None
    lrc_needed = lyric_assets.needed(path, lrc)
    asset = None
    publication_error = None
    rename_needed = bool(rename and tags.rename_target(str(path), new_tags))
    if new_tags == info.tags and final_ids == info.ids and prepared is None and lyrics is None and synced is None and not lrc_needed and not rename_needed:
        return {"status": "skipped", "reason": "unchanged", "original": describe(path), "path": str(path.relative_to(root))}
    writable(path)
    folder, manifest = ensure_backup(path, root, backup_root, expected)
    changed_fields = {field for field in final if final[field] != info.tags.as_dict()[field]}
    content_changed = bool(changed_fields or final_ids != info.ids or prepared is not None or lyrics is not None or synced is not None)
    committed_revision = expected
    if content_changed:
        fd, name = tempfile.mkstemp(prefix=".tagtxn-", suffix=path.suffix, dir=path.parent)
        os.close(fd)
        stage = Path(name)
        try:
            shutil.copyfile(path, stage)
            tags.write_file(str(stage), new_tags, prepared, "image/jpeg",
                            ids=final_ids if final_ids != info.ids else None, replace_ids=True,
                            lyrics=lyrics, fields=changed_fields, synced=synced)
            verified = tags.read_file(str(stage))
            if info.fmt == "MP3":
                preserve = dict(cover=prepared is not None, lyrics=lyrics is not None,
                                synced=synced is not None, ids=final_ids != info.ids)
                before_frames = tags.id3_preserved_frames(str(path), changed_fields, **preserve)
                after_frames = tags.id3_preserved_frames(str(stage), changed_fields, **preserve)
                if before_frames != after_frames:
                    raise StorageError("기존 ID3 프레임이 변경되어 저장을 차단했습니다")
                with path.open("rb") as stream:
                    header = stream.read(4)
                expected_version = 3 if header == b"ID3\x03" else 4
                with stage.open("rb") as stream:
                    if stream.read(4) != b"ID3" + bytes([expected_version]):
                        raise StorageError("ID3 버전 저장 검증 실패")
            if verified.tags != new_tags or (lyrics is not None and verified.lyrics != lyrics.strip()):
                raise StorageError("저장 검증 실패: 원본 파일을 변경하지 않았습니다")
            if (synced is not None and verified.synced != search_lyrics.synced_lines(synced)) or (synced is None and verified.synced != info.synced):
                raise StorageError("시간 동기화 가사 검증 실패")
            if verified.ids != final_ids:
                raise StorageError("식별자 저장 검증 실패: 원본 파일을 변경하지 않았습니다")
            if prepared is not None and verified.cover != prepared:
                raise StorageError("표지 저장 검증 실패")
            if prepared is None and verified.cover != info.cover:
                raise StorageError("기존 표지가 변경되어 저장을 차단했습니다")
            if lyrics is None and verified.lyrics != info.lyrics:
                raise StorageError("기존 가사가 변경되어 저장을 차단했습니다")
            raw = path.read_bytes()
            fmt = tags.format_of(str(path))
            _, _, layout = tags._layout(raw, fmt)
            if tags._audio_bytes(stage.read_bytes(), fmt, layout) != tags._audio_bytes(raw, fmt, layout):
                raise StorageError("오디오 무결성 검증 실패")
            if revision(path) != expected:
                raise StorageError("저장 도중 원본이 변경되었습니다")
            os.chmod(stage, stat.S_IMODE(path.stat().st_mode))
            with stage.open("rb") as stream:
                _fsync(stream.fileno())
            if lrc_needed:
                asset = lyric_assets.begin(path, lrc, root, asset_root or Path(backup_root).parent, expected, revision(stage))
            committed_revision = revision(stage)
            try:
                os.replace(stage, path)
                _sync_dir(path.parent)
            except Exception as exc:
                # Some filesystem wrappers can raise after publishing the staged file.
                if stage.exists() or path.is_symlink() or not path.is_file() or revision(path) != committed_revision:
                    raise
                publication_error = exc
        finally:
            stage.unlink(missing_ok=True)
    # From here on, a verified tag transaction has already been published.
    outcome = {"status": "saved", "changed": bool(content_changed or lrc_needed),
               "music_saved": bool(content_changed or not rename_needed), "path": str(path.relative_to(root)), "rename_error": None}
    if publication_error is not None:
        postprocess_error(outcome, "음악 게시 후 확인", publication_error)
    try:
        if lrc_needed:
            if asset is None:
                asset = lyric_assets.begin(path, lrc, root, asset_root or Path(backup_root).parent, expected, committed_revision)
            try:
                lyric_assets.finish(asset, root)
            except Exception:
                try:
                    lyric_assets.finish(asset, root)
                except Exception as exc:
                    lyric_assets.record_error(asset[0], exc)
                    from . import rename_service
                    rename_service.blocked[str(Path(asset_root or Path(backup_root).parent).resolve())] = str(exc)
                    outcome["recovery_pending"] = True
                    raise StorageError("음악/LRC 기록 복구가 필요합니다: " + str(path) + ": " + str(exc)) from exc
        if rename:
            from . import rename_service
            target = rename_service.automatic_target(path, new_tags)
            if target:
                try:
                    if rename_context is not None:
                        active_jobs, persist_jobs, active_id = rename_context
                        row = next(r for r in active_jobs[active_id]["results"] if r["path"] == str(path.relative_to(root)))
                        row["original"] = describe(path)
                    else:
                        active_jobs, persist_jobs, active_id = {}, lambda: None, None
                    event = rename_service.rename(root, asset_root or Path(backup_root).parent, backup_root,
                                                  active_jobs, persist_jobs, active_id,
                                                  str(path.relative_to(root)), target.stem, committed_revision)
                    path = root / event["new_path"]
                    outcome["changed"] = True
                    outcome["music_saved"] = True
                except Exception as exc:
                    outcome["rename_error"] = "태그 처리 후 이름 변경/후속 처리 오류: " + str(exc)
                    if isinstance(exc, rename_service.RenameIncomplete) and exc.current_path is not None:
                        previous = str(path.relative_to(root))
                        path = Path(exc.current_path)
                        moved = str(path.relative_to(root)) != previous
                        outcome["changed"] |= moved
                        outcome["music_saved"] |= moved
                        outcome["recovery_pending"] = True
                        if rename_context is not None:
                            rename_service.update_jobs(active_jobs, previous, str(path.relative_to(root)), root)
                    raise
    except Exception as exc:
        # Do not infer success from an exception alone: recheck the committed bytes.
        if path.is_symlink() or not path.is_file() or revision(path) != committed_revision:
            raise StorageError("저장된 음악 파일의 상태를 확인할 수 없습니다: " + str(path)) from exc
        postprocess_error(outcome, "LRC/이름 변경 후속 처리", exc)
    outcome["path"] = str(path.relative_to(root))
    try:
        outcome["original"] = describe(path)
    except Exception as exc:
        postprocess_error(outcome, "저장 결과 읽기", exc)
    if not outcome["music_saved"]:
        outcome["status"] = "failed"
        outcome["message"] = outcome.get("warning", "음악 이름 변경을 완료하지 못했습니다")
    return outcome


def restore(path, root, backup_root, expected):
    if revision(path) != expected:
        raise StorageError("확인 이후 파일이 변경되었습니다. 다시 스캔하세요")
    folder, manifest = _verify_backup(path, root, backup_root)
    if revision(path) == manifest["sha256"]:
        return {"status": "skipped", "reason": "unchanged", "exact": True, "original": describe(path)}
    writable(path)
    original = (folder / "original.bin").read_bytes()
    if digest(original) != manifest["sha256"]:
        raise StorageError("복원 직전 원본 백업 검증 실패")
    fmt = tags.format_of(str(path))
    _, _, layout = tags._layout(original, fmt)
    if tags._audio_bytes(path.read_bytes(), fmt, layout) != tags._audio_bytes(original, fmt, layout):
        raise StorageError("오디오 본문이 원본 백업과 다릅니다. 다른 음악 파일로 교체되었을 수 있어 복원을 차단했습니다")
    if revision(path) != expected:
        raise StorageError("복원 도중 파일이 변경되었습니다")
    _replace_file(path, original)
    if revision(path) != manifest["sha256"]:
        raise StorageError("복원 후 SHA256 검증 실패")
    return {"status": "restored", "exact": True, "original": describe(path)}
