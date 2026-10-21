"""Explicit NAS bind-mount smoke test. Generated audio only; never a library path.

Both writable roots must contain only the matching safety marker before import.
Use the currently deployed image and mount separate, newly created NAS folders.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

token = os.environ.get("MTF_RW_TEST_TOKEN", "")
music = Path(os.environ["MUSIC_ROOT"])
data = Path(os.environ["DATA_ROOT"])
marker = ".mtf-generated-test-root"
if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
    raise RuntimeError("Explicit generated-audio test token required")
if music.resolve() == data.resolve():
    raise RuntimeError("Music and state roots must be separate")
for root in (music, data):
    if not root.is_dir() or root.is_symlink() or set(p.name for p in root.iterdir()) != {marker}:
        raise RuntimeError("Refusing to run outside a newly marked, empty test directory")
    if (root / marker).read_text().strip() != token:
        raise RuntimeError("Safety marker mismatch")

sys.path.insert(0, "/app")
import uvicorn
from app import main, storage
from app.upstream import tags


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="error"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.03)
if not server.started:
    raise RuntimeError("Test HTTP server failed to start")


def http(route, value=None):
    request = urllib.request.Request("http://127.0.0.1:" + str(port) + route,
                                     data=json.dumps(value).encode() if value is not None else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("Unexpected HTTP status")
        return json.load(response)


report = {"scope": "generated NAS files only", "formats": []}
try:
    for extension, codec in (("mp3", "libmp3lame"), ("flac", "flac"), ("m4a", "aac"), ("ogg", "libvorbis")):
        relative = "MTF-generated-test." + extension
        path = music / relative
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1", "-c:a", codec, str(path)], check=True)
        tags.write_file(str(path), tags.Tags(title="Generated original", artist="Test artist", album="Test album"),
                        lyrics="Generated test lyrics that must remain unchanged.")
        original_sha = sha(path)
        result = {"path": relative, "original": storage.describe(path), "candidates": [], "parsed": {}}
        main.jobs["rw-smoke"] = {"id": "rw-smoke", "status": "done", "results": [result], "options": {}}
        payload = {"scope": "selected", "paths": [relative], "only_empty": False,
                   "fill_lyrics": False, "rename": False, "items": [{"path": relative,
                    "expected_revision": original_sha, "selection": "edit", "fields": ["title"],
                    "values": {"title": "NAS saved title", "artist": "UNCHECKED MUST NOT WRITE"},
                    "include_cover": False}]}
        saved = http("/api/jobs/rw-smoke/save", payload)
        if saved["saved"] != 1 or saved["failed"] or saved.get("state_error"):
            raise RuntimeError("NAS save failed: " + json.dumps(saved))
        readback = http("/api/files/" + relative)
        if readback["title"] != "NAS saved title" or readback["artist"] != "Test artist":
            raise RuntimeError("HTTP tag readback mismatch")
        if readback["lyrics"] != "Generated test lyrics that must remain unchanged.":
            raise RuntimeError("Existing test lyrics changed")
        backup, manifest = storage._verify_backup(path, music.resolve(), main.BACKUP_ROOT)
        if manifest["sha256"] != original_sha or sha(backup / "original.bin") != original_sha:
            raise RuntimeError("Original NAS backup mismatch")
        sidecar = Path(tags.backup_path(str(path)))
        sidecar_sha = sha(sidecar)
        payload["items"][0].update(expected_revision=readback["revision"], values={"title": "Second edit"})
        second = http("/api/jobs/rw-smoke/save", payload)
        if second["saved"] != 1 or sha(sidecar) != sidecar_sha:
            raise RuntimeError("First backup was not retained")
        current = http("/api/files/" + relative)
        reverted = http("/api/revert/" + relative, {"expected_revision": current["revision"]})
        after = http("/api/files/" + relative)
        if not reverted.get("exact") or sha(path) != original_sha or after["title"] != "Generated original":
            raise RuntimeError("Exact NAS restore failed")
        report["formats"].append({"format": extension, "saved": True, "http_readback": True,
                                  "original_backup_verified": True, "first_backup_retained": True,
                                  "exact_undo": True, "original_sha256": original_sha,
                                  "restored_sha256": sha(path)})
    report["passed"] = True
    (data / "validation-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
finally:
    server.should_exit = True
    thread.join(timeout=5)
