"""TXT导入单元及隔离MySQL集成测试，不调用模型。"""
import importlib
import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_story_reading as reading_base
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class TxtImportIntegration(unittest.TestCase):
    context = base.StudyIntegration.__dict__['context']
    tearDownClass = base.StudyIntegration.__dict__['tearDownClass']
    sql = base.StudyIntegration.sql

    @classmethod
    def setUpClass(cls):
        reading_base.ReadingIntegration.setUpClass.__func__(cls)
        cls.ai = importlib.import_module('services.ai_draft_service')
        cls.ai.get_db = cls.context
        cls.ai.locked_user = cls.module.locked_user
        cls.importer = importlib.import_module('services.txt_import_service')
        cls.importer.get_db = cls.context
        cls.importer.locked_user = cls.module.locked_user
        cls.api_import = cls.importer.TxtImportService

    def setUp(self):
        reading_base.ReadingIntegration.setUp(self)
        for wid, text in [(1,'安静'),(2,'安静地；沉默'),(3,'安静；宁静')]:
            self.sql("UPDATE book_words SET book_trans=%s WHERE book_id='test' AND word_id=%s", (json.dumps([{'pos':'adj','tranCn':text}]),wid))
        self.text='她安静地坐在窗边。屋里很安静，她保持沉默。'
        self.model=patch.object(self.ai.AIDraftService,'_model_text',side_effect=AssertionError('TXT must not call a model'))
        self.model.start()
        self.addCleanup(self.model.stop)

    def preview(self,rid='txt-1',text=None,**kwargs):
        raw=(text or self.text).encode('utf-8')
        result=self.api_import.preview(1,raw,'故事.txt','test',rid,min_gap=0,**kwargs)
        self.assertTrue(result[0],result)
        return result[2]

    def test_longest_match_ambiguity_counts_and_no_publish(self):
        before=self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n']
        draft=self.preview()
        self.assertEqual(draft['status'],'ready')
        self.assertEqual(draft['source_type'],'imported')
        self.assertEqual(draft['source_content'],self.text)
        changes=draft['import_info']['replacements']
        self.assertEqual([r['chinese'] for r in changes],['安静地','安静','沉默'])
        self.assertEqual([r['word_id'] for r in changes],[2,1,2])
        self.assertEqual(changes[1]['candidate_word_ids'],[1,3])
        self.assertEqual(draft['embedded_word_count'],2)
        self.assertEqual(draft['embedded_occurrences'],3)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before)
        self.assertEqual(self.preview()['draft_id'],draft['draft_id'])
        self.assertFalse(self.api_import.preview(1,'不同安静'.encode(),'故事.txt','test','txt-1',min_gap=0)[0])

    def test_density_and_encodings(self):
        text='安静'+('她坐在窗边。'*10)+'沉默安静'
        limited=self.api_import.preview(1,text.encode(),'a.txt','test','limited',max_replacements=1,min_gap=0)
        self.assertEqual(limited[2]['embedded_occurrences'],1)
        spaced=self.api_import.preview(1,text.encode(),'a.txt','test','spaced',min_gap=30)
        changes=spaced[2]['import_info']['replacements']
        self.assertEqual(len(changes),2)
        self.assertGreaterEqual(changes[1]['start']-changes[0]['end'],30)
        for encoding in ('utf-8-sig','utf-16','gb18030'):
            result=self.api_import.preview(1,self.text.encode(encoding),'a.TXT','test',encoding,min_gap=0)
            self.assertTrue(result[0],result)
            self.assertEqual(result[2]['source_content'],self.text)

    def test_edit_save_actual_words_and_original_source(self):
        draft=self.preview()
        edited=self.ai.AIDraftService.edit(1,draft['draft_id'],'导入新标题','正文 <word id="2">word2</word>。',1)
        self.assertTrue(edited[0],edited)
        saved=self.ai.AIDraftService.save(1,draft['draft_id'],'save',2)
        self.assertTrue(saved[0],saved)
        sid=saved[2]['story_id']
        story=self.sql('SELECT * FROM stories WHERE id=%s',(sid,))[0]
        self.assertEqual(story['source_type'],'imported')
        self.assertEqual(story['original_content'],self.text)
        self.assertEqual(story['embedded_word_count'],1)
        self.assertEqual(self.sql('SELECT word_id FROM story_words WHERE story_id=%s',(sid,)),[{'word_id':2}])
        detail=self.story_module.StoryService.get_story_detail(1,sid)
        self.assertTrue(detail[0],detail)
        self.assertEqual(detail[2]['source_type'],'imported')
        self.assertEqual(self.story_module.StoryService.get_story_list(1,source_type='imported')[2]['total'],1)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_story_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)

    def test_concurrent_preview_save_and_rollback(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            drafts=list(pool.map(lambda _:self.preview(),range(2)))
        self.assertEqual(drafts[0]['draft_id'],drafts[1]['draft_id'])
        draft=drafts[0]
        original=self.ai.write_state
        def failure(cursor,draft_id,status,*args,**kwargs):
            if status=='saved':
                raise RuntimeError('injected failure')
            return original(cursor,draft_id,status,*args,**kwargs)
        before=self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n']
        with patch.object(self.ai,'write_state',side_effect=failure):
            with self.assertRaises(RuntimeError):
                self.ai.AIDraftService.save(1,draft['draft_id'],'save',1)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before)
        with ThreadPoolExecutor(max_workers=2) as pool:
            saved=list(pool.map(lambda _:self.ai.AIDraftService.save(1,draft['draft_id'],'save',1),range(2)))
        self.assertTrue(all(r[0] for r in saved),saved)
        self.assertEqual(saved[0][2],saved[1][2])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM stories')[0]['n'],before+1)

    def test_validation_no_match_and_permissions(self):
        cases=[(b'', 'a.txt','test'),(b'\x00\x01','a.txt','test'),('安静'.encode(),'a.pdf','test'),
               ('没有任何可替换词汇'.encode(),'a.txt','test'),('安静'.encode(),'a.txt','missing'),
               ('安静'*40001,'a.txt','test'),(b'a'*(200*1024+1),'a.txt','test')]
        for raw,name,book in cases:
            if isinstance(raw,str):raw=raw.encode()
            self.assertFalse(self.api_import.preview(1,raw,name,book,'invalid')[0])
        self.assertFalse(self.api_import.preview(1,'安静'.encode(),'a.txt','test','invalid',max_replacements=True)[0])
        draft=self.preview()
        self.assertFalse(self.ai.AIDraftService.get(2,draft['draft_id'])[0])
        self.assertFalse(self.ai.AIDraftService.save(2,draft['draft_id'],'save',1)[0])

    def test_uploaded_markup_is_escaped(self):
        draft=self.preview(text='<script>安静</script> & 她沉默。')
        self.assertIn('&lt;script&gt;',draft['processed_content'])
        self.assertNotIn('<script>',draft['processed_content'])
        self.assertIn('&amp;',draft['processed_content'])

    def test_multipart_routes_and_limits(self):
        from flask import Flask
        from routes.ai import ai_bp
        from utils.auth_helper import generate_token
        app=Flask(__name__)
        app.register_blueprint(ai_bp)
        client=app.test_client()
        headers={'Authorization':'Bearer '+generate_token(1,'1')}
        def data():
            return {'file':(io.BytesIO(self.text.encode()),'故事.txt'), 'request_id':'route-txt',
                    'target_book_id':'test','min_gap':'0'}
        self.assertEqual(client.post('/api/ai/import-txt',data=data()).json['code'],401)
        result=client.post('/api/ai/import-txt',data=data(),headers=headers).json
        self.assertEqual(result['code'],200,result)
        self.assertEqual(result['data']['source_type'],'imported')
        self.assertEqual(client.post('/api/ai/import-txt',data={'target_book_id':'test'},headers=headers).json['code'],400)
        bad=data();bad['min_gap']='abc'
        self.assertEqual(client.post('/api/ai/import-txt',data=bad,headers=headers).json['code'],400)
        huge={'file':(io.BytesIO(b'a'*(310*1024)),'a.txt')}
        self.assertEqual(client.post('/api/ai/import-txt',data=huge,headers=headers).status_code,413)
