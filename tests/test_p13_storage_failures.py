"""Storage 0b: generated audio and private temporary data, no operational mounts."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_p0_storage as p0
from app import main, storage, rename_service as ren, lyric_assets
from app.upstream import tags


class RecoveryBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    timed = "[00:00.00]First generated line\n[00:00.20]Second generated line"

    def setUp(self):
        p0.P0Tests.setUp(self)
        ren.blocked.clear()
        ren.active.clear()
        main.save_tasks.clear()

    def tearDown(self):
        ren.blocked.clear()
        ren.active.clear()
        main.save_tasks.clear()
        p0.P0Tests.tearDown(self)

    def _save(self, path, title="Committed", **kwargs):
        with storage.OPERATION_LOCK:
            return storage.save(path, self.root, self.backups, {"title": title},
                                ["title"], False, storage.revision(path),
                                asset_root=self.data, **kwargs)

    def _prepare(self, lrc=False, edited=False):
        path = self.copy()
        self.original = path.read_bytes()
        with storage.OPERATION_LOCK:
            storage.ensure_backup(path, self.root, self.backups, storage.revision(path))
        if edited:
            self._save(path, title="Edited")
        if lrc:
            path.with_suffix(".lrc").write_bytes(lyric_assets.payload(self.timed))
        self.job([path])
        main.save_jobs()
        self.side_bytes = Path(tags.backup_path(str(path))).read_bytes()
        self.core = {p.relative_to(self.backups).as_posix(): p.read_bytes()
                     for p in self.backups.rglob("*") if p.is_file()}
        self.disk_jobs = (self.data / "jobs" / "test.json").read_bytes()
        return path

    def _assert_core(self):
        for name, content in self.core.items():
            self.assertEqual((self.backups / name).read_bytes(), content)
        leftovers = [p for p in Path(self.case.name).rglob("*")
                     if p.name.startswith((".tagtxn-", ".tagbak-", ".backup-"))]
        self.assertEqual(leftovers, [])

    def _assert_backup(self, path):
        folder, manifest = storage._verify_backup(path, self.root, self.backups)
        self.assertEqual((folder / "original.bin").read_bytes(), self.original)
        self.assertEqual(manifest["sha256"], storage.digest(self.original))
        self.assertEqual(Path(tags.backup_path(str(path))).read_bytes(), self.side_bytes)
        self._assert_core()

    def _assert_jobs(self, memory, disk):
        self.assertEqual(main.jobs["test"]["results"][0]["path"], memory)
        value = json.loads((self.data / "jobs" / "test.json").read_bytes())
        self.assertEqual(value["results"][0]["path"], disk)

    def _lrc_record(self, status):
        files = list((self.data / "lyric-assets").glob("*.json"))
        self.assertEqual(len(files), 1)
        value = json.loads(files[0].read_bytes())
        self.assertEqual(value["status"], status)
        return files[0], value

    def _rename_record(self, status):
        records = ren.records(self.data)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1]["status"], status)
        return records[0]

    def _rename(self, path, stem="Renamed"):
        with storage.OPERATION_LOCK:
            return ren.rename(self.root, self.data, self.backups, main.jobs,
                              main.save_jobs, "test", path.name, stem, storage.revision(path))

    def _recover(self):
        main.recover_filename_changes()
        ren.check_ready(self.data)

    def _restore(self, path):
        with storage.OPERATION_LOCK:
            outcome = storage.restore(path, self.root, self.backups, storage.revision(path))
        self.assertTrue(outcome["exact"])
        self.assertEqual(path.read_bytes(), self.original)
        self._assert_backup(path)

    def _expected_defect_guard(self):
        reached = []
        self.addCleanup(lambda: self.assertEqual(reached, [True]))
        return reached

    def test_lrc_journal_create_link_failure_before_music_replace(self):
        path = self._prepare()
        calls = []
        failure = OSError("injected LRC journal publication")

        def fail_link(src, dst, *args, **kwargs):
            if Path(dst).parent == self.data / "lyric-assets":
                calls.append(Path(src))
                self.assertEqual(json.loads(Path(src).read_bytes())["status"], "pending")
                raise failure
            return real_link(src, dst, *args, **kwargs)

        real_link = storage.os.link
        with patch.object(storage.os, "link", side_effect=fail_link):
            with self.assertRaises(OSError) as caught:
                self._save(path, lrc=self.timed)
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].exists())
        self.assertEqual(path.read_bytes(), self.original)
        self.assertEqual(list((self.data / "lyric-assets").iterdir()), [])
        self.assertFalse(path.with_suffix(".lrc").exists())
        self._assert_backup(path)
        self._assert_jobs(path.name, path.name)
        self.assertEqual((self.data / "jobs" / "test.json").read_bytes(), self.disk_jobs)
        self.assertEqual(self._save(path, lrc=self.timed)["status"], "saved")
        self._lrc_record("complete")
        self._restore(path)

    def test_lrc_journal_sync_failure_leaves_abortable_pending_intent(self):
        path = self._prepare()
        sync_dir = ren.sync_dir
        calls = []
        failure = OSError("injected after LRC journal publication")

        def fail_sync(folder):
            if Path(folder) == self.data / "lyric-assets":
                calls.append(Path(folder))
                raise failure
            return sync_dir(folder)

        with patch.object(ren, "sync_dir", side_effect=fail_sync):
            with self.assertRaises(OSError) as caught:
                self._save(path, lrc=self.timed)
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(calls), 1)
        journal, record = self._lrc_record("pending")
        self.assertEqual(record["before"], storage.revision(path))
        self.assertNotEqual(record["after"], record["before"])
        self.assertEqual(path.read_bytes(), self.original)
        self.assertFalse(path.with_suffix(".lrc").exists())
        self._assert_backup(path)
        self._recover()
        self.assertEqual(json.loads(journal.read_bytes())["status"], "aborted")
        self.assertEqual(self._save(path, lrc=self.timed)["status"], "saved")
        statuses = sorted(json.loads(p.read_bytes())["status"]
                          for p in journal.parent.glob("*.json"))
        self.assertEqual(statuses, ["aborted", "complete"])
        self._assert_jobs(path.name, path.name)
        self._restore(path)

    def test_lrc_publish_failure_after_music_commit_recovers_idempotently(self):
        path = self._prepare()
        lrc = path.with_suffix(".lrc")
        real_link = storage.os.link
        calls = []

        def fail_link(src, dst, *args, **kwargs):
            if Path(dst) == lrc:
                calls.append(Path(src))
                raise OSError("injected LRC publication after music commit")
            return real_link(src, dst, *args, **kwargs)

        with patch.object(storage.os, "link", side_effect=fail_link):
            with self.assertRaisesRegex(storage.StorageError, "LRC"):
                self._save(path, lrc=self.timed)
        self.assertEqual(len(calls), 2)  # Initial completion and its retry.
        self.assertTrue(all(not p.exists() for p in calls))
        self.assertFalse(lrc.exists())
        committed = path.read_bytes()
        self.assertNotEqual(committed, self.original)
        self.assertEqual(tags.read_file(str(path)).tags.title, "Committed")
        journal, record = self._lrc_record("pending")
        self.assertEqual(record["after"], storage.revision(path))
        self.assertIn(str(self.data.resolve()), ren.blocked)
        self._assert_backup(path)
        self._assert_jobs(path.name, path.name)
        self._recover()
        self.assertEqual(json.loads(journal.read_bytes())["status"], "complete")
        self.assertEqual(lrc.read_bytes(), lyric_assets.payload(self.timed))
        snapshot = (path.read_bytes(), lrc.read_bytes(), journal.read_bytes(), lrc.stat().st_mtime_ns)
        self._recover()
        self.assertEqual((path.read_bytes(), lrc.read_bytes(), journal.read_bytes(), lrc.stat().st_mtime_ns), snapshot)
        self.assertEqual(path.read_bytes(), committed)
        self.assertEqual(self._save(path, lrc=self.timed)["status"], "skipped")
        self._restore(path)
        self.assertEqual(lrc.read_bytes(), lyric_assets.payload(self.timed))

    def test_lrc_complete_record_update_failure_keeps_created_asset(self):
        path = self._prepare()
        replace_file = storage._replace_file
        calls = []

        def fail_record(target, data):
            if Path(target).parent == self.data / "lyric-assets":
                calls.append(Path(target))
                self.assertEqual(json.loads(data)["status"], "complete")
                raise OSError("injected complete LRC record update")
            return replace_file(target, data)

        with patch.object(storage, "_replace_file", side_effect=fail_record):
            with self.assertRaisesRegex(storage.StorageError, "LRC"):
                self._save(path, lrc=self.timed)
        self.assertEqual(len(calls), 2)
        journal, record = self._lrc_record("pending")
        self.assertEqual(record["after"], storage.revision(path))
        lrc = path.with_suffix(".lrc")
        snapshot = lrc.read_bytes(), lrc.stat().st_ino, lrc.stat().st_mtime_ns
        self.assertEqual(snapshot[0], lyric_assets.payload(self.timed))
        self.assertNotEqual(path.read_bytes(), self.original)
        self._assert_backup(path)
        self._assert_jobs(path.name, path.name)
        self._recover()
        self.assertEqual(json.loads(journal.read_bytes())["status"], "complete")
        self.assertEqual((lrc.read_bytes(), lrc.stat().st_ino, lrc.stat().st_mtime_ns), snapshot)
        self._restore(path)

    def test_lrc_complete_record_transient_failure_retries_in_same_save(self):
        path = self._prepare()
        replace_file = storage._replace_file
        calls = []

        def fail_once(target, data):
            if Path(target).parent == self.data / "lyric-assets":
                calls.append(Path(target))
                if len(calls) == 1:
                    raise OSError("injected transient complete record update")
            return replace_file(target, data)

        with patch.object(storage, "_replace_file", side_effect=fail_once):
            outcome = self._save(path, lrc=self.timed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(outcome["status"], "saved")
        self._lrc_record("complete")
        ren.check_ready(self.data)
        self.assertEqual(path.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._assert_backup(path)
        self._assert_jobs(path.name, path.name)
        self._restore(path)

    def test_journaled_music_move_failure_aborts_then_retry_succeeds(self):
        path = self._prepare(lrc=True, edited=True)
        current = path.read_bytes()
        target = path.with_name("Renamed.mp3")
        no_replace = ren.no_replace
        calls = []

        def fail_music(src, dst):
            if Path(src) == path:
                calls.append((Path(src), Path(dst)))
                raise OSError("injected journaled music move")
            return no_replace(src, dst)

        with patch.object(ren, "no_replace", side_effect=fail_music):
            with self.assertRaisesRegex(storage.StorageError, "injected journaled music move"):
                self._rename(path)
        self.assertEqual(calls, [(path, target)])
        self._rename_record("aborted")
        self.assertEqual(path.read_bytes(), current)
        self.assertFalse(target.exists())
        self.assertFalse(Path(tags.backup_path(str(target))).exists())
        self.assertEqual(path.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._assert_backup(path)
        self._assert_jobs(path.name, path.name)
        ren.check_ready(self.data)
        self.assertEqual(self._rename(path)["status"], "complete")
        self.assertEqual(sorted(r["status"] for _, r in ren.records(self.data)), ["aborted", "complete"])
        self.assertFalse(path.exists())
        self.assertEqual(target.read_bytes(), current)
        self.assertEqual(target.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._assert_jobs(target.name, target.name)
        self._restore(target)

    def _journaled_asset_move_failure(self, kind):
        path = self._prepare(lrc=True, edited=True)
        target = path.with_name("Renamed.mp3")
        current = path.read_bytes()
        source_asset = Path(tags.backup_path(str(path))) if kind == "sidecar" else path.with_suffix(".lrc")
        no_replace = ren.no_replace
        calls = []

        def fail_asset(src, dst):
            if Path(src) == source_asset:
                calls.append((Path(src), Path(dst)))
                raise OSError("injected " + kind + " move")
            return no_replace(src, dst)

        with patch.object(ren, "no_replace", side_effect=fail_asset):
            with self.assertRaisesRegex(storage.StorageError, "injected " + kind):
                self._rename(path)
        self.assertEqual(len(calls), 2)
        self.assertFalse(path.exists())
        self.assertEqual(target.read_bytes(), current)
        self.assertTrue(source_asset.is_file())
        self.assertFalse(target.with_suffix(".lrc").exists())
        self.assertEqual(path.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        if kind == "sidecar":
            self.assertEqual(source_asset.read_bytes(), self.side_bytes)
            self.assertFalse(Path(tags.backup_path(str(target))).exists())
        else:
            self.assertFalse(Path(tags.backup_path(str(path))).exists())
            self._assert_backup(target)
        self._assert_core()
        self._rename_record("pending")
        self._assert_jobs(path.name, path.name)
        self.assertIn(str(self.data.resolve()), ren.blocked)
        self._recover()
        self._rename_record("complete")
        self.assertFalse(source_asset.exists())
        self.assertFalse(path.with_suffix(".lrc").exists())
        self.assertEqual(target.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._assert_jobs(target.name, target.name)
        self._assert_backup(target)
        self._recover()
        self._restore(target)

    def test_journaled_sidecar_move_failure_recovers_forward(self):
        self._journaled_asset_move_failure("sidecar")

    def test_journaled_lrc_move_failure_recovers_forward(self):
        self._journaled_asset_move_failure("LRC")

    def test_journaled_jobs_write_failure_recovers_from_persisted_old_path(self):
        path = self._prepare(lrc=True, edited=True)
        target = path.with_name("Renamed.mp3")
        current = path.read_bytes()
        with patch.object(main, "save_jobs", side_effect=OSError("injected jobs write")) as mocked:
            with self.assertRaisesRegex(storage.StorageError, "injected jobs write"):
                self._rename(path)
        self.assertEqual(mocked.call_count, 2)
        self.assertFalse(path.exists())
        self.assertEqual(target.read_bytes(), current)
        self._assert_backup(target)
        self.assertEqual(target.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._rename_record("pending")
        self._assert_jobs(target.name, path.name)
        self.assertEqual((self.data / "jobs" / "test.json").read_bytes(), self.disk_jobs)
        self.assertIn(str(self.data.resolve()), ren.blocked)
        # Reload only the generated persisted record; this is not a process kill.
        main.jobs.clear()
        main.jobs["test"] = json.loads(self.disk_jobs)
        self._recover()
        self._assert_jobs(target.name, target.name)
        self._rename_record("complete")
        persisted = (self.data / "jobs" / "test.json").read_bytes()
        self._recover()
        self.assertEqual((self.data / "jobs" / "test.json").read_bytes(), persisted)
        self._restore(target)

    def test_journaled_complete_record_failure_recovers_after_jobs_saved(self):
        path = self._prepare(lrc=True, edited=True)
        target = path.with_name("Renamed.mp3")
        current = path.read_bytes()
        replace_file = storage._replace_file
        calls = []

        def fail_record(name, data):
            if Path(name).parent == self.data / "renames" and json.loads(data)["status"] == "complete":
                calls.append(Path(name))
                self.assertEqual(json.loads(data)["status"], "complete")
                raise OSError("injected complete rename record")
            return replace_file(name, data)

        with patch.object(storage, "_replace_file", side_effect=fail_record):
            with self.assertRaisesRegex(storage.StorageError, "injected complete rename record"):
                self._rename(path)
        self.assertEqual(len(calls), 2)
        self.assertFalse(path.exists())
        self.assertEqual(target.read_bytes(), current)
        self._assert_backup(target)
        self._assert_jobs(target.name, target.name)
        self._rename_record("pending")
        self._recover()
        self._rename_record("complete")
        self.assertEqual(target.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._restore(target)

    def _plain_move_failure(self, kind):
        # Recreate an old, unjournaled failure explicitly. New storage.save
        # no longer uses this sidecar-first writer; these are legacy residues.
        path = self._prepare(edited=True)
        target = Path(tags.rename_target(str(path), tags.Tags(title="Committed", artist="Original singer")))
        old_side, new_side = Path(tags.backup_path(str(path))), Path(tags.backup_path(str(target)))
        replace = storage.os.replace
        calls = []

        def fail_move(src, dst, *args, **kwargs):
            src, dst = Path(src), Path(dst)
            if (kind == "sidecar" and src == old_side) or (kind == "music" and src == path):
                calls.append((src, dst))
                raise OSError("injected plain " + kind + " move")
            return replace(src, dst, *args, **kwargs)

        self._save(path)
        folder, manifest = storage._verify_backup(path, self.root, self.backups)
        alias = {"path": target.name, "checksum": storage.digest((target.name + folder.name + manifest["tags_sha256"]).encode())}
        storage._new_file(folder / ("alias-" + storage.digest(target.name.encode()) + ".json"), storage._json_bytes(alias))
        with patch.object(storage.os, "replace", side_effect=fail_move):
            with self.assertRaises(tags.RenameFailed):
                tags.rename_file(str(path), str(target))
        self.assertEqual(len(calls), 1)
        self.assertEqual(tags.read_file(str(path)).tags.title, "Committed")
        self.assertFalse(target.exists())
        self.assertFalse(new_side.exists())
        self.assertTrue(old_side.is_file())  # Includes the music-failure rollback.
        self.assertEqual(ren.records(self.data), [])
        self._assert_backup(path)
        self._assert_jobs(path.name, path.name)
        aliases = list(self.backups.glob("*/alias-*.json"))
        self.assertEqual(len(aliases), 1)
        self.assertEqual(json.loads(aliases[0].read_bytes())["path"], target.name)
        return path, target

    def test_plain_sidecar_failure_retry_should_not_stall_on_existing_alias(self):
        reached = self._expected_defect_guard()
        path, target = self._plain_move_failure("sidecar")
        retry = self._save(path, rename=True)
        if retry["status"] != "saved":
            self.assertIn("[Errno 17]", retry["rename_error"])
            self.assertIn("alias-", retry["rename_error"])
        actual = self.root / retry["path"]
        self._assert_backup(actual)
        self._assert_jobs(path.name, path.name)
        self._restore(actual)
        reached.append(True)
        self.assertEqual(retry["status"], "saved")

    def test_plain_music_failure_retry_should_not_stall_on_existing_alias(self):
        reached = self._expected_defect_guard()
        path, target = self._plain_move_failure("music")
        retry = self._save(path, rename=True)
        if retry["status"] != "saved":
            self.assertIn("[Errno 17]", retry["rename_error"])
            self.assertIn("alias-", retry["rename_error"])
        actual = self.root / retry["path"]
        self._assert_backup(actual)
        self._assert_jobs(path.name, path.name)
        self._restore(actual)
        reached.append(True)
        self.assertEqual(retry["status"], "saved")

    @unittest.expectedFailure
    def test_plain_failed_sidecar_rollback_should_remain_recoverable(self):
        # Existing unjournaled residue remains a #017 repair issue.
        reached = self._expected_defect_guard()
        path = self._prepare(edited=True)
        target = Path(tags.rename_target(str(path), tags.Tags(title="Committed", artist="Original singer")))
        old_side = Path(tags.backup_path(str(path)))
        new_side = Path(tags.backup_path(str(target)))
        replace = storage.os.replace
        calls = []

        def fail_music_and_rollback(src, dst, *args, **kwargs):
            src, dst = Path(src), Path(dst)
            if src == path or (src == new_side and dst == old_side):
                calls.append((src, dst))
                raise OSError("injected music move and sidecar rollback failure")
            return replace(src, dst, *args, **kwargs)

        self._save(path)
        with patch.object(storage.os, "replace", side_effect=fail_music_and_rollback):
            with self.assertRaises(tags.RenameFailed) as failure:
                tags.rename_file(str(path), str(target))
        self.assertEqual(calls, [(path, target), (new_side, old_side)])
        self.assertEqual(failure.exception.backup, str(new_side))
        self.assertTrue(path.is_file())
        self.assertFalse(target.exists())
        self.assertEqual(new_side.read_bytes(), self.side_bytes)
        self.assertFalse(old_side.exists())
        self.assertEqual(ren.records(self.data), [])
        self._assert_core()
        self._assert_jobs(path.name, path.name)
        with self.assertRaises(storage.StorageError):
            storage.restore(path, self.root, self.backups, storage.revision(path))
        self._recover()
        recovered = old_side.is_file()
        # Explicit repair of this generated fixture proves that the first backup
        # remains usable. It is not application recovery and never touches real data.
        if not recovered:
            new_side.rename(old_side)
        self._assert_backup(path)
        self._restore(path)
        reached.append(True)
        self.assertTrue(recovered, "application recovery left the sidecar detached from existing music")

    def test_plain_auto_rename_must_preserve_late_external_target_and_sidecar(self):
        reached = self._expected_defect_guard()
        path = self._prepare(edited=True)
        no_replace = ren.no_replace
        calls = []
        occupant = self.original  # A distinct, valid generated audio file.
        occupant_side = b'{"tags":{},"synthetic_external_backup":true}'

        def late_occupant(src, dst):
            target = Path(dst)
            if Path(src) == path:
                self.assertFalse(target.exists())
                self.assertFalse(Path(tags.backup_path(str(dst))).exists())
                target.write_bytes(occupant)
                Path(tags.backup_path(str(dst))).write_bytes(occupant_side)
                calls.append(target)
            return no_replace(src, dst)

        with patch.object(ren, "no_replace", side_effect=late_occupant):
            outcome = self._save(path, rename=True)
        self.assertEqual(len(calls), 1)
        observed = calls[0].read_bytes(), Path(tags.backup_path(str(calls[0]))).read_bytes()
        actual = self.root / outcome["path"]
        self._assert_backup(actual)
        self.assertEqual(outcome["status"], "partial")
        self._rename_record("pending")
        self.assertIn(str(self.data.resolve()), ren.blocked)
        self._restore(actual)
        reached.append(True)
        self.assertTrue(observed == (occupant, occupant_side), "late external music/sidecar were overwritten")

    def test_plain_auto_rename_jobs_failure_should_recover_persisted_path(self):
        reached = self._expected_defect_guard()
        path = self._prepare(edited=True)
        row = main.jobs["test"]["results"][0]
        request = main.SaveRequest(**self.request([self.item(row)], rename=True))
        with patch.object(main, "save_jobs", side_effect=OSError("injected final jobs write")) as mocked:
            response = main.save_job("test", request)
        self.assertEqual(mocked.call_count, 3)  # finish, recovery, final batch state
        self.assertEqual(response["saved"], 1)
        self.assertIn("state_error", response)
        actual = self.root / response["results"][0]["path"]
        self.assertNotEqual(actual, path)
        self.assertFalse(path.exists())
        self._assert_backup(actual)
        self._assert_jobs(actual.name, path.name)
        self._rename_record("pending")
        main.jobs.clear()
        main.jobs["test"] = json.loads(self.disk_jobs)
        self._recover()
        recovered_path = main.jobs["test"]["results"][0]["path"]
        self.assertNotEqual(actual.read_bytes(), self.original)
        self._restore(actual)
        reached.append(True)
        self.assertEqual(recovered_path, actual.name)

    def test_lrc_auto_rename_jobs_failure_should_report_existing_new_path(self):
        reached = self._expected_defect_guard()
        path = self._prepare(lrc=True, edited=True)
        target = Path(tags.rename_target(str(path), tags.Tags(title="Committed", artist="Original singer")))
        outcome = None
        with patch.object(main, "save_jobs", side_effect=OSError("injected auto LRC jobs write")) as mocked:
            try:
                outcome = self._save(path, rename=True, rename_context=(main.jobs, main.save_jobs, "test"))
            except FileNotFoundError as exc:
                self.assertEqual(Path(exc.filename), path)
        self.assertEqual(mocked.call_count, 2)
        self.assertFalse(path.exists())
        self.assertTrue(target.is_file())
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(outcome["path"], target.name)
        self._assert_backup(target)
        self.assertEqual(target.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self._assert_jobs(target.name, path.name)
        self._rename_record("pending")
        self.assertIn(str(self.data.resolve()), ren.blocked)
        self._recover()
        self._rename_record("complete")
        self._assert_jobs(target.name, target.name)
        self._restore(target)
        reached.append(True)
        self.assertIsNotNone(outcome, "committed rename must return its actual path instead of describing the missing old path")


if __name__ == "__main__":
    unittest.main(verbosity=2)
