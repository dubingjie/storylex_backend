"""收藏夹和小结的自主巩固：只保存练习自身，不写任何正式学习表。"""
import json
import random
import uuid

from db import get_db
from services.study_service import StudyError, locked_user, parsed, positive_id, text_id, translation
from utils.study_time import study_now


def session_packet(row, state):
    data = {'session_id': row['id'], 'source': row['source'], 'status': row['status'],
            'target_book_id': row['book_id'], 'mode': state['input']['mode'],
            'total': len(state['questions']),
            'questions': [{k: v for k, v in q.items() if k not in ('correct_key', 'word_detail')} for q in state['questions']]}
    if row['status'] == 'completed':
        data['result'] = state['result']
    return data


def owned_session(cursor, user_id, session_id):
    if not text_id(session_id):
        raise StudyError('session_id必须为非空字符串（最多64字符）')
    cursor.execute('SELECT * FROM independent_practice_sessions WHERE id = %s AND user_id = %s FOR UPDATE', (session_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise StudyError('自主练习不存在或无权访问')
    return row, parsed(row['state'])


def normalize_answers(answers):
    if not isinstance(answers, list) or not 1 <= len(answers) <= 20:
        raise StudyError('answers必须为包含全部题目的列表（1到20题）')
    normalized, seen = [], set()
    for answer in answers:
        if not isinstance(answer, dict) or not positive_id(answer.get('word_id')) or not text_id(answer.get('question_id')):
            raise StudyError('每题需要正整数word_id和非空question_id')
        if 'is_correct' in answer:
            raise StudyError('请提交selected_key，由后端判断对错，不接受is_correct')
        show = answer.get('is_show_answer', False)
        key = answer.get('selected_key')
        if type(show) is not bool or (show and key is not None):
            raise StudyError('看答案时is_show_answer=true，selected_key=null或省略')
        if not show and (not isinstance(key, str) or key.upper() not in ('A', 'B', 'C', 'D')):
            raise StudyError('selected_key必须为A、B、C、D')
        qid = answer['question_id']
        if qid in seen:
            raise StudyError('同一道题不能重复提交')
        seen.add(qid)
        normalized.append([qid, answer['word_id'], key.upper() if key else None, show])
    return sorted(normalized)


class IndependentPracticeService:
    @staticmethod
    def create(user_id, source, word_ids, request_id, mode='mixed', group_id=None):
        try:
            if source not in ('favorites', 'learn'):
                raise StudyError('练习来源无效')
            if not isinstance(word_ids, list) or not 1 <= len(word_ids) <= 20 or not all(positive_id(w) for w in word_ids):
                raise StudyError('word_ids必须为1到20个正整数，不会静默截断')
            if not text_id(request_id) or mode not in ('mixed', 'en_to_zh', 'zh_to_en'):
                raise StudyError('需要非空request_id，mode必须为mixed、en_to_zh或zh_to_en')
            if group_id is not None and (source != 'learn' or not text_id(group_id)):
                raise StudyError('group_id仅用于小结练习，必须为有效的新学组编号')
            ids = sorted(set(word_ids))
            payload = {'word_ids': ids, 'mode': mode, 'group_id': group_id}
            with get_db() as c:
                user = locked_user(c, user_id)
                c.execute('SELECT * FROM independent_practice_sessions WHERE user_id = %s AND source = %s AND request_id = %s FOR UPDATE', (user_id, source, request_id))
                existing = c.fetchone()
                if existing:
                    state = parsed(existing['state'])
                    if state['input'] != payload:
                        raise StudyError('request_id已用于其他出题参数，请使用新编号')
                    return True, '返回原自主练习', session_packet(existing, state)
                placeholders = ','.join(['%s'] * len(ids))
                if source == 'favorites':
                    c.execute(f'SELECT word_id FROM user_favorite_words WHERE user_id = %s AND word_id IN ({placeholders})', [user_id] + ids)
                else:
                    c.execute(f'SELECT word_id FROM user_word_records WHERE user_id = %s AND word_id IN ({placeholders})', [user_id] + ids)
                if len(c.fetchall()) != len(ids):
                    raise StudyError('所选单词必须全部属于本人收藏' if source == 'favorites' else '小结练习只允许练习本人已学习的单词')
                if group_id is not None:
                    c.execute("SELECT state FROM study_groups WHERE id = %s AND user_id = %s AND task_type = 'learn' AND status = 'completed'", (group_id, user_id))
                    group = c.fetchone()
                    if not group or not set(map(str, ids)) <= set(parsed(group['state'])['words']):
                        raise StudyError('所选单词不属于本人已结算的新学组')
                c.execute(f'''SELECT w.id AS word_id, w.word, w.us_phone, w.uk_phone, bw.book_trans,
                    bw.book_sentences, bw.book_rem_method, bw.book_id AS translation_book_id
                    FROM words w LEFT JOIN book_words bw ON bw.id = (
                        SELECT b.id FROM book_words b WHERE b.word_id = w.id AND b.book_trans IS NOT NULL
                            AND JSON_LENGTH(b.book_trans) > 0
                        ORDER BY (b.book_id = %s) DESC, b.book_id LIMIT 1)
                    WHERE w.id IN ({placeholders}) ORDER BY w.id''', [user['current_book_id']] + ids)
                targets = c.fetchall()
                if len(targets) != len(ids) or any(not r['book_trans'] or translation(r['book_trans']) == '释义待补充' for r in targets):
                    raise StudyError('部分单词没有可用释义，请先补齐释义或取消选择')
                c.execute('''SELECT w.word, bw.book_trans FROM book_words bw JOIN words w ON w.id = bw.word_id
                    WHERE bw.book_trans IS NOT NULL AND JSON_LENGTH(bw.book_trans) > 0
                    ORDER BY (bw.book_id = %s) DESC, RAND() LIMIT 200''', (user['current_book_id'],))
                pool = list(c.fetchall()) + list(targets)
                directions = [mode] * len(targets) if mode != 'mixed' else ['en_to_zh' if i % 2 == 0 else 'zh_to_en' for i in range(len(targets))]
                random.shuffle(directions)
                questions = []
                for word, direction in zip(targets, directions):
                    correct_trans = translation(word['book_trans'])
                    correct = correct_trans if direction == 'en_to_zh' else word['word']
                    distractors = []
                    seen = {correct.casefold()}
                    for candidate in pool:
                        candidate_trans = translation(candidate['book_trans'])
                        if candidate_trans in ('释义待补充', correct_trans) or candidate['word'].casefold() == word['word'].casefold():
                            continue
                        choice = candidate_trans if direction == 'en_to_zh' else candidate['word']
                        if choice.casefold() not in seen:
                            seen.add(choice.casefold())
                            distractors.append(choice)
                    if len(distractors) < 3:
                        raise StudyError('有效且不同的干扰选项不足3个，请补充词库后重试')
                    choices = [correct] + random.sample(distractors, 3)
                    random.shuffle(choices)
                    question = {'question_id': uuid.uuid4().hex, 'word_id': word['word_id'],
                                'question_type': direction, 'prompt': word['word'] if direction == 'en_to_zh' else correct_trans,
                                'options': [{'key': k, 'text': t} for k, t in zip('ABCD', choices)],
                                'correct_key': 'ABCD'[choices.index(correct)],
                                'word_detail': {'word': word['word'], 'us_phone': word['us_phone'], 'uk_phone': word['uk_phone'],
                                                'translations': parsed(word['book_trans']), 'sentences': parsed(word['book_sentences']),
                                                'rem_method': word['book_rem_method'], 'translation_book_id': word['translation_book_id']}}
                    if direction == 'en_to_zh':
                        question.update({'us_phone': word['us_phone'], 'uk_phone': word['uk_phone']})
                    questions.append(question)
                state = {'input': payload, 'questions': questions}
                sid = uuid.uuid4().hex
                c.execute('''INSERT INTO independent_practice_sessions (id, user_id, source, request_id, book_id, state, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                          (sid, user_id, source, request_id, user['current_book_id'], json.dumps(state, ensure_ascii=False), study_now()))
                return True, '自主练习已生成', session_packet({'id': sid, 'source': source, 'status': 'active', 'book_id': user['current_book_id']}, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def get(user_id, session_id):
        try:
            with get_db() as c:
                row, state = owned_session(c, user_id, session_id)
                return True, 'success', session_packet(row, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def answer(user_id, session_id, request_id, answer):
        """判定自主练习中的一道题，不触碰正式学习或复习记录。"""
        try:
            if not text_id(request_id):
                raise StudyError('request_id必须为非空字符串（最多64字符）')
            if not isinstance(answer, dict):
                raise StudyError('answer必须为JSON对象')
            normalized = normalize_answers([answer])[0]
            qid, wid, key, show = normalized
            with get_db() as c:
                locked_user(c, user_id)
                row, state = owned_session(c, user_id, session_id)
                expected = {q['question_id']: q for q in state['questions']}
                q = expected.get(qid)
                if not q:
                    raise StudyError('question_id不属于此练习')
                if q['word_id'] != wid:
                    raise StudyError('word_id与question_id不匹配')

                answers = state.setdefault('question_answers', {})
                requests = state.setdefault('answer_requests', {})
                previous_request = requests.get(request_id)
                if previous_request:
                    if previous_request['answer'] != normalized:
                        raise StudyError('request_id已用于其他答案，请使用新的编号')
                    return True, '返回原题判定结果', previous_request['response']

                previous_answer = answers.get(qid)
                if previous_answer:
                    if previous_answer['answer'] != normalized:
                        raise StudyError('此题已经作答，不能修改答案')
                    return True, '返回原题判定结果', previous_answer['response']
                if row['status'] == 'completed':
                    raise StudyError('练习已完成，不能继续作答')
                if state.get('submission'):
                    raise StudyError('此练习已使用整轮提交，不能再逐题作答')

                feedback = {
                    'session_id': session_id,
                    'question_id': qid,
                    'word_id': wid,
                    'is_correct': not show and key == q['correct_key'],
                    'correct_key': q['correct_key'],
                    'selected_key': key,
                    'is_show_answer': show,
                    'word_detail': q['word_detail'],
                }
                answers[qid] = {'answer': normalized, 'response': feedback}
                completed = len(answers) == len(expected)
                response = dict(feedback, completed=completed)
                result = None
                if completed:
                    results = []
                    for question in state['questions']:
                        item = answers[question['question_id']]
                        _, answer_word_id, selected_key, showed = item['answer']
                        results.append({
                            'question_id': question['question_id'],
                            'word_id': answer_word_id,
                            'question_type': question['question_type'],
                            'is_correct': not showed and selected_key == question['correct_key'],
                            'correct_key': question['correct_key'],
                            'word_detail': question['word_detail'],
                        })
                    correct = sum(item['is_correct'] for item in results)
                    result = {
                        'session_id': session_id,
                        'total': len(results),
                        'correct_count': correct,
                        'wrong_count': len(results) - correct,
                        'score': (100 * correct + len(results) // 2) // len(results),
                        'wrong_word_ids': [item['word_id'] for item in results if not item['is_correct']],
                        'results': results,
                    }
                    state['result'] = result
                    response['summary'] = result
                answers[qid]['response'] = response
                requests[request_id] = {'answer': normalized, 'response': response}
                status = 'completed' if completed else 'active'
                c.execute('''UPDATE independent_practice_sessions
                    SET status = %s, state = %s, completed_at = %s WHERE id = %s''',
                          (status, json.dumps(state, ensure_ascii=False), study_now() if completed else None, session_id))
                return True, '本题判定完成', response
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def submit(user_id, session_id, request_id, answers):
        try:
            if not text_id(request_id):
                raise StudyError('request_id必须为非空字符串（最多64字符）')
            normalized = normalize_answers(answers)
            with get_db() as c:
                locked_user(c, user_id)
                row, state = owned_session(c, user_id, session_id)
                if state.get('question_answers'):
                    raise StudyError('此练习使用逐题判题，不能再整轮提交')
                if row['status'] == 'completed':
                    if state['submission']['answers'] != normalized:
                        raise StudyError('练习已结算，不能修改答案；请使用新request_id重新出题')
                    return True, '返回原练习成绩', state['result']
                expected = {q['question_id']: q for q in state['questions']}
                if len(normalized) != len(expected) or {a[0] for a in normalized} != set(expected):
                    raise StudyError('必须提交本练习全部题目，不得遗漏或加入其他题目')
                results = []
                for qid, wid, key, show in normalized:
                    q = expected[qid]
                    if q['word_id'] != wid:
                        raise StudyError('word_id与question_id不匹配')
                    results.append({'question_id': qid, 'word_id': wid, 'question_type': q['question_type'],
                                    'is_correct': not show and key == q['correct_key'], 'correct_key': q['correct_key'],
                                    'word_detail': q['word_detail']})
                correct = sum(r['is_correct'] for r in results)
                result = {'session_id': session_id, 'total': len(results), 'correct_count': correct,
                          'wrong_count': len(results) - correct, 'score': (100 * correct + len(results) // 2) // len(results),
                          'wrong_word_ids': [r['word_id'] for r in results if not r['is_correct']], 'results': results}
                state['submission'] = {'request_id': request_id, 'answers': normalized}
                state['result'] = result
                c.execute("UPDATE independent_practice_sessions SET status = 'completed', state = %s, completed_at = %s WHERE id = %s",
                          (json.dumps(state, ensure_ascii=False), study_now(), session_id))
                return True, '自主练习完成，不影响正式复习排程', result
        except StudyError as exc:
            return False, str(exc), None
