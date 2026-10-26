"""#016: generated audio only; automatic rename collision/recovery contracts."""
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import test_p0_storage as p0
import test_p13_storage_failures as p13
from app import main, storage, rename_service as ren, lyric_assets
from app.upstream import tags


class AutoRenameTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p13.RecoveryBoundaryTests.setUp
    tearDown = p13.RecoveryBoundaryTests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    timed = p13.RecoveryBoundaryTests.timed
    _save = p13.RecoveryBoundaryTests._save
    _prepare = p13.RecoveryBoundaryTests._prepare
    _assert_core = p13.RecoveryBoundaryTests._assert_core
    _assert_backup = p13.RecoveryBoundaryTests._assert_backup
    _assert_jobs = p13.RecoveryBoundaryTests._assert_jobs
    _rename_record = p13.RecoveryBoundaryTests._rename_record
    _recover = p13.RecoveryBoundaryTests._recover
    _restore = p13.RecoveryBoundaryTests._restore

    def test_direct_save_four_formats_uses_journal_without_job_context(self):
        for extension in ("mp3", "flac", "m4a", "ogg"):
            with self.subTest(extension=extension):
                path = self.copy("original." + extension)
                first = path.read_bytes()
                outcome = self._save(path, rename=True)
                actual = self.root / outcome["path"]
                self.assertEqual(outcome["status"], "saved")
                self.assertFalse(path.exists())
                record = ren.records(self.data)[-1][1]
                self.assertEqual((record["status"], record["new_path"]), ("complete", actual.name))
                self.assertEqual(record["identity"], ren.identity(actual))
                self.assertEqual(record["revision"], storage.revision(actual))
                folder, _ = storage._verify_backup(actual, self.root, self.backups)
                self.assertEqual((folder / "original.bin").read_bytes(), first)
                storage.restore(actual, self.root, self.backups, storage.revision(actual))
                self.assertEqual(actual.read_bytes(), first)

    def test_direct_save_default_data_root_and_existing_lrc(self):
        path = self.copy()
        first = path.read_bytes()
        path.with_suffix(".lrc").write_bytes(lyric_assets.payload(self.timed))
        outcome = storage.save(path, self.root, self.backups, {}, [], False,
                               storage.revision(path), rename=True)
        actual = self.root / outcome["path"]
        self.assertEqual(outcome["status"], "saved")
        self.assertEqual(actual.read_bytes(), first)
        self.assertEqual(actual.with_suffix(".lrc").read_bytes(), lyric_assets.payload(self.timed))
        self.assertEqual(ren.records(self.backups.parent)[0][1]["status"], "complete")
        storage._verify_backup(actual, self.root, self.backups)

    def test_automatic_numbering_checks_music_sidecar_lrc_and_folded_names(self):
        path = self._prepare()
        stem = "Original singer - Committed"
        occupants = {
            self.root / (stem.upper() + ".mp3"): b"external music",
            self.root / (stem + " (2).mp3.tagbak.json"): b"external sidecar",
            self.root / (stem + " (3).lrc"): b"external LRC",
        }
        for target, content in occupants.items():
            target.write_bytes(content)
        outcome = self._save(path, rename=True)
        self.assertEqual(outcome["path"], stem + " (4).mp3")
        self.assertEqual(outcome["status"], "saved")
        for target, content in occupants.items():
            self.assertEqual(target.read_bytes(), content)
        self._assert_backup(self.root / outcome["path"])

    def test_late_music_collision_preserves_both_files_and_pending(self):
        path = self._prepare()
        no_replace = ren.no_replace
        collisions = []

        def collide(source, target):
            if Path(source) == path:
                target = Path(target)
                self.assertFalse(target.exists())
                target.write_bytes(self.original)
                collisions.append(target)
            return no_replace(source, target)

        with patch.object(ren, "no_replace", side_effect=collide), patch.object(tags, "rename_file") as legacy:
            outcome = self._save(path, rename=True)
        legacy.assert_not_called()
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].read_bytes(), self.original)
        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(outcome["path"], path.name)
        self.assertEqual(tags.read_file(str(path)).tags.title, "Committed")
        self._rename_record("pending")
        self._assert_backup(path)
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
        collisions[0].unlink()  # Only the generated external occupant is removed.
        self._recover()
        self._rename_record("aborted")
        self._restore(path)

    def _late_asset_collision(self, kind):
        path = self._prepare(lrc=kind == "lrc")
        source_asset = path.with_suffix(".lrc") if kind == "lrc" else Path(tags.backup_path(str(path)))
        source_bytes = source_asset.read_bytes()
        no_replace = ren.no_replace
        collisions = []
        calls = []

        def collide(source, target):
            if Path(source) == source_asset:
                calls.append(Path(target))
                if not collisions:
                    Path(target).write_bytes(b"external " + kind.encode())
                    collisions.append(Path(target))
            return no_replace(source, target)

        with patch.object(ren, "no_replace", side_effect=collide):
            outcome = self._save(path, rename=True, rename_context=(main.jobs, main.save_jobs, "test"))
        self.assertEqual(len(collisions), 1)
        self.assertEqual(len(calls), 1)  # Recovery rejects the occupied target before another move.
        self.assertEqual(collisions[0].read_bytes(), b"external " + kind.encode())
        self.assertEqual(source_asset.read_bytes(), source_bytes)
        actual = self.root / outcome["path"]
        self.assertFalse(path.exists())
        self.assertTrue(actual.is_file())
        self.assertEqual(outcome["status"], "partial")
        self._rename_record("pending")
        self._assert_core()
        main.recover_filename_changes()
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
        self.assertEqual(collisions[0].read_bytes(), b"external " + kind.encode())
        self.assertEqual(source_asset.read_bytes(), source_bytes)
        collisions[0].unlink()
        self._recover()
        self._rename_record("complete")
        self._assert_jobs(actual.name, actual.name)
        self._assert_backup(actual)
        self._restore(actual)

    def test_late_sidecar_collision_preserved_and_recovers_forward(self):
        self._late_asset_collision("sidecar")

    def test_late_lrc_collision_preserved_and_recovers_forward(self):
        self._late_asset_collision("lrc")

    def test_late_lrc_without_source_lrc_blocks_completion(self):
        path = self._prepare()
        no_replace = ren.no_replace
        collisions = []

        def collide(source, target):
            if Path(source) == path:
                lrc = Path(target).with_suffix(".lrc")
                lrc.write_bytes(b"unrelated LRC")
                collisions.append(lrc)
            return no_replace(source, target)

        with patch.object(ren, "no_replace", side_effect=collide):
            outcome = self._save(path, rename=True)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].read_bytes(), b"unrelated LRC")
        self.assertEqual(outcome["status"], "partial")
        self._rename_record("pending")
        self._assert_backup(self.root / outcome["path"])
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
        collisions[0].unlink()
        self._recover()
        self._restore(self.root / outcome["path"])

    def test_music_move_failure_aborts_and_retry_uses_same_target(self):
        path = self._prepare()
        no_replace = ren.no_replace
        calls = []

        def fail(source, target):
            if Path(source) == path:
                calls.append(Path(target))
                raise OSError("injected automatic music move")
            return no_replace(source, target)

        with patch.object(ren, "no_replace", side_effect=fail):
            outcome = self._save(path, rename=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome["status"], "partial")
        self._rename_record("aborted")
        self.assertEqual(list(self.backups.glob("*/alias-*.json")), [])
        ren.check_ready(self.data)
        retry = self._save(path, rename=True)
        self.assertEqual(retry["status"], "saved")
        self.assertEqual(self.root / retry["path"], calls[0])
        self.assertEqual([r["status"] for _, r in ren.records(self.data)], ["aborted", "complete"])
        self._restore(calls[0])

    def test_unsupported_no_replace_never_falls_back_to_legacy_writer(self):
        path = self._prepare()
        with patch.object(ren, "no_replace", side_effect=storage.StorageError("unsupported")) as move, \
                patch.object(tags, "rename_file") as legacy:
            outcome = self._save(path, rename=True)
        self.assertEqual(move.call_count, 1)
        legacy.assert_not_called()
        self.assertEqual(outcome["status"], "partial")
        self.assertTrue(path.is_file())
        self._rename_record("aborted")
        self._assert_backup(path)

    def test_journal_publication_failure_blocks_next_write(self):
        path = self._prepare()
        write_record = ren.write_record
        calls = []

        def fail_after_publish(target, record, first=False):
            write_record(target, record, first)
            if first:
                calls.append(target)
                raise OSError("injected pending journal sync failure")

        with patch.object(ren, "write_record", side_effect=fail_after_publish), \
                patch.object(ren, "no_replace") as move:
            outcome = self._save(path, rename=True)
        self.assertEqual(len(calls), 1)
        move.assert_not_called()
        self.assertEqual(outcome["status"], "partial")
        self._rename_record("pending")
        before = path.read_bytes()
        with self.assertRaises(storage.StorageError):
            self._save(path, title="Must not write")
        self.assertEqual(path.read_bytes(), before)
        self._recover()
        self._rename_record("aborted")
        self._restore(path)

    def test_source_identity_changed_after_journal_never_moves_replacement(self):
        path = self._prepare()
        write_record = ren.write_record
        injected = []

        def replace_source(target, record, first=False):
            write_record(target, record, first)
            if first:
                replacement = self.copy("external.mp3")
                storage.os.replace(replacement, path)
                injected.append(path.read_bytes())

        with patch.object(ren, "write_record", side_effect=replace_source), patch.object(ren, "no_replace") as move:
            with self.assertRaisesRegex(storage.StorageError, "상태를 확인"):
                self._save(path, rename=True)
        self.assertEqual(len(injected), 1)
        move.assert_not_called()
        self.assertEqual(path.read_bytes(), injected[0])
        self._rename_record("pending")
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)

    def test_pending_on_disk_blocks_direct_save_even_if_memory_flag_lost(self):
        path = self._prepare()
        with patch.object(ren, "finish", side_effect=OSError("injected persistent finish")) as finish:
            outcome = self._save(path, rename=True)
        self.assertEqual(finish.call_count, 2)
        actual = self.root / outcome["path"]
        self.assertTrue(actual.is_file())
        self._rename_record("pending")
        ren.blocked.clear()
        with patch.object(storage, "_save_locked") as save:
            with self.assertRaises(storage.StorageError):
                self._save(actual)
        save.assert_not_called()
        self._recover()
        self._assert_backup(actual)
        self._restore(actual)

    def test_corrupt_rename_journals_block_recovery_without_mutation(self):
        path = self._prepare()
        result = self._save(path, rename=True)
        actual = self.root / result["path"]
        journal, valid = self._rename_record("complete")
        variants = [b"{bad", b"[]"]
        for key, value in (("status", "unknown"), ("old_path", "../outside.mp3"),
                           ("revision", "bad"), ("identity", [1]), ("root", str(self.root.parent)),
                           ("new_path", valid["old_path"]), ("backup_id", None)):
            bad = {**valid, key: value, "status": "pending" if key != "status" else value}
            variants.append(storage._json_bytes(bad))
        missing = dict(valid)
        del missing["side_sha"]
        variants.append(storage._json_bytes(missing))
        before = actual.read_bytes()
        for raw in variants:
            with self.subTest(raw=raw[:80]):
                journal.write_bytes(raw)
                ren.blocked.clear()
                with patch.object(ren, "no_replace") as move, patch.object(storage, "_replace_file") as write:
                    main.recover_filename_changes()
                move.assert_not_called()
                write.assert_not_called()
                with self.assertRaises(storage.StorageError):
                    self._save(actual)
                self.assertEqual(actual.read_bytes(), before)
                self.assertEqual(journal.read_bytes(), raw)
                self._assert_core()
        journal.write_bytes(storage._json_bytes(valid))
        self._recover()

    def test_corrupt_lrc_journals_block_recovery_without_mutation(self):
        path = self._prepare()
        self._save(path, lrc=self.timed)
        journal = next((self.data / "lyric-assets").glob("*.json"))
        valid = json.loads(journal.read_bytes())
        variants = [b"{bad", b"null"]
        for key, value in (("status", "unknown"), ("music", "../outside.mp3"), ("lrc", "wrong.lrc"),
                           ("after", "bad"), ("text", None), ("root", str(self.root.parent))):
            variants.append(storage._json_bytes({**valid, key: value}))
        before = path.read_bytes(), path.with_suffix(".lrc").read_bytes()
        for raw in variants:
            with self.subTest(raw=raw[:80]):
                journal.write_bytes(raw)
                ren.blocked.clear()
                with patch.object(lyric_assets, "finish") as finish, patch.object(ren, "no_replace") as move:
                    main.recover_filename_changes()
                finish.assert_not_called()
                move.assert_not_called()
                with self.assertRaises(storage.StorageError):
                    self._save(path)
                self.assertEqual((path.read_bytes(), path.with_suffix(".lrc").read_bytes()), before)
                self.assertEqual(journal.read_bytes(), raw)
        journal.write_bytes(storage._json_bytes(valid))
        self._recover()

    def test_bad_lrc_record_prevents_valid_pending_rename_from_moving_assets(self):
        path = self._prepare()
        with patch.object(ren, "finish", side_effect=OSError("injected pending")):
            outcome = self._save(path, rename=True)
        old_side = Path(tags.backup_path(str(path)))
        side_bytes = old_side.read_bytes()
        folder = self.data / "lyric-assets"
        folder.mkdir()
        (folder / "bad.json").write_bytes(b"{bad")
        with patch.object(ren, "no_replace") as move:
            main.recover_filename_changes()
        move.assert_not_called()
        self.assertEqual(old_side.read_bytes(), side_bytes)
        self.assertTrue((self.root / outcome["path"]).is_file())
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)

    def test_batch_checks_block_before_each_song(self):
        first, second = self.copy("first.mp3"), self.copy("second.mp3")
        before = second.read_bytes()
        rows = self.job([first, second])
        main.save_jobs()
        request = main.SaveRequest(**self.request([self.item(row) for row in rows], rename=True))
        no_replace = ren.no_replace
        collisions = []

        def collide(source, target):
            if Path(source) == Path(tags.backup_path(str(first))):
                Path(target).write_bytes(b"external backup")
                collisions.append(Path(target))
            return no_replace(source, target)

        with patch.object(ren, "no_replace", side_effect=collide), patch.object(main, "save_one", wraps=main.save_one) as save:
            outcome = main.save_job("test", request)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].read_bytes(), b"external backup")
        self.assertEqual((outcome["saved"], outcome["partial"], outcome["failed"]), (1, 1, 1))
        self.assertEqual(second.read_bytes(), before)
        self.assertFalse(Path(tags.backup_path(str(second))).exists())
        self._rename_record("pending")

    def test_queued_save_rechecks_block_after_acquiring_lock(self):
        path = self._prepare()
        row = main.jobs["test"]["results"][0]
        request = main.SaveRequest(**self.request([self.item(row)]))
        entered = threading.Event()
        perform = main.perform_save_job
        outcomes = []

        def waiting(*args):
            entered.set()
            return perform(*args)

        def run():
            try:
                outcomes.append(main.save_job("test", request))
            except Exception as exc:
                outcomes.append(exc)

        before = path.read_bytes()
        with patch.object(main, "perform_save_job", side_effect=waiting), patch.object(main, "save_one") as save:
            with storage.OPERATION_LOCK:
                thread = threading.Thread(target=run)
                thread.start()
                self.assertTrue(entered.wait(3))
                ren.blocked[str(self.data.resolve())] = "earlier request requires recovery"
            thread.join(5)
        self.assertFalse(thread.is_alive())
        save.assert_not_called()
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], HTTPException)
        self.assertEqual(outcomes[0].status_code, 409)
        self.assertEqual(path.read_bytes(), before)

    def test_api_context_updates_related_job_paths_and_preserves_backup_id(self):
        path = self._prepare()
        main.jobs["related"] = copy.deepcopy(main.jobs["test"])
        main.jobs["related"]["id"] = "related"
        main.jobs["related"]["options"] = {"paths": [path.name]}
        old_folder, _ = storage._verify_backup(path, self.root, self.backups)
        row = main.jobs["test"]["results"][0]
        outcome = main.save_job("test", main.SaveRequest(**self.request([self.item(row)], rename=True)))
        self.assertEqual(outcome["saved"], 1)
        relative = outcome["results"][0]["path"]
        self.assertEqual(main.jobs["related"]["results"][0]["path"], relative)
        self.assertEqual(main.jobs["related"]["options"]["paths"], [relative])
        record = self._rename_record("complete")[1]
        self.assertEqual(record["old_path"], path.name)
        self.assertEqual(record["backup_id"], old_folder.name)
        self._assert_jobs(relative, relative)
        self._restore(self.root / relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
