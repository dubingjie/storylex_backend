"""阅读闭环集成测试，沿用隔离数据库 fixture，绝不读取业务数据库连接。"""
import importlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试 MySQL socket')
class ReadingIntegration(unittest.TestCase):
    context = base.StudyIntegration.__dict__['context']
    tearDownClass = base.StudyIntegration.__dict__['tearDownClass']
    sql = base.StudyIntegration.sql
    group = base.StudyIntegration.group

    @classmethod
    def setUpClass(cls):
        base.StudyIntegration.setUpClass.__func__(cls)
        cls.reading = importlib.import_module('services.story_reading_service')
        cls.reading.get_db = cls.context
        cls.reading.locked_user = cls.module.locked_user
        cls.api = cls.reading.StoryReadingService
        cls.story_module = importlib.import_module('services.story_service')
        cls.story_module.get_db = cls.context
        cls.story_module.StoryReadingService = cls.api
        library = importlib.import_module('services.library_service')
        library.get_db = cls.context
        library.locked_user = cls.module.locked_user

    def setUp(self):
        base.StudyIntegration.setUp(self)
        self.read_clock = patch.object(self.reading, 'study_now', return_value=datetime(2026, 10, 16, 16))
        self.read_clock.start()
        self.addCleanup(self.read_clock.stop)
        self.sql("INSERT INTO stories (id,title,source_type,target_book_id,original_content) VALUES (1,'test','builtin','test','text'),(2,'empty','builtin','test','text')")
        self.sql("INSERT INTO stories (id,title,source_type,user_id,target_book_id,original_content) VALUES (3,'private','imported',2,'test','text')")
        for wid in (1,2,3):
            self.sql('INSERT INTO story_words (story_id,word_id,word_order) VALUES (1,%s,%s)',(wid,4-wid))

    def practice(self):
        result = self.api.practice(1,1)
        self.assertTrue(result[0],result)
        return result[2]

    def state(self, sid):
        return json.loads(self.sql('SELECT state FROM story_practice_sessions WHERE id=%s',(sid,))[0]['state'])

    def answers(self, session, wrong=()):
        answers=[]
        for q in self.state(session['session_id'])['questions']:
            key = q['correct_key'] if q['word_id'] not in wrong else next(k for k in 'ABCD' if k != q['correct_key'])
            answers.append({'word_id':q['word_id'],'question_id':q['question_id'],'selected_key':key})
        return answers

    def submit(self, session, answers, rid='submit-1'):
        return self.api.submit(1,1,session['session_id'],rid,answers)

    def test_vocabulary_order_flags_fallback_and_detail(self):
        self.sql("INSERT INTO books (id,title) VALUES ('other','其他词书')")
        self.sql("UPDATE book_words SET book_id='other' WHERE word_id=1")
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,next_review_at) VALUES (1,2,'mastered','2026-10-17')")
        self.sql("INSERT INTO user_favorite_words (user_id,word_id,source_type) VALUES (1,3,'story')")
        result = self.api.vocabulary(1,1)
        self.assertTrue(result[0],result)
        words=result[2]['words']
        self.assertEqual([w['word_id'] for w in words],[3,2,1])
        self.assertTrue(words[0]['is_favorited'])
        self.assertTrue(words[1]['is_learned'])
        self.assertTrue(words[1]['is_mastered'])
        self.assertTrue(words[2]['is_out_of_book'])
        self.assertEqual(words[2]['translation_book_id'],'other')
        self.assertTrue(words[2]['translations'])
        detail=self.story_module.StoryService.get_story_detail(1,1)
        self.assertTrue(detail[0],detail)
        self.assertEqual(detail[2]['embedded_words'],words)
        self.assertIsNone(detail[2]['last_practice_score'])

    def test_server_grading_replay_and_complete_unchanged(self):
        session=self.practice()
        self.assertEqual(session,self.practice())
        self.assertTrue(all('correct_key' not in q for q in session['questions']))
        answers=self.answers(session,wrong=(1,))
        result=self.submit(session,answers)
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['score'],67)
        self.assertEqual(result[2]['wrong_words_queued'],1)
        row=self.sql('SELECT status,stage,wrong_count,next_review_at FROM user_word_records')[0]
        self.assertEqual(row,{'status':'reviewing','stage':0,'wrong_count':1,'next_review_at':datetime(2026,10,17)})
        self.assertEqual(result[2],self.submit(session,list(reversed(answers)),'another-id')[2])
        self.assertEqual(self.sql('SELECT wrong_count FROM user_word_records')[0]['wrong_count'],1)
        record=self.sql('SELECT last_practice_score,is_completed,completed_at FROM user_story_records')[0]
        self.assertEqual(record,{'last_practice_score':67,'is_completed':0,'completed_at':None})
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM daily_review_words')[0]['n'],0)
        changed=self.answers(session,wrong=(2,))
        self.assertFalse(self.submit(session,changed)[0])
        self.assertNotEqual(session['session_id'],self.practice()['session_id'])

    def test_preserve_stage_mastery_and_earlier_due(self):
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,stage,proficiency,next_review_at) VALUES (1,1,'reviewing',4,70,'2026-11-01'),(1,2,'mastered',7,100,'2026-11-01'),(1,3,'learning',2,30,'2026-10-16')")
        before=self.sql('SELECT * FROM user_word_records WHERE word_id=2')[0]
        self.sql("INSERT INTO user_story_records (user_id,story_id,is_completed,completed_at) VALUES (1,1,1,'2026-10-15')")
        session=self.practice()
        result=self.submit(session,self.answers(session,wrong=(1,2,3)))
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['wrong_words_queued'],2)
        self.assertEqual(self.sql('SELECT * FROM user_word_records WHERE word_id=2')[0],before)
        row=self.sql('SELECT stage,proficiency,next_review_at FROM user_word_records WHERE word_id=1')[0]
        self.assertEqual(row,{'stage':4,'proficiency':70,'next_review_at':datetime(2026,10,17)})
        self.assertEqual(self.sql('SELECT next_review_at FROM user_word_records WHERE word_id=3')[0]['next_review_at'],datetime(2026,10,16))
        self.assertEqual(self.sql('SELECT is_completed,completed_at FROM user_story_records')[0],{'is_completed':1,'completed_at':datetime(2026,10,15)})

    def test_permissions_empty_missing_and_invalid_answers(self):
        for story_id in (3,999,0):
            self.assertFalse(self.api.vocabulary(1,story_id)[0])
            self.assertFalse(self.api.practice(1,story_id)[0])
        self.assertEqual(self.api.practice(1,2)[2]['total'],0)
        self.sql('DELETE FROM book_words WHERE word_id=1')
        session=self.practice()
        self.assertEqual(session['skipped_word_ids'],[1])
        self.assertEqual(session['total'],2)
        answers=self.answers(session)
        bad=[[],answers[:-1],answers+[answers[0]], [{'word_id':True,'question_id':'q','selected_key':'A'}],
             [dict(a,is_correct=True) for a in answers], [dict(a,selected_key='Z') for a in answers],
             [dict(a,question_id='unknown') for a in answers], [dict(a,word_id=20) for a in answers]]
        for case in bad:
            self.assertFalse(self.submit(session,case)[0],case)
        self.assertFalse(self.api.submit(2,1,session['session_id'],'r',answers)[0])
        self.assertFalse(self.api.submit(1,2,session['session_id'],'r',answers)[0])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],0)

    def test_concurrent_creation_and_submit(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            sessions=list(pool.map(lambda _:self.practice(),range(2)))
        self.assertEqual(sessions[0]['session_id'],sessions[1]['session_id'])
        session=sessions[0]
        answers=self.answers(session,wrong=(1,2,3))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.submit(session,answers),range(2)))
        self.assertTrue(all(r[0] for r in results),results)
        self.assertEqual(results[0][2],results[1][2])
        self.assertTrue(all(r['wrong_count']==1 for r in self.sql('SELECT wrong_count FROM user_word_records')))

    def test_rollback_and_crossday(self):
        session=self.practice()
        answers=self.answers(session,wrong=(1,2,3))
        original=self.api._queue_wrong
        def fail_second(cursor,uid,wid,now):
            if wid==2:
                raise RuntimeError('injected failure')
            return original(cursor,uid,wid,now)
        with patch.object(self.api,'_queue_wrong',side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.submit(session,answers)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT status FROM story_practice_sessions')[0]['status'],'active')
        with patch.object(self.reading,'study_now',return_value=datetime(2026,10,17)):
            self.assertFalse(self.submit(session,answers)[0])
            self.assertNotEqual(session['session_id'],self.practice()['session_id'])
        self.assertTrue(self.submit(session,answers)[0])
        with patch.object(self.reading,'study_now',return_value=datetime(2026,10,17)):
            self.assertTrue(self.submit(session,answers)[0])

    def test_out_of_book_wrong_reaches_formal_review(self):
        self.sql("INSERT INTO books (id,title) VALUES ('other','其他词书')")
        self.sql("UPDATE book_words SET book_id='other' WHERE word_id=1")
        session=self.practice()
        self.assertTrue(self.submit(session,self.answers(session,wrong=(1,)))[0])
        with patch.object(self.module,'study_now',return_value=datetime(2026,10,17)):
            group=self.group('review')
            self.assertEqual([w['word_id'] for w in group['words']],[1])

    def test_routes_auth_and_body(self):
        from flask import Flask
        from routes.stories import stories_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__)
        app.register_blueprint(stories_bp)
        client=app.test_client()
        headers={'Authorization':'Bearer '+generate_token(1,'1')}
        self.assertEqual(client.get('/api/stories/1/vocabulary').json['code'],401)
        self.assertEqual(client.get('/api/stories/1/vocabulary',headers=headers).json['code'],200)
        session=client.get('/api/stories/1/practice',headers=headers).json['data']
        self.assertEqual(client.post('/api/stories/1/practice/submit',json=[],headers=headers).json['code'],400)
        answers=self.answers(session)
        answers[0]['selected_key']=None
        answers[0]['is_show_answer']=True
        result=client.post('/api/stories/1/practice/submit',json={'session_id':session['session_id'],'request_id':'r','answers':answers},headers=headers).json
        self.assertEqual(result['code'],200,result)
        self.assertEqual(result['data']['wrong_count'],1)
