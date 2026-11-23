"""Command 001-v2: generated audio only, no production mounts or external API."""
import json
import threading
from unittest.mock import patch
import unittest
import test_p0_storage as p0
from app import main, storage, search_service, rename_service, lyric_assets
from app.upstream import tags, search_lyrics
from mutagen.id3 import ID3


class V2Tests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp = p0.P0Tests.setUp
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    http = p0.P0Tests.http
    timed = '[00:00.00]First verified lyric line\n[00:00.20]Second verified lyric line'
    plain = 'First verified lyric line\nSecond verified lyric line'

    def test_list_first_and_three_bounded_workers(self):
        files = [self.copy(str(i)+'.mp3') for i in range(7)]
        self.job(files);main.jobs['test'].update(status='queued',results=[],cancel_requested=False)
        entered = threading.Event();release = threading.Event();lock=threading.Lock();counts=[0,0]
        def fake(*args, **kwargs):
            with lock:
                counts[0]+=1;counts[1]=max(counts)
                if counts[0]==3:entered.set()
            release.wait(3)
            with lock:counts[0]-=1
            return {'candidates':[], 'search_status':'not_found'}
        with patch.object(search_service,'search',side_effect=fake):
            thread=threading.Thread(target=main.scan_job,args=('test','',{'use_fingerprint':False}));thread.start()
            try:
                self.assertTrue(entered.wait(3));rows=main.jobs['test']['results']
                self.assertEqual(len(rows),7);self.assertTrue(all(r['original'].get('revision') for r in rows if r['search_phase']=='running'))
                self.assertEqual(sum(r['search_phase']=='running' for r in rows),3)
                self.assertEqual(main.jobs['test']['scanned'],0)
                self.assertTrue(all(main.file_state(r) in ('waiting','running') for r in rows))
            finally:release.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(counts[1],3);self.assertEqual(main.jobs['test']['scanned'],7)

    def test_cancel_resume_reuses_only_completed(self):
        files=[self.copy(str(i)+'.mp3') for i in range(5)];self.job(files)
        rows=main.jobs['test']['results'];rows[0]['search_phase']='complete'
        for r in rows[1:]:r.update(search_phase='waiting',candidates=[])
        with patch.object(search_service,'search',return_value={'candidates':[],'search_status':'not_found'}) as mocked:
            main.scan_job('test','',{},True)
        self.assertEqual(mocked.call_count,4);self.assertEqual(main.jobs['test']['scanned'],5)

    def test_sylt_uslt_lrc_roundtrip_restore_and_direct_rename(self):
        path=self.copy();before=path.read_bytes();rows=self.job([path])
        outcome=storage.save(path,self.root,self.backups,{},[],False,storage.revision(path),lyrics=self.plain,
                             replace_lyrics=True,synced=self.timed,lrc=self.timed,asset_root=self.data)
        self.assertTrue(outcome['changed']);info=tags.read_file(str(path))
        self.assertEqual(info.lyrics,self.plain);self.assertEqual(info.synced,[('First verified lyric line',0),('Second verified lyric line',200)])
        self.assertEqual(ID3(str(path)).version[:2],(2,4));self.assertEqual(ID3(str(path)).getall('SYLT')[0].format,2)
        self.assertEqual(path.with_suffix('.lrc').read_text(),self.timed+'\n')
        rows[0]['original']=storage.describe(path)
        rename_service.rename(self.root,self.data,self.backups,main.jobs,main.save_jobs,'test','song.mp3','Renamed',storage.revision(path))
        new=self.root/'Renamed.mp3';self.assertTrue(new.with_suffix('.lrc').exists());self.assertFalse(path.with_suffix('.lrc').exists())
        storage.restore(new,self.root,self.backups,storage.revision(new));self.assertEqual(new.read_bytes(),before)
        self.assertEqual(new.with_suffix('.lrc').read_text(),self.timed+'\n')

    def test_lrc_existing_conflict_never_changes_music(self):
        path=self.copy();before=path.read_bytes();path.with_suffix('.lrc').write_text('Keep existing')
        with self.assertRaises(storage.StorageError):
            storage.save(path,self.root,self.backups,{'title':'New'},['title'],False,storage.revision(path),lrc=self.timed,asset_root=self.data)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(path.with_suffix('.lrc').read_text(),'Keep existing')

    def test_lrc_recovery_after_publication_record_failure(self):
        path=self.copy();asset=lyric_assets.begin(path,self.timed,self.root,self.data,storage.revision(path),storage.revision(path))
        with patch.object(storage,'_replace_file',side_effect=OSError('simulated disk interruption')):
            with self.assertRaises(OSError):lyric_assets.finish(asset,self.root)
        lyric_assets.recover(self.root,self.data)
        self.assertEqual(json.loads(asset[0].read_text())['status'],'complete')
        self.assertEqual(path.with_suffix('.lrc').read_text(),self.timed+'\n')

    def test_lrc_rename_recovery_and_collision(self):
        path=self.copy();self.job([path]);path.with_suffix('.lrc').write_text(self.timed)
        (self.root/'Collision.LRC').write_text('Keep')
        with self.assertRaises(storage.StorageError):rename_service.validate_name(path,'Collision')
        original_finish=rename_service.finish;count=[0]
        def fail_once(*args):
            count[0]+=1
            if count[0]==1:raise OSError('interrupted after music rename')
            return original_finish(*args)
        with patch.object(rename_service,'finish',side_effect=fail_once):
            rename_service.rename(self.root,self.data,self.backups,main.jobs,main.save_jobs,'test','song.mp3','Recovered',storage.revision(path))
        self.assertTrue((self.root/'Recovered.lrc').exists());self.assertEqual(main.jobs['test']['results'][0]['path'],'Recovered.mp3')

    def test_auto_rename_lrc_and_backup(self):
        path=self.copy();self.job([path]);path.with_suffix('.lrc').write_text(self.timed)
        outcome=storage.save(path,self.root,self.backups,{'title':'Changed'},['title'],False,storage.revision(path),rename=True,asset_root=self.data,
                             rename_context=(main.jobs,main.save_jobs,'test'))
        self.assertEqual(outcome['status'],'saved');new=self.root/outcome['path'];self.assertTrue(new.with_suffix('.lrc').exists())
        self.assertEqual(main.jobs['test']['results'][0]['path'],outcome['path']);storage._verify_backup(new,self.root,self.backups)

    def test_only_empty_protects_text_cover_plain_and_synced(self):
        path=self.copy();before=path.read_bytes()
        outcome=storage.save(path,self.root,self.backups,{'title':'Must not change'},['title'],True,storage.revision(path),cover=p0.image_bytes('blue'),
                             lyrics=self.plain,replace_lyrics=True,synced=self.timed,lrc=self.timed,asset_root=self.data)
        self.assertEqual(outcome['status'],'skipped');self.assertEqual(path.read_bytes(),before);self.assertFalse(path.with_suffix('.lrc').exists())

    def test_verified_lyrics_api_and_check_off(self):
        path=self.copy();row=self.job([path])[0]
        found=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain,12,self.timed)
        with patch.object(search_lyrics,'find',return_value=found):
            response=self.http({'path':row['path'],'expected_revision':row['original']['revision'],'title':row['original']['title'],'artist':row['original']['artist']},'/api/jobs/test/lyrics-search')
        self.assertEqual(response['synced'],self.timed)
        item=self.item(row,fields=[],values={},lyrics_id=response['lyrics_id'])
        before=path.read_bytes();request=self.request([item],save_lyrics=False,save_synced=True,create_lrc=True)
        result=self.http(request);self.assertEqual(result['saved'],0);self.assertEqual(path.read_bytes(),before)
        result=self.http(self.request([item],save_lyrics=True,save_synced=True,create_lrc=True))
        self.assertEqual(result['saved'],1);self.assertEqual(tags.read_file(str(path)).synced[1][1],200)

    def test_candidate_availability_cache_force_dedupe_and_no_edit(self):
        path=self.copy();row=self.job([path])[0];original=path.read_bytes()
        request=main.CandidateLyricsRequest(path=row['path'],expected_revision=row['original']['revision'],candidate_id=main.candidate_id(row['candidates'][0]))
        found=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain)
        with patch.object(search_lyrics,'find',return_value=found) as fake:
            result=main.candidate_lyrics('test',request)
            self.assertEqual((result['status'],result['has_lyrics']),('found',True))
            self.assertEqual(result['lyrics'],self.plain);self.assertTrue(result['lyrics_id'])
            main.candidate_lyrics('test',request);self.assertEqual(fake.call_count,1)
            main.candidate_lyrics('test',request.model_copy(update={'force':True}));self.assertEqual(fake.call_count,2)
        self.assertEqual(path.read_bytes(),original);self.assertNotIn('lyrics_search',row)


    def test_synced_no_change_and_plain_without_invented_time(self):
        path=self.copy();tags.write_file(str(path),tags.read_file(str(path)).tags,synced=self.timed)
        before=path.read_bytes();stamp=path.stat().st_mtime_ns
        result=storage.save(path,self.root,self.backups,{},[],False,storage.revision(path),synced=self.timed,asset_root=self.data)
        self.assertEqual(result['status'],'skipped');self.assertEqual(path.read_bytes(),before);self.assertEqual(path.stat().st_mtime_ns,stamp)
        self.assertEqual(search_lyrics.synced_lines(self.plain),[])
        for text in ['[00:60.00]Wrong','[99999999:00]Too late']:
            with self.assertRaises(ValueError):search_lyrics.synced_lines(text)

    def test_music_commit_then_lrc_failure_recovers_forward(self):
        path=self.copy();before=storage.revision(path);original_new=storage._new_file
        def fail_lrc(target, content):
            if str(target).endswith('.lrc'):raise OSError('simulated LRC publish failure')
            return original_new(target,content)
        with patch.object(storage,'_new_file',side_effect=fail_lrc):
            outcome=storage.save(path,self.root,self.backups,{'title':'Committed'},['title'],False,before,lrc=self.timed,asset_root=self.data)
        self.assertEqual(outcome['status'],'partial')
        self.assertTrue(outcome['music_saved'])
        self.assertTrue(outcome['recovery_pending'])
        self.assertIn('simulated LRC publish failure',outcome['warning'])
        self.assertEqual(tags.read_file(str(path)).tags.title,'Committed');self.assertNotEqual(storage.revision(path),before)
        main.recover_filename_changes();rename_service.check_ready(self.data)
        self.assertEqual(path.with_suffix('.lrc').read_text(),self.timed+'\n')
        self.assertEqual(tags.read_file(str(path)).tags.title,'Committed')

    def test_candidate_cover_force_bypasses_positive_cache(self):
        value={'title':'Unique force','artist':'Singer','album':'Force Album','cover_url':'https://example.invalid/force','source':'iTunes'}
        search_service._cover_cache.clear()
        with patch.object(search_service.net,'get_bytes',side_effect=[p0.image_bytes('red'),p0.image_bytes('blue')]) as fake:
            first=search_service.fetch_cover(value)[0];self.assertEqual(search_service.fetch_cover(value)[0],first)
            self.assertNotEqual(search_service.fetch_cover(value,force=True)[0],first);self.assertEqual(fake.call_count,2)

    def test_throttle_reserves_future_windows_for_parallel_search(self):
        from app.upstream.net import _Throttle
        limiter=_Throttle();limiter.set_window('example',2,60)
        with patch('app.upstream.net.time.monotonic',return_value=1000):
            delays=[limiter._reserve('example') for _ in range(7)]
        self.assertEqual(delays,[0,0,60,60,120,120,180])

    def test_search_error_is_not_auto_selected(self):
        self.job([self.copy()]);main.jobs['test'].update(status='queued',results=[],cancel_requested=False)
        with patch.object(search_service,'search',side_effect=RuntimeError('fake search failure')):
            main.scan_job('test','',{})
        row=main.jobs['test']['results'][0];self.assertEqual(main.file_state(row),'error');self.assertFalse(row.get('auto_apply'))


    def test_cancel_keeps_completed_and_resume_six_remaining(self):
        files=[self.copy(str(i)+'.mp3') for i in range(7)];before=[p.read_bytes() for p in files]
        self.job(files);main.jobs['test'].update(status='queued',results=[],scanned=0,cancel_requested=False)
        entered=threading.Event();lock=threading.Lock();calls=[0]
        def fake(*args,**kwargs):
            with lock:
                calls[0]+=1;number=calls[0]
                if number==4:entered.set()
            if number>1:
                while not kwargs['cancel'].is_set():threading.Event().wait(.01)
            return {'candidates':[],'search_status':'not_found'}
        with patch.object(search_service,'search',side_effect=fake):
            worker=threading.Thread(target=main.scan_job,args=('test','',{}));worker.start()
            try:
                self.assertTrue(entered.wait(3));main.cancel_job('test');self.assertEqual(main.jobs['test']['status'],'cancelling')
            finally:main.jobs['test']['cancel_requested']=True;worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(calls[0],4)
        job=main.jobs['test'];self.assertEqual((job['status'],job['scanned'],job['total']),('cancelled',1,7))
        self.assertEqual(sum(r.get('search_phase')=='complete' for r in job['results']),1)
        self.assertEqual(sum(r.get('search_phase')=='waiting' for r in job['results']),6)
        job.update(cancel_requested=False,status='queued')
        with patch.object(search_service,'search',return_value={'candidates':[],'search_status':'not_found'}) as fake:
            main.scan_job('test','',{},True)
        self.assertEqual(fake.call_count,6);self.assertEqual(job['status'],'done');self.assertEqual(job['scanned'],7)
        self.assertEqual(before,[p.read_bytes() for p in files])

    def test_cancellation_during_throttle_sends_no_request(self):
        from app.upstream import net
        from unittest.mock import Mock
        event=threading.Event();session=Mock()
        with patch.object(net,'session',return_value=session),patch.object(net.throttle,'wait',side_effect=lambda *args:event.set()):
            with self.assertRaises(net.NetworkError):net.request('GET','https://example.invalid/',cancel=event)
        session.request.assert_not_called()

    def test_failed_inflight_after_cancel_keeps_waiting_row(self):
        self.job([self.copy()]);main.jobs['test'].update(status='queued',results=[],scanned=0,cancel_requested=False)
        def stop(*args,**kwargs):
            main.cancel_job('test');raise RuntimeError('cancelled in flight')
        with patch.object(search_service,'search',side_effect=stop):main.scan_job('test','',{})
        job=main.jobs['test'];self.assertEqual(job['status'],'cancelled');self.assertEqual(job['scanned'],0)
        self.assertEqual(job['results'][0]['search_phase'],'waiting');self.assertNotIn('error',job['results'][0])

if __name__=='__main__':unittest.main()
