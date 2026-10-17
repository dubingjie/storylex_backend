"""文章词表及阅读测验；收藏和完读均不在这里触发正式学习统计。"""
import json
import random
import uuid

from db import get_db
from services.study_service import StudyError, locked_user, parsed, positive_id, text_id, translation
from utils.study_time import study_now, review_at


def accessible_story(cursor, user_id, story_id):
    if not positive_id(story_id):
        raise StudyError('story_id 必须为正整数')
    cursor.execute("SELECT id, target_book_id FROM stories WHERE id = %s AND (user_id = %s OR source_type = 'builtin')", (story_id, user_id))
    story = cursor.fetchone()
    if not story:
        raise StudyError('文章不存在或无权访问')
    return story


def vocabulary_rows(cursor, user_id, book_id, story):
    # 当前词书优先，其次文章目标词书，最后按词书ID稳定回退；无释义也保留在词表。
    cursor.execute('''SELECT sw.word_order, w.id AS word_id, w.word, w.us_phone, w.uk_phone,
        bw.book_id AS translation_book_id, b.title AS translation_book_title, bw.book_trans,
        EXISTS(SELECT 1 FROM book_words own WHERE own.book_id = %s AND own.word_id = w.id) AS in_current_book,
        EXISTS(SELECT 1 FROM user_favorite_words f WHERE f.user_id = %s AND f.word_id = w.id) AS is_favorited,
        r.status AS learning_status,
        EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = r.user_id AND p.word_id = r.word_id) AS is_review_paused
        FROM story_words sw JOIN words w ON w.id = sw.word_id
        LEFT JOIN book_words bw ON bw.id = (
            SELECT candidate.id FROM book_words candidate WHERE candidate.word_id = w.id
                AND candidate.book_trans IS NOT NULL AND JSON_LENGTH(candidate.book_trans) > 0
            ORDER BY (candidate.book_id = %s) DESC, (candidate.book_id = %s) DESC, candidate.book_id
            LIMIT 1)
        LEFT JOIN books b ON b.id = bw.book_id
        LEFT JOIN user_word_records r ON r.user_id = %s AND r.word_id = w.id
        WHERE sw.story_id = %s ORDER BY sw.word_order, w.id''',
                   (book_id, user_id, book_id, story['target_book_id'], user_id, story['id']))
    words = []
    for row in cursor.fetchall():
        status = row['learning_status']
        words.append({
            'word_order': row['word_order'], 'word_id': row['word_id'], 'word': row['word'],
            'us_phone': row['us_phone'], 'uk_phone': row['uk_phone'],
            'translations': parsed(row['book_trans']),
            'translation_book_id': row['translation_book_id'],
            'translation_book_title': row['translation_book_title'],
            'is_out_of_book': not bool(row['in_current_book']),
            'is_favorited': bool(row['is_favorited']), 'is_mastered': status == 'mastered',
            'is_review_paused': bool(row['is_review_paused']),
            'is_learned': status is not None, 'learning_status': status or 'unlearned'
        })
    return words


def practice_packet(session_id, story_id, state):
    return {'session_id': session_id, 'story_id': story_id, 'total': len(state['questions']),
            'skipped_word_ids': state['skipped_word_ids'],
            'questions': [{k: v for k, v in q.items() if k != 'correct_key'} for q in state['questions']]}


