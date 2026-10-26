"""Recoverable, create-only LRC publication after a verified music transaction."""
import json
from pathlib import Path
import uuid
from . import storage, rename_service


def payload(text):
    return (text.strip() + "\n").encode("utf-8")


def needed(path, text):
    if not text:
        return False
    target = Path(path).with_suffix(".lrc")
    for entry in target.parent.iterdir():
        if rename_service.folded(entry.name) == rename_service.folded(target.name):
            if entry.name != target.name or entry.is_symlink() or not entry.is_file() or entry.read_bytes() != payload(text):
                raise storage.StorageError("기존 LRC 파일은 덮어쓰지 않습니다: " + str(entry))
            return False
    return True


def begin(path, text, root, data, before, after):
    target = Path(path).with_suffix(".lrc")
    folder = Path(data) / "lyric-assets"
    folder.mkdir(parents=True, exist_ok=True)
    rename_service.sync_dir(folder.parent)
    record = {"music": str(Path(path).relative_to(root)), "root": str(Path(root).resolve()),
              "lrc": str(target.relative_to(root)), "before": before, "after": after,
              "text": text, "status": "pending"}
    journal = folder / (uuid.uuid4().hex + ".json")
    storage._new_file(journal, storage._json_bytes(record))
    rename_service.sync_dir(folder)
    return journal, record


def finish(asset, root):
    journal, record = asset
    music = storage.resolve_music(root, record["music"])
    if storage.revision(music) != record["after"]:
        raise storage.StorageError("LRC 복구 대상 음악의 내용이 일치하지 않습니다")
    target = Path(root) / record["lrc"]
    if target != music.with_suffix(".lrc"):
        raise storage.StorageError("LRC 경로 검증 실패")
    if needed(music, record["text"]):
        storage._new_file(target, payload(record["text"]))
    # A previous publication may have succeeded before directory sync failed.
    rename_service.sync_dir(target.parent)
    record["status"] = "complete"
    record.pop("error", None)
    storage._replace_file(journal, storage._json_bytes(record))
    rename_service.sync_dir(journal.parent)


def recover(root, data):
    renames, records = rename_service.recovery_records(data, root)
    for journal, record in records:
        if record["status"] != "pending":
            continue
        try:
            relocated = rename_service.relocated_path(root, record["music"], renames)
            if relocated is not None:
                target = storage.resolve_music(root, relocated)
                if storage.revision(target) not in (record["before"], record["after"]):
                    raise storage.StorageError("이름 변경 기록과 LRC 대상 리비전이 다릅니다")
                # Persist the verified new association before publishing any LRC.
                record.update(music=relocated, lrc=str(Path(relocated).with_suffix(".lrc")))
                storage._replace_file(journal, storage._json_bytes(record))
                rename_service.sync_dir(journal.parent)
            music = storage.resolve_music(root, record["music"])
            prior = [r for _, r in renames if r["status"] == "complete"
                     and Path(r["old_path"]) == Path(record["music"])]
            if prior and all(rename_service.identity(music) != r["identity"] for r in prior):
                raise storage.StorageError("LRC 이전 경로가 다른 파일에 재사용되어 복구를 확정할 수 없습니다")
            current = storage.revision(music)
            if current == record["after"]:
                finish((journal, record), root)
            elif current == record["before"]:
                record["status"] = "aborted"
                record.pop("error", None)
                storage._replace_file(journal, storage._json_bytes(record))
                rename_service.sync_dir(journal.parent)
            else:
                raise storage.StorageError("음악과 LRC 기록의 상태가 모호합니다: " + str(music))
        except Exception as exc:
            record.update(status="pending", error=str(exc))
            try:
                storage._replace_file(journal, storage._json_bytes(record))
                rename_service.sync_dir(journal.parent)
            except OSError:
                pass  # Keep the last durable pending record if error reporting also fails.
            raise storage.StorageError("LRC 복구 확인 필요: " + str(exc)) from exc
