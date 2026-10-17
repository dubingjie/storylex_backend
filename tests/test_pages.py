"""第三批页面接口集成测试，复用独立MySQL库fixture。"""
import importlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch
import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class PageIntegration(unittest.TestCase):
    context = base.StudyIntegration.__dict__['context']
    tearDownClass = base.StudyIntegration.__dict__['tearDownClass']
    sql = base.StudyIntegration.sql
    group = base.StudyIntegration.group

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.pages = importlib.import_module('services.page_service')
        cls.pages.get_db = cls.context
        cls.pages.locked_user = cls.module.locked_user
        cls.api_pages = cls.pages.PageService
        cls.old = importlib.import_module('services.user_service')
        cls.old.get_db = cls.context

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        self.page_clock = patch.object(self.pages, 'study_now', return_value=datetime(2026,10,16,16))
        self.page_clock.start()
        self.addCleanup(self.page_clock.stop)
        self.sql("INSERT INTO books (id,title) VALUES ('other','其他词书')")
        self.sql("INSERT INTO book_words (book_id,word_id,word_rank) VALUES ('other',1,1)")

    def test_books_switch_and_scoped_legacy_progress(self):
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,next_review_at) VALUES (1,1,'mastered','2026-10-17'),(1,2,'learning','2026-10-17')")
        books=self.api_pages.books(1)[2]['books']
        other=next(b for b in books if b['book_id']=='other')
        self.assertEqual(other['total_words'],1)
        self.assertEqual(other['learned_words'],1)
        self.assertTrue(self.api_pages.switch_book(1,'other')[0])
        self.assertEqual(self.sql('SELECT current_book_id FROM users WHERE id=1')[0]['current_book_id'],'other')
        self.assertFalse(self.api_pages.switch_book(1,'missing')[0])
        old=self.old.UserService.get_dashboard_stats(1)
        self.assertTrue(old[0],old)
        self.assertEqual(old[2]['word_distribution'],{'mastered':1,'learning':0,'unlearned':0})
        self.assertEqual(old[2]['book']['progress_percent'],100)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],2)

    def test_stats_unique_days_and_global_counts(self):
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,next_review_at,created_at) VALUES (1,1,'mastered','2026-10-17','2026-10-14'),(1,2,'learning','2026-10-17','2026-10-14')")
        self.sql("INSERT INTO user_study_stats (user_id,study_date,new_learned_count) VALUES (1,'2026-10-14',2),(1,'2026-10-15',1),(1,'2026-10-16',0)")
        self.sql("INSERT INTO user_story_records (user_id,story_id,is_completed,completed_at) VALUES (1,1,1,'2026-10-15')")
        self.assertEqual(self.api_pages.stats(1)[2],{'total_study_days':2,'total_learned_words':2,'total_mastered_words':1,'total_read_stories':1})
        self.api_pages.switch_book(1,'other')
        self.assertEqual(self.api_pages.stats(1)[2]['total_learned_words'],2)

    def test_progress_defaults_replay_conflict_and_manual_completion(self):
        self.assertEqual(self.api_pages.get_progress(1,1)[2]['version'],0)
        first=self.api_pages.save_progress(1,1,40.5,30,0)
        self.assertTrue(first[0],first)
        self.assertEqual(first[2]['version'],1)
        self.assertEqual(self.api_pages.save_progress(1,1,40.5,30,0)[2],first[2])
        self.assertFalse(self.api_pages.save_progress(1,1,20,10,0)[0])
        self.assertTrue(self.api_pages.save_progress(1,1,100,100,1)[0])
        self.assertEqual(self.api_pages.stats(1)[2]['total_read_stories'],0)
        last=self.api_pages.dashboard(1)[2]['last_story']
        self.assertEqual(last['story_id'],1)
        self.assertEqual(last['progress'],100)
        self.sql('INSERT INTO user_story_records (user_id,story_id,is_completed) VALUES (1,1,1)')
        self.assertIsNone(self.api_pages.dashboard(1)[2]['last_story'])

    def test_progress_concurrency_privacy_and_validation(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda n:self.api_pages.save_progress(1,1,n,n,0),[10,20]))
        self.assertEqual(sum(r[0] for r in results),1)
        self.assertEqual(self.api_pages.get_progress(1,1)[2]['version'],1)
        self.assertFalse(self.api_pages.save_progress(1,3,20,20,0)[0])
        self.assertFalse(self.api_pages.get_progress(1,3)[0])
        for progress,position,version in [(True,0,0),(float('inf'),0,0),(101,0,0),(0,-1,0),(0,0,True)]:
            self.assertFalse(self.api_pages.save_progress(1,1,progress,position,version)[0])
        self.assertEqual(self.api_pages.get_progress(2,1)[2]['version'],0)

    def test_batch_delete_ownership_and_learning_unchanged(self):
        self.sql("INSERT INTO user_favorite_words (user_id,word_id) VALUES (1,1),(1,2),(2,1)")
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,next_review_at) VALUES (1,1,'reviewing','2026-10-17')")
        before=self.sql('SELECT * FROM user_word_records')
        self.assertEqual(self.api_pages.batch_delete_favorites(1,[1,1,20])[2]['deleted_count'],1)
        self.assertEqual(self.api_pages.batch_delete_favorites(1,[1])[2]['deleted_count'],0)
        self.assertEqual(self.sql('SELECT * FROM user_word_records'),before)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_favorite_words WHERE user_id=2')[0]['n'],1)
        for ids in ([],[True],['1'],[1]*201):
            self.assertFalse(self.api_pages.batch_delete_favorites(1,ids)[0])

    def test_dashboard_targets_pending_and_active_group(self):
        result=self.api_pages.dashboard(1)[2]
        self.assertIsNone(result['last_story'])
        self.assertEqual(result['new_task']['available_count'],20)
        self.assertFalse(result['review_task']['can_start'])
        group=self.group()
        # 全组点熟后仍应允许进入活动题组结算，即使词书中无其他可学词。
        for w in group['words']:
            self.assertTrue(self.service.master(1,w['word_id'],group['group_id'])[0])
        self.sql('DELETE FROM book_words WHERE book_id=%s AND word_id>10',('test',))
        result=self.api_pages.dashboard(1)[2]
        self.assertEqual(result['new_task']['available_count'],0)
        self.assertTrue(result['new_task']['can_start'])
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,next_review_at) VALUES (1,11,'reviewing','2026-10-16')")
        self.sql("INSERT INTO book_words (book_id,word_id,book_trans) VALUES ('other',11,%s)",('[{"tranCn":"释义"}]',))
        self.assertEqual(self.api_pages.dashboard(1)[2]['review_task']['due_count'],1)
        self.sql("INSERT INTO daily_review_words (user_id,word_id,study_date) VALUES (1,11,'2026-10-16')")
        self.assertEqual(self.api_pages.dashboard(1)[2]['review_task']['due_count'],0)

    def test_switch_blocks_old_answers_and_keeps_counts(self):
        group=self.group()
        self.api_pages.switch_book(1,'other')
        state=__import__('json').loads(self.sql('SELECT state FROM study_groups WHERE id=%s',(group['group_id'],))[0]['state'])
        word=state['words'][str(group['words'][0]['word_id'])]
        result=self.service.answer(1,'learn',group['group_id'],word['word_id'],word['question_id'],'r',word['correct_key'])
        self.assertFalse(result[0])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)

    def test_routes(self):
        from flask import Flask
        from routes.user import user_bp
        from routes.words import words_bp
        from routes.stories import stories_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__)
        for bp in (user_bp,words_bp,stories_bp):
            app.register_blueprint(bp)
        client=app.test_client()
        headers={'Authorization':'Bearer '+generate_token(1,'1')}
        for path in ('/api/user/stats','/api/user/books','/api/user/favorites','/api/words/dashboard/summary','/api/stories/1/progress'):
            self.assertEqual(client.get(path).json['code'],401)
            self.assertEqual(client.get(path,headers=headers).json['code'],200,path)
        for path in ('/api/user/favorites?page=x','/api/user/favorites?page=0','/api/user/favorites?page_size=999'):
            self.assertEqual(client.get(path,headers=headers).json['code'],400)
        self.assertEqual(client.put('/api/user/book',json={'book_id':'other'},headers=headers).json['code'],200)
        self.assertEqual(client.post('/api/user/favorites/batch-delete',json={'word_ids':[1]},headers=headers).json['code'],200)
        self.assertEqual(client.put('/api/stories/1/progress',json={'progress':30,'position':20,'version':0},headers=headers).json['code'],200)
