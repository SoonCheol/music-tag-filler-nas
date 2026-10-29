"""Profile generated-audio saves on dedicated NAS benchmark mounts only.

Run in a disposable container with /bench-music and /bench-data pointing to
separate temporary directories on the production volumes. Never mount the
operating music library or application data. Results are JSON lines.
"""
import argparse
import collections
import functools
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--extra-jobs", type=int, default=0, choices=range(11))
    args = parser.parse_args()
    if not args.run.replace("-", "").isalnum():
        raise SystemExit("Invalid benchmark run name")
    music = Path("/bench-music") / args.run
    data = Path("/bench-data") / args.run
    if music.exists() or data.exists():
        raise SystemExit("Use a fresh run name; existing results are never overwritten")
    music.mkdir()
    os.environ["MUSIC_ROOT"] = str(music)
    os.environ["DATA_ROOT"] = str(data)
    from app import main as app, storage, rename_service
    from app.upstream import tags

    seed = Path("/bench-music/seed.mp3")
    if not seed.exists():
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=303.6", "-c:a", "libmp3lame",
                        "-b:a", "320k", str(seed)], check=True)
        tags.write_file(str(seed), tags.Tags(title="Generated fixture", artist="Diagnostic"),
                        lyrics="Original fixture lyric\n" * 40)
        with seed.open("rb") as stream:
            os.fsync(stream.fileno())
        rename_service.sync_dir(seed.parent)
    path = music / "generated.mp3"
    shutil.copyfile(seed, path)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    rename_service.sync_dir(music)
    original = path.read_bytes()
    for index in range(args.extra_jobs):
        job_id = "background-" + str(index)
        app.jobs[job_id] = {"id": job_id, "status": "done", "options": {},
                            "results": [{"path": "fixture-%s.mp3" % row,
                                         "candidates": [{"title": "Generated candidate", "fixture": "x" * 512}
                                                        for _ in range(20)]}
                                        for row in range(100)]}
    if args.extra_jobs:
        app.save_jobs()
    real_fsync = os.fsync
    timings = collections.defaultdict(lambda: [0, 0.0])
    syncs = []

    def timed_fsync(fd):
        target = os.readlink("/proc/self/fd/" + str(fd))
        tick = time.perf_counter()
        try:
            return real_fsync(fd)
        finally:
            syncs.append({"path": target, "seconds": round(time.perf_counter() - tick, 6)})

    def wrap(module, name):
        fn = getattr(module, name)
        key = module.__name__ + "." + name
        @functools.wraps(fn)
        def measured(*values, **options):
            tick = time.perf_counter()
            try:
                return fn(*values, **options)
            finally:
                timings[key][0] += 1
                timings[key][1] += time.perf_counter() - tick
        setattr(module, name, measured)

    os.fsync = timed_fsync
    for module, names in ((app, ("save_one", "save_jobs")),
                          (storage, ("ensure_backup", "_verify_backup", "describe", "revision",
                                     "_new_file", "_replace_file")),
                          (shutil, ("copyfile",)), (tags, ("write_file",))):
        for name in names:
            wrap(module, name)
    print(json.dumps({"event": "start", "run": args.run,
                      "storage_sha256": hashlib.sha256(Path(storage.__file__).read_bytes()).hexdigest(),
                      "music_bytes": len(original), "extra_jobs": args.extra_jobs}), flush=True)
    for attempt in (1, 2):
        row = {"path": path.name, "original": storage.describe(path), "candidates": []}
        app.prepare_result(row)
        app.jobs["latency"] = {"id": "latency", "status": "done", "options": {}, "results": [row]}
        request = app.SaveRequest(scope="current", paths=[path.name],
                                 items=[app.SaveItem(path=path.name, expected_revision=row["original"]["revision"],
                                                    selection="none", lyrics_text="Generated replacement " + str(attempt))],
                                 save_cover=False, save_lyrics=True, only_empty=False)
        timings.clear()
        syncs.clear()
        tick = time.perf_counter()
        result = app.save_job("latency", request)
        seconds = time.perf_counter() - tick
        assert result["saved"] == 1 and result["failed"] == 0, result
        assert tags.read_file(str(path)).lyrics == "Generated replacement " + str(attempt)
        print(json.dumps({"event": "save", "run": args.run, "attempt": attempt,
                          "seconds": round(seconds, 6), "fsync": list(syncs),
                          "stages_inclusive": {k: {"calls": v[0], "seconds": round(v[1], 6)}
                                               for k, v in timings.items()}}), flush=True)
    restored = storage.restore(path, music, app.BACKUP_ROOT, storage.revision(path))
    assert restored["exact"] and path.read_bytes() == original
    print(json.dumps({"event": "restore", "run": args.run, "exact_original_bytes": True}), flush=True)


if __name__ == "__main__":
    main()
