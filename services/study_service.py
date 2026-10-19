"""正式新学/复习事务。按用户加锁，题组和请求回执持久化到 MySQL。"""
import json
import random
import uuid

from db import get_db
from utils.study_time import study_now, review_at


class StudyError(ValueError):
    pass


def parsed(value, fallback=None):
    if value is None:
        return [] if fallback is None else fallback
    return json.loads(value) if isinstance(value, str) else value


def positive_id(value):
    return type(value) is int and value > 0


def text_id(value):
    return isinstance(value, str) and 0 < len(value) <= 64


def translation(value):
    items = parsed(value)
    if not items:
        return '释义待补充'
    item = items[0]
    if not isinstance(item, dict):
        return str(item)
    pos, text = item.get('pos', ''), item.get('tranCn', '')
    return f'{pos}. {text}' if pos and text else text or '释义待补充'


def public_word(word):
    return {k: v for k, v in word.items() if k not in (
        'correct_key', 'word_detail', 'mistakes', 'result')}


def packet(group_id, state):
    words = list(state['words'].values())
    return {'group_id': group_id, 'total': len(words),
            'passed_count': sum(w['passed'] for w in words),
            'words': [public_word(w) for w in words]}


def locked_user(cursor, user_id):
    # 所有正式题组写入都先锁用户，避免多端产生重叠题组及重复统计。
    cursor.execute('SELECT current_book_id, daily_new_target, daily_review_target FROM users WHERE id = %s FOR UPDATE', (user_id,))
    user = cursor.fetchone()
    if not user:
        raise StudyError('用户不存在')
    return user


def load_group(cursor, user_id, group_id, kind):
    if not text_id(group_id):
        raise StudyError('group_id 必须为非空字符串（最多64字符）')
    cursor.execute('SELECT * FROM study_groups WHERE id = %s AND user_id = %s AND task_type = %s FOR UPDATE', (group_id, user_id, kind))
    group = cursor.fetchone()
    if not group:
        raise StudyError('题组不存在或无权访问，请重新获取题组')
    return group, parsed(group['state'])


def save_group(cursor, group_id, state, completed=False):
    cursor.execute('UPDATE study_groups SET state = %s, status = %s, completed_at = %s WHERE id = %s',
                   (json.dumps(state, ensure_ascii=False), 'completed' if completed else 'active',
                    study_now() if completed else None, group_id))


def check_active(group, user):
    if group['status'] != 'active':
        raise StudyError('题组已完成')
    if group['study_date'] != study_now().date():
        raise StudyError('题组已跨日，请重新获取今日题组')
    if group['book_id'] != user['current_book_id']:
        raise StudyError('主修词书已切换，请重新获取题组')


def add_stats(cursor, user_id, column, amount, today):
    # column 只由内部固定调用点提供。
    cursor.execute(f'''INSERT INTO user_study_stats (user_id, study_date, {column}, created_at)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE {column} = {column} + VALUES({column})''',
                   (user_id, today, amount, study_now()))