class StoryReadingService:
    @staticmethod
    def vocabulary(user_id, story_id):
        try:
            with get_db() as cursor:
                story = accessible_story(cursor, user_id, story_id)
                cursor.execute('SELECT current_book_id FROM users WHERE id = %s', (user_id,))
                user = cursor.fetchone()
                if not user:
                    raise StudyError('用户不存在')
                words = vocabulary_rows(cursor, user_id, user['current_book_id'], story)
                return True, 'success', {'story_id': story_id, 'total': len(words), 'words': words}
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def practice(user_id, story_id):
        try:
            with get_db() as cursor:
                user = locked_user(cursor, user_id)
                story = accessible_story(cursor, user_id, story_id)
                now = study_now()
                cursor.execute('''SELECT id, state FROM story_practice_sessions
                    WHERE user_id = %s AND story_id = %s AND book_id = %s AND study_date = %s
                    AND status = 'active' ORDER BY created_at DESC LIMIT 1 FOR UPDATE''',
                               (user_id, story_id, user['current_book_id'], now.date()))
                session = cursor.fetchone()
                if session:
                    return True, '继续当前阅读练习', practice_packet(session['id'], story_id, parsed(session['state']))
                words = vocabulary_rows(cursor, user_id, user['current_book_id'], story)
                skipped = [w['word_id'] for w in words if not w['translations'] or translation(w['translations']) == '释义待补充']
                targets = [w for w in words if w['word_id'] not in skipped]
                if not targets:
                    return True, '文章暂无可出题词汇', {'session_id': None, 'story_id': story_id, 'total': 0, 'questions': [], 'skipped_word_ids': skipped}
                cursor.execute('''SELECT book_trans FROM book_words WHERE book_id = %s
                    AND book_trans IS NOT NULL ORDER BY RAND() LIMIT 100''', (user['current_book_id'],))
                pool = [translation(r['book_trans']) for r in cursor.fetchall()]
                pool += [translation(w['translations']) for w in targets]
                pool += ['n. 景象，视线', 'v. 维持，保持', 'adj. 复杂的', 'adv. 逐渐地']
                state = {'questions': [], 'skipped_word_ids': skipped}
                for word in targets:
                    correct = translation(word['translations'])
                    wrong = list(dict.fromkeys(t for t in pool if t != correct and t != '释义待补充'))
                    choices = [correct] + random.sample(wrong, 3)
                    random.shuffle(choices)
                    state['questions'].append({
                        'question_id': uuid.uuid4().hex, 'word_id': word['word_id'], 'word': word['word'],
                        'us_phone': word['us_phone'], 'uk_phone': word['uk_phone'],
                        'options': [{'key': k, 'trans': t} for k, t in zip('ABCD', choices)],
                        'correct_key': 'ABCD'[choices.index(correct)]
                    })
                session_id = uuid.uuid4().hex
                cursor.execute('''INSERT INTO story_practice_sessions
                    (id, user_id, story_id, book_id, study_date, state, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                               (session_id, user_id, story_id, user['current_book_id'], now.date(), json.dumps(state, ensure_ascii=False), now))
                return True, 'success', practice_packet(session_id, story_id, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def submit(user_id, story_id, session_id, request_id, answers):
        try:
            if not text_id(session_id) or not text_id(request_id):
                raise StudyError('session_id、request_id 必须为非空字符串（最多64字符）')
            if not isinstance(answers, list) or not answers:
                raise StudyError('answers 必须为非空列表，包含本题组全部题目')
            normalized = []
            seen = set()
            for answer in answers:
                if not isinstance(answer, dict) or not positive_id(answer.get('word_id')) or not text_id(answer.get('question_id')):
                    raise StudyError('每个答案需要正整数 word_id 和非空 question_id')
                if 'is_correct' in answer:
                    raise StudyError('请提交 selected_key，由后端判断对错，不接受 is_correct')
                show = answer.get('is_show_answer', False)
                key = answer.get('selected_key')
                if type(show) is not bool or (show and key is not None):
                    raise StudyError('看答案时 is_show_answer=true，selected_key=null 或省略')
                if not show and (not isinstance(key, str) or key.upper() not in ('A', 'B', 'C', 'D')):
                    raise StudyError('selected_key 必须为 A、B、C、D')
                qid = answer['question_id']
                if qid in seen:
                    raise StudyError('同一道题不能重复提交')
                seen.add(qid)
                normalized.append([qid, answer['word_id'], key.upper() if key else None, show])
            normalized.sort()
            with get_db() as cursor:
                user = locked_user(cursor, user_id)
                accessible_story(cursor, user_id, story_id)
                cursor.execute('''SELECT * FROM story_practice_sessions
                    WHERE id = %s AND user_id = %s AND story_id = %s FOR UPDATE''', (session_id, user_id, story_id))
                session = cursor.fetchone()
                if not session:
                    raise StudyError('阅读练习不存在或不属于当前用户、文章')
                state = parsed(session['state'])
                if session['status'] == 'completed':
                    if state['submission']['answers'] != normalized:
                        raise StudyError('本次练习已提交，不能更换答案；请重新获取练习')
                    return True, '本次练习已结算', state['result']
                now = study_now()
                if session['study_date'] != now.date() or session['book_id'] != user['current_book_id']:
                    raise StudyError('练习已跨日或主修词书已改变，请重新获取练习')
                expected = {q['question_id']: q for q in state['questions']}
                if len(normalized) != len(expected) or seen != set(expected):
                    raise StudyError('必须提交本题组的全部题目，不能遗漏或加入其他题目')
                # 全部校验通过后才开始写入，避免错误请求留下部分学习记录。
                results = []
                for qid, wid, key, show in normalized:
                    question = expected[qid]
                    if question['word_id'] != wid:
                        raise StudyError('word_id 与 question_id 不匹配')
                    correct = not show and key == question['correct_key']
                    results.append({'question_id': qid, 'word_id': wid, 'is_correct': correct, 'correct_key': question['correct_key']})
                queued = 0
                for result in results:
                    if not result['is_correct']:
                        queued += StoryReadingService._queue_wrong(cursor, user_id, result['word_id'], now)
                correct_count = sum(r['is_correct'] for r in results)
                result = {'session_id': session_id, 'story_id': story_id, 'total': len(results),
                          'correct_count': correct_count, 'wrong_count': len(results) - correct_count,
                          'score': (100 * correct_count + len(results) // 2) // len(results),
                          'wrong_words_queued': queued, 'results': results}
                cursor.execute('''INSERT INTO user_story_records (user_id, story_id, last_practice_score)
                    VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE last_practice_score = VALUES(last_practice_score)''',
                               (user_id, story_id, result['score']))
                state['submission'] = {'request_id': request_id, 'answers': normalized}
                state['result'] = result
                cursor.execute("UPDATE story_practice_sessions SET status = 'completed', state = %s, completed_at = %s WHERE id = %s",
                               (json.dumps(state, ensure_ascii=False), now, session_id))
                return True, '练习完成', result
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def _queue_wrong(cursor, user_id, word_id, now):
        cursor.execute('SELECT status, next_review_at, EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = user_word_records.user_id AND p.word_id = user_word_records.word_id) AS is_review_paused FROM user_word_records WHERE user_id = %s AND word_id = %s FOR UPDATE', (user_id, word_id))
        record = cursor.fetchone()
        if record and (record['status'] == 'mastered' or record['is_review_paused']):
            return 0  # 已掌握保持不变，主动重置属于后续功能。
        due = review_at(1, now)
        if record:
            cursor.execute('''UPDATE user_word_records SET wrong_count = wrong_count + 1,
                next_review_at = LEAST(next_review_at, %s) WHERE user_id = %s AND word_id = %s''', (due, user_id, word_id))
        else:
            cursor.execute('''INSERT INTO user_word_records
                (user_id, word_id, status, stage, wrong_count, next_review_at, created_at)
                VALUES (%s, %s, 'reviewing', 0, 1, %s, %s)''', (user_id, word_id, due, now))
        return 1
