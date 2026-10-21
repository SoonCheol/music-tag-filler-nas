"""Read-only scan input collection and restart/resume rules."""
import os
from pathlib import Path
from . import storage
from .upstream import tags

ACTIVE = {"queued", "scanning", "cancelling"}


def normalize_jobs(raw):
    if not isinstance(raw, dict) or any(not isinstance(j, dict) for j in raw.values()):
        raise ValueError("invalid job store")
    for job in raw.values():
        if not isinstance(job.get("results", []), list):
            raise ValueError("invalid job results")
        if job.get("status") in ACTIVE:
            job.update(status="interrupted", cancel_requested=False,
                       diagnostic="서버 재시작으로 중단됨. 이어하기 시 경로와 SHA256을 다시 확인합니다")
    return raw


class ScanCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ScanCancelled()


def collect(root, paths, recurse=True, cancel=None):
    root = Path(root).resolve()
    found = set()
    for value in paths:
        check_cancel(cancel)
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise storage.StorageError("음악 폴더 밖의 경로는 사용할 수 없습니다")
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.exists():
            raise storage.StorageError("존재하는 음악 파일/폴더를 지정하세요: " + value)
        if target.is_file():
            storage.resolve_music(root, value)
            found.add(target.resolve())
            continue
        for parent, directories, files in os.walk(target, followlinks=False):
            check_cancel(cancel)
            directories[:] = [d for d in directories if not (Path(parent) / d).is_symlink()] if recurse else []
            for name in files:
                check_cancel(cancel)
                path = Path(parent) / name
                if not path.is_symlink() and tags.format_of(str(path)) is not None:
                    found.add(path.resolve())
    return sorted(found, key=lambda p: p.as_posix().casefold())


def retained_results(root, files, previous, cancel=None):
    """Keep only unchanged, successfully read paths; never resume by row count."""
    previous = {r.get("path"): r for r in previous}
    retained, pending = [], []
    for path in files:
        check_cancel(cancel)
        relative = path.relative_to(Path(root).resolve()).as_posix()
        old = previous.get(relative)
        if (old and not old.get("error") and old.get("original", {}).get("revision")
                == storage.revision(path)):
            retained.append(old)
        else:
            pending.append(path)
    current = {p.relative_to(Path(root).resolve()).as_posix() for p in files}
    return retained, pending, sorted(set(previous) - current)
