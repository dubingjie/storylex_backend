import importlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch
import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class ReviewStateIntegration(unittest.TestCase):
    context=base.StudyIntegration.__dict__['context']
    tearDownClass=base.StudyIntegration.__dict__['tearDownClass']
    sql=base.StudyIntegration.sql
    group=base.StudyIntegration.group

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.states=importlib.import_module('services.review_state_service')
        cls.states.get_db=cls.context
        cls.states.locked_user=cls.module.locked_user
        cls.state_api=cls.states.ReviewStateService
        cls.pages=importlib.import_module('services.page_service')
        cls.pages.get_db=cls.context
        cls.old_user=importlib.import_module('services.user_service')
        cls.old_user.get_db=cls.context

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        self.clock_state=patch.object(self.states,'study_now',return_value=datetime(2026,10,16,12))
        self.clock_state.start();self.addCleanup(self.clock_state.stop)
        self.clock_pages=patch.object(self.pages,'study_now',return_value=datetime(2026,10,16,12))
        self.clock_pages.start();self.addCleanup(self.clock_pages.stop)
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,stage,proficiency,wrong_count,review_count,next_review_at) VALUES (1,1,'reviewing',3,50,2,5,'2026-10-16'),(1,2,'mastered',7,100,3,8,'2026-10-20'),(1,3,'learning',0,0,0,0,'2026-10-16')")
        self.sql('INSERT INTO user_favorite_words (user_id,word_id) VALUES (1,1)')

    def test_pause_preserves_record_and_excludes_queue_dashboard(self):
        before=self.sql('SELECT * FROM user_word_records WHERE word_id=1')[0]
        result=self.state_api.change(1,1,'pause','p')
        self.assertTrue(result[0],result)
        self.assertTrue(result[2]['is_review_paused'])
        self.assertIsNone(result[2]['next_review_at'])
        self.assertEqual(self.sql('SELECT * FROM user_word_records WHERE word_id=1')[0],before)
        self.assertEqual([w['word_id'] for w in self.group('review')['words']],[3])
        self.assertEqual(self.pages.PageService.dashboard(1)[2]['review_task']['due_count'],1)
        self.assertEqual(self.state_api.paused_words(1)[2]['total'],1)
        self.assertEqual(self.state_api.paused_words(2)[2]['total'],0)
        detail=self.story_module.StoryService.get_story_detail(1,1)
        self.assertTrue(next(w for w in detail[2]['embedded_words'] if w['word_id']==1)['is_review_paused'])

    def test_pause_skips_active_word_without_counting(self):
        group=self.group('review')
        raw=json.loads(self.sql('SELECT state FROM study_groups WHERE id=%s',(group['group_id'],))[0]['state'])
        word=raw['words']['1']
        self.state_api.change(1,1,'pause','p')
        refreshed=self.group('review')
        self.assertTrue(next(w for w in refreshed['words'] if w['word_id']==1)['skipped'])
        result=self.service.answer(1,'review',group['group_id'],1,word['question_id'],'old-answer',word['correct_key'])
        self.assertFalse(result[0])
        self.assertEqual(self.service.review_summary(1,group['group_id'])[2]['reviewed_count'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM daily_review_words')[0]['n'],0)

    def test_resume_next_midnight_idempotent_delayed_retry(self):
        self.state_api.change(1,1,'pause','p')
        result=self.state_api.change(1,1,'resume','r')
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['stage'],3)
        self.assertEqual(result[2]['proficiency'],50)
        self.assertEqual(result[2]['next_review_at'],'2026-10-17 00:00:00')
        self.state_api.change(1,1,'pause','p2')
        self.assertEqual(self.state_api.change(1,1,'resume','r')[2],result[2])
        self.assertEqual(self.state_api.paused_words(1)[2]['total'],1)
        self.assertFalse(self.state_api.change(1,3,'resume','r')[0])
        self.state_api.change(1,1,'resume','r2')
        with patch.object(self.states,'study_now',return_value=datetime(2026,10,18)):
            self.assertFalse(self.state_api.change(1,1,'resume','r3')[2]['changed'])
        self.assertEqual(self.sql('SELECT next_review_at FROM user_word_records WHERE word_id=1')[0]['next_review_at'],datetime(2026,10,17))

    def test_reset_mastery_history_and_counts(self):
        result=self.state_api.change(1,2,'reset','reset')
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['stage'],0)
        self.assertEqual(result[2]['proficiency'],0)
        self.assertEqual(result[2]['status'],'reviewing')
        record=self.sql('SELECT wrong_count,review_count,next_review_at FROM user_word_records WHERE word_id=2')[0]
        self.assertEqual(record,{'wrong_count':3,'review_count':8,'next_review_at':datetime(2026,10,17)})
        self.assertFalse(self.state_api.change(1,2,'reset','different')[0])
        self.assertEqual(self.state_api.change(1,2,'reset','reset')[2],result[2])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_favorite_words')[0]['n'],1)

    def test_master_clears_pause_and_reading_wrong_does_not_resume(self):
        self.state_api.change(1,1,'pause','p')
        before=self.sql('SELECT * FROM user_word_records WHERE word_id=1')[0]
        with self.context() as c:
            queued=self.api._queue_wrong(c,1,1,datetime(2026,10,16))
        self.assertEqual(queued,0)
        self.assertEqual(self.sql('SELECT * FROM user_word_records WHERE word_id=1')[0],before)
        self.assertTrue(self.service.master(1,1)[0])
        self.assertEqual(self.state_api.paused_words(1)[2]['total'],0)
        self.assertFalse(self.state_api.change(1,1,'pause','new')[0])

    def test_concurrent_reset_and_rollback(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.state_api.change(1,2,'reset','same'),range(2)))
        self.assertTrue(all(r[0] for r in results),results)
        self.assertEqual(results[0][2],results[1][2])
        before=self.sql('SELECT * FROM user_word_records WHERE word_id=1')[0]
        with patch.object(self.states,'skip_review_word',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                self.state_api.change(1,1,'pause','fail')
        self.assertEqual(self.state_api.paused_words(1)[2]['total'],0)
        self.assertEqual(self.sql('SELECT * FROM user_word_records WHERE word_id=1')[0],before)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM review_state_requests WHERE request_id='fail'")[0]['n'],0)

    def test_routes_validation_and_owner(self):
        from flask import Flask
        from routes.words import words_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__);app.register_blueprint(words_bp)
        client=app.test_client();headers={'Authorization':'Bearer '+generate_token(1,'1')}
        self.assertEqual(client.post('/api/words/review/pause',json={'word_id':1,'request_id':'p'}).json['code'],401)
        self.assertEqual(client.post('/api/words/review/pause',json={'word_id':1,'request_id':'p'},headers=headers).json['code'],200)
        self.assertEqual(client.get('/api/words/review/paused',headers=headers).json['data']['total'],1)
        self.assertEqual(client.get('/api/words/review/paused?page=x',headers=headers).json['code'],400)
        self.assertEqual(client.post('/api/words/review/resume',json={'word_id':1,'request_id':'r'},headers=headers).json['code'],200)
        self.assertEqual(client.post('/api/words/master/reset',json={'word_id':2,'request_id':'reset'},headers=headers).json['code'],200)
        self.assertFalse(self.state_api.change(2,1,'pause','p')[0])
        self.assertFalse(self.state_api.change(1,True,'pause','p')[0])
        self.assertFalse(self.state_api.change(1,20,'pause','p20')[0])
