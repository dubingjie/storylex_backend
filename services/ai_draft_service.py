"""AI生成草稿与显式保存；模型网络调用不占用数据库事务。"""
import html
import logging
import json
import re
import uuid
from datetime import timedelta
from xml.etree import ElementTree

from openai import OpenAI
from config import Config
from db import get_db
from services.study_service import StudyError, locked_user, parsed, positive_id, text_id, translation
from utils.model_errors import model_error
from utils.study_time import study_now


def validate_title(title):
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 150 or any(ord(c) < 32 for c in title):
        raise StudyError('标题必须为1到150字符的单行文本')
    return title.strip()


def validate_content(content, targets, require_all=False):
    """仅接收文本和word标签，规范化后按正文实际出现的唯一词生成映射。"""
    if not isinstance(content, str) or not content.strip() or len(content) > 50000:
        raise StudyError('正文必须为1到50000字符的文本')
    if '<!' in content or '<?' in content:
        raise StudyError('正文不允许声明、注释或处理指令')
    try:
        root = ElementTree.fromstring('<root>' + content.strip() + '</root>')
    except ElementTree.ParseError:
        raise StudyError('正文标签格式错误，仅允许 <word id="单词ID">英文单词</word>；文本中的 & 请写为 &amp;') from None
    allowed = {str(w['word_id']): w['word'] for w in targets}
    mapping = []
    occurrences = 0
    chunks = [html.escape(root.text or '', quote=False)]
    plain = [root.text or '']
    for child in root:
        wid = child.attrib.get('id')
        if child.tag != 'word' or set(child.attrib) != {'id'} or len(child) or wid not in allowed:
            raise StudyError('正文仅允许不嵌套的word标签，id必须来自本草稿的目标词')
        label = child.text or ''
        normalized = ' '.join(label.split()).casefold()
        if normalized != ' '.join(allowed[wid].split()).casefold():
            raise StudyError(f'单词标签内容与词库不匹配：ID {wid} 应为 {allowed[wid]}')
        occurrences += 1
        if int(wid) not in mapping:
            mapping.append(int(wid))
        chunks.append(f'<word id="{wid}">{html.escape(label, quote=False)}</word>')
        chunks.append(html.escape(child.tail or '', quote=False))
        plain.extend([label, child.tail or ''])
    if not mapping:
        raise StudyError('正文至少保留一个有效的目标单词标签')
    missing = [w['word_id'] for w in targets if w['word_id'] not in mapping]
    if require_all and missing:
        raise StudyError('AI生成正文缺少部分目标单词，请重新生成')
    original = ''.join(plain)
    return {'processed_content': ''.join(chunks), 'original_content': original,
            'word_count': len(re.findall(r'[\u4e00-\u9fff]', original)),
            'embedded_word_count': len(mapping), 'embedded_occurrences': occurrences,
            'word_ids': mapping, 'missing_word_ids': missing}


