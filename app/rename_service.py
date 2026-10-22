"""No-replace filename transactions; callers hold storage.OPERATION_LOCK."""
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import uuid
from . import storage
from .upstream import tags

renaming = False
active = {}
blocked = {}


def records(data):
    folder = Path(data) / "renames"
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(folder.glob("*.json"))]


def check_ready(data):
    message = blocked.get(str(Path(data).resolve()))
    if message:
        raise storage.StorageError("이름 변경 복구 확인 필요: " + message)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def no_replace(source, target):
    source, target = Path(source), Path(target)
    if source.parent != target.parent:
        raise storage.StorageError("같은 폴더 안에서만 이름을 변경할 수 있습니다")
    fn = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if fn is None:
        raise storage.StorageError("덮어쓰기 없는 원자적 이름 변경을 지원하지 않습니다")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if fn(fd, os.fsencode(source.name), fd, os.fsencode(target.name), 1):
            code = ctypes.get_errno()
            if code in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
                raise storage.StorageError("NAS 파일시스템이 안전한 원자적 이름 변경을 지원하지 않습니다")
            raise OSError(code, os.strerror(code), str(target))
        os.fsync(fd)
    finally:
        os.close(fd)


def folded(name):
    return unicodedata.normalize("NFC", name).casefold()


def validate_name(source, stem):
    if (not stem or stem != stem.strip() or stem.endswith(".") or stem in (".", "..")
            or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', stem)
            or any(unicodedata.category(c).startswith("C") for c in stem)
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|CLOCK\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", stem)):
        raise storage.StorageError("빈 이름·금지 문자·예약 이름·끝 공백/마침표는 사용할 수 없습니다")
    target = source.with_name(stem + source.suffix)
    if len(os.fsencode(target.name + tags.BACKUP_SUFFIX)) > min(255, os.pathconf(source.parent, "PC_NAME_MAX")):
        raise storage.StorageError("파일명이 허용 길이를 초과합니다")
    if target.name == source.name:
        return target
    wanted = {folded(target.name), folded(Path(tags.backup_path(str(target))).name)}
    if any(folded(p.name) in wanted for p in source.parent.iterdir()):
        raise storage.StorageError("동일하거나 대소문자만 다른 파일명 또는 백업 이름이 존재합니다")
    return target


def write_record(path, record, first=False):
    if first:
        storage._new_file(path, storage._json_bytes(record))
    else:
        storage._replace_file(path, storage._json_bytes(record))
    sync_dir(path.parent)


def identity(path):
    st = path.stat(follow_symlinks=False)
    return [st.st_dev, st.st_ino]


def update_jobs(jobs, old, new, root):
    for job in jobs.values():
        for row in job.get("results", []):
            if row.get("path") == old:
                row["path"] = new
                if "abs_path" in row:
                    row["abs_path"] = str(Path(root) / new)
        opts = job.get("options", {})
        if isinstance(opts.get("paths"), list):
            opts["paths"] = [new if p == old else p for p in opts["paths"]]
        if opts.get("sub_path") == old:
            opts["sub_path"] = new
        if job.get("sub_path") == old:
            job["sub_path"] = new
        if isinstance(job.get("missing_paths"), list):
            job["missing_paths"] = [new if p == old else p for p in job["missing_paths"]]


def finish(record, path, root, backups, jobs, save_jobs):
    old, new = Path(root) / record["old_path"], Path(root) / record["new_path"]
    if old.exists() or old.is_symlink() or new.is_symlink() or not new.is_file():
        raise storage.StorageError("이전/새 파일 상태가 모호합니다: " + str(old) + " / " + str(new))
    if identity(new) != record["identity"] or storage.revision(new) != record["revision"]:
        raise storage.StorageError("새 경로의 파일 정체 또는 내용이 일치하지 않습니다: " + str(new))
    old_side, new_side = Path(tags.backup_path(str(old))), Path(tags.backup_path(str(new)))
    if record["backup_id"]:
        if old_side.exists():
            if new_side.exists() or new_side.is_symlink() or storage.revision(old_side) != record["side_sha"]:
                raise storage.StorageError("동반 백업 충돌 또는 내용 불일치")
            no_replace(old_side, new_side)
        if not new_side.is_file() or new_side.is_symlink() or storage.revision(new_side) != record["side_sha"]:
            raise storage.StorageError("새 이름의 동반 백업을 확인할 수 없습니다")
        folder = Path(backups) / record["backup_id"]
        relative = record["new_path"]
        alias = {"path": relative, "checksum": storage.digest((relative + folder.name + record["tags_sha"]).encode())}
        alias_path = folder / ("alias-" + storage.digest(relative.encode()) + ".json")
        if alias_path.exists():
            if alias_path.is_symlink() or alias_path.read_bytes() != storage._json_bytes(alias):
                raise storage.StorageError("기존 백업 별칭이 일치하지 않습니다")
        else:
            storage._new_file(alias_path, storage._json_bytes(alias))
            sync_dir(folder)
        storage._verify_backup(new, root, backups)
    elif old_side.exists() or new_side.exists() or new_side.is_symlink():
        raise storage.StorageError("예상하지 못한 동반 백업이 있습니다")
    update_jobs(jobs, record["old_path"], record["new_path"], root)
    save_jobs()
    record["status"] = "complete"
    record.pop("error", None)
    write_record(path, record)
    return record


def recover(root, data, backups, jobs, save_jobs):
    key = str(Path(data).resolve())
    blocked.pop(key, None)
    try:
        for path, record in records(data):
            if record["status"] in ("complete", "aborted"):
                continue
            if record["root"] != str(Path(root).resolve()):
                raise storage.StorageError("복구 기록의 음악 루트가 다릅니다")
            old, new = Path(root) / record["old_path"], Path(root) / record["new_path"]
            if old.is_file() and not new.exists() and not new.is_symlink() and identity(old) == record["identity"] and storage.revision(old) == record["revision"]:
                if record["backup_id"]:
                    storage._verify_backup(old, root, backups)
                record["status"] = "aborted"
                write_record(path, record)
            else:
                finish(record, path, root, backups, jobs, save_jobs)
    except Exception as exc:
        blocked[key] = str(exc)
        raise storage.StorageError(str(exc)) from exc


def rename(root, data, backups, jobs, save_jobs, job_id, relative, stem, revision):
    check_ready(data)
    row = next((r for r in jobs.get(job_id, {}).get("results", []) if r.get("path") == relative), None)
    if row is None:
        raise storage.StorageError("이 작업에 속한 파일이 아닙니다")
    source = storage.resolve_music(root, relative)
    # No symlinked parent directories, even if they lead back inside the root.
    parent = Path(root)
    for part in Path(relative).parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise storage.StorageError("심볼릭 링크 폴더에서는 이름을 변경할 수 없습니다")
    if storage.revision(source) != revision or row.get("original", {}).get("revision") != revision:
        raise storage.StorageError("파일이 변경되었습니다. 다시 확인하세요")
    target = validate_name(source, stem)
    if source == target:
        return {"status": "unchanged", "old_path": relative, "new_path": relative}
    storage.writable(source)
    backup_id = side_sha = tags_sha = None
    side = Path(tags.backup_path(str(source)))
    if side.exists() or side.is_symlink():
        if side.is_symlink():
            raise storage.StorageError("심볼릭 링크 백업은 처리할 수 없습니다")
        folder, manifest = storage._verify_backup(source, root, backups)
        backup_id, tags_sha, side_sha = folder.name, manifest["tags_sha256"], storage.revision(side)
    elif (Path(backups) / storage.digest(relative.encode())).exists():
        raise storage.StorageError("동반 백업이 누락되었습니다. 백업 연결을 확인하세요")
    previous = records(data)
    record = {"seq": max((r["seq"] for _, r in previous), default=0) + 1, "id": uuid.uuid4().hex,
              "status": "pending", "root": str(Path(root).resolve()), "old_path": relative,
              "new_path": target.relative_to(root).as_posix(), "revision": revision,
              "identity": identity(source), "backup_id": backup_id, "side_sha": side_sha, "tags_sha": tags_sha,
              "created_at": time.time()}
    folder = Path(data) / "renames"
    folder.mkdir(exist_ok=True)
    sync_dir(folder.parent)
    journal = folder / (str(record["seq"]).zfill(16) + "-" + record["id"] + ".json")
    write_record(journal, record, first=True)
    try:
        if storage.revision(source) != revision or identity(source) != record["identity"]:
            raise storage.StorageError("이름 변경 직전 파일이 변경되었습니다")
        no_replace(source, target)
        return finish(record, journal, root, backups, jobs, save_jobs)
    except Exception as exc:
        # Prefer completing a successful filesystem rename; never roll it back blindly.
        try:
            recover(root, data, backups, jobs, save_jobs)
            value = json.loads(journal.read_text())
            if value["status"] == "complete":
                return value
        except Exception:
            pass
        existing = [str(p) for p in (source, target) if p.exists() or p.is_symlink()]
        raise storage.StorageError("이름 변경/기록 복구 오류: " + str(exc) + "; 현재 존재하는 경로: " + ", ".join(existing)) from exc


def changes(data, after):
    check_ready(data)
    return [r for _, r in records(data) if r["status"] == "complete" and r["seq"] > after]
