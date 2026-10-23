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
        rename_service.sync_dir(target.parent)
    record["status"] = "complete"
    storage._replace_file(journal, storage._json_bytes(record))
    rename_service.sync_dir(journal.parent)


def recover(root, data):
    for journal in sorted((Path(data) / "lyric-assets").glob("*.json")):
        record = json.loads(journal.read_text())
        if record["status"] != "pending":
            continue
        if record["root"] != str(Path(root).resolve()):
            raise storage.StorageError("LRC 복구 기록의 음악 루트가 다릅니다")
        music = storage.resolve_music(root, record["music"])
        current = storage.revision(music)
        if current == record["after"]:
            finish((journal, record), root)
        elif current == record["before"]:
            record["status"] = "aborted"
            storage._replace_file(journal, storage._json_bytes(record))
        else:
            raise storage.StorageError("음악과 LRC 기록의 상태가 모호합니다: " + str(music))
