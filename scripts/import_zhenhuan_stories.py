import sys
from pathlib import Path

# 支持从任意目录直接执行脚本，统一读取项目根目录的 .env。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Config

import os
import re
import json
import pymysql
from pymysql.cursors import DictCursor

# 1. 数据库连接配置
DB_CONFIG = {
    "host": Config.DB_HOST,
    "port": Config.DB_PORT,
    "user": Config.DB_USER,
    "password": Config.DB_PASSWORD,
    "database": Config.DB_NAME,
    "charset": Config.DB_CHARSET,
    "cursorclass": DictCursor,
    "autocommit": False
}

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.abspath(os.path.join(CURRENT_DIR, "..", "data", "甄嬛传合集.md"))

TARGET_BOOK_ID = 'CET6luan_1'


def get_or_create_word(cursor, word_str):
    """
    根据单词原型获取 word_id；如果 words 表中不存在该词，自动补建一条记录。
    """
    clean_word = word_str.strip().lower()
    cursor.execute("SELECT id FROM words WHERE word = %s", (clean_word,))
    row = cursor.fetchone()
    if row:
        return row["id"]
    
    cursor.execute("INSERT INTO words (word) VALUES (%s)", (clean_word,))
    return cursor.lastrowid


def ensure_book_word_trans(cursor, word_id, word_str, cn_trans):
    """
    【新增关键逻辑】：确保 book_words 表中该词在当前词书下有释义！
    如果不存在，则直接利用 Markdown 括号里的中文释义自动插入。
    """
    cursor.execute("""
        SELECT id FROM book_words 
        WHERE book_id = %s AND word_id = %s LIMIT 1;
    """, (TARGET_BOOK_ID, word_id))
    
    if not cursor.fetchone():
        # 解析中文里的词性（比如若有 'adj. ' 或 'v. '）
        pos_match = re.match(r'^([a-zA-Z]+)\.\s*(.*)', cn_trans.strip())
        if pos_match:
            pos = pos_match.group(1)
            meaning = pos_match.group(2)
        else:
            pos = ""
            meaning = cn_trans.strip()

        trans_json = json.dumps([{
            "pos": pos,
            "descCn": "中释",
            "tranCn": meaning,
            "descOther": "英释",
            "tranOther": ""
        }], ensure_ascii=False)

        # 写入 book_words 表，排位给 9999 避免打乱原生词书正规排位
        cursor.execute("""
            INSERT INTO book_words (book_id, word_id, word_rank, book_trans)
            VALUES (%s, %s, 9999, %s)
            ON DUPLICATE KEY UPDATE book_trans = VALUES(book_trans);
        """, (TARGET_BOOK_ID, word_id, trans_json))


def parse_and_import():
    if not os.path.exists(FILE_PATH):
        print(f"找不到文件: {FILE_PATH}，请确认文件是否已放入 backend/data/ 目录！")
        return

    with open(FILE_PATH, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # 按照 markdown 标题切分篇章
    story_blocks = re.split(r'(?=^##\s+第.*?篇：)', raw_text, flags=re.MULTILINE)
    
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            imported_count = 0
            
            for block in story_blocks:
                block = block.strip()
                if not block.startswith("##"):
                    continue

                lines = block.split("\n")
                title_line = lines[0].replace("##", "").strip()
                
                # 剔除正文后面的“重点词汇”部分与水平分割线
                content_part = "\n".join(lines[1:])
                content_part = re.split(r'\*\*重点词汇[：:]\*\*', content_part)[0]
                content_part = re.sub(r'^-{3,}$', '', content_part, flags=re.MULTILINE).strip()

                # 正则匹配形如: **exquisite**（精致的） 或 **refrain from**（克制）
                pattern = r'\*\*([a-zA-Z\s\-]+)\*\*[（\(]([^）\)]*?)[）\)]'
                
                matches = re.findall(pattern, content_part)
                if not matches:
                    continue

                embedded_words = []
                seen_words = set()

                for word_text, cn_trans in matches:
                    clean_w = word_text.strip().lower()
                    word_id = get_or_create_word(cursor, clean_w)
                    
                    # 关键补充：为该词向 book_words 写入释义
                    ensure_book_word_trans(cursor, word_id, clean_w, cn_trans)

                    if clean_w not in seen_words:
                        seen_words.add(clean_w)
                        embedded_words.append((word_id, clean_w))

                # 1. 生成带标签正文 processed_content: 将 **word**（释义） 替换为 <word id="xx">word</word>
                def tag_replacer(m):
                    w_text = m.group(1).strip()
                    w_id = get_or_create_word(cursor, w_text)
                    return f'<word id="{w_id}">{w_text}</word>'

                processed_content = re.sub(pattern, tag_replacer, content_part)

                # 2. 生成纯中文正文 original_content: 直接替换为其括号内的中文释义
                def cn_replacer(m):
                    return m.group(2).strip()

                original_content = re.sub(pattern, cn_replacer, content_part)

                word_count = len(re.findall(r'[\u4e00-\u9fa5]', original_content))
                embedded_word_count = len(seen_words)

                # 插入或更新 stories 表（按标题判断，防止重复执行脚本导致大量重复文章）
                cursor.execute("SELECT id FROM stories WHERE title = %s LIMIT 1;", (title_line,))
                existing_story = cursor.fetchone()

                if existing_story:
                    story_id = existing_story["id"]
                    cursor.execute("""
                        UPDATE stories 
                        SET original_content = %s, processed_content = %s, 
                            word_count = %s, embedded_word_count = %s
                        WHERE id = %s;
                    """, (original_content, processed_content, word_count, embedded_word_count, story_id))
                else:
                    sql_story = """
                        INSERT INTO stories (
                            title, source_type, user_id, target_book_id,
                            original_content, processed_content, word_count, embedded_word_count
                        ) VALUES (%s, 'builtin', NULL, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql_story, (
                        title_line,
                        TARGET_BOOK_ID,
                        original_content,
                        processed_content,
                        word_count,
                        embedded_word_count
                    ))
                    story_id = cursor.lastrowid

                # 重新刷入 story_words 关联
                cursor.execute("DELETE FROM story_words WHERE story_id = %s;", (story_id,))
                sql_sw = """
                    INSERT INTO story_words (story_id, word_id, word_order)
                    VALUES (%s, %s, %s)
                """
                for order, (w_id, _) in enumerate(embedded_words, start=1):
                    cursor.execute(sql_sw, (story_id, w_id, order))

                imported_count += 1
                print(f"成功处理: 《{title_line}》 | 生词数: {embedded_word_count}")

            conn.commit()
            print(f"\n全部处理完毕！共计同步 {imported_count} 篇甄嬛传短文。")

    except Exception as e:
        conn.rollback()
        print(f"导入中断，已回滚: {e}")
        raise e
    finally:
        conn.close()

if __name__ == "__main__":
    parse_and_import()