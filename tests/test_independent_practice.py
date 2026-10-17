import importlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class IndependentPracticeIntegration(unittest.TestCase):
    context=base.StudyIntegration.__dict__['context']
    tearDownClass=base.StudyIntegration.__dict__['tearDownClass']
    sql=base.StudyIntegration.sql

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.practice_module=importlib.import_module('services.independent_practice_service')
        cls.practice_module.get_db=cls.context
        cls.practice_module.locked_user=cls.module.locked_user
        cls.practice_api=cls.practice_module.IndependentPracticeService

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        self.sql('INSERT INTO user_favorite_words (user_id,word_id) VALUES (1,1),(1,2),(2,3)')
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,stage,next_review_at) VALUES (1,1,'mastered',7,'2026-11-01'),(1,2,'reviewing',3,'2026-11-01')")

    def create(self,source='favorites',mode='mixed',rid='create'):
        result=self.practice_api.create(1,source,[1,2],rid,mode)
        self.assertTrue(result[0],result)
        return result[2]

    def answers(self,session,wrong=()):
        state=json.loads(self.sql('SELECT state FROM independent_practice_sessions WHERE id=%s',(session['session_id'],))[0]['state'])
        return [{'question_id':q['question_id'],'word_id':q['word_id'],
                 'selected_key':q['correct_key'] if q['word_id'] not in wrong else next(k for k in 'ABCD' if k!=q['correct_key'])}
                for q in state['questions']]

    def test_mixed_and_directional_no_answer_leak(self):
        session=self.create()
        self.assertEqual({q['question_type'] for q in session['questions']},{'en_to_zh','zh_to_en'})
        for q in session['questions']:
            self.assertNotIn('correct_key',q)
            self.assertNotIn('word_detail',q)
            self.assertEqual(len({o['text'] for o in q['options']}),4)
            if q['question_type']=='zh_to_en':
                self.assertNotIn('us_phone',q)
                self.assertNotIn('word',q)
        for mode in ('en_to_zh','zh_to_en'):
            one=self.create(mode=mode,rid=mode)
            self.assertEqual({q['question_type'] for q in one['questions']},{mode})
        self.assertEqual(self.create()['session_id'],session['session_id'])
        self.assertFalse(self.practice_api.create(1,'favorites',[1],'create')[0])

    def test_grade_replay_and_formal_tables_unchanged(self):
        before=self.sql('SELECT * FROM user_word_records ORDER BY id')
        favorites=self.sql('SELECT * FROM user_favorite_words ORDER BY id')
        session=self.create()
        answers=self.answers(session,wrong=(1,))
        result=self.practice_api.submit(1,session['session_id'],'submit',answers)
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['score'],50)
        self.assertEqual(result[2]['wrong_word_ids'],[1])
        replay=self.practice_api.submit(1,session['session_id'],'other',list(reversed(answers)))
        self.assertEqual(result[2],replay[2])
        self.assertFalse(self.practice_api.submit(1,session['session_id'],'other',self.answers(session,wrong=(2,)))[0])
        self.assertEqual(self.sql('SELECT * FROM user_word_records ORDER BY id'),before)
        self.assertEqual(self.sql('SELECT * FROM user_favorite_words ORDER BY id'),favorites)
        for table in ('user_study_stats','daily_review_words','user_story_records','study_groups'):
            self.assertEqual(self.sql(f'SELECT COUNT(*) AS n FROM {table}')[0]['n'],0)
        self.assertEqual(self.practice_api.get(1,session['session_id'])[2]['result'],result[2])

    def test_permissions_membership_and_validation(self):
        self.assertFalse(self.practice_api.create(1,'favorites',[3],'r')[0])
        self.assertFalse(self.practice_api.create(1,'learn',[3],'r')[0])
        for words in ([],[True],['1'],[1]*21):
            self.assertFalse(self.practice_api.create(1,'favorites',words,'r')[0])
        self.assertFalse(self.practice_api.create(1,'favorites',[1],'r',mode='bad')[0])
        session=self.create()
        self.assertFalse(self.practice_api.get(2,session['session_id'])[0])
        self.assertFalse(self.practice_api.submit(2,session['session_id'],'r',self.answers(session))[0])
        answers=self.answers(session)
        for bad in ([],answers[:1],answers+[answers[0]],[dict(a,is_correct=True) for a in answers],
                    [dict(a,word_id=20) for a in answers],[dict(a,selected_key='Z') for a in answers]):
            self.assertFalse(self.practice_api.submit(1,session['session_id'],'r',bad)[0],bad)

    def test_concurrent_create_and_submit(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            sessions=list(pool.map(lambda _:self.create(),range(2)))
        self.assertEqual(sessions[0]['session_id'],sessions[1]['session_id'])
        answers=self.answers(sessions[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.practice_api.submit(1,sessions[0]['session_id'],'s',answers),range(2)))
        self.assertTrue(all(r[0] for r in results),results)
        self.assertEqual(results[0][2],results[1][2])

    def test_learn_group_membership_and_fallback(self):
        self.assertTrue(self.create(source='learn')['questions'])
        self.assertFalse(self.practice_api.create(1,'learn',[1,2],'group',group_id='missing')[0])
        state=json.dumps({'words':{'1':{},'2':{}}})
        self.sql("INSERT INTO study_groups (id,user_id,book_id,task_type,study_date,status,state,created_at) VALUES ('done',1,'test','learn','2026-10-16','completed',%s,'2026-10-16')",(state,))
        self.assertTrue(self.practice_api.create(1,'learn',[1,2],'group',group_id='done')[0])
        self.sql("INSERT INTO books (id,title) VALUES ('other','other')")
        self.sql("UPDATE book_words SET book_id='other' WHERE word_id=1")
        session=self.create(rid='fallback')
        self.assertEqual(session['total'],2)

    def test_cancel_favorite_or_switch_does_not_destroy_snapshot(self):
        session=self.create()
        self.sql('DELETE FROM user_favorite_words WHERE user_id=1')
        self.sql("INSERT INTO books (id,title) VALUES ('other','other')")
        self.sql("UPDATE users SET current_book_id='other' WHERE id=1")
        self.assertEqual(self.create()['session_id'],session['session_id'])
        answers=self.answers(session)
        answers[0]['selected_key']=None;answers[0]['is_show_answer']=True
        result=self.practice_api.submit(1,session['session_id'],'s',answers)
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['wrong_count'],1)
        self.assertFalse(self.practice_api.create(1,'favorites',[1,2],'new')[0])

    def test_routes(self):
        from flask import Flask
        from routes.user import user_bp
        from routes.words import words_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__);app.register_blueprint(user_bp);app.register_blueprint(words_bp)
        client=app.test_client();headers={'Authorization':'Bearer '+generate_token(1,'1')}
        payload={'word_ids':[1,2],'request_id':'route'}
        self.assertEqual(client.post('/api/user/favorites/practice',json=payload).json['code'],401)
        session=client.post('/api/user/favorites/practice',json=payload,headers=headers).json['data']
        path='/api/words/practice/'+session['session_id']
        self.assertEqual(client.get(path,headers=headers).json['code'],200)
        self.assertEqual(client.post(path+'/submit',json={'request_id':'s','answers':self.answers(session)},headers=headers).json['code'],200)
        self.assertEqual(client.post('/api/words/learn/group/practice',json=payload,headers=headers).json['code'],200)
        self.assertEqual(client.post('/api/words/learn/group/practice',json=[],headers=headers).json['code'],400)

    def test_no_placeholder_choices_when_dictionary_insufficient(self):
        self.sql('DELETE FROM book_words WHERE word_id>2')
        self.assertFalse(self.practice_api.create(1,'favorites',[1,2],'insufficient')[0])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM independent_practice_sessions')[0]['n'],0)
