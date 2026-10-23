"""Small NAS preferences and bounded, temporary pending cover store."""
from collections import OrderedDict
import json
from pathlib import Path
import threading
import time
import uuid
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from . import storage, search_service


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    country: Literal["KR", "US", "JP", "CN", "TW", "HK", "GB", "DE", "FR"] = "KR"
    recurse: bool = True
    only_empty: bool = True
    fill_lyrics: bool = False
    save_synced: bool = False
    create_lrc: bool = False
    rename: bool = False
    include_ids: bool = False
    artist_name_preference: Literal["original", "latin"] = "original"
    cover_max_px: int = Field(default=1000, ge=100, le=1000)


def read(root):
    path = Path(root) / "settings.json"
    if not path.exists():
        return Preferences()
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("settings.json must contain an object")
    return Preferences(**{k: v for k, v in value.items() if k in Preferences.model_fields})


def write(root, value):
    path = Path(root) / "settings.json"
    with storage.OPERATION_LOCK:
        old = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(old, dict):
            raise ValueError("settings.json must contain an object")
        # Keep keys/desktop settings; expose and edit only the nonsecret NAS schema.
        old.update(value.model_dump())
        storage._replace_file(path, json.dumps(old, ensure_ascii=False, indent=2).encode("utf-8"))


_covers = OrderedDict()
_lock = threading.Lock()


def put_cover(job_id, data):
    data = search_service.prepare_image(data)
    token = uuid.uuid4().hex
    with _lock:
        _covers[token] = (job_id, time.monotonic(), data)
        while len(_covers) > 32 or sum(len(v[2]) for v in _covers.values()) > 32 * 1024 * 1024:
            _covers.popitem(last=False)
    return token


def get_cover(job_id, token):
    with _lock:
        value = _covers.get(token)
        if not value or value[0] != job_id or time.monotonic() - value[1] > 3600:
            if value and time.monotonic() - value[1] > 3600:
                _covers.pop(token, None)
            raise storage.StorageError("임시 커버가 만료되었거나 다른 작업의 커버입니다. 다시 선택하세요")
        return value[2]
