"""AI草稿集成测试；模型响应固定mock，不消耗模型额度。"""
import importlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class AIDraftIntegration(unittest.TestCase):
    context = base.StudyIntegration.__dict__['context']
    tearDownClass = base.StudyIntegration.__dict__['tearDownClass']
    sql = base.StudyIntegration.sql

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.ai = importlib.import_module('services.ai_draft_service')
        cls.ai.get_db = cls.context
        cls.ai.locked_user = cls.module.locked_user
        cls.api_ai = cls.ai.AIDraftService

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        self.model = patch.object(self.api_ai, '_model_text', return_value='# 测试标题\n他选择 <word id="2">word2</word>，然后 <word id="1">word1</word>，又 <word id="2">word2</word>。')
        self.mock_model = self.model.start()
        self.addCleanup(self.model.stop)

    def generate(self, rid='generate-1'):
        result = self.api_ai.generate(1,[1,2],rid,'都市小说')
        self.assertTrue(result[0],result)
        return result[2]

    def test_preview_is_separate_and_save_uses_actual_order(self):
        before=self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n']
        draft=self.generate()
        self.assertEqual(draft['status'],'ready')
        self.assertIsNone(draft['story_id'])
        self.assertEqual(draft['embedded_word_count'],2)
        self.assertEqual(draft['embedded_occurrences'],3)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before)
        saved=self.api_ai.save(1,draft['draft_id'],'save-1',draft['version'])
        self.assertTrue(saved[0],saved)
        sid=saved[2]['story_id']
        words=self.sql('SELECT word_id,word_order FROM story_words WHERE story_id=%s ORDER BY word_order',(sid,))
        self.assertEqual(words,[{'word_id':2,'word_order':1},{'word_id':1,'word_order':2}])
        detail=self.story_module.StoryService.get_story_detail(1,sid)
        self.assertTrue(detail[0],detail)
        self.assertEqual([w['word_id'] for w in detail[2]['embedded_words']],[2,1])
        listing=self.story_module.StoryService.get_story_list(1,source_type='ai_generated')
        self.assertEqual(listing[2]['total'],1)
        self.assertEqual(self.sql('SELECT original_content FROM stories WHERE id=%s',(sid,))[0]['original_content'],'他选择 word2，然后 word1，又 word2。')
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)

    def test_edit_version_replay_removed_target_and_save(self):
        draft=self.generate()
        content='修改后 <word id="1">word1</word> 和 <word id="1">word1</word>。'
        edit=self.api_ai.edit(1,draft['draft_id'],'新标题',content,1)
        self.assertTrue(edit[0],edit)
        self.assertEqual(edit[2]['version'],2)
        self.assertEqual(edit[2]['missing_word_ids'],[2])
        self.assertEqual(self.api_ai.edit(1,draft['draft_id'],'新标题',content,1)[2],edit[2])
        self.assertFalse(self.api_ai.edit(1,draft['draft_id'],'不同标题',content,1)[0])
        self.assertFalse(self.api_ai.save(1,draft['draft_id'],'s',1)[0])
        result=self.api_ai.save(1,draft['draft_id'],'s',2)
        self.assertTrue(result[0],result)
        self.assertEqual(result[2]['embedded_word_count'],1)
        self.assertFalse(self.api_ai.edit(1,draft['draft_id'],'不能修改',content,3)[0])

    def test_concurrent_generation_reserves_one_draft(self):
        entered,release=Event(),Event()
        def model(*args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test timeout')
            return '# 标题\n<word id="1">word1</word><word id="2">word2</word>'
        self.mock_model.side_effect=model
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(self.api_ai.generate,1,[1,2],'same','都市小说')
            try:
                self.assertTrue(entered.wait(5))
                second=self.api_ai.generate(1,[1,2],'same','都市小说')
                self.assertTrue(second[0],second)
                self.assertEqual(second[2]['status'],'generating')
            finally:
                release.set()
            first=future.result(timeout=10)
        self.assertEqual(first[2]['draft_id'],second[2]['draft_id'])
        self.assertEqual(self.mock_model.call_count,1)
        self.assertFalse(self.api_ai.generate(1,[1,3],'same','都市小说')[0])
        self.assertEqual(self.api_ai.generate(1,[2,1],'same','都市小说')[2]['status'],'ready')

    def test_concurrent_save_and_transaction_rollback(self):
        draft=self.generate()
        original=self.ai.write_state
        def fail(cursor,draft_id,status,*args,**kwargs):
            if status=='saved':
                raise RuntimeError('injected failure')
            return original(cursor,draft_id,status,*args,**kwargs)
        before=self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n']
        with patch.object(self.ai,'write_state',side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.api_ai.save(1,draft['draft_id'],'s',1)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before)
        self.assertEqual(self.api_ai.get(1,draft['draft_id'])[2]['status'],'ready')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda n:self.api_ai.save(1,draft['draft_id'],'save-'+str(n),1),range(2)))
        self.assertTrue(all(r[0] for r in results),results)
        self.assertEqual(results[0][2],results[1][2])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before+1)

    def test_permissions_validation_and_book_snapshot(self):
        draft=self.generate()
        self.assertFalse(self.api_ai.get(2,draft['draft_id'])[0])
        self.assertFalse(self.api_ai.save(2,draft['draft_id'],'s',1)[0])
        self.assertFalse(self.api_ai.edit(2,draft['draft_id'],'标题','<word id="1">word1</word>',1)[0])
        for ids in ([True,2],[1],[1,1],[1,999],[1]*21):
            self.assertFalse(self.api_ai.generate(1,ids,'bad','主题')[0])
        self.sql("INSERT INTO books (id,title) VALUES ('other','other')")
        self.sql("UPDATE users SET current_book_id='other' WHERE id=1")
        saved=self.api_ai.save(1,draft['draft_id'],'s',1)
        self.assertTrue(saved[0],saved)
        self.assertEqual(self.sql('SELECT target_book_id FROM stories WHERE id=%s',(saved[2]['story_id'],))[0]['target_book_id'],'test')

    def test_failed_generation_does_not_publish_or_retry(self):
        before=self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n']
        self.mock_model.side_effect=RuntimeError('secret-must-not-leak')
        draft=self.generate()
        self.assertEqual(draft['status'],'failed')
        self.assertNotIn('secret',draft['error'])
        self.assertFalse(self.api_ai.save(1,draft['draft_id'],'s',1)[0])
        self.assertEqual(self.generate()['status'],'failed')
        self.assertEqual(self.mock_model.call_count,1)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before)
        self.mock_model.side_effect=None
        self.mock_model.return_value='# 标题\n<word id="1">word1</word>'
        self.assertEqual(self.generate('missing')['status'],'failed')

    def test_routes_preview_alias_edit_save(self):
        from flask import Flask
        from routes.ai import ai_bp
        from routes.stories import stories_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__)
        app.register_blueprint(ai_bp)
        app.register_blueprint(stories_bp)
        client=app.test_client()
        headers={'Authorization':'Bearer '+generate_token(1,'1')}
        payload={'word_ids':[1,2],'request_id':'route','story_type':'都市小说'}
        self.assertEqual(client.post('/api/ai/generate-story',json=payload).json['code'],401)
        draft=client.post('/api/ai/generate-story',json=payload,headers=headers).json['data']
        self.assertEqual(draft['status'],'ready')
        alias=client.post('/api/stories/generate',json=payload,headers=headers).json
        self.assertEqual(alias['data']['draft_id'],draft['draft_id'])
        path='/api/ai/drafts/'+draft['draft_id']
        self.assertEqual(client.get(path,headers=headers).json['code'],200)
        self.assertEqual(client.put(path,json=[],headers=headers).json['code'],400)
        edit=client.put(path,json={'version':1,'title':'已编辑','processed_content':draft['processed_content']},headers=headers).json
        self.assertEqual(edit['code'],200,edit)
        saved=client.post(path+'/save',json={'version':2,'request_id':'save'},headers=headers).json
        self.assertEqual(saved['code'],200,saved)

    def test_abandoned_generating_expires(self):
        draft=self.generate()
        self.sql("UPDATE ai_story_drafts SET status='generating',version=0,created_at='2020-01-01' WHERE id=%s",(draft['draft_id'],))
        state=self.api_ai.get(1,draft['draft_id'])
        self.assertTrue(state[0],state)
        self.assertEqual(state[2]['status'],'failed')


