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


class RenameIncomplete(storage.StorageError):
    """A failed transaction may already have moved the verified music file."""
    def __init__(self, message, current_path=None):
        super().__init__(message)
        self.current_path = current_path


def journal_records(data, kind):
    """Validate every record before recovery performs any filesystem mutation."""
    folder = Path(data) / kind
    try:
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("invalid journal directory")
        values = []
        for path in sorted(folder.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ValueError("invalid journal file")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("status") not in ("pending", "complete", "aborted"):
                raise ValueError("invalid journal status")
            root = Path(record["root"])
            if not root.is_absolute() or root != root.resolve():
                raise ValueError("invalid journal root")

            def relative(key):
                value = record[key]
                if not isinstance(value, str) or not value or "\x00" in value:
                    raise ValueError("invalid journal path")
                rel = Path(value)
                if rel.is_absolute() or rel.drive or ".." in rel.parts or not rel.name:
                    raise ValueError("invalid journal path")
                target = root / rel
                if not target.resolve().is_relative_to(root):
                    raise ValueError("journal path outside root")
                parent = root
                for part in rel.parts:
                    parent /= part
                    if parent.is_symlink():
                        raise ValueError("symlink in journal path")
                return target

            def sha(key):
                if not isinstance(record.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", record[key]):
                    raise ValueError("invalid journal checksum: " + key)

            if kind == "renames":
                old, new = relative("old_path"), relative("new_path")
                if old == new or old.parent != new.parent or old.suffix != new.suffix:
                    raise ValueError("invalid rename paths")
                sha("revision")
                if (type(record["seq"]) is not int or record["seq"] < 1
                        or not isinstance(record["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", record["id"])
                        or not isinstance(record["identity"], list) or len(record["identity"]) != 2
                        or any(type(n) is not int or n < 0 for n in record["identity"])):
                    raise ValueError("invalid rename identity")
                if record["backup_id"] is not None:
                    for key in ("backup_id", "side_sha", "tags_sha"):
                        sha(key)
                elif record["side_sha"] is not None or record["tags_sha"] is not None:
                    raise ValueError("invalid backup association")
                if record.get("lrc_sha") is not None:
                    sha("lrc_sha")
                for key, checksum in (("side_identity", "side_sha"), ("lrc_identity", "lrc_sha")):
                    if key in record and record[key] is not None:
                        value = record[key]
                        if (not record.get(checksum) or not isinstance(value, list) or len(value) != 2
                                or any(type(n) is not int or n < 0 for n in value)):
                            raise ValueError("invalid asset identity")
            else:
                if relative("lrc") != relative("music").with_suffix(".lrc"):
                    raise ValueError("invalid LRC association")
                sha("before")
                sha("after")
                if not isinstance(record["text"], str) or not record["text"].strip():
                    raise ValueError("invalid LRC payload")
            values.append((path, record))
        if kind == "renames" and (len({r["seq"] for _, r in values}) != len(values)
                                  or len({r["id"] for _, r in values}) != len(values)):
            raise ValueError("duplicate rename sequence or identity")
        return values
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise storage.StorageError("복구 저널을 안전하게 해석할 수 없습니다: " + str(folder) + ": " + str(exc)) from exc


def records(data):
    return journal_records(data, "renames")


def recovery_records(data, root=None):
    renames, lyrics = records(data), journal_records(data, "lyric-assets")
    if root is not None and any(r["root"] != str(Path(root).resolve()) for _, r in renames + lyrics):
        raise storage.StorageError("복구 기록의 음악 루트가 다릅니다")
    return renames, lyrics


def check_ready(data, root=None):
    key = str(Path(data).resolve())
    message = blocked.get(key)
    if message:
        raise storage.StorageError("이름 변경 복구 확인 필요: " + message)
    try:
        renames, lyrics = recovery_records(data, root)
        if any(r["status"] == "pending" for _, r in renames + lyrics):
            raise storage.StorageError("미완료 음악/이름 변경 저널의 복구가 필요합니다")
    except storage.StorageError as exc:
        blocked[key] = str(exc)
        raise


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


def automatic_target(source, new_tags):
    target = tags.rename_target(str(source), new_tags)
    if target is None:
        return None
    target = Path(target)
    stem = tags.safe_filename(f"{new_tags.artist} - {new_tags.title}" if new_tags.artist else new_tags.title)
    occupied = {folded(p.name) for p in source.parent.iterdir()}
    number = 2
    while any(folded(p.name) in occupied for p in
              (target, Path(tags.backup_path(str(target))), target.with_suffix(".lrc"))):
        target = source.with_name(f"{stem} ({number}){source.suffix}")
        number += 1
    return target


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
    wanted = {folded(target.name), folded(Path(tags.backup_path(str(target))).name), folded(target.with_suffix(".lrc").name)}
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


def ensure_alias(folder, relative, tags_sha):
    """Reuse only a verified alias; create-only publication also handles a race."""
    alias = {"path": relative, "checksum": storage.digest((relative + folder.name + tags_sha).encode())}
    path = folder / ("alias-" + storage.digest(relative.encode()) + ".json")
    created = False
    if not path.exists() and not path.is_symlink():
        try:
            storage._new_file(path, storage._json_bytes(alias))
            created = True
        except FileExistsError:
            pass  # Another publisher won; validate its data before reusing it.
    try:
        if path.is_symlink() or not path.is_file() or json.loads(path.read_bytes()) != alias:
            raise ValueError("alias mismatch")
    except (OSError, ValueError) as exc:
        raise storage.StorageError("기존 백업 별칭이 일치하지 않습니다") from exc
    # A prior attempt may have published the alias but failed this sync.
    sync_dir(folder)
    return created


def finish_asset(old, new, checksum, expected_identity=None):
    """Resume a journaled asset move without replacing or adopting another file."""
    if any(folded(p.name) == folded(new.name) and p.name != new.name for p in new.parent.iterdir()):
        raise storage.StorageError("동반 파일 이름 충돌")
    if old.exists() or old.is_symlink():
        if (old.is_symlink() or not old.is_file() or storage.revision(old) != checksum
                or (expected_identity is not None and identity(old) != expected_identity)):
            raise storage.StorageError("이전 동반 파일 정체 또는 내용 불일치")
        if new.exists() or new.is_symlink():
            raise storage.StorageError("동반 파일 충돌")
        no_replace(old, new)
    if (new.is_symlink() or not new.is_file() or storage.revision(new) != checksum
            or (expected_identity is not None and identity(new) != expected_identity)):
        raise storage.StorageError("새 동반 파일 정체 또는 내용 불일치")
    sync_dir(new.parent)


def finish(record, path, root, backups, jobs, save_jobs):
    old, new = Path(root) / record["old_path"], Path(root) / record["new_path"]
    if old.exists() or old.is_symlink() or new.is_symlink() or not new.is_file():
        raise storage.StorageError("이전/새 파일 상태가 모호합니다: " + str(old) + " / " + str(new))
    if identity(new) != record["identity"] or storage.revision(new) != record["revision"]:
        raise storage.StorageError("새 경로의 파일 정체 또는 내용이 일치하지 않습니다: " + str(new))
    old_side, new_side = Path(tags.backup_path(str(old))), Path(tags.backup_path(str(new)))
    if record["backup_id"]:
        finish_asset(old_side, new_side, record["side_sha"], record.get("side_identity"))
        folder = Path(backups) / record["backup_id"]
        ensure_alias(folder, record["new_path"], record["tags_sha"])
        storage._verify_backup(new, root, backups)
    elif any(p.exists() or p.is_symlink() for p in (old_side, new_side)):
        raise storage.StorageError("예상하지 못한 동반 백업이 있습니다")
    old_lrc, new_lrc = old.with_suffix(".lrc"), new.with_suffix(".lrc")
    if record.get("lrc_sha"):
        finish_asset(old_lrc, new_lrc, record["lrc_sha"], record.get("lrc_identity"))
    elif any(p.exists() or p.is_symlink() for p in (old_lrc, new_lrc)):
        raise storage.StorageError("예상하지 못한 LRC가 있습니다")
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
        renames, _ = recovery_records(data, root)
        for path, record in renames:
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
    check_ready(data, root)
    row = next((r for r in jobs.get(job_id, {}).get("results", []) if r.get("path") == relative), None)
    if row is None and job_id is not None:
        raise storage.StorageError("이 작업에 속한 파일이 아닙니다")
    source = storage.resolve_music(root, relative)
    # No symlinked parent directories, even if they lead back inside the root.
    parent = Path(root)
    for part in Path(relative).parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise storage.StorageError("심볼릭 링크 폴더에서는 이름을 변경할 수 없습니다")
    if storage.revision(source) != revision or (row is not None and row.get("original", {}).get("revision") != revision):
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
    lrc = source.with_suffix(".lrc")
    if lrc.is_symlink() or (lrc.exists() and not lrc.is_file()):
        raise storage.StorageError("연결된 LRC가 일반 파일이 아닙니다")
    lrc_sha = storage.revision(lrc) if lrc.exists() else None
    previous = records(data)
    record = {"seq": max((r["seq"] for _, r in previous), default=0) + 1, "id": uuid.uuid4().hex,
              "status": "pending", "root": str(Path(root).resolve()), "old_path": relative,
              "new_path": target.relative_to(root).as_posix(), "revision": revision,
              "identity": identity(source), "backup_id": backup_id, "side_sha": side_sha, "tags_sha": tags_sha,
              "created_at": time.time(), "lrc_sha": lrc_sha,
              "side_identity": identity(side) if backup_id else None,
              "lrc_identity": identity(lrc) if lrc_sha else None}
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
        current = None
        try:
            candidates = [p for p in (source, target) if p.is_file() and not p.is_symlink()
                          and identity(p) == record["identity"] and storage.revision(p) == record["revision"]]
            if len(candidates) == 1:
                current = candidates[0]
        except OSError:
            pass
        raise RenameIncomplete("이름 변경/기록 복구 오류: " + str(exc) + "; 현재 존재하는 경로: " + ", ".join(existing), current) from exc


def changes(data, after):
    check_ready(data)
    return [r for _, r in records(data) if r["status"] == "complete" and r["seq"] > after]
