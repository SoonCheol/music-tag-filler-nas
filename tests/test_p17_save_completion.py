"""#019: generated temporary music only; committed saves survive ancillary errors."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_p0_storage as p0
import test_p13_storage_failures as p13
from app import main, storage, rename_service as ren, lyric_assets, job_store
from app.upstream import tags


class SaveCompletionTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p13.RecoveryBoundaryTests.setUp
    tearDown = p13.RecoveryBoundaryTests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    _prepare = p13.RecoveryBoundaryTests._prepare
    _save = p13.RecoveryBoundaryTests._save
    _recover = p13.RecoveryBoundaryTests._recover
    timed = p13.RecoveryBoundaryTests.timed

    def _request(self, path, **kwargs):
        row = main.jobs['test']['results'][0]
        return main.SaveRequest(**self.request([self.item(row)], save_lyrics=False, **kwargs))

    def test_rename_only_music_move_failure_is_failed(self):
        path = self._prepare()
        before = path.read_bytes()
        with patch.object(ren, 'no_replace', side_effect=OSError('injected rename-only move')):
            outcome = storage.save(path, self.root, self.backups, {}, [], False,
                                   storage.revision(path), rename=True, asset_root=self.data)
        self.assertEqual(outcome['status'], 'failed')
        self.assertFalse(outcome['music_saved'])
        self.assertEqual(path.read_bytes(), before)

    def test_replace_raises_after_publishing_verified_music(self):
        path = self._prepare()
        replace = storage.os.replace
        def fail(source, target):
            replace(source, target)
            if Path(source).name.startswith('.tagtxn-'):
                raise OSError('injected after music publication')
        with patch.object(storage.os, 'replace', side_effect=fail):
            outcome = self._save(path)
        self.assertEqual(outcome['status'], 'partial')
        self.assertTrue(outcome['music_saved'])
        self.assertEqual(tags.read_file(str(path)).tags.title, 'Committed')

    def test_replace_fails_before_publication_preserves_music(self):
        path = self._prepare()
        before = path.read_bytes()
        replace = storage.os.replace
        def fail(source, target):
            if Path(source).name.startswith('.tagtxn-'):
                raise OSError('injected before music publication')
            return replace(source, target)
        with patch.object(storage.os, 'replace', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'before music publication'):
                self._save(path)
        self.assertEqual(path.read_bytes(), before)

    def test_post_commit_description_error_is_partial(self):
        path = self._prepare()
        with patch.object(storage, 'describe', side_effect=OSError('injected description')):
            outcome = self._save(path)
        self.assertEqual(outcome['status'], 'partial')
        self.assertTrue(outcome['music_saved'])
        self.assertNotIn('original', outcome)
        self.assertIn('injected description', outcome['warning'])
        self.assertEqual(tags.read_file(str(path)).tags.title, 'Committed')

    def test_actual_write_failure_is_failed_and_preserves_bytes(self):
        path = self._prepare()
        before = path.read_bytes()
        request = self._request(path)
        with patch.object(tags, 'write_file', side_effect=OSError('injected music write')):
            response = main.save_job('test', request)
        self.assertEqual((response['saved'], response['failed']), (0, 1))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(main.jobs['test']['results'][0]['last_save']['status'], 'failed')

    def test_job_result_error_keeps_saved_outcome(self):
        path = self._prepare()
        request = self._request(path)
        state = main.file_state
        def fail(row):
            if row.get('stored_saved'):
                raise ValueError('injected row response')
            return state(row)
        with patch.object(main, 'file_state', side_effect=fail):
            response = main.save_job('test', request)
        self.assertEqual((response['saved'], response['failed'], response['partial']), (1, 0, 1))
        self.assertTrue(main.jobs['test']['results'][0]['stored_saved'])
        self.assertIn('injected row response', response['results'][0]['warning'])

    def test_lyrics_response_error_keeps_saved_outcome(self):
        path = self._prepare()
        row = main.jobs['test']['results'][0]
        request = self._request(path)
        request.save_lyrics = True
        request.items[0].lyrics_id = 'test-token'
        choice = {'status': 'found', 'lyrics': 'generated lyrics', 'synced': None}
        with patch.object(main, 'selected_lyrics', return_value=choice), patch.object(main, 'lyric_response', side_effect=ValueError('injected lyrics response')):
            response = main.save_job('test', request)
        self.assertEqual((response['saved'], response['failed'], response['partial']), (1, 0, 1))
        self.assertIn('injected lyrics response', response['results'][0]['warning'])

    def test_final_response_error_uses_confirmed_file_outcomes(self):
        path = self._prepare()
        request = self._request(path)
        perform = main.perform_save_job
        def fail(*args):
            perform(*args)
            raise ValueError('injected final response')
        with patch.object(main, 'perform_save_job', side_effect=fail):
            response = main.save_job('test', request)
        self.assertEqual((response['saved'], response['failed']), (1, 0))
        self.assertEqual(response['status'], 'partial')
        self.assertEqual(response['results'][0]['status'], 'saved')
        self.assertEqual(main.save_tasks[response['save_task_id']]['status'], 'done')
        self.assertIn('injected final response', response['state_error'])

    def test_state_persist_error_does_not_change_music_result(self):
        path = self._prepare()
        request = self._request(path)
        with patch.object(main, 'save_jobs', side_effect=ValueError('injected job serialization')):
            response = main.save_job('test', request)
        self.assertEqual((response['saved'], response['failed']), (1, 0))
        self.assertIn('injected job serialization', response['state_error'])

    def test_lrc_failure_restart_recovers_only_asset(self):
        path = self._prepare()
        with patch.object(lyric_assets, 'finish', side_effect=OSError('injected LRC finish')):
            outcome = self._save(path, lrc=self.timed)
        self.assertEqual(outcome['status'], 'partial')
        journal = next((self.data / 'lyric-assets').glob('*.json'))
        record = json.loads(journal.read_bytes())
        self.assertEqual(record['status'], 'pending')
        self.assertIn('injected LRC finish', record['error'])
        snapshot = path.read_bytes(), path.stat().st_mtime_ns
        main.jobs.clear()
        main.jobs.update(job_store.load(self.data))
        ren.blocked.clear()
        with patch.object(tags, 'write_file') as write, patch.object(ren, 'no_replace') as move:
            self._recover()
            self._recover()
        write.assert_not_called()
        move.assert_not_called()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshot)
        self.assertEqual(json.loads(journal.read_bytes())['status'], 'complete')
        self.assertEqual(self._save(path, lrc=self.timed)['status'], 'skipped')

    def test_lrc_recovery_failure_keeps_pending_and_foreign_file(self):
        path = self._prepare()
        with patch.object(lyric_assets, 'finish', side_effect=OSError('injected LRC finish')):
            self._save(path, lrc=self.timed)
        foreign = path.with_suffix('.lrc')
        foreign.write_bytes(b'foreign lyrics')
        snapshot = path.read_bytes()
        main.recover_filename_changes()
        journal = next((self.data / 'lyric-assets').glob('*.json'))
        self.assertEqual(json.loads(journal.read_bytes())['status'], 'pending')
        self.assertEqual(foreign.read_bytes(), b'foreign lyrics')
        self.assertEqual(path.read_bytes(), snapshot)
        with self.assertRaises(storage.StorageError):
            ren.check_ready(self.data)

    def test_save_jobs_failure_restart_keeps_original_filename(self):
        path = self._prepare()
        request = self._request(path, rename=True)
        with patch.object(main, 'save_jobs', side_effect=OSError('injected path persistence')):
            response = main.save_job('test', request)
        self.assertEqual((response['saved'], response['failed'], response['partial']), (1, 0, 0))
        outcome = response['results'][0]
        actual = self.root / outcome['path']
        self.assertTrue(path.exists())
        self.assertEqual(actual, path)
        self.assertTrue(actual.is_file())
        self.assertFalse(outcome.get('recovery_pending', False))
        snapshot = actual.read_bytes(), actual.stat().st_mtime_ns
        main.jobs.clear()
        main.jobs.update(job_store.load(self.data))
        ren.blocked.clear()
        with patch.object(tags, 'write_file') as write, patch.object(ren, 'no_replace') as move:
            self._recover()
            self._recover()
        write.assert_not_called()
        move.assert_not_called()
        self.assertEqual((actual.read_bytes(), actual.stat().st_mtime_ns), snapshot)
        self.assertEqual(main.jobs['test']['results'][0]['path'], actual.name)

    def test_stop_after_music_commit_restarts_from_lrc_journal(self):
        path = self._prepare()
        with patch.object(lyric_assets, 'finish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self._save(path, lrc=self.timed)
        snapshot = path.read_bytes(), path.stat().st_mtime_ns
        main.jobs.clear()
        main.jobs.update(job_store.load(self.data))
        ren.blocked.clear()
        with patch.object(tags, 'write_file') as write:
            self._recover()
        write.assert_not_called()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshot)
        self.assertEqual(path.with_suffix('.lrc').read_bytes(), lyric_assets.payload(self.timed))
        row = main.jobs['test']['results'][0]
        self.assertTrue(row['stored_saved'])
        self.assertEqual(row['last_save']['status'], 'saved')
        self.assertEqual(main.jobs['test']['save_status'], 'saved')
        self.assertEqual(main.jobs['test']['saved_count'], 1)
        self.assertEqual(row['original']['revision'], storage.revision(path))


if __name__ == '__main__':
    unittest.main()
