"""Job JSON isolation, legacy preservation and deletion use temporary directories only."""
import copy,json,threading,unittest
from unittest.mock import patch
import test_p0_storage as p0
from app import main,storage,job_store
from fastapi import HTTPException

class JobStoreTests(unittest.TestCase):
 setUpClass=classmethod(p0.P0Tests.setUpClass.__func__)
 tearDownClass=classmethod(p0.P0Tests.tearDownClass.__func__)
 setUp=p0.P0Tests.setUp
 tearDown=p0.P0Tests.tearDown
 copy=p0.P0Tests.copy
 job=p0.P0Tests.job
 item=p0.P0Tests.item
 request=p0.P0Tests.request
 http=p0.P0Tests.http

 def test_legacy_archive_is_exact_and_never_imported(self):
  source=self.data/'jobs.json';raw=b'{"old":{"status":"done","results":[]}}';source.write_bytes(raw)
  self.assertEqual(job_store.load(self.data),{});self.assertFalse(source.exists());self.assertEqual((self.data/'jobs_legacy.json').read_bytes(),raw)
  self.assertEqual(job_store.load(self.data),{})

 def test_archive_collision_and_active_fail_closed(self):
  source=self.data/'jobs.json';source.write_text('{"old":{"status":"done"}}');legacy=self.data/'jobs_legacy.json';legacy.write_bytes(b'keep')
  with self.assertRaises(OSError):job_store.load(self.data)
  self.assertEqual(legacy.read_bytes(),b'keep');self.assertTrue(source.exists())
  legacy.unlink();source.write_text('{"old":{"status":"scanning"}}')
  with self.assertRaises(OSError):job_store.load(self.data)
  self.assertTrue(source.exists());self.assertFalse(legacy.exists())

 def test_only_target_record_written_and_noop_unchanged(self):
  jobs={'first':{'id':'first','status':'done','results':[]},'second':{'id':'second','status':'done','results':[]}}
  job_store.save(self.data,jobs);other=self.data/'jobs/second.json';stamp=other.stat().st_mtime_ns;raw=other.read_bytes()
  jobs['first']['scanned']=2
  with patch.object(storage,'_replace_file',wraps=storage._replace_file) as writes:job_store.save(self.data,jobs,['first'])
  self.assertEqual(writes.call_count,1);self.assertEqual(other.read_bytes(),raw);self.assertEqual(other.stat().st_mtime_ns,stamp)
  with patch.object(storage,'_replace_file',wraps=storage._replace_file) as writes:job_store.save(self.data,jobs)
  writes.assert_not_called()

 def test_restart_normalizes_and_summary_has_no_results(self):
  main.jobs['running']={'id':'running','status':'scanning','results':[]};main.save_jobs('running')
  loaded=job_store.load(self.data);self.assertEqual(loaded['running']['status'],'interrupted')
  summary=main.list_jobs(summary=True);self.assertNotIn('results',summary[0]);self.assertNotIn('options',summary[0])

 def test_summary_does_not_rank_candidates(self):
  self.job([self.copy()]);main.jobs['test']['results'][0].pop('ranking_version',None)
  with patch.object(main,'prepare_result',side_effect=AssertionError('must not rank for summaries')):self.assertEqual(len(main.list_jobs(summary=True)),1)

 def test_bulk_delete_preserves_music_backups_and_other_records(self):
  path=self.copy();before=path.read_bytes();self.job([path]);main.save_jobs()
  main.jobs['keep']={'id':'keep','status':'done','results':[]};main.save_jobs('keep');keep=(self.data/'jobs/keep.json').read_bytes()
  main.jobs['cancelled']={'id':'cancelled','status':'cancelled','results':[]};main.save_jobs('cancelled')
  response=self.http({'ids':['test','cancelled']},'/api/jobs/delete')
  self.assertEqual(response['deleted'],['test','cancelled']);self.assertEqual(path.read_bytes(),before)
  self.assertFalse((self.data/'jobs/test.json').exists());self.assertEqual((self.data/'jobs/keep.json').read_bytes(),keep)

 def test_bulk_active_validation_before_any_delete(self):
  for key,state in [('done','done'),('busy','scanning')]:main.jobs[key]={'id':key,'status':state,'results':[]}
  main.save_jobs()
  with self.assertRaises(HTTPException):main.remove_job_records(['done','busy'])
  self.assertTrue((self.data/'jobs/done.json').exists());self.assertIn('done',main.jobs)

 def test_write_failure_preserves_last_good_json(self):
  main.jobs['j']={'id':'j','status':'done','results':[]};main.save_jobs('j');path=self.data/'jobs/j.json';before=path.read_bytes()
  main.jobs['j']['scanned']=4
  with patch.object(storage.os,'replace',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):main.save_jobs('j')
  self.assertEqual(path.read_bytes(),before)

 def test_corrupt_and_symlink_records_are_not_silently_lost(self):
  folder=self.data/'jobs';folder.mkdir();(folder/'bad.json').write_text('{bad')
  with self.assertRaises(ValueError):job_store.load(self.data)
  (folder/'bad.json').unlink();outside=self.data/'outside';outside.write_text('keep');(folder/'link.json').symlink_to(outside)
  with self.assertRaises(OSError):job_store.load(self.data)
  with self.assertRaises(OSError):job_store.delete(self.data,['link'])
  self.assertEqual(outside.read_text(),'keep')

 def test_path_traversal_rejected(self):
  for value in ['../music','/tmp/file','a/b','a.json','']:
   with self.assertRaises(OSError):job_store.record_path(self.data,value)

 def test_queued_tag_save_prevents_parent_record_deletion(self):
  self.job([self.copy()]);main.save_jobs()
  with patch.dict(main.save_tasks,{'pending':{'job_id':'test','status':'queued'}},clear=True):
   with self.assertRaises(HTTPException):main.remove_job_records(['test'])
  self.assertTrue((self.data/'jobs/test.json').exists());self.assertIn('test',main.jobs)

if __name__=='__main__':unittest.main()
