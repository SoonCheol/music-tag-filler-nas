"""Live operation state, generated files only."""
import json
from types import SimpleNamespace
import threading
import unittest
import urllib.request
from fastapi import HTTPException
import test_p0_storage as p0
from app import main, storage, rename_service

class OperationTests(unittest.TestCase):
    setUpClass=classmethod(p0.P0Tests.setUpClass.__func__)
    tearDownClass=classmethod(p0.P0Tests.tearDownClass.__func__)
    setUp=p0.P0Tests.setUp
    copy=p0.P0Tests.copy
    job=p0.P0Tests.job
    http=p0.P0Tests.http

    def tearDown(self):
        main.save_tasks.clear()
        main._activity.clear()
        rename_service.active.clear()
        p0.P0Tests.tearDown(self)

    def status(self):
        with urllib.request.urlopen('http://127.0.0.1:'+str(self.port)+'/api/background-operations',timeout=2) as response:
            return json.load(response)['operations']

    def test_live_while_mutation_locked_and_conflict_reason(self):
        path=self.copy();row=self.job([path])[0]
        started=threading.Event();release=threading.Event()
        @main.path_operation('앨범 이미지 검색')
        def work(request):
            with storage.OPERATION_LOCK:
                started.set();release.wait(4)
        thread=threading.Thread(target=lambda:work(SimpleNamespace(path=path.name)))
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            items=self.status();self.assertEqual(len(items),1)
            self.assertEqual(items[0]['message'],'앨범 이미지 검색 중...');self.assertEqual(items[0]['file'],path.name)
            result=self.http({'path':path.name,'stem':'new','expected_revision':row['original']['revision']},route='/api/jobs/test/rename',expected=409)
            self.assertIn('앨범 이미지 검색 중이어서',result['detail'])
        finally:
            release.set();thread.join()
        self.assertEqual(self.status(),[])
        result=self.http({'path':path.name,'stem':'new','expected_revision':row['original']['revision']},route='/api/jobs/test/rename')
        self.assertEqual(result['status'],'renamed');self.assertEqual(self.status(),[])

    def test_multiple_details_and_terminal_states(self):
        self.job([self.copy()]);main.jobs['test'].update(status='scanning',current_file='Folder/scan.mp3')
        main.save_tasks['test']={'status':'queued','current_file':'save.mp3'}
        token=main.begin_activity('가사 검색','Folder/lyrics.mp3')
        try:
            items=self.status();self.assertEqual(len(items),3)
            self.assertEqual({e['label'] for e in items},{'파일 스캔','태그 저장','가사 검색'})
            self.assertTrue(any(e['message']=='태그 저장 대기 중...' for e in items))
            main.jobs['test']['status']='cancelling'
            self.assertTrue(any(e['message']=='파일 스캔 중지 중...' for e in self.status()))
            for state in ('done','failed','cancelled','interrupted'):
                main.jobs['test']['status']=state;main.save_tasks['test']['status']=state
                self.assertEqual(len(self.status()),1)
        finally:main.end_activity(token)
        self.assertEqual(self.status(),[])

    def test_exception_and_cancel_release_and_rename_visible(self):
        for error in (RuntimeError('failed'),HTTPException(409,'cancelled')):
            @main.path_operation('가사 검색')
            def fail(request):
                self.assertEqual(self.status()[0]['file'],'test.mp3')
                raise error
            with self.assertRaises(type(error)):fail(SimpleNamespace(path='test.mp3'))
            self.assertEqual(self.status(),[]);self.assertEqual(rename_service.active['가사 검색'],0)
        token=main.begin_activity('파일명 변경','new.mp3')
        try:self.assertEqual(self.status()[0]['message'],'파일명 변경 중...')
        finally:main.end_activity(token)
