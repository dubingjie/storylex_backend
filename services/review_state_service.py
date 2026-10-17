"""正式复习暂停/恢复和掌握重置；保留历史及每日去重记录。"""
import json
from db import get_db
from services.study_service import StudyError, locked_user, parsed, positive_id, text_id, save_group
from utils.study_time import study_now, review_at


def skip_review_word(cursor, user_id, word_id, reason):
    cursor.execute("SELECT * FROM study_groups WHERE user_id = %s AND status = 'active' FOR UPDATE", (user_id,))
    for group in cursor.fetchall():
        state = parsed(group['state'])
        word = state['words'].get(str(word_id))
        if not word:
            continue
        if reason == 'reset':
            word['is_mastered'] = False
        if group['task_type'] == 'review' and not word['passed']:
            word.update({'passed': True, 'skipped': True, 'skip_reason': reason})
        completed = group['task_type'] == 'review' and all(w['passed'] for w in state['words'].values())
        save_group(cursor, group['id'], state, completed)


class ReviewStateService:
    @staticmethod
    def change(user_id, word_id, action, request_id):
        try:
            if not positive_id(word_id) or not text_id(request_id) or action not in ('pause', 'resume', 'reset'):
                raise StudyError('需要正整数word_id、非空request_id（最多64字符）及有效操作')
            with get_db() as c:
                locked_user(c, user_id)
                c.execute('SELECT action, word_id, result FROM review_state_requests WHERE user_id = %s AND request_id = %s FOR UPDATE', (user_id, request_id))
                receipt = c.fetchone()
                if receipt:
                    if receipt['action'] != action or receipt['word_id'] != word_id:
                        raise StudyError('request_id已用于其他状态操作，请使用新编号')
                    return True, '返回原操作结果（当前状态请重新查询）', parsed(receipt['result'])
                c.execute('SELECT status, stage, proficiency, next_review_at FROM user_word_records WHERE user_id = %s AND word_id = %s FOR UPDATE', (user_id, word_id))
                record = c.fetchone()
                if not record:
                    raise StudyError('该单词没有本人的学习记录')
                c.execute('SELECT paused_at FROM review_pauses WHERE user_id = %s AND word_id = %s FOR UPDATE', (user_id, word_id))
                pause = c.fetchone()
                now = study_now()
                changed = False
                if action == 'pause':
                    if record['status'] == 'mastered':
                        raise StudyError('该词已掌握，无需暂停复习；重新学习请使用重置接口')
                    if not pause:
                        c.execute('INSERT INTO review_pauses (user_id, word_id, paused_at) VALUES (%s, %s, %s)', (user_id, word_id, now))
                        changed = True
                    skip_review_word(c, user_id, word_id, 'paused')
                    paused = True
                elif action == 'resume':
                    if pause:
                        c.execute('DELETE FROM review_pauses WHERE user_id = %s AND word_id = %s', (user_id, word_id))
                        c.execute('UPDATE user_word_records SET next_review_at = %s WHERE user_id = %s AND word_id = %s', (review_at(1, now), user_id, word_id))
                        record['next_review_at'] = review_at(1, now)
                        changed = True
                        skip_review_word(c, user_id, word_id, 'rescheduled')
                    paused = False
                else:
                    if record['status'] != 'mastered':
                        raise StudyError('只有已掌握的单词可以重置掌握状态')
                    c.execute('''UPDATE user_word_records SET status = 'reviewing', stage = 0, proficiency = 0,
                        next_review_at = %s WHERE user_id = %s AND word_id = %s''', (review_at(1, now), user_id, word_id))
                    c.execute('DELETE FROM review_pauses WHERE user_id = %s AND word_id = %s', (user_id, word_id))
                    record.update({'status': 'reviewing', 'stage': 0, 'proficiency': 0, 'next_review_at': review_at(1, now)})
                    changed, paused = True, False
                    skip_review_word(c, user_id, word_id, 'reset')
                result = {'word_id': word_id, 'action': action, 'changed': changed,
                          'status': record['status'], 'stage': record['stage'], 'proficiency': record['proficiency'],
                          'is_mastered': record['status'] == 'mastered', 'is_review_paused': paused,
                          'next_review_at': record['next_review_at'].strftime('%Y-%m-%d %H:%M:%S') if not paused and record['status'] != 'mastered' else None}
                c.execute('INSERT INTO review_state_requests (user_id, request_id, action, word_id, result, created_at) VALUES (%s, %s, %s, %s, %s, %s)',
                          (user_id, request_id, action, word_id, json.dumps(result, ensure_ascii=False), now))
                return True, '复习状态已更新', result
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def paused_words(user_id, page=1, page_size=20):
        try:
            if type(page) is not int or not 1 <= page <= 2147483647 or type(page_size) is not int or not 1 <= page_size <= 100:
                raise StudyError('page必须为正整数，page_size必须为1到100')
            with get_db() as c:
                c.execute('SELECT current_book_id FROM users WHERE id = %s', (user_id,))
                user = c.fetchone()
                if not user:
                    raise StudyError('用户不存在')
                c.execute('SELECT COUNT(*) AS total FROM review_pauses WHERE user_id = %s', (user_id,))
                total = c.fetchone()['total']
                c.execute('''SELECT p.word_id, p.paused_at, w.word, w.us_phone, w.uk_phone,
                    r.status, r.stage, r.proficiency, bw.book_trans, bw.book_id AS translation_book_id
                    FROM review_pauses p JOIN user_word_records r ON r.user_id = p.user_id AND r.word_id = p.word_id
                    JOIN words w ON w.id = p.word_id
                    LEFT JOIN book_words bw ON bw.id = (
                        SELECT b.id FROM book_words b WHERE b.word_id = w.id AND b.book_trans IS NOT NULL AND JSON_LENGTH(b.book_trans) > 0
                        ORDER BY (b.book_id = %s) DESC, b.book_id LIMIT 1)
                    WHERE p.user_id = %s ORDER BY p.paused_at DESC, p.word_id DESC LIMIT %s OFFSET %s''',
                          (user['current_book_id'], user_id, page_size, (page - 1) * page_size))
                words = list(c.fetchall())
                for word in words:
                    word['translations'] = parsed(word.pop('book_trans'))
                    word['paused_at'] = word['paused_at'].strftime('%Y-%m-%d %H:%M:%S')
                    word['is_review_paused'] = True
                return True, 'success', {'total': total, 'page': page, 'page_size': page_size, 'list': words}
        except StudyError as exc:
            return False, str(exc), None
