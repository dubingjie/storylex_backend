import importlib
import unittest
from concurrent.futures import ThreadPoolExecutor
import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class LibraryIntegration(unittest.TestCase):
    context = base.StudyIntegration.__dict__['context']
    tearDownClass = base.StudyIntegration.__dict__['tearDownClass']
    sql = base.StudyIntegration.sql

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.lib=importlib.import_module('services.library_service').LibraryService

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        self.sql("INSERT INTO stories (id,title,source_type,user_id,target_book_id,original_content) VALUES (4,'我的AI故事','ai_generated',1,'test','text'),(5,%s,'imported',1,'test','text')", ('导入100%_文章',))

    def listing(self,**kwargs):
        result=self.lib.list_stories(1,**kwargs)
        self.assertTrue(result[0],result)
        return result[2]

    def test_scope_categories_and_legacy(self):
        self.assertEqual(self.listing()['total'],4)
        self.assertEqual(self.listing(scope='mine')['total'],2)
        self.assertEqual(self.listing(scope='recommended')['total'],2)
        self.assertEqual(self.listing(category='imported')['list'][0]['story_id'],5)
        self.assertEqual(self.listing(source_type='ai_generated')['total'],1)
        self.assertEqual(self.listing(source_type='builtin',category='imported')['total'],0)
        self.assertTrue(self.lib.set_favorite(1,1,True)[0])
        self.assertEqual(self.listing(scope='mine')['total'],3)
        self.assertEqual(self.listing(scope='mine',category='favorites')['list'][0]['story_id'],1)
        self.assertEqual(self.listing(scope='recommended',category='favorites')['total'],1)

    def test_literal_search_and_pagination(self):
        self.assertEqual(self.listing(keyword='%_')['total'],1)
        self.assertEqual(self.listing(keyword='AI')['total'],1)
        self.assertEqual(self.listing(keyword="' OR 1=1 --")['total'],0)
        first=self.listing(page_size=1)
        second=self.listing(page=2,page_size=1)
        self.assertEqual(first['total'],second['total'])
        self.assertNotEqual(first['list'][0]['story_id'],second['list'][0]['story_id'])
        self.assertEqual(self.listing(page=100)['list'],[])

    def test_favorite_idempotency_concurrency_and_detail(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.lib.set_favorite(1,1,True),range(2)))
        self.assertTrue(all(r[0] for r in results),results)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_favorite_stories')[0]['n'],1)
        detail=self.story_module.StoryService.get_story_detail(1,1)
        self.assertTrue(detail[2]['is_favorited'])
        for _ in range(2):
            self.assertTrue(self.lib.set_favorite(1,1,False)[0])
        self.assertEqual(self.listing(category='favorites')['total'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_story_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)

    def test_access_ownership_and_invalid(self):
        self.assertFalse(self.lib.set_favorite(1,3,True)[0])
        self.assertFalse(self.lib.set_favorite(1,999,True)[0])
        self.assertTrue(self.lib.set_favorite(2,1,True)[0])
        self.lib.set_favorite(1,1,False)
        self.assertEqual(self.listing(category='favorites')['total'],0)
        self.assertEqual(self.lib.list_stories(2,category='favorites')[2]['total'],1)
        for value in ('true',1,None):
            self.assertFalse(self.lib.set_favorite(1,1,value)[0])
        for kwargs in ({'page':0},{'page_size':101},{'page':True},{'scope':'bad'},{'category':'bad'},{'source_type':'bad'},{'keyword':'a'*151}):
            self.assertFalse(self.lib.list_stories(1,**kwargs)[0])

    def test_routes(self):
        from flask import Flask
        from routes.stories import stories_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__);app.register_blueprint(stories_bp)
        client=app.test_client()
        headers={'Authorization':'Bearer '+generate_token(1,'1')}
        self.assertEqual(client.put('/api/stories/1/favorite',json={'is_favorited':True}).json['code'],401)
        self.assertEqual(client.put('/api/stories/1/favorite',json={'is_favorited':True},headers=headers).json['code'],200)
        self.assertEqual(client.get('/api/stories/list?scope=mine&category=favorites',headers=headers).json['data']['total'],1)
        self.assertEqual(client.get('/api/stories/list?page=abc',headers=headers).json['code'],400)
        self.assertEqual(client.put('/api/stories/1/favorite',json=[],headers=headers).json['code'],400)
