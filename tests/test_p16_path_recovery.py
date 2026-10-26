"""#018 generated audio only: persisted paths and LRC recovery after rename."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_p0_storage as p0
import test_p13_storage_failures as p13
from app import main, storage, rename_service as ren, lyric_assets, job_store, job_service


class PathRecoveryTests(unittest.TestCase):
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

    def _reload(self):
        main.jobs.clear()
        main.jobs.update(job_store.load(self.data))
        ren.blocked.clear()

    def _stale(self, snapshot):
        for key, value in snapshot.items():
            storage._replace_file(self.data / 'jobs' / (key + '.json'), storage._json_bytes(value))
        self._reload()

    def test_completed_journal_repairs_stale_json_and_is_idempotent(self):
        old = self._prepare()
        job = main.jobs['test']
        job.update(sub_path=old.name, current_file=old.name, current_path=str(old), missing_paths=[old.name])
        job['options'] = {'paths': [old.name], 'sub_path': old.name}
        job['results'][0]['last_save'] = {'path': old.name, 'request_path': old.name, 'status': 'saved'}
        snapshot = copy.deepcopy(main.jobs)
        new = self.root / self._save(old, rename=True, rename_context=(main.jobs, main.save_jobs, 'test'))['path']
        self._stale(snapshot)
        with patch.object(ren, 'no_replace') as move:
            self._recover()
        move.assert_not_called()
        job = main.jobs['test']
        self.assertEqual(job['sub_path'], new.name)
        self.assertEqual(job['current_file'], new.name)
        self.assertEqual(job['current_path'], str(new))
        self.assertEqual(job['missing_paths'], [new.name])
        self.assertEqual(job['options'], {'paths': [new.name], 'sub_path': new.name})
        self.assertEqual(job['results'][0]['last_save']['path'], new.name)
        self.assertEqual(job['results'][0]['last_save']['request_path'], old.name)  # Historical request.
        self._assert_jobs(new.name, new.name)
        disk = self.data / 'jobs/test.json'
        stamp = disk.read_bytes(), disk.stat().st_mtime_ns
        self._reload()
        self._recover()
        self.assertEqual((disk.read_bytes(), disk.stat().st_mtime_ns), stamp)
        self._restore(new)

    def test_chained_rename_restart_resume_retains_completed_scan(self):
        old = self._prepare()
        main.jobs['test']['options'] = {'paths': [old.name]}
        snapshot = copy.deepcopy(main.jobs)
        row = main.jobs['test']['results'][0]
        with storage.OPERATION_LOCK:
            first = ren.rename(self.root, self.data, self.backups, main.jobs, main.save_jobs,
                               'test', old.name, 'middle', row['original']['revision'])
            ren.rename(self.root, self.data, self.backups, main.jobs, main.save_jobs,
                       'test', first['new_path'], 'final', row['original']['revision'])
        self._stale(snapshot)
        self._recover()
        final = self.root / 'final.mp3'
        main.jobs['test']['status'] = 'interrupted'
        with patch.object(main.search_service, 'search') as search:
            main.scan_job('test', '', main.jobs['test']['options'], resume=True)
        search.assert_not_called()
        self.assertEqual(main.jobs['test']['status'], 'done')
        self.assertEqual(main.jobs['test']['scanned'], 1)
        self._assert_jobs(final.name, final.name)
        self._restore(final)

    def test_reconciliation_write_failure_replays_remaining_job(self):
        old = self._prepare()
        main.jobs['related'] = copy.deepcopy(main.jobs['test'])
        main.jobs['related']['id'] = 'related'
        main.save_jobs()
        snapshot = copy.deepcopy(main.jobs)
        new = self.root / self._save(old, rename=True, rename_context=(main.jobs, main.save_jobs, 'test'))['path']
        self._stale(snapshot)
        write = storage._replace_file
        hits = []

        def fail(path, data):
            if Path(path) == self.data / 'jobs/test.json':
                hits.append(path)
                raise OSError('injected reconciliation JSON failure')
            return write(path, data)

        with patch.object(storage, '_replace_file', side_effect=fail):
            main.recover_filename_changes()
        self.assertEqual(len(hits), 1)
        self.assertEqual(json.loads((self.data / 'jobs/related.json').read_bytes())['results'][0]['path'], new.name)
        self.assertEqual(json.loads((self.data / 'jobs/test.json').read_bytes())['results'][0]['path'], old.name)
        self.assertIn(str(self.data.resolve()), ren.blocked)
        self._reload()
        self._recover()
        self._assert_jobs(new.name, new.name)
        self._restore(new)

    def test_completed_journal_rejects_replaced_destination(self):
        old = self._prepare()
        snapshot = copy.deepcopy(main.jobs)
        new = self.root / self._save(old, rename=True)['path']
        held = new.with_suffix('.held')
        new.rename(held)
        new.write_bytes(held.read_bytes())
        self._stale(snapshot)
        disk = (self.data / 'jobs/test.json').read_bytes()
        with patch.object(ren, 'no_replace') as move:
            main.recover_filename_changes()
        move.assert_not_called()
        self.assertEqual((self.data / 'jobs/test.json').read_bytes(), disk)
        self.assertEqual(new.read_bytes(), held.read_bytes())
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
        new.unlink()
        held.rename(new)
        self._recover()
        self._restore(new)

    def _old_pending_lrc(self):
        old = self._prepare()
        self._save(old, lrc=self.timed)
        journal = next((self.data / 'lyric-assets').glob('*.json'))
        record = json.loads(journal.read_bytes())
        new = self.root / self._save(old, rename=True, rename_context=(main.jobs, main.save_jobs, 'test'))['path']
        record['status'] = 'pending'  # Recreate a durable old-path record from an interrupted older flow.
        journal.write_bytes(storage._json_bytes(record))
        return old, new, journal

    def test_lrc_pending_old_path_rebases_without_duplicate_publication(self):
        old, new, journal = self._old_pending_lrc()
        lrc = new.with_suffix('.lrc')
        before = new.read_bytes(), lrc.read_bytes(), lrc.stat().st_mtime_ns
        self._reload()
        with patch.object(storage, '_new_file', wraps=storage._new_file) as publish, patch.object(ren, 'no_replace') as move:
            self._recover()
            self._recover()
        publish.assert_not_called()
        move.assert_not_called()
        record = json.loads(journal.read_bytes())
        self.assertEqual((record['music'], record['lrc'], record['status']), (new.name, lrc.name, 'complete'))
        self.assertEqual((new.read_bytes(), lrc.read_bytes(), lrc.stat().st_mtime_ns), before)
        self._assert_jobs(new.name, new.name)
        self._restore(new)

    def test_lrc_conflict_after_rename_records_error_and_recovers_forward(self):
        old, new, journal = self._old_pending_lrc()
        lrc = new.with_suffix('.lrc')
        original_lrc = lrc.read_bytes()
        lrc.write_bytes(b'external LRC')
        music = new.read_bytes()
        main.recover_filename_changes()
        record = json.loads(journal.read_bytes())
        self.assertEqual((record['music'], record['status']), (new.name, 'pending'))
        self.assertIn('LRC', record['error'])
        self.assertEqual(lrc.read_bytes(), b'external LRC')
        self.assertEqual(new.read_bytes(), music)
        self.assertFalse(old.exists())
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
        lrc.write_bytes(original_lrc)  # Restore only this generated conflict fixture.
        self._recover()
        self.assertNotIn('error', json.loads(journal.read_bytes()))
        self.assertEqual(new.read_bytes(), music)
        self._restore(new)

    def test_lrc_write_failure_after_rename_preserves_pending_and_music(self):
        old, new, journal = self._old_pending_lrc()
        lrc = new.with_suffix('.lrc')
        lrc.unlink()
        music = new.read_bytes()
        with patch.object(storage, '_new_file', side_effect=OSError('injected new LRC publication')) as publish:
            main.recover_filename_changes()
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(publish.call_args.args[0], lrc)
        record = json.loads(journal.read_bytes())
        self.assertEqual(record['status'], 'pending')
        self.assertIn('injected new LRC', record['error'])
        self.assertEqual(new.read_bytes(), music)
        self._reload()
        self._recover()
        self.assertEqual(lrc.read_bytes(), lyric_assets.payload(self.timed))
        self.assertEqual(new.read_bytes(), music)
        self._restore(new)

    def test_missing_lrc_music_without_journal_evidence_blocks(self):
        old = self._prepare()
        self._save(old, lrc=self.timed)
        journal = next((self.data / 'lyric-assets').glob('*.json'))
        record = json.loads(journal.read_bytes())
        record['status'] = 'pending'
        journal.write_bytes(storage._json_bytes(record))
        unknown = old.with_name('unknown.mp3')
        old.rename(unknown)
        before = unknown.read_bytes()
        with patch.object(ren, 'no_replace') as move:
            main.recover_filename_changes()
        move.assert_not_called()
        self.assertEqual(unknown.read_bytes(), before)
        self.assertFalse(old.exists())
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
        self.assertEqual(json.loads(journal.read_bytes())['music'], old.name)

    def test_path_outcome_without_original_is_persisted(self):
        old = self._prepare()
        row = main.jobs['test']['results'][0]
        request = main.SaveRequest(**self.request([self.item(row)], rename=True))
        save = main.save_one

        def without_original(*args):
            outcome = save(*args)
            outcome.pop('original', None)
            return outcome

        with patch.object(main, 'save_one', side_effect=without_original):
            outcome = main.save_job('test', request)
        new = self.root / outcome['results'][0]['path']
        self.assertFalse(old.exists())
        self.assertTrue(new.is_file())
        self._assert_jobs(new.name, new.name)
        self.assertEqual(row['abs_path'], str(new))
        self._restore(new)

    def test_lrc_move_error_is_durable_and_pending_path_recovers(self):
        old = self._prepare(lrc=True)
        lrc = old.with_suffix('.lrc')
        original_lrc = lrc.read_bytes()
        move = ren.no_replace
        hits = []

        def fail(source, target):
            if Path(source) == lrc:
                hits.append(target)
                raise OSError('injected LRC move failure')
            return move(source, target)

        with patch.object(ren, 'no_replace', side_effect=fail):
            outcome = self._save(old, rename=True, rename_context=(main.jobs, main.save_jobs, 'test'))
        self.assertEqual(len(hits), 2)
        new = self.root / outcome['path']
        journal, record = self._rename_record('pending')
        self.assertIn('injected LRC move', record['error'])
        self.assertEqual(lrc.read_bytes(), original_lrc)
        self.assertEqual(main.jobs['test']['results'][0]['path'], new.name)
        music = new.read_bytes()
        self._reload()
        self._recover()
        self._assert_jobs(new.name, new.name)
        self.assertEqual(new.read_bytes(), music)
        self.assertEqual(new.with_suffix('.lrc').read_bytes(), original_lrc)
        self.assertNotIn('error', json.loads(journal.read_bytes()))
        self._restore(new)

    def test_post_rename_describe_failure_reports_actual_path_and_restart_retry_is_noop(self):
        old = self._prepare()
        row = main.jobs['test']['results'][0]
        request = main.SaveRequest(**self.request([self.item(row)], rename=True))
        describe = storage.describe
        hits = []

        def fail(path):
            if Path(path) != old:
                hits.append(path)
                raise OSError('injected describe after rename')
            return describe(path)

        with patch.object(storage, 'describe', side_effect=fail):
            outcome = main.save_job('test', request)
        self.assertEqual(len(hits), 1)
        new = Path(hits[0])
        self.assertEqual(outcome['results'][0]['path'], new.name)
        self.assertEqual(outcome['results'][0]['request_path'], old.name)
        self._reload()
        self._recover()
        self._assert_jobs(new.name, new.name)
        current = main.jobs['test']['results'][0]
        with patch.object(ren, 'no_replace') as move:
            retry = main.save_job('test', main.SaveRequest(**self.request([self.item(current)], rename=True)))
        move.assert_not_called()
        self.assertEqual(retry['skipped'], 1)
        self._restore(new)

    def test_reconciliation_save_retry_in_same_process_persists_memory(self):
        old = self._prepare()
        snapshot = copy.deepcopy(main.jobs)
        new = self.root / self._save(old, rename=True)['path']
        self._stale(snapshot)
        with patch.object(main, 'save_jobs', side_effect=OSError('injected save failure')) as save:
            main.recover_filename_changes()
        save.assert_called_once()
        self._assert_jobs(new.name, old.name)
        self._recover()  # No reload: memory already contains the new path.
        self._assert_jobs(new.name, new.name)
        self._restore(new)

    def test_only_absolute_and_last_save_references_are_reconciled(self):
        old = self._prepare()
        new = self.root / self._save(old, rename=True, rename_context=(main.jobs, main.save_jobs, 'test'))['path']
        row = main.jobs['test']['results'][0]
        row.update(abs_path=str(old), last_save={'path': old.name})
        main.jobs['test']['current_path'] = str(old)
        main.save_jobs()
        self._reload()
        self._recover()
        self.assertEqual(main.jobs['test']['results'][0]['abs_path'], str(new))
        self.assertEqual(main.jobs['test']['results'][0]['last_save']['path'], new.name)
        self.assertEqual(main.jobs['test']['current_path'], str(new))
        self._restore(new)

    def test_lrc_relocation_revision_mismatch_keeps_original_association(self):
        old, new, journal = self._old_pending_lrc()
        record = json.loads(journal.read_bytes())
        record.update(before='a' * 64, after='b' * 64)
        journal.write_bytes(storage._json_bytes(record))
        music = new.read_bytes()
        main.recover_filename_changes()
        failed = json.loads(journal.read_bytes())
        self.assertEqual(failed['music'], old.name)
        self.assertEqual(failed['status'], 'pending')
        self.assertIn('error', failed)
        self.assertEqual(new.read_bytes(), music)
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)

    def test_lrc_reused_old_path_does_not_adopt_unrelated_file(self):
        old, new, journal = self._old_pending_lrc()
        old.write_bytes(new.read_bytes())
        before = old.read_bytes(), new.read_bytes()
        main.recover_filename_changes()
        failed = json.loads(journal.read_bytes())
        self.assertEqual((failed['music'], failed['status']), (old.name, 'pending'))
        self.assertIn('재사용', failed['error'])
        self.assertEqual((old.read_bytes(), new.read_bytes()), before)
        self.assertFalse(old.with_suffix('.lrc').exists())
        old.unlink()  # Only the generated unrelated occupant.
        self._recover()
        self._restore(new)

    def test_resume_endpoint_reconciles_completed_paths_before_scheduling(self):
        from fastapi import BackgroundTasks
        old = self._prepare()
        main.jobs['test']['options'] = {'paths': [old.name]}
        snapshot = copy.deepcopy(main.jobs)
        row = main.jobs['test']['results'][0]
        with storage.OPERATION_LOCK:
            ren.rename(self.root, self.data, self.backups, main.jobs, main.save_jobs,
                       'test', old.name, 'resumed', row['original']['revision'])
        self._stale(snapshot)
        main.jobs['test']['status'] = 'interrupted'
        tasks = BackgroundTasks()
        outcome = main.resume_job('test', tasks)
        self.assertEqual(outcome['status'], 'resumed')
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(tasks.tasks[0].args[2]['paths'], ['resumed.mp3'])
        with patch.object(main.search_service, 'search') as search:
            tasks.tasks[0].func(*tasks.tasks[0].args, **tasks.tasks[0].kwargs)
        search.assert_not_called()
        self._assert_jobs('resumed.mp3', 'resumed.mp3')
        self._restore(self.root / 'resumed.mp3')

    def test_ambiguous_completed_lineage_blocks_without_changing_jobs(self):
        old = self._prepare()
        snapshot = copy.deepcopy(main.jobs)
        new = self.root / self._save(old, rename=True)['path']
        journal, record = self._rename_record('complete')
        ambiguous = {**record, 'seq': record['seq'] + 1, 'id': 'f' * 32, 'new_path': 'other.mp3'}
        other = journal.parent / ('9999999999999999-' + ambiguous['id'] + '.json')
        other.write_bytes(storage._json_bytes(ambiguous))
        self._stale(snapshot)
        disk = (self.data / 'jobs/test.json').read_bytes()
        with patch.object(ren, 'no_replace') as move:
            main.recover_filename_changes()
        move.assert_not_called()
        self.assertEqual((self.data / 'jobs/test.json').read_bytes(), disk)
        self.assertFalse(old.exists())
        self.assertTrue(new.is_file())
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)
