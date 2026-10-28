"""Local browser fixture: actual page + lyrics service; generated temporary audio only."""
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from app import storage
from app.lyrics_service import LyricsService, lyric_response
from app.upstream import search_lyrics as lyrics, tags, net

scratch = tempfile.TemporaryDirectory(prefix="music-tag-022-ui-")
root = Path(scratch.name)
service = LyricsService(lambda: root, lambda c: c["id"])
queries, requests, originals, rows = [], [], {}, []
for name, title, artist in [("fixture.mp3", "Stored title", "Stored artist"), ("blank.mp3", "", "")]:
    path = root / name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)], check=True)
    tags.write_file(str(path), tags.Tags(title=title, artist=artist))
    originals[name] = (storage.revision(path), path.stat().st_mtime_ns)
    rows.append({"path": name, "original": storage.describe(path), "parsed": {"title": title, "artist": artist}, "candidates": [], "auto_apply": False, "file_state": "review"})
job = {"id": "fixture-022", "status": "done", "created_at": time.time(), "options": {}, "results": rows, "scanned": 2, "total": 2}


def fixture_search(params, cancel):
    queries.append(params)
    if "API error" in str(params):
        raise net.NetworkError("HTTP 502")
    if "No results" in str(params):
        return []
    base = {"trackName": "너 때문에", "artistName": "After School"}
    return [{**base, "id": 101, "albumName": "Fixture A", "duration": 241, "plainLyrics": "Fixture candidate ONE lyric text for browser validation only", "syncedLyrics": "[04:00.00]Fixture candidate ONE"},
            {**base, "id": 102, "albumName": "Fixture B", "duration": 300, "plainLyrics": "Fixture candidate TWO different lyric text for browser validation only"}]


lyrics._search = fixture_search
static = Path(__file__).resolve().parents[1] / "app" / "static"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(static), **kwargs)

    def log_message(self, *args):
        pass

    def send_json(self, value, status=200):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/fixture-report":
            return self.send_json({"queries": queries, "requests": requests, "music_unchanged": all((storage.revision(root / name), (root / name).stat().st_mtime_ns) == value for name, value in originals.items())})
        if path == "/api/preferences":
            return self.send_json({"country": "KR", "only_empty": False, "recurse": False, "rename": False, "fill_lyrics": False, "save_synced": False, "create_lrc": False, "include_ids": False, "artist_name_preference": "original", "cover_max_px": 1000, "use_fingerprint": False})
        if path == "/api/jobs":
            return self.send_json([job])
        if path == "/api/jobs/fixture-022":
            return self.send_json(job)
        if path.startswith("/api/lyrics/"):
            return self.send_json({"lyrics": ""})
        if path == "/api/background-operations":
            return self.send_json({"operations": []})
        if path == "/api/path-changes":
            return self.send_json({"changes": []})
        if path == "/api/folders":
            return self.send_json({"path": "", "folders": [], "files": 2})
        if path.startswith("/api/"):
            return self.send_json([])
        if path.startswith("/static/"):
            self.path = path[len("/static"):]
        super().do_GET()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append({"path": self.path, "body": body})
        if not self.path.endswith("/lyrics-search"):
            return self.send_json({"detail": "Fixture permits lyrics search only"}, 405)
        path = storage.resolve_music(root, body["path"])
        if storage.revision(path) != body["expected_revision"]:
            return self.send_json({"detail": "revision mismatch"}, 409)
        result = service.lookup_lyrics("fixture-022", body["path"], body["expected_revision"], body["title"], body["artist"], 0, force=True, manual=True)
        self.send_json(lyric_response(result))


if __name__ == "__main__":
    print("Temporary browser fixture: http://127.0.0.1:18022", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 18022), Handler).serve_forever()
