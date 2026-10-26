"""#017: generated audio only; alias and journaled asset replay safety."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_p0_storage as p0
import test_p13_storage_failures as p13
from app import main, storage, rename_service as ren
from app.upstream import tags


class AliasSidecarTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p13.RecoveryBoundaryTests.setUp
    tearDown = p13.RecoveryBoundaryTests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    timed = p13.RecoveryBoundaryTests.timed
    _save = p13.RecoveryBoundaryTests._save
    _prepare = p13.RecoveryBoundaryTests._prepare
    _assert_core = p13.RecoveryBoundaryTests._assert_core
    _assert_backup = p13.RecoveryBoundaryTests._assert_backup
    _assert_jobs = p13.RecoveryBoundaryTests._assert_jobs
    _rename_record = p13.RecoveryBoundaryTests._rename_record
    _recover = p13.RecoveryBoundaryTests._recover
    _restore = p13.RecoveryBoundaryTests._restore

    def _pending(self, lrc=False):
        old = self._prepare(lrc=lrc)
        with patch.object(ren, 'finish', side_effect=OSError('injected stop before assets')) as finish:
            outcome = self._save(old, rename=True)
        self.assertEqual(finish.call_count, 2)
        self.assertEqual(outcome['status'], 'partial')
        journal, record = self._rename_record('pending')
        return old, self.root / outcome['path'], journal, record

    def _alias(self, record):
        folder = self.backups / record['backup_id']
        relative = record['new_path']
        value = {'path': relative, 'checksum': storage.digest((relative + folder.name + record['tags_sha']).encode())}
        return folder, folder / ('alias-' + storage.digest(relative.encode()) + '.json'), value

    def test_equivalent_alias_reused_without_rewriting(self):
        old, new, journal, record = self._pending()
        folder, alias, value = self._alias(record)
        raw = json.dumps(value, indent=2).encode()
        alias.write_bytes(raw)
        stamp = alias.stat().st_mtime_ns
        with patch.object(storage, '_new_file', wraps=storage._new_file) as publish:
            self.assertFalse(ren.ensure_alias(folder, record['new_path'], record['tags_sha']))
            self.assertFalse(ren.ensure_alias(folder, record['new_path'], record['tags_sha']))
        publish.assert_not_called()
        self._recover()
        self._recover()
        self.assertEqual((alias.read_bytes(), alias.stat().st_mtime_ns), (raw, stamp))
        self.assertEqual(len(list(folder.glob('alias-*.json'))), 1)
        self._restore(new)

    def test_new_alias_is_distinguished_and_other_alias_preserved(self):
        folder = self.data / 'aliases'
        folder.mkdir()
        sha = 'a' * 64
        self.assertTrue(ren.ensure_alias(folder, 'first.mp3', sha))
        first = next(folder.glob('alias-*.json'))
        before = first.read_bytes(), first.stat().st_mtime_ns
        self.assertTrue(ren.ensure_alias(folder, 'second.mp3', sha))
        self.assertFalse(ren.ensure_alias(folder, 'second.mp3', sha))
        self.assertEqual(len(list(folder.glob('alias-*.json'))), 2)
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), before)

    def test_alias_publication_race_validates_existing_data(self):
        for valid in (True, False):
            with self.subTest(valid=valid):
                folder = self.data / ('race-' + str(valid))
                folder.mkdir()
                relative, sha = 'new.mp3', 'a' * 64
                expected = {'path': relative, 'checksum': storage.digest((relative + folder.name + sha).encode())}
                winner = storage._json_bytes(expected if valid else {'path': 'other.mp3'})
                publish = storage._new_file
                calls = []

                def race(path, data):
                    calls.append(path)
                    publish(path, winner)
                    return publish(path, data)

                with patch.object(storage, '_new_file', side_effect=race):
                    if valid:
                        self.assertFalse(ren.ensure_alias(folder, relative, sha))
                    else:
                        with self.assertRaises(storage.StorageError):
                            ren.ensure_alias(folder, relative, sha)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].read_bytes(), winner)

    def test_alias_sync_failure_retries_sync_without_duplicate_publication(self):
        old, new, journal, record = self._pending(lrc=True)
        folder, alias, value = self._alias(record)
        sync = ren.sync_dir
        hits = []

        def fail(path):
            if Path(path) == folder:
                hits.append(path)
                raise OSError('injected alias directory sync')
            return sync(path)

        with patch.object(ren, 'sync_dir', side_effect=fail):
            main.recover_filename_changes()
        self.assertEqual(len(hits), 1)
        self._rename_record('pending')
        before = alias.read_bytes(), alias.stat().st_mtime_ns
        with patch.object(storage, '_new_file', wraps=storage._new_file) as publish, \
                patch.object(ren, 'sync_dir', wraps=sync) as synced:
            self._recover()
        publish.assert_not_called()
        self.assertIn(unittest.mock.call(folder), synced.call_args_list)
        self.assertEqual((alias.read_bytes(), alias.stat().st_mtime_ns), before)
        self._restore(new)

    def test_alias_conflict_preserved_until_explicitly_removed(self):
        old, new, journal, record = self._pending()
        folder, alias, value = self._alias(record)
        alias.write_bytes(b'{"path":"external"}')
        for _ in range(2):
            main.recover_filename_changes()
            self._rename_record('pending')
            self.assertEqual(alias.read_bytes(), b'{"path":"external"}')
            with self.assertRaises(storage.StorageError):
                ren.check_ready(self.data)
        alias.unlink()  # Generated conflict only; never remove an operational alias.
        self._recover()
        self._restore(new)

    def test_sidecar_move_completed_before_error_is_not_moved_twice(self):
        old, new, journal, record = self._pending(lrc=True)
        side = Path(tags.backup_path(str(old)))
        move = ren.no_replace
        calls = []

        def moved_then_error(source, target):
            result = move(source, target)
            if Path(source) == side:
                calls.append((source, target))
                raise OSError('injected after sidecar move')
            return result

        with patch.object(ren, 'no_replace', side_effect=moved_then_error):
            main.recover_filename_changes()
        self.assertEqual(len(calls), 1)
        self._rename_record('pending')
        self._recover()
        snapshot = journal.read_bytes(), Path(tags.backup_path(str(new))).read_bytes()
        with patch.object(ren, 'no_replace') as again:
            self._recover()
        again.assert_not_called()
        self.assertEqual((journal.read_bytes(), Path(tags.backup_path(str(new))).read_bytes()), snapshot)
        self._restore(new)

    def _replacement_asset(self, kind):
        old, new, journal, record = self._pending(lrc=True)
        asset = Path(tags.backup_path(str(old))) if kind == 'sidecar' else old.with_suffix('.lrc')
        original = asset.with_name(asset.name + '.held')
        asset.rename(original)  # Keep the original inode alive.
        asset.write_bytes(original.read_bytes())
        with patch.object(ren, 'no_replace', wraps=ren.no_replace) as move:
            main.recover_filename_changes()
        self.assertFalse(any(Path(c.args[0]) == asset for c in move.call_args_list))
        self._rename_record('pending')
        self.assertTrue(asset.is_file())
        asset.unlink()
        original.rename(asset)
        self._recover()
        self._restore(new)

    def test_same_bytes_replacement_sidecar_is_not_adopted(self):
        self._replacement_asset('sidecar')

    def test_same_bytes_replacement_lrc_is_not_adopted(self):
        self._replacement_asset('lrc')

    def test_same_bytes_replacement_at_new_sidecar_blocks_recovery(self):
        old, new, journal, record = self._pending()
        side = Path(tags.backup_path(str(old)))
        target = Path(tags.backup_path(str(new)))
        ren.no_replace(side, target)
        held = target.with_name(target.name + '.held')
        target.rename(held)
        target.write_bytes(held.read_bytes())
        main.recover_filename_changes()
        self._rename_record('pending')
        self.assertTrue(held.is_file())
        target.unlink()
        held.rename(target)
        self._recover()
        self._restore(new)

    def test_recovery_rechecks_folded_asset_collision(self):
        old, new, journal, record = self._pending()
        conflict = Path(tags.backup_path(str(new))).with_name(Path(tags.backup_path(str(new))).name.upper())
        conflict.write_bytes(b'external')
        with patch.object(ren, 'no_replace') as move:
            main.recover_filename_changes()
        move.assert_not_called()
        self.assertEqual(conflict.read_bytes(), b'external')
        self._rename_record('pending')
        conflict.unlink()
        self._recover()
        self._restore(new)

    def test_old_journal_without_asset_identities_still_recovers(self):
        old, new, journal, record = self._pending(lrc=True)
        del record['side_identity'], record['lrc_identity']
        journal.write_bytes(storage._json_bytes(record))
        self._recover()
        self._restore(new)

    def test_malformed_asset_identity_blocks_all_moves(self):
        old, new, journal, record = self._pending()
        bad = {**record, 'side_identity': [1]}
        journal.write_bytes(storage._json_bytes(bad))
        with patch.object(ren, 'no_replace') as move:
            main.recover_filename_changes()
        move.assert_not_called()
        self.assertEqual(journal.read_bytes(), storage._json_bytes(bad))
        journal.write_bytes(storage._json_bytes(record))
        self._recover()
        self._restore(new)
