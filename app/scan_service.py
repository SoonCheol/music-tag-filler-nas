"""Scan execution with explicitly supplied application state and callbacks.

This module owns no jobs, clocks, paths or operation lock and never imports main.
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Dict, Optional, Tuple

from . import job_service, search_service, storage
from .upstream import match as original_match


@dataclass(frozen=True)
class ScanContext:
    """References to the existing state; created at invocation, never copied."""

    jobs: Dict[str, dict]
    scan_clocks: Dict[str, Tuple[float, float]]
    music_root: Path
    data_root: Path
    save_jobs: Callable[[Optional[str]], None]
    operation_lock: ContextManager
    parse_filename: Callable[[Path], Tuple[str, str]]
    prepare_result: Callable[[dict], dict]
    file_state: Callable[[dict], str]


def update_scan_timing(jobs, _scan_clocks, job_id=None):
    """Refresh persisted timing while the caller holds its operation lock."""
    for key in [job_id] if job_id else list(_scan_clocks):
        if key in _scan_clocks and key in jobs:
            started, accumulated = _scan_clocks[key]
            segment = max(0.0, time.perf_counter() - started)
            jobs[key].update(scan_segment_seconds=segment,
                             scan_elapsed_seconds=accumulated + segment)
            if jobs[key].get("status") not in job_service.ACTIVE:
                jobs[key].update(scan_segment_finished_at=time.time(), scan_finished_at=time.time())


class ScanCancellation:
    def __init__(self, job):
        self.job = job

    def is_set(self):
        return bool(self.job.get("cancel_requested"))


def scan_job(context: ScanContext, job_id: str, sub_path: str, opts: dict, resume: bool = False):
    jobs = context.jobs
    _scan_clocks = context.scan_clocks
    MUSIC_ROOT = context.music_root
    DATA_ROOT = context.data_root
    save_jobs = context.save_jobs
    operation_lock = context.operation_lock
    parse_filename = context.parse_filename
    prepare_result = context.prepare_result
    file_state = context.file_state
    job = jobs.get(job_id)
    if not job:
        return
    cancelled = ScanCancellation(job)
    scan_started = time.perf_counter()
    with operation_lock:
        _scan_clocks[job_id] = (scan_started, job.get("scan_elapsed_seconds", 0.0))
        job.setdefault("scan_started_at", time.time())
        job.update(scan_segment_started_at=time.time(), scan_segment_seconds=0.0)
        job.pop("scan_segment_finished_at", None)
        job.pop("scan_finished_at", None)
    logging.getLogger("uvicorn.error").info("scan_timing %s", json.dumps({
        "event": "start", "job_id": job_id, "options": opts,
        "intervals": search_service.net.throttle._intervals,
        "windows": search_service.net.throttle._windows}))
    try:
        files = job_service.collect(MUSIC_ROOT, opts.get("paths") or [sub_path], opts.get("recurse", True), cancel=cancelled)
        previous = job.get("results", []) if resume else []
        retained, pending, missing = job_service.retained_results(MUSIC_ROOT, files, previous, cancel=cancelled)
        known = {r["path"]: r for r in retained}
        rows = [known.get(p.relative_to(MUSIC_ROOT.resolve()).as_posix()) or
                {"path": p.relative_to(MUSIC_ROOT.resolve()).as_posix(), "original": {}, "candidates": [],
                 "search_phase": "waiting", "scan_auto_selected": False, "file_state": "waiting"} for p in files]
        with operation_lock:
            job.update(status="scanning", total=len(files), results=rows, scanned=len(retained),
                       missing_paths=missing, diagnostic="기존 태그 읽는 중", search_wait_seconds=0)
            save_jobs(job_id)
        by_path = {r["path"]: r for r in rows}
        ready = []
        last_metadata_save = time.monotonic()
        for path in pending:
            if cancelled.is_set():
                break
            relative = path.relative_to(MUSIC_ROOT.resolve()).as_posix()
            try:
                original = storage.describe(path)
                artist, title = parse_filename(path)
                artist, title = original.get("artist") or artist, original.get("title") or title
                with operation_lock:
                    by_path[relative].update(original=original, parsed={"artist": artist, "title": title})
                    job["view_revision"] = job.get("view_revision",0)+1
                    if time.monotonic() - last_metadata_save >= 2:
                        save_jobs(job_id)
                        last_metadata_save = time.monotonic()
                ready.append((path, relative, original, artist, title, time.perf_counter(), len(ready) + 1))
            except Exception as exc:
                with operation_lock:
                    by_path[relative].update(error=str(exc), search_phase="error", file_state="error")
                    job["scanned"] += 1
                    save_jobs(job_id)
        with operation_lock:
            save_jobs(job_id)
        def lookup(item):
            path, relative, original, artist, title, queued_at, index = item
            lookup_started = time.perf_counter()
            timing = {}
            if cancelled.is_set():
                return None
            with operation_lock:
                by_path[relative].update(search_phase="running", file_state="running")
                job["view_revision"] = job.get("view_revision",0)+1
                job["current_file"] = relative
            try:
                found = search_service.search(path, original_match.build_query(title, artist), opts.get("country"),
                                              original.get("duration", 0), DATA_ROOT,
                                              use_fingerprint=opts.get("use_fingerprint", False), cancel=cancelled,
                                              on_wait=lambda seconds: job.update(search_wait_seconds=seconds))
                if cancelled.is_set():
                    return None
                timing = found.pop("_timing", {})
                result = {**found, "path": relative, "original": original,
                          "parsed": {"artist": artist, "title": title}, "lyrics": None,
                          "lyrics_status": "skipped", "search_phase": "complete"}
                tick = time.perf_counter()
                prepare_result(result)
                timing["candidate_seconds"] = time.perf_counter() - tick
                result["scan_auto_selected"] = result["best"] is not None
                result["file_state"] = file_state(result)
                if result.get("search_status") in ("error", "failed"):
                    result.update(search_phase="error", file_state="error")
            except Exception as exc:
                if cancelled.is_set():
                    return None
                result = {"path": relative, "original": original, "candidates": [],
                          "error": str(exc), "search_phase": "error", "file_state": "error"}
            with operation_lock:
                if cancelled.is_set():
                    return None
                by_path[relative].update(result)
                job["scanned"] += 1
                job["diagnostic"] = ""
                tick = time.perf_counter()
                save_jobs(job_id)
                timing["json_seconds"] = time.perf_counter() - tick
            timing.update(event="song", job_id=job_id, index=index, path=relative,
                          queue_seconds=lookup_started - queued_at,
                          total_seconds=time.perf_counter() - lookup_started,
                          completed_seconds=time.perf_counter() - scan_started)
            logging.getLogger("uvicorn.error").info("scan_timing %s", json.dumps(timing))
            return relative
        with ThreadPoolExecutor(max_workers=3) as pool:
            iterator = iter(ready)
            futures = set()
            while not cancelled.is_set() and (futures or iterator is not None):
                while len(futures) < 3 and iterator is not None and not cancelled.is_set():
                    item = next(iterator, None)
                    if item is None:
                        iterator = None
                        break
                    futures.add(pool.submit(lookup, item))
                if futures:
                    done, futures = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
                    for future in done:
                        future.result()
        with operation_lock:
            for row in rows:
                if row.get("search_phase") == "running":
                    row.update(search_phase="waiting", file_state="waiting")
            job.update(status="cancelled" if cancelled.is_set() else "done", finished_at=time.time(),
                       current_file="", search_wait_seconds=0,
                       diagnostic="중지 완료" if cancelled.is_set() else "")
            save_jobs(job_id)
    except job_service.ScanCancelled:
        with operation_lock:
            job.update(status="cancelled", finished_at=time.time(), current_file="", search_wait_seconds=0, diagnostic="중지 완료")
            save_jobs(job_id)
    except Exception as exc:
        with operation_lock:
            job.update(status="failed", error=str(exc), diagnostic="작업 상태 기록 또는 파일 탐색 실패")
            try:
                save_jobs(job_id)
            except OSError:
                job["state_error"] = "작업 기록 실패. 기존 디스크 기록은 보존했습니다"
    finally:
        with operation_lock:
            _scan_clocks.pop(job_id, None)
        logging.getLogger("uvicorn.error").info("scan_timing %s", json.dumps({
            "event": "finish", "job_id": job_id, "status": job.get("status"),
            "elapsed_seconds": time.perf_counter() - scan_started}))
