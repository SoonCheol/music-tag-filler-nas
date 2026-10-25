import threading
from unittest.mock import patch, Mock
import unittest
from test_p2_workflow import P2Tests
from app import main, search_service
from app.upstream import net

class Probe(unittest.TestCase):
    setUpClass = P2Tests.__dict__["setUpClass"]
    tearDownClass = P2Tests.__dict__["tearDownClass"]
    setUp = P2Tests.setUp
    tearDown = P2Tests.tearDown
    copy = P2Tests.copy
    job = P2Tests.job
    item = P2Tests.item
    request = P2Tests.request
    http = P2Tests.http
    def test_stop_restart_progress(self):
        paths=[self.copy(str(i)+'.mp3') for i in range(3)]
        before=[(p.read_bytes(),p.stat().st_mtime_ns) for p in paths]
        self.job(paths)
        main.jobs['test'].update(status='queued',results=[],scanned=0,cancel_requested=False)
        entered, first_saved = threading.Event(), threading.Event()
        gate=threading.Lock()
        counts={'calls':0,'blocked':0}
        original_save=main.save_jobs
        def persist(job_id=None):
            original_save(job_id)
            if main.jobs['test']['scanned']==1:
                first_saved.set()
        def search(*args,**kwargs):
            with gate:
                counts['calls']+=1
                first=counts['calls']==1
                if not first:
                    counts['blocked']+=1
                    if counts['blocked']==2:entered.set()
            if not first:
                while not kwargs['cancel'].is_set():
                    threading.Event().wait(.01)
            return {'candidates':[],'search_status':'not_found'}
        with patch.object(search_service,'search',side_effect=search) as search_mock, patch.object(main,'save_jobs',side_effect=persist):
            worker=threading.Thread(target=main.scan_job,args=('test','',{}))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(first_saved.wait(5))
                main.cancel_job('test')
                self.assertEqual(main.jobs['test']['status'],'cancelling')
            finally:
                main.jobs['test']['cancel_requested']=True
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(search_mock.call_count,3)
        job=main.jobs['test']
        self.assertEqual((job['status'],job['scanned'],job['total'],job['current_file'],job['search_wait_seconds']),('cancelled',1,3,'',0))
        with patch.object(search_service,'search',return_value={'candidates':[],'search_status':'not_found'}):
            from fastapi import BackgroundTasks
            background=BackgroundTasks()
            new=main.start_scan(main.ScanRequest(use_fingerprint=False),background)['job_id']
            main.scan_job(new,'',{'use_fingerprint':False})
            self.assertEqual(main.jobs[new]['status'],'done')
        self.assertEqual(before,[(p.read_bytes(),p.stat().st_mtime_ns) for p in paths])
        print('PROBE stop/restart: cancelled 1/3; three-worker limit; metadata unchanged')

    def test_throttle_cancel_boundary(self):
        event=threading.Event()
        response=Mock(status_code=200)
        session=Mock()
        session.request.return_value=response
        with patch.object(net,'session',return_value=session),patch.object(net.throttle,'wait',side_effect=lambda *a:event.set()):
            with self.assertRaises(net.NetworkError):
                net.request('GET','https://example.invalid/',cancel=event)
            session.request.assert_not_called()
            session.reset_mock()
            with self.assertRaises(net.NetworkError):
                net.request('GET','https://example.invalid/',cancel=event)
            session.request.assert_not_called()
        print('PASS: cancellation during throttle sends no request')

    def test_cancel_collection_preserves_results(self):
        from app import job_service
        path=self.copy()
        self.job([path])
        job=main.jobs['test']
        previous=list(job['results'])
        job.update(status='cancelling',cancel_requested=True)
        main.scan_job('test','',{},resume=True)
        self.assertEqual(job['status'],'cancelled')
        self.assertEqual(job['results'],previous)
        with self.assertRaises(job_service.ScanCancelled):
            job_service.retained_results(self.root,[path],previous,main.ScanCancellation(job))

    def test_cancel_error_does_not_publish_result(self):
        self.job([self.copy()])
        main.jobs['test'].update(status='queued',results=[],scanned=0,cancel_requested=False)
        def stop(*args,**kwargs):
            main.cancel_job('test')
            raise RuntimeError('cancelled in flight')
        with patch.object(search_service,'search',side_effect=stop):
            main.scan_job('test','',{})
        self.assertEqual(main.jobs['test']['status'],'cancelled')
        rows=main.jobs['test']['results']
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['search_phase'],rows[0]['file_state']),('waiting','waiting'))
        self.assertEqual(rows[0]['candidates'],[])
        self.assertNotIn('error',rows[0])
        self.assertEqual(main.jobs['test']['scanned'],0)
