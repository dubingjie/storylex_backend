import sys
from pathlib import Path

# 支持从任意目录直接执行脚本，统一读取项目根目录的 .env。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Config

import pymysql
from pymysql.cursors import DictCursor
import eng_to_ipa as ipa

# 数据库连接配置
DB_CONFIG = {
    "host": Config.DB_HOST,
    "port": Config.DB_PORT,
    "user": Config.DB_USER,
    "password": Config.DB_PASSWORD,
    "database": Config.DB_NAME,
    "charset": Config.DB_CHARSET,
    "cursorclass": DictCursor,
    "autocommit": True
}
# 云端托管 MySQL（如 Aiven）强制要求 SSL；DB_SSL=true 时开启加密连接
if Config.DB_SSL:
    import ssl as _ssl_module
    _ssl_ctx = _ssl_module.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl_module.CERT_NONE
    DB_CONFIG['ssl'] = _ssl_ctx


def enrich_all_missing_phonetics():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            # 1. 查询所有缺少音标的单词
            cursor.execute("""
                SELECT id, word 
                FROM words 
                WHERE us_phone IS NULL OR uk_phone IS NULL OR us_phone = '' OR uk_phone = '';
            """)
            missing_words = cursor.fetchall()
            print(f"检测到共有 {len(missing_words)} 个单词缺少音标，开始自动补全...")

            success_count = 0
            for item in missing_words:
                wid = item["id"]
                word_str = item["word"].strip()

                # eng-to-ipa 转换
                phone = ipa.convert(word_str)

                # 若词库未识别，返回值中会带有 '*' 标记
                if phone and "*" not in phone:
                    cursor.execute("""
                        UPDATE words 
                        SET us_phone = %s, uk_phone = %s 
                        WHERE id = %s;
                    """, (phone, phone, wid))
                    success_count += 1
                else:
                    # 如果带连字符或特殊变体无法直接识别，尝试去掉后缀（如 ly、ed）再次识别
                    fallback_word = None
                    if word_str.endswith('ly'):
                        fallback_word = word_str[:-2]
                    elif word_str.endswith('ed'):
                        fallback_word = word_str[:-1]

                    if fallback_word:
                        fb_phone = ipa.convert(fallback_word)
                        if fb_phone and "*" not in fb_phone:
                            cursor.execute("""
                                UPDATE words 
                                SET us_phone = %s, uk_phone = %s 
                                WHERE id = %s;
                            """, (fb_phone, fb_phone, wid))
                            success_count += 1

            print(f"处理完成！成功补齐 {success_count} 个单词的纯文本音标。")
    finally:
        conn.close()

if __name__ == "__main__":
    enrich_all_missing_phonetics()