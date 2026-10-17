"""从正式基础SQL和迁移初始化的隔离数据库验收。"""
import unittest
from pathlib import Path
import test_study_service as base


@unittest.skipUnless(base.SOCKET, '需要显式设置隔离测试MySQL socket')
class DatabaseInitialization(unittest.TestCase):
    context=base.StudyIntegration.__dict__['context']
    tearDownClass=base.StudyIntegration.__dict__['tearDownClass']
    setUpClass=base.StudyIntegration.__dict__['setUpClass']

    def test_complete_structure_foreign_keys_and_seed_reexecution(self):
        with self.context() as c:
            c.execute('SHOW TABLES')
            self.assertEqual(len(c.fetchall()),19)
            c.execute("SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME='user_story_records'",(self.database,))
            self.assertEqual({r['CONSTRAINT_NAME'] for r in c.fetchall()},{'fk_usr_user','fk_usr_story'})
            for statement in Path('database/seed.sql').read_text().split(';'):
                if statement.strip():c.execute(statement)
            c.execute("UPDATE books SET title='Existing title',word_count=123 WHERE id='CET6luan_1'")
            for file in [Path('database/schema.sql'),*sorted(Path('migrations').glob('*.sql')),Path('database/seed.sql')]:
                for statement in file.read_text().split(';'):
                    if statement.strip():c.execute(statement)
            c.execute("SELECT title,word_count FROM books WHERE id='CET6luan_1'")
            self.assertEqual(c.fetchone(),{'title':'Existing title','word_count':123})
            c.execute('SELECT COUNT(*) AS n FROM users')
            self.assertEqual(c.fetchone()['n'],0)
