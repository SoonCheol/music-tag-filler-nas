"""Generated audio and private /tmp data only; no operational mounts."""
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import test_p0_storage as p0
from app import main, storage, rename_service as ren


class FilenameTests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    save = p0.P0Tests.save
    http = p0.P0Tests.http
    item = p0.P0Tests.item
    request = p0.P0Tests.request

    def tearDown(self):
        ren.blocked.clear()
        ren.active.clear()
        main.save_tasks.clear()
        p0.P0Tests.tearDown(self)

    def rename(self, row, stem, expected=200, revision=None):
        return self.http({'path':row['path'], 'stem':stem, 'expected_revision':revision or row['original']['revision']},
                         route='/api/jobs/test/rename',expected=expected)

    def test_formats_backup_restore_and_state_preserved(self):
        for ext in ('mp3','flac','m4a','ogg'):
            path=self.copy('Original.'+ext);first=path.read_bytes()
            self.save(path);rows=self.job([path]);row=rows[0]
            main.jobs['copy']=copy.deepcopy(main.jobs['test'])
            main.jobs['test']['options']={'paths':[row['path']]}
            before=path.read_bytes(),path.stat().st_mtime_ns
            side=Path(p0.tags.backup_path(str(path))).read_bytes()
            result=self.rename(row,'한글 new.name')['change'];new=self.root/result['new_path']
            self.assertFalse(path.exists());self.assertEqual((new.read_bytes(),new.stat().st_mtime_ns),before)
            self.assertEqual(main.jobs['copy']['results'][0]['path'],new.name)
            self.assertEqual(main.jobs['test']['options']['paths'],[new.name])
            self.assertFalse(row['stored_saved']);self.assertTrue(row['scan_auto_selected'])
            self.assertEqual(Path(p0.tags.backup_path(str(new))).read_bytes(),side)
            storage.restore(new,self.root,self.backups,storage.revision(new))
            self.assertEqual(new.read_bytes(),first)
            self.assertEqual(len(main.path_changes()['changes']),len(ren.changes(self.data,0)))

    def test_invalid_names_collisions_and_noop(self):
        path=self.copy();row=self.job([path])[0];before=path.read_bytes()
        for stem in ('',' ','x ','x.','../x','a/b','a\\b','CON','con.txt','CONIN$','CONOUT$','LPT1','x\x00','a\n','x'*250,'SONG'):
            self.rename(row,stem,409)
        (self.root/'taken.mp3').mkdir();self.rename(row,'taken',409)
        (self.root/'backup.mp3.tagbak.json').write_text('do not touch');self.rename(row,'backup',409)
        self.assertEqual(self.rename(row,'song')['status'],'unchanged')
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.data/'renames').exists())

    def test_atomic_no_replace_and_unsupported(self):
        a=self.root/'a';b=self.root/'b';a.write_bytes(b'a');b.write_bytes(b'b')
        with self.assertRaises(FileExistsError):ren.no_replace(a,b)
        self.assertEqual(a.read_bytes(),b'a');self.assertEqual(b.read_bytes(),b'b')
        path=self.copy();row=self.job([path])[0]
        with patch.object(ren,'no_replace',side_effect=storage.StorageError('unsupported')):
            self.rename(row,'new',409)
        self.assertTrue(path.exists());self.assertFalse((self.root/'new.mp3').exists())

    def test_revision_job_permissions_symlinks(self):
        path=self.copy();row=self.job([path])[0]
        self.rename(row,'new',409,'0'*64)
        with patch.object(storage,'writable',side_effect=storage.StorageError('read only')):
            self.rename(row,'new',409)
        outside=self.copy('other.mp3')
        self.http({'path':outside.name,'stem':'new','expected_revision':storage.revision(outside)},route='/api/jobs/test/rename',expected=409)
        directory=self.root/'link';directory.symlink_to(self.root,target_is_directory=True)
        row['path']='link/song.mp3';self.rename(row,'new',409)
        self.assertTrue(path.exists())

    def test_busy_and_concurrent_change(self):
        path=self.copy();row=self.job([path])[0]
        for state in ('queued','scanning','cancelling'):
            main.jobs['test']['status']=state;self.rename(row,'new',409)
        main.jobs['test']['status']='done'
        for label in ('가사 검색','태그 검색','원본 복원','태그 저장'):
            ren.active[label]=1;self.rename(row,'new',409);ren.active[label]=0
        main.save_tasks['queued']={'status':'queued'};self.rename(row,'new',409);main.save_tasks.clear()
        results=[]
        request=main.RenameRequest(path=path.name,stem='concurrent',expected_revision=storage.revision(path))
        def run():
            try:results.append(main.rename_file('test',request)['status'])
            except HTTPException:results.append('blocked')
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sorted(results),['blocked','renamed'])

    def test_failed_jobs_write_then_restart_recovers_forward(self):
        path=self.copy();self.save(path);row=self.job([path])[0];before=path.read_bytes()
        with patch.object(main,'save_jobs',side_effect=OSError('disk full')):
            self.rename(row,'forward',409)
        new=self.root/'forward.mp3';self.assertTrue(new.exists());self.assertFalse(path.exists())
        self.assertIn(str(self.data.resolve()),ren.blocked)
        main.jobs.clear();main.jobs['test']={'results':[{'path':'song.mp3','original':storage.describe(new)}]}
        ren.recover(self.root,self.data,self.backups,main.jobs,main.save_jobs)
        self.assertEqual(main.jobs['test']['results'][0]['path'],'forward.mp3')
        self.assertEqual(new.read_bytes(),before);storage._verify_backup(new,self.root,self.backups)
        self.assertEqual(ren.changes(self.data,0)[0]['new_path'],'forward.mp3')

    def test_sidecar_failure_and_ambiguous_recovery(self):
        path=self.copy();self.save(path);row=self.job([path])[0]
        original=ren.no_replace
        def fail_side(a,b):
            if str(a).endswith('.tagbak.json'):raise OSError('sidecar failure')
            return original(a,b)
        with patch.object(ren,'no_replace',side_effect=fail_side):self.rename(row,'new',409)
        ren.recover(self.root,self.data,self.backups,main.jobs,main.save_jobs)
        new=self.root/'new.mp3';storage._verify_backup(new,self.root,self.backups)
        record_path,record=ren.records(self.data)[0];record['status']='pending';ren.write_record(record_path,record)
        path.write_bytes(new.read_bytes())
        with self.assertRaises(storage.StorageError):ren.recover(self.root,self.data,self.backups,main.jobs,main.save_jobs)
        self.assertTrue(path.exists());self.assertTrue(new.exists())

    def test_lyrics_token_migrated_and_auto_rename_retained(self):
        path=self.copy();row=self.job([path])[0]
        key=(str(self.root.resolve()),'test',path.name,storage.revision(path),row['original']['title'],row['original']['artist'])
        entry=main.remember_lyrics(key,main.original_lyrics.LyricsResult(main.original_lyrics.FOUND,'new lyrics'))
        result=self.rename(row,'manual')['change'];mapping=result['lyrics_tokens'][0]
        self.assertEqual(mapping['old_id'],entry['lyrics_id'])
        with self.assertRaises(storage.StorageError):main.selected_lyrics('test',path.name,key[3],entry['lyrics_id'],key[4],key[5])
        self.assertEqual(main.selected_lyrics('test','manual.mp3',key[3],mapping['new_id'],key[4],key[5])['lyrics'],'new lyrics')
        new=self.root/'manual.mp3'
        saved=storage.save(new,self.root,self.backups,{},[],False,storage.revision(new),rename=True)
        self.assertEqual(saved['status'],'saved');self.assertNotEqual(saved['path'],'manual.mp3')

    def test_search_registration_spans_network_and_releases(self):
        path=self.copy();row=self.job([path])[0]
        entered=threading.Event();release=threading.Event()
        def find(*args):
            entered.set();release.wait(3)
            return main.original_lyrics.LyricsResult(main.original_lyrics.NOT_FOUND)
        request=main.LyricsSearchRequest(path=path.name,expected_revision=storage.revision(path),title='Unique test',artist='Singer')
        with patch.object(main.original_lyrics,'find',side_effect=find):
            thread=threading.Thread(target=lambda:main.search_file_lyrics('test',request));thread.start()
            self.assertTrue(entered.wait(2));self.rename(row,'new',409);release.set();thread.join()
        self.assertEqual(ren.active.get('가사 검색'),0)
        self.rename(row,'new')

    def test_persistent_changes_replay_and_reservation_gate(self):
        path=self.copy();row=self.job([path])[0]
        first=self.rename(row,'first')['change']
        second=self.rename(row,'second')['change']
        self.assertEqual([e['seq'] for e in ren.changes(self.data,first['seq'])],[second['seq']])
        ren.recover(self.root,self.data,self.backups,main.jobs,main.save_jobs)
        self.assertEqual([e['new_path'] for e in main.path_changes(0)['changes']],['first.mp3','second.mp3'])
        ren.renaming=True
        try:
            self.http(self.request([self.item(row)]),expected=409)
        finally:
            ren.renaming=False
    def test_tag_save_after_manual_rename_uses_new_path(self):
        path=self.copy();row=self.job([path])[0]
        self.rename(row,'new name')
        item=self.item(row,selection='edit',fields=['title'],values={'title':'Saved after rename'})
        response=self.http(self.request([item]))
        self.assertEqual(response['saved'],1)
        self.assertEqual(p0.tags.read_file(str(self.root/'new name.mp3')).tags.title,'Saved after rename')
        self.assertFalse(path.exists())
