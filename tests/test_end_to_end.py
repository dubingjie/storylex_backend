"""通过真实Flask应用、鉴权和隔离MySQL验证跨模块完整流程。"""
import importlib
import io
import json
import unittest
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import patch
import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class EndToEndAcceptance(unittest.TestCase):
    context=base.StudyIntegration.__dict__['context']
    tearDownClass=base.StudyIntegration.__dict__['tearDownClass']
    sql=base.StudyIntegration.sql

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.application=importlib.import_module('app')
        cls.application.get_db=cls.context

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        self.sql("INSERT INTO books (id,title) VALUES ('CET6luan_1','注册默认词书'),('other','第二词书')")
        self.sql("UPDATE book_words SET book_trans=%s WHERE word_id=1",(json.dumps([{'pos':'adj','tranCn':'安静'}]),))
        self.sql("UPDATE book_words SET book_trans=%s WHERE word_id=2",(json.dumps([{'pos':'n','tranCn':'希望'}]),))
        self.app=self.application.create_app()
        self.app.config['TESTING']=True
        self.client=self.app.test_client()
        self.headers={}
        self.time=datetime(2026,10,16,16)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name in ('services.study_service','services.story_reading_service','services.page_service',
                     'services.review_state_service','services.ai_draft_service','services.story_service',
                     'services.txt_import_service','services.library_service','services.independent_practice_service'):
            module=importlib.import_module(name)
            module.get_db=self.context
            if hasattr(module,'study_now'):
                self.stack.enter_context(patch.object(module,'study_now',side_effect=lambda:self.time))
        registered=self.call('POST','/api/auth/register',{'username':'acceptance','password':'acceptance-test-password'})
        self.uid=registered['user_id'];self.headers={'Authorization':'Bearer '+registered['token']}
        self.call('PUT','/api/user/book',{'book_id':'test'})

    def call(self,method,path,body=None,code=200):
        response=self.client.open(path,method=method,json=body,headers=self.headers)
        self.assertIsNotNone(response.json,response.data[:200])
        self.assertEqual(response.json['code'],code,response.json)
        return response.json['data']

    def private_state(self,table,identifier):
        return json.loads(self.sql(f'SELECT state FROM {table} WHERE id=%s',(identifier,))[0]['state'])

    def test_learning_review_management_and_relogin(self):
        self.call('PUT','/api/words/target/update',{'task_type':'new','target_count':2})
        group=self.call('GET','/api/words/learn/group')
        self.assertEqual(group['total'],2)
        state=self.private_state('study_groups',group['group_id'])
        first=state['words'][str(group['words'][0]['word_id'])]
        wrong=next(k for k in 'ABCD' if k!=first['correct_key'])
        body={'group_id':group['group_id'],'word_id':first['word_id'],'question_id':first['question_id'],
              'request_id':'wrong','selected_key':wrong}
        result=self.call('POST','/api/words/learn/answer',body)
        self.assertFalse(result['is_correct']);self.assertIn('retry_question',result)
        self.call('POST','/api/words/learn/group/complete',{'group_id':group['group_id']},code=400)
        for i,w in enumerate(self.private_state('study_groups',group['group_id'])['words'].values()):
            self.call('POST','/api/words/learn/answer',{'group_id':group['group_id'],'word_id':w['word_id'],
                'question_id':w['question_id'],'request_id':'correct-'+str(i),'selected_key':w['correct_key']})
        self.call('POST','/api/words/learn/group/complete',{'group_id':group['group_id']})
        self.call('POST','/api/words/learn/group/complete',{'group_id':group['group_id']})
        self.assertEqual(self.call('GET','/api/words/dashboard/summary')['new_task']['learned_today'],2)
        self.assertEqual(self.call('GET','/api/words/review/queue')['total'],0)
        self.time=datetime(2026,10,17,0,0,1)
        review=self.call('GET','/api/words/review/queue');self.assertEqual(review['total'],2)
        words=list(self.private_state('study_groups',review['group_id'])['words'].values())
        w=words[0]
        answer={'group_id':review['group_id'],'word_id':w['word_id'],'question_id':w['question_id'],'request_id':'review','selected_key':w['correct_key']}
        self.call('POST','/api/words/review/answer',answer);self.call('POST','/api/words/review/answer',answer)
        paused=words[1]['word_id']
        self.call('POST','/api/words/review/pause',{'word_id':paused,'request_id':'pause'})
        self.assertEqual(self.call('GET','/api/words/review/paused')['total'],1)
        restored=self.call('POST','/api/words/review/resume',{'word_id':paused,'request_id':'resume'})
        self.assertEqual(restored['next_review_at'],'2026-10-18 00:00:00')
        self.call('POST','/api/words/master',{'word_id':paused})
        self.call('POST','/api/words/master/reset',{'word_id':paused,'request_id':'reset'})
        self.assertEqual(self.call('GET','/api/words/dashboard/summary')['review_task']['reviewed_today'],1)
        self.call('PUT','/api/user/book',{'book_id':'other'})
        login=self.call('POST','/api/auth/login',{'username':'acceptance','password':'acceptance-test-password'})
        self.headers={'Authorization':'Bearer '+login['token']}
        self.assertEqual(self.call('GET','/api/user/books')['current_book_id'],'other')
        self.assertEqual(self.call('GET','/api/user/stats')['total_learned_words'],2)

    def test_content_reading_autonomous_practice_and_data_sync(self):
        ai=importlib.import_module('services.ai_draft_service')
        with patch.object(ai.AIDraftService,'_model_text',return_value='# 故事\n她 <word id="1">word1</word>，带着 <word id="2">word2</word>。'):
            draft=self.call('POST','/api/ai/generate-story',{'request_id':'ai','word_ids':[1,2],'story_type':'日常'})
        self.assertEqual(self.call('GET','/api/stories/list?source_type=ai_generated')['total'],0)
        edited=self.call('PUT','/api/ai/drafts/'+draft['draft_id'],{'version':1,'title':'编辑后故事','processed_content':draft['processed_content']})
        saved=self.call('POST','/api/ai/drafts/'+draft['draft_id']+'/save',{'version':edited['version'],'request_id':'save'})
        sid=saved['story_id']
        self.call('PUT',f'/api/stories/{sid}/favorite',{'is_favorited':True})
        self.assertEqual(self.call('GET','/api/stories/list?scope=mine&category=favorites&keyword=编辑')['total'],1)
        self.call('PUT',f'/api/stories/{sid}/progress',{'progress':40,'position':5,'version':0})
        self.assertEqual(self.call('GET','/api/words/dashboard/summary')['last_story']['story_id'],sid)
        self.call('POST','/api/stories/complete',{'story_id':sid});self.call('POST','/api/stories/complete',{'story_id':sid})
        practice=self.call('GET',f'/api/stories/{sid}/practice')
        questions=self.private_state('story_practice_sessions',practice['session_id'])['questions']
        answers=[{'word_id':q['word_id'],'question_id':q['question_id'],'selected_key':next(k for k in 'ABCD' if k!=q['correct_key'])} for q in questions]
        score=self.call('POST',f'/api/stories/{sid}/practice/submit',{'request_id':'reading','session_id':practice['session_id'],'answers':answers})
        self.assertEqual(score['wrong_words_queued'],2)
        self.assertEqual(self.call('GET','/api/user/stats')['total_read_stories'],1)
        self.call('POST','/api/words/favorite/toggle',{'word_id':1,'source_type':'story'})
        before=self.sql('SELECT * FROM user_word_records WHERE user_id=%s ORDER BY word_id',(self.uid,))
        autonomous=self.call('POST','/api/user/favorites/practice',{'word_ids':[1],'request_id':'autonomous'})
        q=self.private_state('independent_practice_sessions',autonomous['session_id'])['questions'][0]
        self.call('POST','/api/words/practice/'+autonomous['session_id']+'/submit',{'request_id':'autonomous-submit','answers':[{'question_id':q['question_id'],'word_id':q['word_id'],'is_show_answer':True}]})
        self.assertEqual(self.sql('SELECT * FROM user_word_records WHERE user_id=%s ORDER BY word_id',(self.uid,)),before)
        self.assertEqual(self.call('GET','/api/words/dashboard/summary')['review_task']['reviewed_today'],0)
        imported=self.client.post('/api/ai/import-txt',headers=self.headers,data={'file':(io.BytesIO('她安静地带着希望出发。'.encode()),'验收.txt'),
             'target_book_id':'test','request_id':'txt','min_gap':'0'}).json
        self.assertEqual(imported['code'],200,imported)
        self.call('POST','/api/ai/drafts/'+imported['data']['draft_id']+'/save',{'version':1,'request_id':'txt-save'})
        self.assertEqual(self.call('GET','/api/stories/list?scope=mine&category=imported')['total'],1)
        self.call('PUT','/api/user/book',{'book_id':'other'})
        login=self.call('POST','/api/auth/login',{'username':'acceptance','password':'acceptance-test-password'})
        self.headers={'Authorization':'Bearer '+login['token']}
        self.assertEqual(self.call('GET',f'/api/stories/{sid}/progress')['progress'],40)
        self.assertEqual(self.call('GET','/api/user/favorites')['total'],1)
        self.time=datetime(2026,10,17,0,0,1)
        self.assertEqual(self.call('GET','/api/words/review/queue')['total'],2)

    def test_malformed_inputs_return_business_errors(self):
        for path in ('/api/auth/register','/api/auth/login'):
            self.call('POST',path,{'username':123,'password':[]},code=400)
            self.call('POST',path,[],code=400)
        self.call('GET','/api/words/book/list?page=abc',code=400)

        for path in ('/api/words/favorite/toggle','/api/words/target/update','/api/stories/complete'):
            self.call('POST' if path!='/api/words/target/update' else 'PUT',path,[],code=400)
        self.call('POST','/api/words/favorite/toggle',{'word_id':True},code=400)
        self.call('POST','/api/words/favorite/toggle',{'word_id':1,'source_type':'invalid'},code=400)
        self.call('POST','/api/stories/complete',{'story_id':[1]},code=400)
        self.call('GET','/api/words/favorite/list?page=-1',code=400)
        self.call('GET','/api/words/book/list?filter=invalid',code=400)
