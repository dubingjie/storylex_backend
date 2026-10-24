import sys
from pathlib import Path

# 支持从任意目录直接执行脚本，统一读取项目根目录的 .env。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Config

import os
import json
import pymysql

# ==========================================
# 1. 数据库连接配置
# ==========================================
DB_CONFIG = {
    'host': Config.DB_HOST,
    'port': Config.DB_PORT,
    'user': Config.DB_USER,
    'password': Config.DB_PASSWORD,
    'database': Config.DB_NAME,
    'charset': Config.DB_CHARSET,
    'autocommit': False
}
# 云端托管 MySQL（如 Aiven）强制要求 SSL；DB_SSL=true 时开启加密连接
if Config.DB_SSL:
    import ssl as _ssl_module
    _ssl_ctx = _ssl_module.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl_module.CERT_NONE
    DB_CONFIG['ssl'] = _ssl_ctx


# 动态定位 data 目录绝对路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CURRENT_DIR, '..', 'data')


def safe_json_dumps(data):
    """辅助函数：将列表或字典转为 JSON 字符串，若为空则返回 None"""
    if data:
        return json.dumps(data, ensure_ascii=False)
    return None


def get_or_create_word(cursor, word, us_phone, uk_phone):
    """
    确保单词在 words 表中全局唯一存在：
    若不存在则插入；若已存在且原音标为空，则尝试补充音标。
    返回 word_id
    """
    # 1. 查询是否已存在
    cursor.execute("SELECT id, us_phone, uk_phone FROM words WHERE word = %s LIMIT 1;", (word,))
    row = cursor.fetchone()

    if row:
        word_id, exist_us, exist_uk = row[0], row[1], row[2]
        # 如果旧记录音标缺失，而新数据中有，顺手补齐音标
        if (not exist_us and us_phone) or (not exist_uk and uk_phone):
            cursor.execute("""
                UPDATE words 
                SET us_phone = COALESCE(us_phone, %s),
                    uk_phone = COALESCE(uk_phone, %s)
                WHERE id = %s;
            """, (us_phone, uk_phone, word_id))
        return word_id
    else:
        # 2. 首次出现，插入 words 表
        cursor.execute("""
            INSERT INTO words (word, us_phone, uk_phone)
            VALUES (%s, %s, %s);
        """, (word, us_phone, uk_phone))
        return cursor.lastrowid


def import_single_book(conn, filename, book_id, book_title, book_desc):
    """导入单本词书的专属物料与排位"""
    file_path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(file_path):
        print(f"[错误] 未找到文件: {file_path}")
        return

    cursor = conn.cursor()
    print(f"\n==========================================")
    print(f"正在导入词书: 《{book_title}》({book_id})")
    print(f"读取文件: {file_path}")

    try:
        # 按行读取 JSON
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]

        total_words_count = len(lines)
        print(f"总计读取到 {total_words_count} 条词汇...")

        # 1. 写入/更新 books 表
        insert_book_sql = """
            INSERT INTO books (id, title, description, word_count)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                title = VALUES(title),
                description = VALUES(description),
                word_count = VALUES(word_count);
        """
        cursor.execute(insert_book_sql, (book_id, book_title, book_desc, total_words_count))

        # 2. 逐词入库
        success_count = 0
        for idx, line in enumerate(lines, start=1):
            item = json.loads(line)

            # 提取英文单词原型（小写去空格）
            raw_word = item.get('headWord') or item.get('content', {}).get('word', {}).get('wordHead', '')
            word = raw_word.strip().lower()
            if not word:
                continue

            word_rank = item.get('wordRank', idx)
            word_content = item.get('content', {}).get('word', {}).get('content', {})

            # 客观音标
            us_phone = word_content.get('usphone')
            uk_phone = word_content.get('ukphone')

            # 教学物料（专属释义、例句、记忆法、短语、同近义、同根）
            rem_method = (
                word_content.get('remMethod', {}).get('val')
                if isinstance(word_content.get('remMethod'), dict)
                else None
            )
            trans = safe_json_dumps(word_content.get('trans'))
            sentences = safe_json_dumps(word_content.get('sentence', {}).get('sentences'))
            phrases = safe_json_dumps(word_content.get('phrase', {}).get('phrases'))
            synos = safe_json_dumps(word_content.get('syno', {}).get('synos'))
            rel_words = safe_json_dumps(word_content.get('relWord', {}).get('rels'))

            # (1) 获取或创建全局客观单词
            word_id = get_or_create_word(cursor, word, us_phone, uk_phone)

            # (2) 写入词书专属物料到 book_words 表
            insert_bw_sql = """
                INSERT INTO book_words (
                    book_id, word_id, word_rank,
                    book_trans, book_sentences, book_phrases,
                    book_rem_method, book_synos, book_rel_words
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    word_rank = VALUES(word_rank),
                    book_trans = VALUES(book_trans),
                    book_sentences = VALUES(book_sentences),
                    book_phrases = VALUES(book_phrases),
                    book_rem_method = VALUES(book_rem_method),
                    book_synos = VALUES(book_synos),
                    book_rel_words = VALUES(book_rel_words);
            """
            cursor.execute(insert_bw_sql, (
                book_id, word_id, word_rank,
                trans, sentences, phrases,
                rem_method, synos, rel_words
            ))

            success_count += 1
            if idx % 100 == 0:
                conn.commit()
                print(f"进度: [{idx}/{total_words_count}]")

        conn.commit()
        print(f"《{book_title}》导入完成！成功录入 {success_count} 个考点词汇。")

    except Exception as e:
        conn.rollback()
        print(f"导入《{book_title}》时出错已回滚: {e}")
        raise e
    finally:
        cursor.close()


def main():
    print("正在连接 MySQL 数据库...")
    conn = pymysql.connect(**DB_CONFIG)

    try:
        # 1. 导入六级乱序核心词汇
        import_single_book(
            conn=conn,
            filename='CET6luan_1.json',
            book_id='CET6luan_1',
            book_title='大学英语六级乱序核心词汇',
            book_desc='六级真题高频乱序核心词汇'
        )

        # 2. 导入考研英语核心词汇
        import_single_book(
            conn=conn,
            filename='KaoYan_2.json',
            book_id='KaoYan_2',
            book_title='考研英语核心词汇',
            book_desc='考研英语真题高频核心词汇精选'
        )

    finally:
        conn.close()
        print("\n数据库连接已关闭，全部词书导入工作圆满完成！")


if __name__ == '__main__':
    main()