def read_draft(cursor, user_id, draft_id):
    if not text_id(draft_id):
        raise StudyError('draft_id 必须为非空字符串（最多64字符）')
    cursor.execute('SELECT * FROM ai_story_drafts WHERE id = %s AND user_id = %s FOR UPDATE', (draft_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise StudyError('草稿不存在或无权访问')
    return row, parsed(row['state'])


def write_state(cursor, draft_id, status, version, state, story_id=None):
    cursor.execute('UPDATE ai_story_drafts SET status = %s, version = %s, state = %s, story_id = %s, updated_at = %s WHERE id = %s',
                   (status, version, json.dumps(state, ensure_ascii=False), story_id, study_now(), draft_id))


def draft_packet(row, state):
    data = {'draft_id': row['id'], 'status': row['status'], 'version': row['version'],
            'target_book_id': row['book_id'], 'story_id': row['story_id'],
            'target_words': state['targets'], 'story_type': state['input']['story_type'],
            'title': state.get('title'), 'processed_content': state.get('processed_content'),
            'error': state.get('error'), 'error_code': state.get('error_code'),
            'http_status': state.get('http_status'),
            'source_type': state.get('source_type', 'ai_generated')}
    if state.get('source_type') == 'imported':
        data['source_content'] = state['source_content']
        data['import_info'] = state['import_info']
    if state.get('processed_content'):
        for key, value in validate_content(state['processed_content'], state['targets']).items():
            data[key] = value
    return data


def expire_generating(cursor, row, state):
    if row['status'] == 'generating' and study_now() - row['created_at'] > timedelta(minutes=5):
        state['error'] = '生成超时，请使用新的request_id重新生成'
        write_state(cursor, row['id'], 'failed', row['version'], state)
        row['status'] = 'failed'


class AIDraftService:
    @staticmethod
    def _model_text(targets, story_type):
        material = '\n'.join(f'{w["word_id"]}: {w["word"]}（{w["translation"]}）' for w in targets)
        with OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_BASE_URL,
                        timeout=60.0, max_retries=0) as client:
            response = client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=[
                    {'role': 'system', 'content': '你是中文故事创作者。输出400到600字的中英混排故事；第一行为# 标题，其后为正文。正文只允许纯文本和word标签，不要代码块或其他HTML。'},
                    {'role': 'user', 'content': f'主题风格：{story_type}\n必须自然使用全部目标词：\n{material}\n'
                     '每个目标词使用 <word id="对应数字ID">词库中的英文原词</word>。'
                     '标签中的英文必须与提供的词逐字一致，不变形，不添加其他ID，不嵌套标签。文本中的&写成&amp;。'}],
                temperature=0.7)
        if not response.choices:
            raise StudyError('模型响应没有choices，服务商可能未返回有效生成结果')
        text = response.choices[0].message.content
        if not isinstance(text, str) or not text.strip():
            raise StudyError('模型未返回有效正文')
        return text.strip()

    @staticmethod
    def generate(user_id, word_ids, request_id, story_type='都市小说', title=None):
        try:
            if not isinstance(word_ids, list) or not 2 <= len(word_ids) <= 20 or not all(positive_id(w) for w in word_ids):
                raise StudyError('word_ids 必须为2到20个正整数的列表')
            ids = sorted(set(word_ids))
            if len(ids) < 2:
                raise StudyError('至少选择2个不同单词')
            if not text_id(request_id):
                raise StudyError('request_id 必须为非空字符串（最多64字符）')
            if not isinstance(story_type, str) or not story_type.strip() or len(story_type) > 1000:
                raise StudyError('story_type 必须为1到1000字符的主题')
            if title is not None:
                title = validate_title(title)
            payload = {'word_ids': ids, 'story_type': story_type.strip(), 'title': title}
            with get_db() as c:
                user = locked_user(c, user_id)
                c.execute('SELECT * FROM ai_story_drafts WHERE user_id = %s AND request_id = %s FOR UPDATE', (user_id, request_id))
                existing = c.fetchone()
                if existing:
                    state = parsed(existing['state'])
                    if state['input'] != payload:
                        raise StudyError('request_id已用于其他生成参数，请使用新编号')
                    expire_generating(c, existing, state)
                    return True, '返回原生成任务；失败时请用新request_id重试', draft_packet(existing, state)
                placeholders = ','.join(['%s'] * len(ids))
                c.execute(f'''SELECT w.id AS word_id, w.word, bw.book_trans FROM words w
                    LEFT JOIN book_words bw ON bw.id = (
                        SELECT b.id FROM book_words b WHERE b.word_id = w.id AND b.book_trans IS NOT NULL
                            AND JSON_LENGTH(b.book_trans) > 0
                        ORDER BY (b.book_id = %s) DESC, b.book_id LIMIT 1)
                    WHERE w.id IN ({placeholders}) ORDER BY w.id''', [user['current_book_id']] + ids)
                rows = c.fetchall()
                if len(rows) != len(ids):
                    raise StudyError('部分目标单词不存在，请重新选择')
                targets = [{'word_id': r['word_id'], 'word': r['word'], 'translation': translation(r['book_trans'])} for r in rows]
                state = {'input': payload, 'targets': targets}
                draft_id = uuid.uuid4().hex
                now = study_now()
                c.execute('''INSERT INTO ai_story_drafts (id, user_id, book_id, request_id, state, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                          (draft_id, user_id, user['current_book_id'], request_id, json.dumps(state, ensure_ascii=False), now, now))
            # 网络调用在提交草稿占位记录之后执行，不持有用户锁。
            try:
                raw = AIDraftService._model_text(targets, payload['story_type'])
                lines = raw.splitlines()
                generated_title = lines.pop(0)[2:].strip() if lines and lines[0].startswith('# ') else payload['story_type'][:100] + '故事'
                generated_title = validate_title(title or generated_title)
                body = validate_content('\n'.join(lines), targets, require_all=True)
                failure = None
            except StudyError as exc:
                failure = {'error': str(exc), 'error_code': 'MODEL_OUTPUT_INVALID', 'http_status': None}
            except Exception as exc:
                failure = model_error(exc)
                # 不记录str(exc)、traceback或供应商响应，防止意外带出鉴权信息。
                logging.getLogger(__name__).warning('AI draft %s failed: %s, http_status=%s, exception_type=%s',
                    draft_id, failure['error_code'], failure['http_status'], type(exc).__name__)
            with get_db() as c:
                locked_user(c, user_id)
                row, state = read_draft(c, user_id, draft_id)
                if row['status'] != 'generating':
                    return True, '返回原生成状态', draft_packet(row, state)
                if failure:
                    state.update(failure)
                    write_state(c, draft_id, 'failed', 0, state)
                    row['status'] = 'failed'
                else:
                    state.update({'title': generated_title, 'processed_content': body['processed_content']})
                    write_state(c, draft_id, 'ready', 1, state)
                    row.update({'status': 'ready', 'version': 1})
                return True, '生成失败，请查看error_code和error' if failure else '草稿已生成，请预览后保存', draft_packet(row, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def get(user_id, draft_id):
        try:
            with get_db() as c:
                locked_user(c, user_id)
                row, state = read_draft(c, user_id, draft_id)
                expire_generating(c, row, state)
                return True, 'success', draft_packet(row, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def edit(user_id, draft_id, title, processed_content, version):
        try:
            title = validate_title(title)
            if type(version) is not int or not 1 <= version < 4294967295:
                raise StudyError('version必须为查询草稿得到的正整数')
            with get_db() as c:
                locked_user(c, user_id)
                row, state = read_draft(c, user_id, draft_id)
                if row['status'] != 'ready':
                    raise StudyError('只有生成成功且未保存的草稿可以编辑')
                body = validate_content(processed_content, state['targets'])
                if row['version'] != version:
                    if version == row['version'] - 1 and state['title'] == title and state['processed_content'] == body['processed_content']:
                        return True, '草稿已更新', draft_packet(row, state)
                    raise StudyError('草稿已更新，请重新获取最新version')
                state.update({'title': title, 'processed_content': body['processed_content']})
                write_state(c, draft_id, 'ready', version + 1, state)
                row['version'] = version + 1
                return True, '草稿已更新', draft_packet(row, state)
        except StudyError as exc:
            return False, str(exc), None

    @staticmethod
    def save(user_id, draft_id, request_id, version):
        try:
            if not text_id(request_id) or type(version) is not int or version < 1:
                raise StudyError('需要有效的request_id及草稿version')
            with get_db() as c:
                locked_user(c, user_id)
                row, state = read_draft(c, user_id, draft_id)
                if row['status'] == 'saved':
                    if row['story_id'] is None:
                        raise StudyError('该草稿已保存过，关联文章已删除，不能重复保存')
                    return True, '已保存，请勿重复创建', state['saved_result']
                if row['status'] != 'ready':
                    raise StudyError('草稿尚未生成成功，无法保存')
                if row['version'] != version:
                    raise StudyError('草稿版本已更新，请重新获取后保存')
                body = validate_content(state['processed_content'], state['targets'])
                ids = body['word_ids']
                placeholders = ','.join(['%s'] * len(ids))
                c.execute(f'SELECT id FROM words WHERE id IN ({placeholders})', ids)
                if len(c.fetchall()) != len(ids):
                    raise StudyError('草稿中的单词已不存在，请重新生成')
                c.execute('''INSERT INTO stories (title, source_type, user_id, target_book_id, original_content,
                    processed_content, word_count, embedded_word_count, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                          (state['title'], state.get('source_type', 'ai_generated'), user_id, row['book_id'],
                           state.get('source_content', body['original_content']), body['processed_content'],
                           body['word_count'], body['embedded_word_count'], study_now()))
                story_id = c.lastrowid
                for order, wid in enumerate(ids, 1):
                    c.execute('INSERT INTO story_words (story_id, word_id, word_order) VALUES (%s, %s, %s)', (story_id, wid, order))
                result = {'draft_id': draft_id, 'story_id': story_id, 'title': state['title'], 'word_count': body['word_count'],
                          'embedded_word_count': body['embedded_word_count'],
                          'source_type': state.get('source_type', 'ai_generated')}
                state['saved_result'] = result
                state['save_request_id'] = request_id
                write_state(c, draft_id, 'saved', version + 1, state, story_id)
                return True, '已保存至文库', result
        except StudyError as exc:
            return False, str(exc), None
