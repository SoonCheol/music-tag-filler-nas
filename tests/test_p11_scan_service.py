"""Scan extraction regression: generated audio and temporary data only."""
import asyncio
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import test_p0_storage as p0
from app import main, scan_service, search_service, storage


class ScanServiceTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job

    def test_import_has_no_main_or_application_state(self):
        unused = self.data / "unused"
        env = dict(os.environ, MUSIC_ROOT=str(unused / "music"), DATA_ROOT=str(unused / "data"))
        subprocess.run([sys.executable, "-c",
                        "import sys; from app import scan_service as s; "
                        "assert 'app.main' not in sys.modules; "
                        "assert not hasattr(s, 'jobs'); assert not hasattr(s, '_scan_clocks')"],
                       env=env, check=True, capture_output=True)
        self.assertFalse(unused.exists())

    def test_wrapper_passes_live_shared_references(self):
        jobs, clocks, opts = {}, {}, {"recurse": False}
        with patch.object(main, "jobs", jobs), patch.object(main, "_scan_clocks", clocks), \
                patch.object(main, "save_jobs") as persist, patch.object(scan_service, "scan_job") as execute:
            main.scan_job("id", "Album", opts, True)
            context, job_id, sub_path, actual_opts, resume = execute.call_args.args
            self.assertIs(context.jobs, jobs)
            self.assertIs(context.scan_clocks, clocks)
            self.assertIs(context.save_jobs, persist)
            self.assertIs(context.operation_lock, storage.OPERATION_LOCK)
            self.assertIs(context.music_root, main.MUSIC_ROOT)
            self.assertIs(context.data_root, main.DATA_ROOT)
            self.assertIs(context.parse_filename, main.parse_filename)
            self.assertIs(context.prepare_result, main.prepare_result)
            self.assertIs(context.file_state, main.file_state)
            self.assertIs(actual_opts, opts)
            self.assertEqual((job_id, sub_path, resume), ("id", "Album", True))
        self.assertIs(main.ScanCancellation, scan_service.ScanCancellation)

    def test_missing_job_does_not_collect_or_persist(self):
        before = dict(main._scan_clocks)
        with patch.object(scan_service.job_service, "collect") as collect, patch.object(main, "save_jobs") as persist:
            main.scan_job("missing", "", {})
            collect.assert_not_called()
            persist.assert_not_called()
        self.assertEqual(main._scan_clocks, before)

    def test_queued_cancel_and_resume_execute_registered_background_worker(self):
        from fastapi import BackgroundTasks
        path = self.copy()
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        background = BackgroundTasks()
        job_id = main.start_scan(main.ScanRequest(paths=[path.name], search_mode="quick"), background)["job_id"]
        self.assertEqual(main.jobs[job_id]["options"]["search_mode"], "quick")
        self.assertEqual(main.jobs[job_id]["status"], "queued")
        self.assertIs(background.tasks[0].func, main.scan_job)
        self.assertFalse(background.tasks[0].args[-1])
        main.cancel_job(job_id)
        with patch.object(search_service, "search") as search:
            asyncio.run(background())
            search.assert_not_called()
        self.assertEqual(main.jobs[job_id]["status"], "cancelled")
        resumed = BackgroundTasks()
        self.assertEqual(main.resume_job(job_id, resumed), {"status": "resumed", "id": job_id})
        self.assertIs(resumed.tasks[0].func, main.scan_job)
        self.assertTrue(resumed.tasks[0].args[-1])
        self.assertEqual(resumed.tasks[0].args[2]["search_mode"], "quick")
        self.assertFalse(main.jobs[job_id]["cancel_requested"])
        with patch.object(search_service, "search", return_value={"candidates": [], "search_status": "not_found"}) as search:
            asyncio.run(resumed())
        search.assert_called_once()
        self.assertEqual(search.call_args.kwargs["search_mode"], "quick")
        job = main.jobs[job_id]
        self.assertEqual((job["status"], job["scanned"], job["total"]), ("done", 1, 1))
        self.assertEqual(json.loads((self.data / "jobs" / (job_id + ".json")).read_text()), job)
        self.assertNotIn(job_id, main._scan_clocks)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_parallel_search_progress_lock_and_record_identity(self):
        paths = [self.copy(str(i) + ".mp3") for i in range(4)]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        self.job(paths)
        job = main.jobs["test"]
        job.update(status="queued", results=[], scanned=0, cancel_requested=False)
        entered, release, guard = threading.Event(), threading.Event(), threading.Lock()
        counts = {"running": 0, "peak": 0, "calls": 0}
        snapshots = []
        original_save = main.save_jobs
        original_describe = storage.describe
        read_paths = []

        def describe(path):
            read_paths.append(path)
            return original_describe(path)

        def persist(job_id=None):
            self.assertTrue(storage.OPERATION_LOCK._is_owned())
            snapshots.append(job["scanned"])
            return original_save(job_id)

        def search(*args, **kwargs):
            with guard:
                counts["running"] += 1
                counts["calls"] += 1
                counts["peak"] = max(counts["peak"], counts["running"])
                if counts["running"] == 3:
                    entered.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("test release timed out")
                return {"candidates": [], "search_status": "not_found", "_timing": {"fixture": True}}
            finally:
                with guard:
                    counts["running"] -= 1

        with patch.object(search_service, "search", side_effect=search), patch.object(main, "save_jobs", side_effect=persist), patch.object(storage, "describe", side_effect=describe):
            worker = threading.Thread(target=main.scan_job, args=("test", "", {}))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(len(read_paths), 3, "do not read the whole folder before searching")
                acquired = storage.OPERATION_LOCK.acquire(timeout=.5)
                self.assertTrue(acquired, "network search must not hold the operation lock")
                if acquired:
                    try:
                        self.assertIs(main.jobs["test"], job)
                        self.assertEqual((job["status"], job["total"], job["scanned"]), ("scanning", 4, 0))
                        self.assertEqual(sum(r["search_phase"] == "running" for r in job["results"]), 3)
                        self.assertIn("test", main._scan_clocks)
                    finally:
                        storage.OPERATION_LOCK.release()
            finally:
                release.set()
                worker.join(8)
            self.assertFalse(worker.is_alive())
        self.assertEqual((counts["peak"], counts["calls"]), (3, 4))
        self.assertEqual((job["status"], job["scanned"], job["total"]), ("done", 4, 4))
        self.assertEqual(snapshots, sorted(snapshots))
        self.assertNotIn("test", main._scan_clocks)
        stored = json.loads((self.data / "jobs/test.json").read_text())
        self.assertEqual(stored, job)
        self.assertGreaterEqual(stored["scan_elapsed_seconds"], stored["scan_segment_seconds"])
        self.assertTrue(all("_timing" not in r for r in stored["results"]))
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])
