"""纯词书匹配的TXT导入，不调用模型、不保存上传文件到磁盘。"""
import hashlib
import html
import json
import re
import uuid

from db import get_db
from services.study_service import StudyError, locked_user, parsed, text_id, translation
from services.ai_draft_service import validate_content, validate_title, draft_packet
from utils.study_time import study_now

MAX_FILE_BYTES = 200 * 1024
MAX_TEXT_CHARS = 40000


def decode_txt(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FILE_BYTES:
        raise StudyError('TXT文件不能为空，且不能超过200KB')
    encodings = ['utf-16'] if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise StudyError('无法识别文件编码，请另存为UTF-8后重试')
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text or len(text) > MAX_TEXT_CHARS:
        raise StudyError('TXT正文必须为1到40000字符，长篇请分章导入')
    if any(ord(c) < 32 and c not in '\n\t' for c in text):
        raise StudyError('文件包含二进制或非法控制字符，请上传纯文本TXT')
    if not re.search(r'[\u4e00-\u9fff]', text):
        raise StudyError('请上传包含中文的TXT正文')
    return text, encoding


def replacement_dictionary(rows):
    """只提取完整、长度2～12的中文义项，不对解释性长句或单字做替换。"""
    meanings = {}
    for row in rows:
        entries = parsed(row['book_trans'])
        if not isinstance(entries, list):
            continue
        for item in entries:
            text = item.get('tranCn', '') if isinstance(item, dict) else item
            if not isinstance(text, str):
                continue
            for term in re.split(r'[；;，,、/（）()\n]', text):
                term = term.strip()
                if re.fullmatch(r'[\u4e00-\u9fff]{2,12}', term):
                    meanings.setdefault(term, []).append(row)
    # 输入已按词书rank和word_id排序，同中文义项稳定选排位最前的词。
    trie = {}
    for term, candidates in meanings.items():
        node = trie
        for char in term:
            node = node.setdefault(char, {})
        node[''] = (term, candidates[0], sorted({r['word_id'] for r in candidates}))
    return trie


def convert_text(text, rows, max_replacements, min_gap):
    trie = replacement_dictionary(rows)
    parts, replacements, targets = [], [], {}
    index = plain_start = 0
    last_end = -min_gap
    while index < len(text) and len(replacements) < max_replacements:
        if index - last_end < min_gap:
            index += 1
            continue
        node = trie
        stop = index
        match = None
        while stop < len(text) and text[stop] in node:
            node = node[text[stop]]
            stop += 1
            if '' in node:
                match = (stop, node[''])
        if match is None:
            index += 1
            continue
        end, (term, row, alternatives) = match
        parts.append(html.escape(text[plain_start:index], quote=False))
        parts.append(f'<word id="{row["word_id"]}">{html.escape(row["word"], quote=False)}</word>')
        replacements.append({'chinese': term, 'word_id': row['word_id'], 'word': row['word'],
                             'start': index, 'end': end, 'candidate_word_ids': alternatives})
        targets.setdefault(row['word_id'], {'word_id': row['word_id'], 'word': row['word'],
                                           'translation': translation(row['book_trans'])})
        index = plain_start = last_end = end
    parts.append(html.escape(text[plain_start:], quote=False))
    if not replacements:
        raise StudyError('正文未匹配到可替换的中文义项，请更换词书或正文；目前仅匹配2到12字的完整词书义项')
    body = validate_content(''.join(parts), list(targets.values()))
    return body, list(targets.values()), replacements


class TxtImportService:
    @staticmethod
    def preview(user_id, raw, filename, target_book_id, request_id, title=None, max_replacements=20, min_gap=30):
        try:
            if not isinstance(filename, str) or not filename.lower().endswith('.txt'):
                raise StudyError('只支持.txt文件')
            if not text_id(request_id):
                raise StudyError('request_id必须为非空字符串（最多64字符）')
            if not isinstance(target_book_id, str) or not 1 <= len(target_book_id) <= 32:
                raise StudyError('target_book_id必须为有效词书ID')
            if type(max_replacements) is not int or not 1 <= max_replacements <= 100:
                raise StudyError('max_replacements必须为1到100的整数')
            if type(min_gap) is not int or not 0 <= min_gap <= 1000:
                raise StudyError('min_gap必须为0到1000的整数')
            text, encoding = decode_txt(raw)
            # 文件名只作显示，不作为服务器路径使用。
            display_name = filename.replace('\\', '/').rsplit('/', 1)[-1][:255]
            title = validate_title(title if title is not None else display_name[:-4])
            payload = {'source_type': 'imported', 'story_type': 'TXT导入', 'target_book_id': target_book_id,
                       'content_sha256': hashlib.sha256(raw).hexdigest(), 'filename': display_name,
                       'title': title, 'max_replacements': max_replacements, 'min_gap': min_gap}
            with get_db() as c:
                locked_user(c, user_id)
                c.execute('SELECT * FROM ai_story_drafts WHERE user_id = %s AND request_id = %s FOR UPDATE', (user_id, request_id))
                existing = c.fetchone()
                if existing:
                    state = parsed(existing['state'])
                    if state['input'] != payload:
                        raise StudyError('request_id已用于其他文件或参数，请使用新编号')
                    return True, '返回原导入草稿', draft_packet(existing, state)
                c.execute('SELECT id FROM books WHERE id = %s', (target_book_id,))
                if not c.fetchone():
                    raise StudyError('目标词书不存在')
                c.execute('''SELECT w.id AS word_id, w.word, bw.book_trans FROM book_words bw
                    JOIN words w ON w.id = bw.word_id WHERE bw.book_id = %s AND bw.book_trans IS NOT NULL
                    ORDER BY bw.word_rank, w.id''', (target_book_id,))
                body, targets, replacements = convert_text(text, c.fetchall(), max_replacements, min_gap)
                state = {'input': payload, 'source_type': 'imported', 'source_content': text,
                         'targets': targets, 'title': title, 'processed_content': body['processed_content'],
                         'import_info': {'filename': display_name, 'encoding': encoding,
                                         'max_replacements': max_replacements, 'min_gap': min_gap,
                                         'replacements': replacements,
                                         'notice': '按词书字面义项替换，未做语境消歧，请预览检查后保存'}}
                draft_id = uuid.uuid4().hex
                now = study_now()
                c.execute('''INSERT INTO ai_story_drafts
                    (id, user_id, book_id, request_id, status, version, state, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'ready', 1, %s, %s, %s)''',
                          (draft_id, user_id, target_book_id, request_id, json.dumps(state, ensure_ascii=False), now, now))
                row = {'id': draft_id, 'status': 'ready', 'version': 1, 'book_id': target_book_id, 'story_id': None}
                return True, '导入预览已生成，请确认后保存', draft_packet(row, state)
        except StudyError as exc:
            return False, str(exc), None