class StudyService:
    INTERVALS = [1, 2, 4, 7, 15, 30, 60, 0]

    @staticmethod
    def get_group(user_id, kind):
        try:
            with get_db() as cursor:
                user = locked_user(cursor, user_id)
                now = study_now()
                book_id = user['current_book_id']
                cursor.execute('''SELECT * FROM study_groups WHERE user_id = %s AND book_id = %s
                    AND task_type = %s AND study_date = %s AND status = 'active'
                    ORDER BY created_at DESC LIMIT 1 FOR UPDATE''', (user_id, book_id, kind, now.date()))
                active = cursor.fetchone()
                if active:
                    return True, '继续当前题组', packet(active['id'], parsed(active['state']))
                column = 'new_learned_count' if kind == 'learn' else 'reviewed_count'
                cursor.execute(f'SELECT {column} AS finished FROM user_study_stats WHERE user_id = %s AND study_date = %s', (user_id, now.date()))
                stats = cursor.fetchone()
                remaining = max(0, user['daily_new_target' if kind == 'learn' else 'daily_review_target'] - (stats['finished'] if stats else 0))
                if not remaining:
                    return True, '今日目标已完成', {'group_id': None, 'total': 0, 'passed_count': 0, 'words': []}
                select = '''SELECT w.id AS word_id, w.word, w.us_phone, w.uk_phone,
                    bw.book_trans, bw.book_sentences, bw.book_phrases, bw.book_rem_method,
                    EXISTS(SELECT 1 FROM user_favorite_words f WHERE f.user_id = %s AND f.word_id = w.id) AS is_favorited
                    FROM book_words bw JOIN words w ON w.id = bw.word_id'''
                if kind == 'learn':
                    sql = select + ''' LEFT JOIN user_word_records r ON r.word_id = w.id AND r.user_id = %s
                        WHERE bw.book_id = %s AND r.id IS NULL ORDER BY bw.word_rank, w.id LIMIT %s'''
                    params = (user_id, user_id, book_id, min(10, remaining))
                else:
                    sql = select.split('FROM book_words bw')[0] + '''FROM words w
                        JOIN user_word_records r ON r.word_id = w.id AND r.user_id = %s
                        JOIN book_words bw ON bw.id = (
                            SELECT candidate.id FROM book_words candidate
                            WHERE candidate.word_id = w.id AND candidate.book_trans IS NOT NULL
                                AND JSON_LENGTH(candidate.book_trans) > 0
                            ORDER BY (candidate.book_id = %s) DESC, candidate.book_id LIMIT 1)
                        WHERE r.status != 'mastered' AND r.next_review_at <= %s
                        AND NOT EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = r.user_id AND p.word_id = r.word_id)
                        AND NOT EXISTS(SELECT 1 FROM daily_review_words d WHERE d.user_id = r.user_id
                            AND d.word_id = r.word_id AND d.study_date = %s)
                        ORDER BY r.next_review_at, w.id LIMIT %s'''
                    params = (user_id, user_id, book_id, now, now.date(), min(10, remaining))
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                if not rows:
                    return True, '暂无可学习的单词' if kind == 'learn' else '暂无到期复习单词', {'group_id': None, 'total': 0, 'passed_count': 0, 'words': []}
                cursor.execute('SELECT book_trans FROM book_words WHERE book_id = %s AND book_trans IS NOT NULL ORDER BY RAND() LIMIT 100', (book_id,))
                pool = list(dict.fromkeys(translation(r['book_trans']) for r in cursor.fetchall()))
                pool += ['n. 景象，视线', 'v. 维持，保持', 'adj. 复杂的', 'adv. 逐渐地']
                state = {'words': {}, 'receipts': {}}
                for row in rows:
                    correct = translation(row['book_trans'])
                    wrong = list(dict.fromkeys(x for x in pool if x != correct))
                    choices = [correct] + random.sample(wrong, 3)
                    random.shuffle(choices)
                    word = {k: row[k] for k in ('word_id', 'word', 'us_phone', 'uk_phone')}
                    word.update({'question_id': uuid.uuid4().hex, 'is_favorited': bool(row['is_favorited']),
                                 'is_mastered': False, 'passed': False, 'mistakes': 0,
                                 'options': [{'key': k, 'trans': t} for k, t in zip('ABCD', choices)],
                                 'correct_key': 'ABCD'[choices.index(correct)],
                                 'word_detail': {'word': row['word'], 'us_phone': row['us_phone'], 'uk_phone': row['uk_phone'],
                                                 'translations': parsed(row['book_trans']), 'sentences': parsed(row['book_sentences']),
                                                 'phrases': parsed(row['book_phrases']), 'rem_method': row['book_rem_method']}})
                    state['words'][str(row['word_id'])] = word
                group_id = uuid.uuid4().hex
                cursor.execute('''INSERT INTO study_groups (id, user_id, book_id, task_type, study_date, state, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                               (group_id, user_id, book_id, kind, now.date(), json.dumps(state, ensure_ascii=False), now))
                return True, 'success', packet(group_id, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def answer(user_id, kind, group_id, word_id, question_id, request_id, selected_key=None, is_show_answer=False):
        try:
            if not positive_id(word_id) or not text_id(question_id) or not text_id(request_id):
                raise StudyError('需要正整数 word_id，以及非空 question_id、request_id（最多64字符）')
            if type(is_show_answer) is not bool:
                raise StudyError('is_show_answer 必须为布尔值')
            if is_show_answer:
                if selected_key is not None:
                    raise StudyError('看答案时 selected_key 必须为 null 或省略')
            elif not isinstance(selected_key, str) or selected_key.upper() not in ('A', 'B', 'C', 'D'):
                raise StudyError('selected_key 必须为 A、B、C、D')
            selected_key = selected_key.upper() if selected_key else None
            fingerprint = [word_id, question_id, selected_key, is_show_answer]
            with get_db() as cursor:
                user = locked_user(cursor, user_id)
                group, state = load_group(cursor, user_id, group_id, kind)
                receipt = state['receipts'].get(request_id)
                if receipt:
                    if receipt['input'] != fingerprint:
                        raise StudyError('request_id 已用于其他答案；重试必须保持原请求内容')
                    return True, '已处理该请求', receipt['data']
                check_active(group, user)
                word = state['words'].get(str(word_id))
                if not word:
                    raise StudyError('该单词不属于此题组')
                if word['passed']:
                    raise StudyError('该词已完成，无需重复答题')
                if word['question_id'] != question_id:
                    raise StudyError('题目版本已更新，请重新获取题组')
                correct = not is_show_answer and selected_key == word['correct_key']
                result = {'is_correct': correct, 'correct_key': word['correct_key'], 'word_detail': word['word_detail']}
                if kind == 'review':
                    result.update(StudyService._apply_review(cursor, user_id, word_id, correct))
                    word['passed'] = True  # 正式复习每词本次只作答一次，错词安排到明天。
                else:
                    word['passed'] = correct
                if not correct:
                    word['mistakes'] += 1
                if kind == 'learn' and not correct:
                    # 错题生成新版本，旧请求即便更换 request_id 也不能再次计错。
                    correct_trans = next(o['trans'] for o in word['options'] if o['key'] == word['correct_key'])
                    random.shuffle(word['options'])
                    for key, option in zip('ABCD', word['options']):
                        option['key'] = key
                        if option['trans'] == correct_trans:
                            word['correct_key'] = key
                    word['question_id'] = uuid.uuid4().hex
                    result['retry_question'] = public_word(word)
                result['passed_count'] = sum(w['passed'] for w in state['words'].values())
                result['total'] = len(state['words'])
                state['receipts'][request_id] = {'input': fingerprint, 'data': result}
                completed = kind == 'review' and all(w['passed'] for w in state['words'].values())
                save_group(cursor, group_id, state, completed)
                return True, 'success', result
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def _apply_review(cursor, user_id, word_id, correct):
        now = study_now()
        cursor.execute('SELECT stage, proficiency, status, next_review_at, EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = user_word_records.user_id AND p.word_id = user_word_records.word_id) AS is_review_paused FROM user_word_records WHERE user_id = %s AND word_id = %s FOR UPDATE', (user_id, word_id))
        record = cursor.fetchone()
        if not record or record['status'] == 'mastered' or record['is_review_paused'] or record['next_review_at'] > now:
            raise StudyError('该词不在到期复习队列中，请刷新题组')
        cursor.execute('SELECT word_id FROM daily_review_words WHERE user_id = %s AND study_date = %s AND word_id = %s', (user_id, now.date(), word_id))
        if cursor.fetchone():
            raise StudyError('该词今日已完成正式复习')
        stage = min(record['stage'] + 1, 7) if correct else 0
        status = 'mastered' if stage == 7 else 'reviewing'
        proficiency = min(record['proficiency'] + 10, 100) if correct else max(record['proficiency'] - 5, 0)
        # 旧表 next_review_at 非空，mastered 使用当天零点占位；队列始终排除 mastered。
        next_time = review_at(StudyService.INTERVALS[stage] if stage < 7 else 0, now)
        cursor.execute('''UPDATE user_word_records SET stage = %s, status = %s, proficiency = %s,
            wrong_count = wrong_count + %s, review_count = review_count + 1,
            last_reviewed_at = %s, next_review_at = %s WHERE user_id = %s AND word_id = %s''',
                       (stage, status, proficiency, int(not correct), now, next_time, user_id, word_id))
        cursor.execute('INSERT INTO daily_review_words (user_id, study_date, word_id) VALUES (%s, %s, %s)', (user_id, now.date(), word_id))
        add_stats(cursor, user_id, 'reviewed_count', 1, now.date())
        return {'new_stage': stage, 'new_status': status, 'next_review_at': next_time.strftime('%Y-%m-%d %H:%M:%S') if stage < 7 else None}

    @staticmethod
    def complete_learn_group(user_id, group_id):
        try:
            with get_db() as cursor:
                user = locked_user(cursor, user_id)
                group, state = load_group(cursor, user_id, group_id, 'learn')
                if group['status'] == 'completed':
                    return True, '本组已结算', state['summary']
                check_active(group, user)
                if not all(w['passed'] for w in state['words'].values()):
                    raise StudyError('本组尚未全部通过，请完成错词重测或标记已掌握')
                now = study_now()
                summary = []
                for word in state['words'].values():
                    # 新学结算只插入缺失记录，保留已有掌握状态和排程。
                    cursor.execute('''INSERT INTO user_word_records
                        (user_id, word_id, status, stage, wrong_count, next_review_at, created_at)
                        VALUES (%s, %s, 'learning', 0, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE id = id''',
                                   (user_id, word['word_id'], word['mistakes'], review_at(1, now), now))
                    summary.append({'word_id': word['word_id'], 'word': word['word'],
                                    'trans': translation(word['word_detail']['translations']),
                                    'is_mastered': word['is_mastered'],
                                    'performance': '已掌握' if word['is_mastered'] else ('一次通过' if not word['mistakes'] else f"错{word['mistakes']}次")})
                add_stats(cursor, user_id, 'new_learned_count', len(summary), now.date())
                state['summary'] = {'group_id': group_id, 'summary_list': summary}
                save_group(cursor, group_id, state, True)
                return True, '本组学习完成', state['summary']
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def master(user_id, word_id, group_id=None):
        try:
            if not positive_id(word_id):
                raise StudyError('word_id 必须为正整数')
            with get_db() as cursor:
                user = locked_user(cursor, user_id)
                group = state = None
                if group_id is not None:
                    group, state = load_group(cursor, user_id, group_id, 'learn')
                    check_active(group, user)
                    if str(word_id) not in state['words']:
                        raise StudyError('该单词不属于此题组')
                cursor.execute('SELECT id FROM words WHERE id = %s', (word_id,))
                if not cursor.fetchone():
                    raise StudyError('单词不存在')
                now = study_now()
                cursor.execute('''INSERT INTO user_word_records (user_id, word_id, status, stage, proficiency, next_review_at, created_at)
                    VALUES (%s, %s, 'mastered', 7, 100, %s, %s)
                    ON DUPLICATE KEY UPDATE status = 'mastered', stage = 7, proficiency = 100''', (user_id, word_id, review_at(0, now), now))
                cursor.execute('DELETE FROM review_pauses WHERE user_id = %s AND word_id = %s', (user_id, word_id))
                # 同步当前用户全部活动题组，避免阅读页标熟后，已有题组仍强制答题。
                cursor.execute("SELECT * FROM study_groups WHERE user_id = %s AND status = 'active' AND study_date = %s FOR UPDATE", (user_id, now.date()))
                for active in cursor.fetchall():
                    active_state = parsed(active['state'])
                    word = active_state['words'].get(str(word_id))
                    if word:
                        word['passed'] = True
                        word['is_mastered'] = True
                        save_group(cursor, active['id'], active_state,
                                   active['task_type'] == 'review' and all(w['passed'] for w in active_state['words'].values()))
                result = {'word_id': word_id, 'is_mastered': True}
                if group is not None:
                    state['words'][str(word_id)]['passed'] = True
                    result.update({'group_id': group_id, 'passed_count': sum(w['passed'] for w in state['words'].values()), 'total': len(state['words'])})
                return True, '已标记为掌握', result
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def review_summary(user_id, group_id):
        try:
            with get_db() as cursor:
                locked_user(cursor, user_id)
                group, state = load_group(cursor, user_id, group_id, 'review')
                receipts_by_word = {}
                for receipt in state['receipts'].values():
                    request_input = receipt.get('input') or []
                    result = receipt.get('data') or {}
                    if request_input and result:
                        receipts_by_word[str(request_input[0])] = (request_input, result)

                summary_list = []
                for word_id, word in state['words'].items():
                    saved = receipts_by_word.get(str(word.get('word_id', word_id)))
                    detail = (saved[1].get('word_detail') if saved else None) or word.get('word_detail') or {}
                    correct_key = saved[1].get('correct_key') if saved else word.get('correct_key')
                    selected_key = saved[0][2] if saved and len(saved[0]) > 2 else None
                    is_show_answer = bool(saved and len(saved[0]) > 3 and saved[0][3])
                    options = word.get('options') or []
                    correct_text = next((o.get('trans') for o in options if o.get('key') == correct_key), None)
                    selected_text = next((o.get('trans') for o in options if o.get('key') == selected_key), None)
                    is_correct = bool(saved and saved[1].get('is_correct'))
                    skipped = bool(word.get('skipped')) or saved is None
                    summary_list.append({
                        'word_id': word.get('word_id', int(word_id)),
                        'word': word.get('word', detail.get('word', '')),
                        'trans': translation(detail.get('translations')),
                        'performance': '已跳过' if skipped else ('答对' if is_correct else ('查看答案' if is_show_answer else '答错')),
                        'is_correct': is_correct,
                        'is_skipped': skipped,
                        'is_show_answer': is_show_answer,
                        'selected_key': selected_key,
                        'selected_text': selected_text,
                        'correct_key': correct_key,
                        'correct_text': correct_text,
                        'is_mastered': bool(saved and saved[1].get('new_status') == 'mastered'),
                        'word_detail': detail,
                    })
                reviewed_count = len(receipts_by_word)
                return True, '复习数量已在答题时统计，此接口不再累加', {
                    'group_id': group_id, 'is_completed': group['status'] == 'completed',
                    'reviewed_count': reviewed_count, 'total': len(state['words']),
                    'summary_list': summary_list}
        except StudyError as exc:
            return False, str(exc), None