class ContentValidation(unittest.TestCase):
    def test_reject_invalid_tags_and_keep_actual_unique_order(self):
        # 不导入服务模块，避免没有socket时触发业务数据库连接。
        import ast
        from pathlib import Path
        from xml.etree import ElementTree
        import html,re
        tree=ast.parse(Path('services/ai_draft_service.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_content')
        ns={'StudyError':ValueError,'ElementTree':ElementTree,'html':html,'re':re}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'validate_content','exec'),ns)
        validate=ns['validate_content']
        targets=[{'word_id':1,'word':'one'},{'word_id':2,'word':'two'}]
        for body in ['<script>x</script>','<word id="3">one</word>','<word id="1">wrong</word>',
                     '<word id="1"><word id="2">two</word></word>','<!DOCTYPE root>text','text',
                     '<word id="1" onclick="x">one</word>','<word id="1">one']:
            with self.assertRaises(ValueError,msg=body):
                validate(body,targets)
        body='他 <word id="2">two</word> &amp; <word id="1">ONE</word> <word id="2">two</word>'
        result=validate(body,targets,True)
        self.assertEqual(result['word_ids'],[2,1])
        self.assertEqual(result['embedded_word_count'],2)
        self.assertEqual(result['embedded_occurrences'],3)
        self.assertIn('&',result['original_content'])
