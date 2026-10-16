import json
from datetime import datetime
from db import get_db
import re
import json
from openai import OpenAI
from config import Config
from db import get_db

class StoryService:
    @staticmethod
    def get_story_list(user_id: int, page: int = 1, page_size: int = 10, source_type: str = None):
        """
        5.1 分页获取文章列表
        """
        offset = (page - 1) * page_size
        with get_db() as cursor:
            # 查出当前用户主修词书
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            where_clauses = ["(s.user_id = %s OR s.source_type = 'builtin')"]
            params = [user_id]

            if source_type:
                where_clauses.append("s.source_type = %s")
                params.append(source_type)

            where_sql = " AND ".join(where_clauses)

            # 1. 统计总数
            cursor.execute(f"SELECT COUNT(*) AS total FROM stories s WHERE {where_sql};", params)
            total = cursor.fetchone()["total"]

            # 2. 分页查列表
            sql = f"""
                SELECT 
                    s.id AS story_id,
                    s.title,
                    s.source_type,
                    s.target_book_id,
                    s.word_count,
                    s.embedded_word_count,
                    s.created_at
                FROM stories s
                WHERE {where_sql}
                ORDER BY s.created_at DESC
                LIMIT %s OFFSET %s;
            """
            cursor.execute(sql, params + [page_size, offset])
            rows = cursor.fetchall()

            stories = []
            for r in rows:
                stories.append({
                    "story_id": r["story_id"],
                    "title": r["title"],
                    "source_type": r["source_type"],
                    "word_count": r["word_count"],
                    "embedded_word_count": r["embedded_word_count"],
                    "created_at": r["created_at"].strftime('%Y-%m-%d %H:%M:%S') if r["created_at"] else ""
                })

            return True, "success", {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": stories
            }

    @staticmethod
    def get_story_detail(user_id: int, story_id: int):
        """
        5.2 获取文章正文及内嵌单词详情（带当前词书释义与收藏状态）
        """
        with get_db() as cursor:
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            # 1. 查询文章基础内容
            sql_story = """
                SELECT 
                    id AS story_id, title, source_type, target_book_id,
                    original_content, processed_content, word_count, embedded_word_count
                FROM stories
                WHERE id = %s AND (user_id = %s OR source_type = 'builtin')
                LIMIT 1;
            """
            cursor.execute(sql_story, (story_id, user_id))
            story = cursor.fetchone()
            if not story:
                return False, "文章不存在或无权访问", None

            # 2. 查询文章内嵌的生词物料及当前用户对其的收藏/掌握状态
            sql_embedded_words = """
                SELECT 
                    sw.word_order,
                    w.id AS word_id,
                    w.word,
                    w.us_phone,
                    w.uk_phone,
                    bw.book_trans,
                    EXISTS(SELECT 1 FROM user_favorite_words ufw WHERE ufw.user_id = %s AND ufw.word_id = w.id) AS is_favorited,
                    EXISTS(SELECT 1 FROM user_word_records uwr WHERE uwr.user_id = %s AND uwr.word_id = w.id AND uwr.status = 'mastered') AS is_mastered
                FROM story_words sw
                JOIN words w ON sw.word_id = w.id
                LEFT JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE sw.story_id = %s
                ORDER BY sw.word_order ASC;
            """
            cursor.execute(sql_embedded_words, (user_id, user_id, book_id, story_id))
            raw_words = cursor.fetchall()

            embedded_words = []
            for item in raw_words:
                raw_trans = item["book_trans"]
                trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                embedded_words.append({
                    "word_order": item["word_order"],
                    "word_id": item["word_id"],
                    "word": item["word"],
                    "us_phone": item["us_phone"],
                    "uk_phone": item["uk_phone"],
                    "translations": trans_list,
                    "is_favorited": bool(item["is_favorited"]),
                    "is_mastered": bool(item["is_mastered"])
                })

            return True, "success", {
                "story_id": story["story_id"],
                "title": story["title"],
                "source_type": story["source_type"],
                "processed_content": story["processed_content"] or story["original_content"],
                "embedded_words": embedded_words
            }

    @staticmethod
    def complete_story(user_id: int, story_id: int):
        """
        5.3 完成文章阅读打卡：更新今日 user_study_stats 的 read_story_count
        """
        today = datetime.now().date()
        with get_db() as cursor:
            # 确认文章有效性
            cursor.execute("SELECT id FROM stories WHERE id = %s;", (story_id,))
            if not cursor.fetchone():
                return False, "文章不存在", None

            # 累加今日文章阅读数
            cursor.execute("""
                INSERT INTO user_study_stats (user_id, study_date, new_learned_count, reviewed_count, read_story_count, created_at)
                VALUES (%s, %s, 0, 0, 1, NOW())
                ON DUPLICATE KEY UPDATE 
                    read_story_count = read_story_count + 1;
            """, (user_id, today))

        return True, "文章阅读完成，打卡成功！", {"story_id": story_id}




    @staticmethod
    def generate_ai_story(user_id: int, word_ids: list, theme: str = "都市小说"):
        """
        基于指定生词和大模型自适应文风能力，生成小说并入库持久化
        """
        if not word_ids or len(word_ids) < 2:
            return False, "请至少提供 2 个生词供生成故事", None

        # 1. 查询待嵌入生词的原文、释义及所在词书
        with get_db() as cursor:
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            format_strings = ','.join(['%s'] * len(word_ids))
            sql = f"""
                SELECT w.id, w.word, bw.book_trans
                FROM words w
                LEFT JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE w.id IN ({format_strings});
            """
            cursor.execute(sql, [book_id] + word_ids)
            word_rows = cursor.fetchall()

        if not word_rows:
            return False, "未能从词库中检索到指定生词", None

        # 构造提示词物料：包含单词原型、释义参考以及入库用的唯一 ID
        word_prompts = []
        for r in word_rows:
            meaning = ""
            if r.get("book_trans"):
                try:
                    trans_data = json.loads(r["book_trans"]) if isinstance(r["book_trans"], str) else r["book_trans"]
                    if trans_data and isinstance(trans_data, list):
                        meaning = trans_data[0].get("tranCn", "")
                except Exception:
                    meaning = ""
            word_prompts.append(f"{r['word']}（释义参考: {meaning}，ID: {r['id']}）")

        # 2. 构造通用自适应 Prompt（解除死板字典，充分释放大模型的模仿与创作能力）
        system_prompt = (
            "你是一位具备顶级文风模仿能力的文学作家兼英语语境大师。"
            "你能够精准驾驭任何流派的网络小说（如修仙、末世、无限流、青春言情、悬疑等）、文学名著风格，"
            "或还原经典影视与小说作品（如《甄嬛传》、《知否》、《天官赐福》、《哈利波特》等）的人物口吻、语言质感与戏剧张力。"
        )

        user_prompt = f"""
请围绕用户指定的主题风格或经典名场面【{theme}】，创作一段 400~600 字的沉浸式精彩故事片段。

【必须自然融入的生词物料】：
{', '.join(word_prompts)}

【写作核心准则】：
1. 【文风自适应】：深度契合【{theme}】特有的语言风格与叙事节奏。若是特定影视/名作重现，必须精准还原其角色口吻、时代氛围或名场面内核；若是泛题材网文/小说，必须写出该流派最地道的韵味与戏剧张力。
2. 【语境第一，拒绝生搬硬套】：英文单词必须作为情节或人物表达的核心部分自然登场（允许根据语法合理变形），词义需完全贴合句子语义，绝不能有突兀的机器翻译感。
3. 【严格标签约束】：
   正文中凡是出现上述目标英文生词，必须且仅使用以下 XML 标签包裹：
   <word id="单词ID">英文单词</word>
   例如：在这偌大的深宫里，她行事愈发显得 <word id="4981">composed</word>，从不轻易落人把柄。
4. 【纯净输出格式】：
   - 第一行必须输出故事标题，格式：# 故事标题
   - 紧接着输出正文内容。
   - 严禁输出任何多余的开场白、问候语、结语或文末单词列表。
"""

        # 3. 调用大语言模型 API
        try:
            client = OpenAI(
                api_key=Config.OPENAI_API_KEY,
                base_url=Config.OPENAI_BASE_URL
            )
            response = client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7
            )
            raw_text = response.choices[0].message.content.strip()
        except Exception as e:
            return False, f"大模型接口调用异常: {str(e)}", None

        # 4. 正文与标题解析
        lines = raw_text.split("\n")
        title = f"{theme}定制故事"
        content_lines = []

        for line in lines:
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
            else:
                content_lines.append(line)

        processed_content = "\n".join(content_lines).strip()

        # 生成去除标签的纯正文并统计字数
        original_content = re.sub(r'<word id="\d+">(.*?)</word>', r'\1', processed_content)
        word_count = len(re.findall(r'[\u4e00-\u9fa5]', original_content))
        embedded_count = len(re.findall(r'<word id="\d+">', processed_content))

        # 5. 持久化至数据库 stories 与 story_words 表
        with get_db() as cursor:
            cursor.execute("""
                INSERT INTO stories (
                    title, source_type, user_id, target_book_id,
                    original_content, processed_content, word_count, embedded_word_count, created_at
                ) VALUES (%s, 'ai_generated', %s, %s, %s, %s, %s, %s, NOW());
            """, (
                title, user_id, book_id,
                original_content, processed_content,
                word_count, embedded_count
            ))
            story_id = cursor.lastrowid

            # 插入文章-生词映射表
            sql_sw = """
                INSERT INTO story_words (story_id, word_id, word_order)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE word_order = VALUES(word_order);
            """
            for order, w_info in enumerate(word_rows, start=1):
                cursor.execute(sql_sw, (story_id, w_info["id"], order))

        return True, "故事生成成功", {
            "story_id": story_id,
            "title": title,
            "word_count": word_count,
            "embedded_word_count": embedded_count
        }