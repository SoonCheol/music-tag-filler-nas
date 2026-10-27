"""#020: Linux durability and real SIGKILL recovery; generated audio only."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_p0_storage as p0
import test_p13_storage_failures as p13
from app import main, storage, rename_service as ren, job_store, lyric_assets
from app.upstream import tags


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux fsync/renameat2/SIGKILL')
class LinuxIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p13.RecoveryBoundaryTests.setUp
    tearDown = p13.RecoveryBoundaryTests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    _prepare = p13.RecoveryBoundaryTests._prepare
    _save = p13.RecoveryBoundaryTests._save
    timed = p13.RecoveryBoundaryTests.timed

    def test_backup_sync_failure_blocks_music_and_retry(self):
        path = self.copy()
        before = path.read_bytes()
        sync = storage._sync_dir
        hits = []
        def fail(folder):
            if Path(folder) == self.backups:
                hits.append(folder)
                raise OSError('injected backup directory sync')
            sync(folder)
        with patch.object(storage, '_sync_dir', side_effect=fail):
            for _ in range(2):
                with self.assertRaises((storage.StorageError, OSError)):
                    self._save(path)
                self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(hits), 2)
        self.assertEqual(self._save(path)['status'], 'saved')
        storage.restore(path, self.root, self.backups, storage.revision(path))
        self.assertEqual(path.read_bytes(), before)

    def test_existing_backup_sync_failure_still_blocks_save(self):
        path = self._prepare()
        with patch.object(storage, '_sync_dir', side_effect=OSError('injected existing backup sync')):
            with self.assertRaisesRegex(OSError, 'existing backup sync'):
                self._save(path)
        self.assertEqual(path.read_bytes(), self.original)

    def test_music_directory_sync_failure_reports_partial(self):
        path = self._prepare()
        sync = storage._sync_dir
        hits = []
        def fail(folder):
            if Path(folder) == path.parent and tags.read_file(str(path)).tags.title == 'Committed':
                hits.append(folder)
                raise OSError('injected music directory sync')
            sync(folder)
        with patch.object(storage, '_sync_dir', side_effect=fail):
            outcome = self._save(path)
        self.assertEqual(len(hits), 1)
        self.assertEqual(outcome['status'], 'partial')
        self.assertTrue(outcome['music_saved'])
        self.assertIn('injected music directory sync', outcome['warning'])
        storage.restore(path, self.root, self.backups, storage.revision(path))
        self.assertEqual(path.read_bytes(), self.original)

    def test_create_only_hardlink_and_noreplace_preserve_collision(self):
        first, occupied = self.root / 'first.json', self.root / 'occupied.json'
        storage._new_file(first, b'first')
        storage._new_file(occupied, b'foreign')
        with self.assertRaises(FileExistsError):
            storage._new_file(occupied, b'overwrite')
        with self.assertRaises(FileExistsError):
            ren.no_replace(first, occupied)
        self.assertEqual(first.read_bytes(), b'first')
        self.assertEqual(occupied.read_bytes(), b'foreign')
        ren.no_replace(first, self.root / 'moved.json')
        self.assertFalse(first.exists())
        self.assertEqual((self.root / 'moved.json').read_bytes(), b'first')

    def _kill_and_restart(self, phase):
        # A fresh app process derives BACKUP_ROOT from DATA_ROOT.
        self.backups = self.data / 'backups'
        main.BACKUP_ROOT = self.backups
        path = self._prepare(lrc=phase != 'lrc', edited=phase != 'lrc')
        env = dict(os.environ, MUSIC_ROOT=str(self.root), DATA_ROOT=str(self.data))
        child = r'''
import os, signal, sys
from pathlib import Path
from app import main, storage, rename_service as ren, lyric_assets
phase = sys.argv[1]
path = main.MUSIC_ROOT / 'song.mp3'
def stop(): os.kill(os.getpid(), signal.SIGKILL)
if phase == 'lrc':
    lyric_assets.finish = lambda *args: stop()
    storage.save(path, main.MUSIC_ROOT, main.BACKUP_ROOT, {'title': 'Committed'}, ['title'], False,
                 storage.revision(path), lrc='[00:00.00]Generated', asset_root=main.DATA_ROOT)
else:
    move = ren.no_replace
    def kill_after_move(source, target):
        move(source, target)
        if (phase == 'music' and Path(source) == path) or (phase == 'sidecar' and str(source).endswith('.tagbak.json')):
            stop()
    ren.no_replace = kill_after_move
    ren.rename(main.MUSIC_ROOT, main.DATA_ROOT, main.BACKUP_ROOT, main.jobs, main.save_jobs,
               'test', path.name, 'Renamed', storage.revision(path))
raise AssertionError('kill boundary not reached')
'''
        result = subprocess.run([sys.executable, '-B', '-c', child, phase], env=env, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr.decode())
        actual = path if phase == 'lrc' else self.root / 'Renamed.mp3'
        snapshot = actual.read_bytes(), actual.stat().st_ino, actual.stat().st_mtime_ns
        restart = r'''
from app import main, storage, rename_service as ren
from app.upstream import tags
from unittest.mock import patch
with patch.object(tags, 'write_file', side_effect=AssertionError('music rewritten')):
    main.recover_filename_changes()
    ren.check_ready(main.DATA_ROOT, main.MUSIC_ROOT)
    with patch.object(ren, 'no_replace', side_effect=AssertionError('repeat move')):
        main.recover_filename_changes()
        ren.check_ready(main.DATA_ROOT, main.MUSIC_ROOT)
'''
        result = subprocess.run([sys.executable, '-B', '-c', restart], env=env, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual((actual.read_bytes(), actual.stat().st_ino, actual.stat().st_mtime_ns), snapshot)
        jobs = job_store.load(self.data)
        self.assertEqual(jobs['test']['results'][0]['path'], actual.name)
        self.assertTrue(actual.with_suffix('.lrc').is_file())
        if phase == 'lrc':
            self.assertTrue(jobs['test']['results'][0]['stored_saved'])
            self.assertEqual(actual.with_suffix('.lrc').read_bytes(), lyric_assets.payload('[00:00.00]Generated'))
        else:
            self.assertEqual(ren.records(self.data)[0][1]['status'], 'complete')
            self.assertFalse(path.exists())
        storage.restore(actual, self.root, self.backups, storage.revision(actual))
        self.assertEqual(actual.read_bytes(), self.original)

    def test_sigkill_after_music_move_recovers_forward(self):
        self._kill_and_restart('music')

    def test_sigkill_after_sidecar_move_recovers_forward(self):
        self._kill_and_restart('sidecar')

    def test_sigkill_after_tag_commit_recovers_lrc_and_status(self):
        self._kill_and_restart('lrc')
