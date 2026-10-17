"""隔离 MySQL 集成测试。仅连接显式提供的临时 socket，创建/删除随机测试库。
STUDY_TEST_SOCKET=/tmp/storylex-study.sock venv/bin/python -m unittest discover -s tests -v
"""
import importlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

import pymysql

SOCKET = os.environ.get('STUDY_TEST_SOCKET')


@unittest.skipUnless(SOCKET, '需要显式设置隔离测试 MySQL socket')
class StudyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = 'study_test_' + uuid.uuid4().hex
        cls.admin = pymysql.connect(unix_socket=SOCKET, user='root', autocommit=True)
        with cls.admin.cursor() as c:
            c.execute(f'CREATE DATABASE `{cls.database}` CHARACTER SET utf8mb4')
        cls.saved_db = sys.modules.get('db')
        fake_db = types.ModuleType('db')
        fake_db.get_db = cls.context
        sys.modules['db'] = fake_db
        cls.module = importlib.import_module('services.study_service')
        cls.module.get_db = cls.context
        # 多个测试类共享导入缓存；统一将已加载的服务绑定到本类随机库，
        # 避免路由较早导入的服务仍引用上一类已清理的数据库。
        for name, module in list(sys.modules.items()):
            if name.startswith('services.') and hasattr(module, 'get_db'):
                module.get_db = cls.context
        cls.service = cls.module.StudyService
        with cls.context() as c:
            schema = Path('database/schema.sql').read_text()
            for statement in schema.split(';'):
                if statement.strip():
                    c.execute(statement)
            for migration in sorted(Path('migrations').glob('*.sql')):
                for statement in migration.read_text().split(';'):
                    if statement.strip():
                        c.execute(statement)

    @classmethod
    def context(cls):
        class DB:
            def __enter__(self):
                self.conn = pymysql.connect(unix_socket=SOCKET, user='root', database=cls.database,
                                            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
                self.cursor = self.conn.cursor()
                return self.cursor

            def __exit__(self, typ, value, traceback):
                try:
                    self.conn.rollback() if typ else self.conn.commit()
                finally:
                    self.cursor.close()
                    self.conn.close()
        return DB()

    @classmethod
    def tearDownClass(cls):
        with cls.admin.cursor() as c:
            c.execute(f'DROP DATABASE `{cls.database}`')
        cls.admin.close()
        if cls.saved_db is None:
            sys.modules.pop('db', None)
        else:
            sys.modules['db'] = cls.saved_db

    def setUp(self):
        self.clock = patch.object(self.module, 'study_now', return_value=datetime(2026, 10, 16, 23, 59, 59))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        with self.context() as c:
            for table in ('story_practice_sessions', 'user_story_records', 'story_words', 'stories', 'study_groups', 'daily_review_words', 'user_study_stats', 'user_word_records', 'user_favorite_words', 'users', 'book_words', 'words', 'books'):
                c.execute(f'DELETE FROM {table}')
            c.execute("INSERT INTO books (id,title) VALUES ('test','test')")
            for uid in (1, 2):
                c.execute("INSERT INTO users (id,username,password_hash,current_book_id,daily_new_target,daily_review_target) VALUES (%s,%s,'hash','test',15,15)", (uid, str(uid)))
            for wid in range(1, 21):
                c.execute('INSERT INTO words (id,word) VALUES (%s,%s)', (wid, 'word'+str(wid)))
                c.execute("INSERT INTO book_words (book_id,word_id,word_rank,book_trans) VALUES ('test',%s,%s,%s)", (wid, wid, json.dumps([{'pos':'n','tranCn':'释义'+str(wid)}])))

    def sql(self, statement, params=()):
        with self.context() as c:
            c.execute(statement, params)
            return c.fetchall() if c.description else c.rowcount

    def group(self, kind='learn'):
        result = self.service.get_group(1, kind)
        self.assertTrue(result[0], result)
        return result[2]

    def state(self, gid):
        return json.loads(self.sql('SELECT state FROM study_groups WHERE id=%s', (gid,))[0]['state'])

    def answer(self, group, wid, key=None, request=None, question=None, kind='learn', show=False):
        word = self.state(group['group_id'])['words'][str(wid)]
        return self.service.answer(1, kind, group['group_id'], wid, question or word['question_id'],
                                   request or uuid.uuid4().hex, key if key is not None else (None if show else word['correct_key']), show)

    def pass_all(self, group):
        for w in group['words']:
            self.assertTrue(self.answer(group, w['word_id'])[0])

    def test_wrong_retry_and_completion_is_idempotent(self):
        group = self.group()
        self.assertEqual(group['total'], 10)
        self.assertEqual(self.group(), group)
        self.assertNotIn('correct_key', group['words'][0])
        self.assertFalse(self.service.complete_learn_group(1, group['group_id'])[0])
        word = self.state(group['group_id'])['words']['1']
        wrong = next(k for k in 'ABCD' if k != word['correct_key'])
        first = self.answer(group, 1, wrong, 'retry', word['question_id'])
        self.assertFalse(first[2]['is_correct'])
        replay = self.answer(group, 1, wrong, 'retry', word['question_id'])
        self.assertTrue(replay[0])
        self.assertEqual(first[2], replay[2])
        self.assertFalse(self.answer(group, 1, wrong, 'different', word['question_id'])[0])
        self.assertFalse(self.answer(group, 1, 'A', 'retry')[0])
        self.pass_all(group)
        first = self.service.complete_learn_group(1, group['group_id'])
        self.assertTrue(first[0])
        self.assertEqual(first[2], self.service.complete_learn_group(1, group['group_id'])[2])
        self.assertEqual(self.sql('SELECT new_learned_count FROM user_study_stats')[0]['new_learned_count'], 10)
        self.assertEqual(self.sql('SELECT next_review_at FROM user_word_records LIMIT 1')[0]['next_review_at'], datetime(2026,10,17))
        self.assertEqual(self.sql('SELECT wrong_count FROM user_word_records WHERE word_id=1')[0]['wrong_count'], 1)
        last = self.group()
        self.assertEqual(last['total'], 5)
        self.pass_all(last)
        self.assertTrue(self.service.complete_learn_group(1,last['group_id'])[0])
        self.assertEqual(self.group()['total'], 0)

    def test_show_answer_master_and_ownership(self):
        group = self.group()
        self.assertFalse(self.answer(group, 1, show=True)[2]['is_correct'])
        self.assertFalse(self.service.complete_learn_group(2,group['group_id'])[0])
        self.assertFalse(self.service.answer(1,'learn',group['group_id'],20,'q','r','A')[0])
        self.assertTrue(self.service.master(1,1,group['group_id'])[0])
        self.assertTrue(self.group()['words'][0]['passed'])
        for w in group['words'][1:]:
            self.assertTrue(self.answer(group,w['word_id'])[0])
        self.assertTrue(self.service.complete_learn_group(1,group['group_id'])[0])
        self.assertEqual(self.sql('SELECT status FROM user_word_records WHERE word_id=1')[0]['status'], 'mastered')

    def test_review_replay_concurrency_and_readonly_summary(self):
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,stage,next_review_at) VALUES (1,1,'reviewing',0,'2026-10-16'),(1,2,'reviewing',2,'2026-10-16')")
        group = self.group('review')
        word = self.state(group['group_id'])['words']['1']
        args = (1,'review',group['group_id'],1,word['question_id'],'same-request',word['correct_key'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.answer(*args), range(2)))
        self.assertTrue(all(r[0] for r in results),results)
        self.assertEqual(results[0][2],results[1][2])
        self.assertEqual(self.sql('SELECT stage,review_count FROM user_word_records WHERE word_id=1')[0], {'stage':1,'review_count':1})
        self.assertEqual(self.sql('SELECT next_review_at FROM user_word_records WHERE word_id=1')[0]['next_review_at'],datetime(2026,10,18))
        self.assertTrue(self.answer(group,2,kind='review',show=True)[0])
        self.assertEqual(self.sql('SELECT next_review_at FROM user_word_records WHERE word_id=2')[0]['next_review_at'],datetime(2026,10,17))
        for _ in range(2):
            self.assertTrue(self.service.review_summary(1,group['group_id'])[0])
        self.assertEqual(self.sql('SELECT reviewed_count FROM user_study_stats')[0]['reviewed_count'],2)
        self.assertEqual(self.group('review')['total'],0)

    def test_concurrent_group_creation_and_completion(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            groups = list(pool.map(lambda _:self.group(),range(2)))
        self.assertEqual(groups[0]['group_id'],groups[1]['group_id'])
        self.pass_all(groups[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:self.service.complete_learn_group(1,groups[0]['group_id']),range(2)))
        self.assertTrue(all(r[0] for r in results))
        self.assertEqual(self.sql('SELECT new_learned_count FROM user_study_stats')[0]['new_learned_count'],10)

    def test_cross_day_and_short_book(self):
        self.sql('DELETE FROM book_words WHERE word_id>3')
        group = self.group()
        self.assertEqual(group['total'],3)
        with patch.object(self.module,'study_now',return_value=datetime(2026,10,17,0,0)):
            self.assertFalse(self.answer(group,1)[0])
            self.assertNotEqual(group['group_id'],self.group()['group_id'])

    def test_transaction_rollback(self):
        group = self.group()
        self.pass_all(group)
        with patch.object(self.module, 'add_stats', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                self.service.complete_learn_group(1,group['group_id'])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_word_records')[0]['n'],0)
        self.assertEqual(self.sql('SELECT status FROM study_groups')[0]['status'],'active')
        self.assertTrue(self.service.complete_learn_group(1,group['group_id'])[0])

    def test_review_target_mastered_and_daily_dedup(self):
        self.sql('UPDATE users SET daily_review_target=1 WHERE id=1')
        self.sql("INSERT INTO user_word_records (user_id,word_id,status,stage,next_review_at) VALUES (1,1,'reviewing',6,'2026-10-16'),(1,2,'reviewing',1,'2026-10-16')")
        group = self.group('review')
        self.assertEqual(group['total'],1)
        result = self.answer(group,1,kind='review')
        self.assertEqual(result[2]['new_status'],'mastered')
        self.assertIsNone(result[2]['next_review_at'])
        self.assertEqual(self.group('review')['total'],0)
        self.sql('UPDATE users SET daily_review_target=3 WHERE id=1')
        self.sql("UPDATE user_word_records SET status='reviewing',next_review_at='2026-10-16' WHERE word_id=1")
        self.assertEqual([w['word_id'] for w in self.group('review')['words']],[2])

    def test_flask_routes_and_legacy_fields(self):
        from flask import Flask
        from routes.words import words_bp
        from utils.auth_helper import generate_token
        app = Flask(__name__)
        app.register_blueprint(words_bp)
        client = app.test_client()
        headers = {'Authorization': 'Bearer '+generate_token(1,'1')}
        self.assertEqual(client.get('/api/words/learn/group').json['code'],401)
        group = client.get('/api/words/learn/group',headers=headers).json['data']
        for body in ([],None,{'word_id':1,'selected_key':'A','options':[{'key':'A','trans':'fake'}]}):
            self.assertEqual(client.post('/api/words/learn/answer',json=body,headers=headers).json['code'],400)
        self.assertEqual(client.post('/api/words/learn/group/complete',json={'group_id':group['group_id'],'word_mistakes':{'1':0}},headers=headers).json['code'],400)
        result = client.post('/api/words/master',json={'word_id':1,'group_id':group['group_id']},headers=headers).json
        self.assertEqual(result['code'],200)
        self.assertEqual(result['data']['passed_count'],1)
        self.assertEqual(client.get('/api/words/review/queue',headers=headers).json['code'],200)
        self.assertEqual(client.get('/api/words/review/group',headers=headers).json['code'],200)
        self.assertEqual(client.post('/api/words/review/complete',json={'reviewed_count':999},headers=headers).json['code'],400)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM user_study_stats')[0]['n'],0)

    def test_input_validation(self):
        for wid,key,show in [(True,'A',False),(1,'Z',False),(1,'A','false'),(1,'A',True)]:
            self.assertFalse(self.service.answer(1,'learn','g',wid,'q','r',key,show)[0])
        self.assertFalse(self.service.master(1,True)[0])
        self.assertFalse(self.service.master(1,999)[0])


class TimeTests(unittest.TestCase):
    def test_midnight(self):
        from utils.study_time import review_at
        self.assertEqual(review_at(1,datetime(2026,12,31,23,59,59)),datetime(2027,1,1))
        self.assertEqual(review_at(4,datetime(2026,10,16,12)),datetime(2026,10,20))
