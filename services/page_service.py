"""首页任务、个人统计、词书设置和跨设备阅读位置。"""
import math
from db import get_db
from services.study_service import StudyError, locked_user, positive_id
from services.story_reading_service import accessible_story
from utils.study_time import study_now


def progress_data(story_id, row):
    return {'story_id': story_id, 'progress': float(row['progress']) if row else 0,
            'position': row['position'] if row else 0, 'version': row['version'] if row else 0,
            'last_read_at': row['last_read_at'].strftime('%Y-%m-%d %H:%M:%S') if row else None}


class PageService:
    @staticmethod
    def dashboard(user_id):
        with get_db() as c:
            c.execute('''SELECT u.current_book_id, u.daily_new_target, u.daily_review_target, b.title
                FROM users u JOIN books b ON b.id = u.current_book_id WHERE u.id = %s''', (user_id,))
            user = c.fetchone()
            if not user:
                return False, '用户不存在', None
            now = study_now()
            c.execute('SELECT new_learned_count, reviewed_count FROM user_study_stats WHERE user_id = %s AND study_date = %s', (user_id, now.date()))
            stats = c.fetchone() or {'new_learned_count': 0, 'reviewed_count': 0}
            c.execute('''SELECT COUNT(*) AS n FROM book_words bw LEFT JOIN user_word_records r
                ON r.word_id = bw.word_id AND r.user_id = %s WHERE bw.book_id = %s AND r.id IS NULL''', (user_id, user['current_book_id']))
            available = c.fetchone()['n']
            c.execute('''SELECT COUNT(*) AS n FROM user_word_records r
                WHERE r.user_id = %s AND r.status != 'mastered' AND r.next_review_at <= %s
                AND NOT EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = r.user_id AND p.word_id = r.word_id)
                AND NOT EXISTS(SELECT 1 FROM daily_review_words d WHERE d.user_id = r.user_id AND d.word_id = r.word_id AND d.study_date = %s)
                AND EXISTS(SELECT 1 FROM book_words bw WHERE bw.word_id = r.word_id AND bw.book_trans IS NOT NULL AND JSON_LENGTH(bw.book_trans) > 0)''', (user_id, now, now.date()))
            due = c.fetchone()['n']
            c.execute('''SELECT p.*, s.title, s.embedded_word_count FROM reading_progress p
                JOIN stories s ON s.id = p.story_id
                LEFT JOIN user_story_records r ON r.user_id = p.user_id AND r.story_id = p.story_id
                WHERE p.user_id = %s AND (s.user_id = %s OR s.source_type = 'builtin')
                AND COALESCE(r.is_completed, 0) = 0 ORDER BY p.last_read_at DESC, p.story_id DESC LIMIT 1''', (user_id, user_id))
            last = c.fetchone()
            c.execute("SELECT DISTINCT task_type FROM study_groups WHERE user_id = %s AND book_id = %s AND study_date = %s AND status = 'active'", (user_id, user['current_book_id'], now.date()))
            active = {row['task_type'] for row in c.fetchall()}
            new_done = stats['new_learned_count'] >= user['daily_new_target']
            review_done = stats['reviewed_count'] >= user['daily_review_target']
            return True, 'success', {
                'current_book': {'book_id': user['current_book_id'], 'title': user['title']},
                'new_task': {'target_count': user['daily_new_target'], 'learned_today': stats['new_learned_count'],
                             'is_completed': new_done, 'available_count': available, 'can_start': 'learn' in active or (not new_done and available > 0)},
                'review_task': {'target_count': user['daily_review_target'], 'reviewed_today': stats['reviewed_count'],
                                'is_completed': review_done, 'due_count': due, 'can_start': 'review' in active or (not review_done and due > 0)},
                'last_story': dict(progress_data(last['story_id'], last), title=last['title'], embedded_word_count=last['embedded_word_count']) if last else None}

    @staticmethod
    def stats(user_id):
        with get_db() as c:
            c.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not c.fetchone():
                return False, '用户不存在', None
            c.execute("SELECT COUNT(*) AS learned, COUNT(CASE WHEN status = 'mastered' THEN 1 END) AS mastered FROM user_word_records WHERE user_id = %s", (user_id,))
            words = c.fetchone()
            c.execute('SELECT COUNT(*) AS n FROM user_story_records WHERE user_id = %s AND is_completed = 1', (user_id,))
            read = c.fetchone()['n']
            c.execute('''SELECT COUNT(*) AS n FROM (
                SELECT study_date AS day FROM user_study_stats WHERE user_id = %s AND (new_learned_count > 0 OR reviewed_count > 0 OR read_story_count > 0)
                UNION SELECT DATE(created_at) FROM user_word_records WHERE user_id = %s
                UNION SELECT DATE(completed_at) FROM user_story_records WHERE user_id = %s AND is_completed = 1 AND completed_at IS NOT NULL
                UNION SELECT DATE(completed_at) FROM story_practice_sessions WHERE user_id = %s AND status = 'completed' AND completed_at IS NOT NULL
                ) activity_days''', (user_id, user_id, user_id, user_id))
            return True, 'success', {'total_study_days': c.fetchone()['n'], 'total_learned_words': words['learned'],
                                     'total_mastered_words': words['mastered'], 'total_read_stories': read}

    @staticmethod
    def books(user_id):
        with get_db() as c:
            c.execute('SELECT current_book_id FROM users WHERE id = %s', (user_id,))
            user = c.fetchone()
            if not user:
                return False, '用户不存在', None
            c.execute('''SELECT b.id AS book_id, b.title, b.description, COUNT(bw.id) AS total_words,
                COUNT(r.id) AS learned_words, COUNT(CASE WHEN r.status = 'mastered' THEN 1 END) AS mastered_words
                FROM books b LEFT JOIN book_words bw ON bw.book_id = b.id
                LEFT JOIN user_word_records r ON r.word_id = bw.word_id AND r.user_id = %s
                GROUP BY b.id, b.title, b.description ORDER BY b.id''', (user_id,))
            books = c.fetchall()
            for book in books:
                book['is_current'] = book['book_id'] == user['current_book_id']
            return True, 'success', {'current_book_id': user['current_book_id'], 'books': books}

    @staticmethod
    def switch_book(user_id, book_id):
        try:
            if not isinstance(book_id, str) or not 0 < len(book_id) <= 32:
                raise StudyError('book_id 必须为非空字符串（最多32字符）')
            with get_db() as c:
                locked_user(c, user_id)
                c.execute('SELECT id FROM books WHERE id = %s', (book_id,))
                if not c.fetchone():
                    raise StudyError('词书不存在')
                c.execute('UPDATE users SET current_book_id = %s, updated_at = %s WHERE id = %s', (book_id, study_now(), user_id))
                return True, '主修词书已更新', {'current_book_id': book_id}
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def batch_delete_favorites(user_id, word_ids):
        try:
            if not isinstance(word_ids, list) or not 1 <= len(word_ids) <= 200 or not all(positive_id(w) for w in word_ids):
                raise StudyError('word_ids 必须为1到200个正整数的列表')
            ids = list(dict.fromkeys(word_ids))
            with get_db() as c:
                locked_user(c, user_id)
                placeholders = ','.join(['%s'] * len(ids))
                c.execute(f'DELETE FROM user_favorite_words WHERE user_id = %s AND word_id IN ({placeholders})', [user_id] + ids)
                return True, '已批量取消收藏', {'deleted_count': c.rowcount}
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def get_progress(user_id, story_id):
        try:
            with get_db() as c:
                accessible_story(c, user_id, story_id)
                c.execute('SELECT * FROM reading_progress WHERE user_id = %s AND story_id = %s', (user_id, story_id))
                return True, 'success', progress_data(story_id, c.fetchone())
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def save_progress(user_id, story_id, progress, position, version):
        try:
            if type(progress) not in (int, float) or not math.isfinite(progress) or not 0 <= progress <= 100:
                raise StudyError('progress 必须为0到100之间的有限数值')
            if type(position) is not int or not 0 <= position <= 4294967295:
                raise StudyError('position 必须为非负整数（正文字符偏移）')
            if type(version) is not int or not 0 <= version < 4294967295:
                raise StudyError('version 必须为读取进度时返回的非负整数')
            progress = round(progress, 2)
            with get_db() as c:
                locked_user(c, user_id)
                accessible_story(c, user_id, story_id)
                c.execute('SELECT * FROM reading_progress WHERE user_id = %s AND story_id = %s FOR UPDATE', (user_id, story_id))
                row = c.fetchone()
                current = row['version'] if row else 0
                if version != current:
                    if row and version == current - 1 and float(row['progress']) == progress and row['position'] == position:
                        return True, '进度已保存', progress_data(story_id, row)
                    raise StudyError('阅读进度已被其他请求更新，请重新获取最新version后提交')
                now = study_now()
                c.execute('''INSERT INTO reading_progress (user_id, story_id, progress, position, version, last_read_at)
                    VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE progress = VALUES(progress),
                    position = VALUES(position), version = VALUES(version), last_read_at = VALUES(last_read_at)''',
                          (user_id, story_id, progress, position, current + 1, now))
                return True, '进度已保存', progress_data(story_id, {'progress': progress, 'position': position, 'version': current + 1, 'last_read_at': now})
        except StudyError as exc:
            return False, str(exc), None
