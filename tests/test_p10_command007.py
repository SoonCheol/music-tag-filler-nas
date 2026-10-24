"""Command 007: generated files and mocked lyrics only, no production mounts."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_p0_storage as p0
import test_p2_workflow as p2
import test_p5_command001 as v2
from app import main, storage
from app.upstream import tags, search_lyrics


class Command007Tests(unittest.TestCase):
    setUpClass = classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass = classmethod(p0.P0Tests.tearDownClass.__func__)
    tearDown = p0.P0Tests.tearDown
    copy = p0.P0Tests.copy
    job = p0.P0Tests.job
    item = p0.P0Tests.item
    request = p0.P0Tests.request
    http = p0.P0Tests.http
    lyrics_search = p2.P2Tests.lyrics_search
    timed = v2.V2Tests.timed
    plain = v2.V2Tests.plain

    def setUp(self):
        p0.P0Tests.setUp(self)
        for cache in (main._lyrics_cache, main._lyrics_tokens, main._lyrics_results,
                      main._lyrics_results_pending, main._lyrics_pending):
            cache.clear()

    def candidate_request(self, row, index=0, **changes):
        return main.CandidateLyricsRequest(path=row['path'], expected_revision=row['original']['revision'],
                                          candidate_id=main.candidate_id(row['candidates'][index]), **changes)

    def test_candidate_and_apply_share_full_result_force_and_no_write(self):
        path=self.copy();row=self.job([path])[0];before=path.read_bytes();request=self.candidate_request(row)
        c=row['candidates'][0]
        found=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain,12,self.timed)
        with patch.object(search_lyrics,'find',return_value=found) as lookup:
            first=main.candidate_lyrics('test',request)
            actual=main.search_file_lyrics('test',main.LyricsSearchRequest(path=row['path'],expected_revision=row['original']['revision'],title=c['title'],artist=c['artist'],candidate_id=request.candidate_id))
            self.assertEqual(first['lyrics_id'],actual['lyrics_id']);self.assertEqual(actual['synced'],self.timed)
            self.assertEqual(lookup.call_count,1)
            refreshed=main.candidate_lyrics('test',request.model_copy(update={'force':True}))
            self.assertEqual(lookup.call_count,2);self.assertNotEqual(first['lyrics_id'],refreshed['lyrics_id'])
            # A user-edited draft keeps its old verified binding after refresh.
            self.assertEqual(main.selected_lyrics('test',row['path'],row['original']['revision'],first['lyrics_id'],c['title'],c['artist'])['lyrics'],self.plain)
        self.assertEqual(path.read_bytes(),before)

    def test_shared_content_cache_separates_duration_artist_and_edition(self):
        found=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain)
        with patch.object(search_lyrics,'find',return_value=found) as lookup:
            def get(path='a.mp3',title='Song',artist='Singer',duration=180,candidate=None):
                return main.lookup_lyrics('test',path,'a'*64,title,artist,duration,candidate)
            get();get('b.mp3');self.assertEqual(lookup.call_count,1)
            get('c.mp3',duration=181);get('d.mp3',artist='Other');get('e.mp3',title='Song (Live)')
            get('f.mp3',candidate={'title':'Song','artist':'Singer','album':'Remastered'})
            self.assertEqual(lookup.call_count,5)

    def test_cache_lru_and_expiry(self):
        found=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain)
        with patch.object(main,'LYRICS_CACHE_LIMIT',2),patch.object(search_lyrics,'find',return_value=found) as lookup:
            for title in ('A','B','A','C'):
                main.lookup_lyrics('test',title,'a'*64,title,'Singer',180)
            self.assertEqual([key[0] for key in main._lyrics_results],['A','C'])
            self.assertLessEqual(len(main._lyrics_cache),2);self.assertLessEqual(len(main._lyrics_tokens),2)
            key=next(k for k in main._lyrics_results if k[0]=='A')
            main._lyrics_results[key]=(0,found)
            main._lyrics_cache.pop((str(main.MUSIC_ROOT.resolve()),'test','A','a'*64,'A','Singer'),None)
            main.lookup_lyrics('test','A','a'*64,'A','Singer',180)
            self.assertEqual(lookup.call_count,4)
        self.assertEqual(main.LYRICS_CACHE_LIMIT,2000);self.assertEqual(main.LYRICS_CACHE_TTL,86400)

    def test_concurrent_requests_and_network_does_not_hold_save_lock(self):
        entered=threading.Event();release=threading.Event()
        def find(*args):
            entered.set();release.wait(3);return search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain)
        with patch.object(search_lyrics,'find',side_effect=find) as lookup,ThreadPoolExecutor(2) as pool:
            args=('test','song.mp3','a'*64,'Song','Singer',180)
            first=pool.submit(main.lookup_lyrics,*args);self.assertTrue(entered.wait(2))
            self.assertTrue(storage.OPERATION_LOCK.acquire(timeout=.2));storage.OPERATION_LOCK.release()
            second=pool.submit(main.lookup_lyrics,*args);release.set()
            self.assertEqual(first.result(3)['lyrics_id'],second.result(3)['lyrics_id']);self.assertEqual(lookup.call_count,1)

    def test_refresh_error_preserves_previous_verified_token(self):
        args=('test','song.mp3','a'*64,'Song','Singer',180)
        with patch.object(search_lyrics,'find',return_value=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain)):
            first=main.lookup_lyrics(*args)
        with patch.object(search_lyrics,'find',return_value=search_lyrics.LyricsResult(search_lyrics.BUSY)):
            self.assertEqual(main.lookup_lyrics(*args,force=True)['status'],'error')
        self.assertEqual(main.selected_lyrics(*args[:3],first['lyrics_id'],*args[3:5])['lyrics'],self.plain)

    def test_manual_edit_save_does_not_reuse_old_timestamps_and_restores(self):
        path=self.copy();row=self.job([path])[0];before=path.read_bytes()
        with patch.object(search_lyrics,'find',return_value=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain,12,self.timed)):
            result=self.lyrics_search(row)
        item=self.item(row,fields=[],values={},lyrics_id=result['lyrics_id'],lyrics_text='Manually edited lyrics\nKeep exactly this text')
        saved=self.http(self.request([item],save_lyrics=True,save_synced=True,create_lrc=True))
        self.assertEqual(saved['saved'],1);self.assertEqual(tags.read_file(str(path)).lyrics,item['lyrics_text'])
        self.assertFalse(tags.read_file(str(path)).synced);self.assertFalse(path.with_suffix('.lrc').exists())
        storage.restore(path,self.root,self.backups,storage.revision(path));self.assertEqual(path.read_bytes(),before)

    def test_candidate_binding_rejects_same_title_other_edition(self):
        path=self.copy();row=self.job([path])[0];c=row['candidates'][0]
        row['candidates'][1].update(title=c['title'],artist=c['artist'],album='Other edition');main.prepare_result(row)
        with patch.object(search_lyrics,'find',return_value=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain)):
            value=main.candidate_lyrics('test',self.candidate_request(row))
        b=row['candidates'][1]
        item=self.item(row,selection='manual',candidate_id=b['id'],values={'title':c['title'],'artist':c['artist']},fields=['title','artist'],lyrics_id=value['lyrics_id'])
        self.assertEqual(self.http(self.request([item],save_lyrics=True))['failed'],1)

    def test_live_and_remaster_validation(self):
        self.assertNotEqual(search_lyrics.version_flags('Song'),search_lyrics.version_flags('Song (Live)'))
        self.assertNotEqual(search_lyrics.version_flags('Song (1999 Remastered)'),search_lyrics.version_flags('Song (2010 Remastered)'))
        self.assertEqual(search_lyrics.version_flags('Live Forever'),search_lyrics.version_flags('Forever'))

    def test_plain_only_refresh_detaches_old_synced_and_edit_preserves_existing(self):
        path=self.copy();row=self.job([path])[0]
        timed=search_lyrics.LyricsResult(search_lyrics.FOUND,self.plain,12,self.timed)
        with patch.object(search_lyrics,'find',return_value=timed):
            first=self.lyrics_search(row)
        with patch.object(search_lyrics,'find',return_value=search_lyrics.LyricsResult(search_lyrics.FOUND,'A different verified plain lyric')):
            plain=self.lyrics_search(row,force=True)
        self.assertEqual(plain['synced'],'');self.assertNotEqual(first['lyrics_id'],plain['lyrics_id'])
        # Existing synchronized lyrics/LRC are preserved when edited plain text is saved.
        tags.write_file(str(path),tags.read_file(str(path)).tags,synced=self.timed)
        path.with_suffix('.lrc').write_text(self.timed+'\n')
        row['original']=storage.describe(path)
        with patch.object(search_lyrics,'find',return_value=timed):
            value=self.lyrics_search(row,force=True)
        item=self.item(row,fields=[],values={},lyrics_id=value['lyrics_id'],lyrics_text='Edited plain lyrics without verified timing')
        outcome=self.http(self.request([item],save_lyrics=True,save_synced=True,create_lrc=True))
        self.assertEqual(outcome['saved'],1)
        self.assertEqual(tags.read_file(str(path)).synced,search_lyrics.synced_lines(self.timed))
        self.assertEqual(path.with_suffix('.lrc').read_text(),self.timed+'\n')

    def test_existing_file_job_revision_query_guards(self):
        p2.P2Tests.test_lyrics_choice_is_bound_to_file_job_revision_and_query(self)

    def test_existing_verified_synced_save_and_checkbox_off(self):
        v2.V2Tests.test_verified_lyrics_api_and_check_off(self)

    def test_existing_empty_or_missing_results_preserve_files(self):
        p2.P2Tests.test_unsearched_empty_or_not_found_lyrics_always_preserve_file(self)


if __name__=='__main__':
    unittest.main()
