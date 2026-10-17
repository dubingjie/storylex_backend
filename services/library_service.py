"""文库列表及幂等文章收藏。"""
from db import get_db
from services.study_service import StudyError, locked_user
from services.story_reading_service import accessible_story
from utils.study_time import study_now


class LibraryService:
    @staticmethod
    def list_stories(user_id, page=1, page_size=10, source_type=None, category='all', keyword=None, scope='all'):
        try:
            if type(page) is not int or page < 1 or page > 2147483647 or type(page_size) is not int or not 1 <= page_size <= 100:
                raise StudyError('page必须为正整数，page_size必须为1到100的整数')
            if scope not in ('all', 'mine', 'recommended'):
                raise StudyError('scope必须为all、mine或recommended')
            if category not in ('all', 'imported', 'ai_generated', 'favorites'):
                raise StudyError('category必须为all、imported、ai_generated或favorites')
            if source_type not in (None, 'builtin', 'imported', 'ai_generated'):
                raise StudyError('source_type必须为builtin、imported或ai_generated')
            if keyword is not None and (not isinstance(keyword, str) or len(keyword) > 150):
                raise StudyError('keyword最多150字符')
            clauses = ["(s.user_id = %s OR s.source_type = 'builtin')"]
            params = [user_id]
            if scope == 'mine':
                clauses.append('(s.user_id = %s OR f.story_id IS NOT NULL)')
                params.append(user_id)
            elif scope == 'recommended':
                clauses.append("s.source_type = 'builtin'")
            if category == 'favorites':
                clauses.append('f.story_id IS NOT NULL')
            elif category != 'all':
                clauses.append('s.source_type = %s')
                params.append(category)
            if source_type:
                clauses.append('s.source_type = %s')
                params.append(source_type)
            if keyword and keyword.strip():
                term = keyword.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_')
                clauses.append("s.title LIKE %s ESCAPE '!'")
                params.append('%' + term + '%')
            where = ' AND '.join(clauses)
            base = 'FROM stories s LEFT JOIN user_favorite_stories f ON f.story_id = s.id AND f.user_id = %s'
            with get_db() as c:
                c.execute(f'SELECT COUNT(*) AS total {base} WHERE {where}', [user_id] + params)
                total = c.fetchone()['total']
                c.execute(f'''SELECT s.id AS story_id, s.title, s.source_type, s.target_book_id,
                    s.word_count, s.embedded_word_count, s.created_at,
                    (f.story_id IS NOT NULL) AS is_favorited, COALESCE(r.is_completed, 0) AS is_completed,
                    r.last_practice_score {base}
                    LEFT JOIN user_story_records r ON r.user_id = %s AND r.story_id = s.id
                    WHERE {where} ORDER BY s.id ASC LIMIT %s OFFSET %s''',
                          [user_id, user_id] + params + [page_size, (page - 1) * page_size])
                rows = list(c.fetchall())
                for row in rows:
                    row['is_favorited'] = bool(row['is_favorited'])
                    row['is_completed'] = bool(row['is_completed'])
                    row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['created_at'] else ''
                return True, 'success', {'total': total, 'page': page, 'page_size': page_size, 'list': rows}
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def set_favorite(user_id, story_id, is_favorited):
        try:
            if type(is_favorited) is not bool:
                raise StudyError('is_favorited必须为布尔值true或false')
            with get_db() as c:
                locked_user(c, user_id)
                accessible_story(c, user_id, story_id)
                if is_favorited:
                    c.execute('''INSERT INTO user_favorite_stories (user_id, story_id, created_at)
                        VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE story_id = story_id''', (user_id, story_id, study_now()))
                else:
                    c.execute('DELETE FROM user_favorite_stories WHERE user_id = %s AND story_id = %s', (user_id, story_id))
                return True, '已收藏文章' if is_favorited else '已取消文章收藏', {'story_id': story_id, 'is_favorited': is_favorited}
        except StudyError as exc:
            return False, str(exc), None
