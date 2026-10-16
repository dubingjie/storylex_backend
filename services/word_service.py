import json
import random
import uuid
from datetime import datetime, timedelta
from db import get_db

def format_translation(raw_trans_item) -> str:
    """将释义数据转换为形如 'adj. 一致的' 的规范字符串"""
    if isinstance(raw_trans_item, dict):
        pos = raw_trans_item.get("pos", "")
        tran_cn = raw_trans_item.get("tranCn", "")
        if pos and tran_cn:
            return f"{pos}. {tran_cn}"
        return tran_cn or str(raw_trans_item)
    return str(raw_trans_item)


class WordService:
    @staticmethod
    def get_learn_group(user_id: int):
        """
        1.3 拉取新学10词组题目：
        从当前词书中按 word_rank 提取10个未学单词，
        并从该词书中随机抓取3个其他词的释义组装为打乱的 A/B/C/D 选项。
        """
        with get_db() as cursor:
            # 1. 查询当前用户绑定的主修词书
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            if not user or not user["current_book_id"]:
                return False, "用户未绑定词书", None
            book_id = user["current_book_id"]

            # 2. 从当前词书按 word_rank 抽取 10 个未背新词
            sql_words = """
                SELECT 
                    w.id AS word_id, 
                    w.word, 
                    w.us_phone, 
                    w.uk_phone, 
                    bw.book_trans,
                    EXISTS(SELECT 1 FROM user_favorite_words ufw WHERE ufw.user_id = %s AND ufw.word_id = w.id) AS is_favorited,
                    EXISTS(SELECT 1 FROM user_word_records uwr WHERE uwr.user_id = %s AND uwr.word_id = w.id AND uwr.status = 'mastered') AS is_mastered
                FROM book_words bw
                JOIN words w ON bw.word_id = w.id
                LEFT JOIN user_word_records uwr ON uwr.user_id = %s AND uwr.word_id = w.id
                WHERE bw.book_id = %s AND uwr.id IS NULL
                ORDER BY bw.word_rank ASC
                LIMIT 10;
            """
            cursor.execute(sql_words, (user_id, user_id, user_id, book_id))
            target_words = cursor.fetchall()

            if not target_words:
                return False, "当前词书所有单词均已学习完成！", None

            # 3. 抽取干扰项池（从当前词书中随机抽取 40 个其他单词的释义）
            target_word_ids = [item["word_id"] for item in target_words]
            format_strings = ','.join(['%s'] * len(target_word_ids))
            sql_distractors = f"""
                SELECT bw.book_trans 
                FROM book_words bw
                WHERE bw.book_id = %s AND bw.word_id NOT IN ({format_strings})
                ORDER BY RAND()
                LIMIT 40;
            """
            cursor.execute(sql_distractors, [book_id] + target_word_ids)
            distractor_rows = cursor.fetchall()
            
            distractor_pool = []
            for row in distractor_rows:
                raw_trans = row["book_trans"]
                trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                if trans_list and len(trans_list) > 0:
                    distractor_pool.append(format_translation(trans_list[0]))

            # 备用保底干扰项
            fallback_distractors = ["adj. 重要的，显著的", "v. 维持，保持", "n. 方面，方向", "adv. 彻底地", "adj. 复杂的"]
            while len(distractor_pool) < 30:
                distractor_pool.extend(fallback_distractors)

            # 4. 为每个词生成打乱的 A/B/C/D 四个选项
            group_words_res = []
            for item in target_words:
                raw_trans = item["book_trans"]
                trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                correct_trans = format_translation(trans_list[0]) if trans_list else "释义加载中"

                distractors = random.sample(distractor_pool, 3)
                options_candidates = [correct_trans] + distractors
                random.shuffle(options_candidates)

                option_keys = ["A", "B", "C", "D"]
                options = [{"key": key, "trans": trans} for key, trans in zip(option_keys, options_candidates)]

                group_words_res.append({
                    "word_id": item["word_id"],
                    "word": item["word"],
                    "us_phone": item["us_phone"],
                    "uk_phone": item["uk_phone"],
                    "is_favorited": bool(item["is_favorited"]),
                    "is_mastered": bool(item["is_mastered"]),
                    "options": options
                })

            group_id = f"grp_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            return True, "success", {
                "group_id": group_id,
                "total": len(group_words_res),
                "words": group_words_res
            }

    @staticmethod
    def check_learn_answer(user_id: int, word_id: int, selected_key: str, is_show_answer: bool, options: list = None):
        """
        1.4 单题提交答案判定与解析获取
        """
        with get_db() as cursor:
            # 查出当前用户绑定的词书
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            sql = """
                SELECT 
                    w.id, w.word, w.us_phone, w.uk_phone, 
                    bw.book_trans, bw.book_sentences, bw.book_phrases, bw.book_rem_method
                FROM words w
                JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE w.id = %s LIMIT 1;
            """
            cursor.execute(sql, (book_id, word_id))
            detail = cursor.fetchone()
            if not detail:
                return False, "未找到该单词的详细解析数据", None

            raw_trans = detail["book_trans"]
            trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
            raw_sentences = detail["book_sentences"]
            sent_list = json.loads(raw_sentences) if isinstance(raw_sentences, str) else (raw_sentences or [])
            raw_phrases = detail["book_phrases"]
            phrase_list = json.loads(raw_phrases) if isinstance(raw_phrases, str) else (raw_phrases or [])
            
            correct_trans = format_translation(trans_list[0]) if trans_list else ""

            # 判断选项正确性
            is_correct = False
            correct_key = None
            if options:
                for opt in options:
                    if opt.get("trans") == correct_trans:
                        correct_key = opt.get("key")
                        break

            if not is_show_answer and selected_key and correct_key:
                is_correct = (selected_key.upper() == correct_key.upper())

            return True, "success", {
                "is_correct": is_correct,
                "correct_key": correct_key,
                "word_detail": {
                    "word": detail["word"],
                    "us_phone": detail["us_phone"],
                    "uk_phone": detail["uk_phone"],
                    "translations": trans_list,
                    "sentences": sent_list,
                    "phrases": phrase_list,
                    "rem_method": detail["book_rem_method"]
                }
            }

    @staticmethod
    def complete_learn_group(user_id: int, group_id: str, word_mistakes: dict):
        """
        1.5 组结清零小结结算与数据入库
        """
        if not word_mistakes:
            return False, "缺少小结单词统计参数", None

        word_ids = [int(wid) for wid in word_mistakes.keys()]
        summary_list = []
        next_review_at = datetime.now() + timedelta(days=1)

        with get_db() as cursor:
            # 1. 批量写入 user_word_records
            for wid_str, mistakes in word_mistakes.items():
                wid = int(wid_str)
                cursor.execute("""
                    INSERT INTO user_word_records 
                        (user_id, word_id, stage, status, proficiency, wrong_count, review_count, last_reviewed_at, next_review_at, created_at)
                    VALUES (%s, %s, 0, 'learning', 0, %s, 0, NOW(), %s, NOW())
                    ON DUPLICATE KEY UPDATE 
                        stage = 0,
                        status = 'learning',
                        wrong_count = wrong_count + VALUES(wrong_count),
                        last_reviewed_at = NOW(),
                        next_review_at = VALUES(next_review_at);
                """, (user_id, wid, mistakes, next_review_at))

            # 2. 更新今日新学统计数
            today = datetime.now().date()
            cursor.execute("""
                INSERT INTO user_study_stats (user_id, study_date, new_learned_count, reviewed_count, read_story_count, created_at)
                VALUES (%s, %s, %s, 0, 0, NOW())
                ON DUPLICATE KEY UPDATE 
                    new_learned_count = new_learned_count + VALUES(new_learned_count);
            """, (user_id, today, len(word_ids)))

            # 3. 组装返回小结卡片
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            format_strings = ','.join(['%s'] * len(word_ids))
            sql_summary = f"""
                SELECT w.id AS word_id, w.word, bw.book_trans
                FROM words w
                JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE w.id IN ({format_strings});
            """
            cursor.execute(sql_summary, [book_id] + word_ids)
            word_rows = {row["word_id"]: row for row in cursor.fetchall()}

            for wid_str, mistakes in word_mistakes.items():
                wid = int(wid_str)
                row = word_rows.get(wid)
                if row:
                    raw_trans = row["book_trans"]
                    trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                    trans_text = format_translation(trans_list[0]) if trans_list else ""
                    performance = "一次通过" if mistakes == 0 else f"错{mistakes}次"
                    summary_list.append({
                        "word_id": wid,
                        "word": row["word"],
                        "trans": trans_text,
                        "performance": performance
                    })

            return True, "本组学习完成", {"summary_list": summary_list}
    


    # 艾宾浩斯各阶段复习间隔（天）：Stage 0 到 Stage 7
    EBBINGHAUS_INTERVALS = [1, 2, 4, 7, 15, 30, 60, 0]

    @staticmethod
    def get_review_group(user_id: int):
        """
        2.1 拉取今日待复习单词组（到期检测）：
        筛选 next_review_at <= NOW() 且状态不是 mastered 的单词，单次取 10 个。
        """
        with get_db() as cursor:
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            if not user or not user["current_book_id"]:
                return False, "用户未绑定词书", None
            book_id = user["current_book_id"]

            # 1. 查找已到期的待复习单词
            sql_review_words = """
                SELECT 
                    w.id AS word_id, 
                    w.word, 
                    w.us_phone, 
                    w.uk_phone, 
                    bw.book_trans,
                    uwr.stage,
                    uwr.proficiency,
                    EXISTS(SELECT 1 FROM user_favorite_words ufw WHERE ufw.user_id = %s AND ufw.word_id = w.id) AS is_favorited
                FROM user_word_records uwr
                JOIN words w ON uwr.word_id = w.id
                JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE uwr.user_id = %s 
                  AND uwr.status != 'mastered'
                  AND uwr.next_review_at <= NOW()
                ORDER BY uwr.next_review_at ASC
                LIMIT 10;
            """
            cursor.execute(sql_review_words, (user_id, book_id, user_id))
            target_words = cursor.fetchall()

            if not target_words:
                return True, "今日暂无待复习的单词！", {"total": 0, "words": []}

            # 2. 抽取干扰项池
            target_word_ids = [item["word_id"] for item in target_words]
            format_strings = ','.join(['%s'] * len(target_word_ids))
            sql_distractors = f"""
                SELECT bw.book_trans 
                FROM book_words bw
                WHERE bw.book_id = %s AND bw.word_id NOT IN ({format_strings})
                ORDER BY RAND()
                LIMIT 40;
            """
            cursor.execute(sql_distractors, [book_id] + target_word_ids)
            distractor_rows = cursor.fetchall()
            
            distractor_pool = []
            for row in distractor_rows:
                raw_trans = row["book_trans"]
                trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                if trans_list and len(trans_list) > 0:
                    distractor_pool.append(format_translation(trans_list[0]))

            fallback_distractors = ["adj. 重要的，显著的", "v. 维持，保持", "n. 方面，方向", "adv. 彻底地", "adj. 复杂的"]
            while len(distractor_pool) < 30:
                distractor_pool.extend(fallback_distractors)

            # 3. 组装选项
            group_words_res = []
            for item in target_words:
                raw_trans = item["book_trans"]
                trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                correct_trans = format_translation(trans_list[0]) if trans_list else "释义加载中"

                distractors = random.sample(distractor_pool, 3)
                options_candidates = [correct_trans] + distractors
                random.shuffle(options_candidates)

                option_keys = ["A", "B", "C", "D"]
                options = [{"key": key, "trans": trans} for key, trans in zip(option_keys, options_candidates)]

                group_words_res.append({
                    "word_id": item["word_id"],
                    "word": item["word"],
                    "us_phone": item["us_phone"],
                    "uk_phone": item["uk_phone"],
                    "stage": item["stage"],
                    "is_favorited": bool(item["is_favorited"]),
                    "options": options
                })

            group_id = f"rev_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            return True, "success", {
                "group_id": group_id,
                "total": len(group_words_res),
                "words": group_words_res
            }

    @staticmethod
    def answer_review_word(user_id: int, word_id: int, selected_key: str, is_show_answer: bool, options: list = None):
        """
        2.2 复习答题提交与艾宾浩斯动态升降级计算
        """
        with get_db() as cursor:
            # 1. 查单词详情和当前复习状态
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            sql = """
                SELECT 
                    w.id, w.word, w.us_phone, w.uk_phone, 
                    bw.book_trans, bw.book_sentences, bw.book_phrases, bw.book_rem_method,
                    uwr.stage, uwr.proficiency, uwr.wrong_count, uwr.review_count
                FROM words w
                JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                LEFT JOIN user_word_records uwr ON uwr.user_id = %s AND uwr.word_id = w.id
                WHERE w.id = %s LIMIT 1;
            """
            cursor.execute(sql, (book_id, user_id, word_id))
            detail = cursor.fetchone()
            if not detail:
                return False, "单词或学习记录不存在", None

            raw_trans = detail["book_trans"]
            trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
            raw_sentences = detail["book_sentences"]
            sent_list = json.loads(raw_sentences) if isinstance(raw_sentences, str) else (raw_sentences or [])
            phrase_list = json.loads(detail["book_phrases"]) if isinstance(detail["book_phrases"], str) else (detail["book_phrases"] or [])
            correct_trans = format_translation(trans_list[0]) if trans_list else ""

            # 判断正确性
            correct_key = None
            if options:
                for opt in options:
                    if opt.get("trans") == correct_trans:
                        correct_key = opt.get("key")
                        break

            is_correct = False
            if not is_show_answer and selected_key and correct_key:
                is_correct = (selected_key.upper() == correct_key.upper())

            # 2. 艾宾浩斯阶段与排程计算
            current_stage = detail["stage"] or 0
            current_proficiency = detail["proficiency"] or 0

            if is_correct:
                # 答对：阶数 +1，熟练度 +10
                new_stage = min(current_stage + 1, 7)
                new_status = 'mastered' if new_stage == 7 else 'reviewing'
                new_proficiency = min(current_proficiency + 10, 100)
                interval_days = WordService.EBBINGHAUS_INTERVALS[new_stage]
                next_review = datetime.now() + timedelta(days=interval_days) if new_stage < 7 else datetime.now() + timedelta(days=365)
                wrong_increment = 0
            else:
                # 答错 / 看答案：直接打回 Stage 0，熟练度 -5
                new_stage = 0
                new_status = 'reviewing'
                new_proficiency = max(current_proficiency - 5, 0)
                next_review = datetime.now() + timedelta(days=1)
                wrong_increment = 1

            # 3. 更新 user_word_records
            cursor.execute("""
                UPDATE user_word_records
                SET stage = %s,
                    status = %s,
                    proficiency = %s,
                    wrong_count = wrong_count + %s,
                    review_count = review_count + 1,
                    last_reviewed_at = NOW(),
                    next_review_at = %s
                WHERE user_id = %s AND word_id = %s;
            """, (new_stage, new_status, new_proficiency, wrong_increment, next_review, user_id, word_id))

            return True, "success", {
                "is_correct": is_correct,
                "correct_key": correct_key,
                "new_stage": new_stage,
                "new_status": new_status,
                "next_review_at": next_review.strftime('%Y-%m-%d %H:%M:%S'),
                "word_detail": {
                    "word": detail["word"],
                    "us_phone": detail["us_phone"],
                    "uk_phone": detail["uk_phone"],
                    "translations": trans_list,
                    "sentences": sent_list,
                    "phrases": phrase_list,
                    "rem_method": detail["book_rem_method"]
                }
            }

    @staticmethod
    def complete_review_group(user_id: int, reviewed_count: int):
        """
        2.3 复习结算：更新 user_study_stats 的 reviewed_count 今日复习量
        """
        if reviewed_count <= 0:
            return True, "无需更新", {}

        today = datetime.now().date()
        with get_db() as cursor:
            cursor.execute("""
                INSERT INTO user_study_stats (user_id, study_date, new_learned_count, reviewed_count, read_story_count, created_at)
                VALUES (%s, %s, 0, %s, 0, NOW())
                ON DUPLICATE KEY UPDATE 
                    reviewed_count = reviewed_count + VALUES(reviewed_count);
            """, (user_id, today, reviewed_count))

        return True, "复习数据结算成功", {"reviewed_count": reviewed_count}



    @staticmethod
    def toggle_favorite(user_id: int, word_id: int, source_type: str = 'flashcard'):
        """
        3.1 切换生词收藏状态（已收藏则取消，未收藏则新增）
        """
        with get_db() as cursor:
            cursor.execute("""
                SELECT id FROM user_favorite_words 
                WHERE user_id = %s AND word_id = %s LIMIT 1;
            """, (user_id, word_id))
            fav = cursor.fetchone()

            if fav:
                cursor.execute("""
                    DELETE FROM user_favorite_words 
                    WHERE user_id = %s AND word_id = %s;
                """, (user_id, word_id))
                return True, "已取消收藏", {"is_favorited": False}
            else:
                cursor.execute("""
                    INSERT INTO user_favorite_words (user_id, word_id, source_type, created_at)
                    VALUES (%s, %s, %s, NOW());
                """, (user_id, word_id, source_type))
                return True, "收藏成功", {"is_favorited": True}

    @staticmethod
    def get_favorite_words(user_id: int, page: int = 1, page_size: int = 15, keyword: str = None):
        """
        3.2 分页获取生词本列表（支持按英文单词模糊搜索）
        """
        offset = (page - 1) * page_size
        with get_db() as cursor:
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            where_clauses = ["ufw.user_id = %s"]
            params = [user_id]

            if keyword:
                where_clauses.append("w.word LIKE %s")
                params.append(f"%{keyword.strip().lower()}%")

            where_sql = " AND ".join(where_clauses)

            # 1. 查询总数
            sql_count = f"""
                SELECT COUNT(*) AS total
                FROM user_favorite_words ufw
                JOIN words w ON ufw.word_id = w.id
                WHERE {where_sql};
            """
            cursor.execute(sql_count, params)
            total = cursor.fetchone()["total"]

            # 2. 查询分页单词列表
            sql_list = f"""
                SELECT 
                    w.id AS word_id,
                    w.word,
                    w.us_phone,
                    w.uk_phone,
                    bw.book_trans,
                    ufw.source_type,
                    ufw.created_at AS favorited_at
                FROM user_favorite_words ufw
                JOIN words w ON ufw.word_id = w.id
                LEFT JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE {where_sql}
                ORDER BY ufw.created_at DESC
                LIMIT %s OFFSET %s;
            """
            cursor.execute(sql_list, [book_id] + params + [page_size, offset])
            rows = cursor.fetchall()

            word_list = []
            for r in rows:
                raw_trans = r["book_trans"]
                trans_list = json.loads(raw_trans) if isinstance(raw_trans, str) else raw_trans
                word_list.append({
                    "word_id": r["word_id"],
                    "word": r["word"],
                    "us_phone": r["us_phone"],
                    "uk_phone": r["uk_phone"],
                    "translations": trans_list,
                    "source_type": r["source_type"],
                    "favorited_at": r["favorited_at"].strftime('%Y-%m-%d %H:%M:%S') if r["favorited_at"] else ""
                })

            return True, "success", {
                "total": total,
                "page": page,
                "page_size": page_size,
                "list": word_list
            }



    @staticmethod
    def update_daily_target(user_id: int, task_type: str, target_count: int):
        """
        1.2 修改用户每日学习目标（新学或复习）
        """
        if task_type not in ("new", "review"):
            return False, "任务类型必须为 'new' 或 'review'"
        
        if not isinstance(target_count, int) or target_count <= 0 or target_count > 200:
            return False, "目标数量必须是 1 到 200 之间的整数"

        column = "daily_new_target" if task_type == "new" else "daily_review_target"
        
        with get_db() as cursor:
            cursor.execute(f"""
                UPDATE users 
                SET {column} = %s, updated_at = NOW() 
                WHERE id = %s;
            """, (target_count, user_id))
            
        return True, "目标修改成功"

    @staticmethod
    def get_group_practice_questions(user_id: int, word_ids: list):
        """
        1.6 基于指定单词列表（当堂学完的10词）抽取巩固练习题（四选一）
        """
        if not word_ids or not isinstance(word_ids, list):
            return False, "word_ids 必须为非空整数数组", None

        # 限制一次练习的词量，防止恶意传入超大列表
        word_ids = word_ids[:20]

        with get_db() as cursor:
            # 1. 查询当前用户的词书
            cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
            user = cursor.fetchone()
            book_id = user["current_book_id"] if user else "CET6luan_1"

            # 2. 查询目标单词的基础信息和释义
            format_strings = ','.join(['%s'] * len(word_ids))
            sql = f"""
                SELECT w.id, w.word, w.us_phone, w.uk_phone, bw.book_trans
                FROM words w
                LEFT JOIN book_words bw ON bw.word_id = w.id AND bw.book_id = %s
                WHERE w.id IN ({format_strings});
            """
            cursor.execute(sql, [book_id] + word_ids)
            target_words = cursor.fetchall()

            if not target_words:
                return False, "未检索到指定单词数据", None

            # 3. 随机抽取干扰项释义物料池
            cursor.execute("""
                SELECT book_trans 
                FROM book_words 
                WHERE book_id = %s AND book_trans IS NOT NULL 
                ORDER BY RAND() 
                LIMIT %s;
            """, (book_id, len(target_words) * 5))
            distractor_rows = cursor.fetchall()

        # 解析备选干扰项中文释义
        distractor_pool = []
        for r in distractor_rows:
            try:
                trans_data = json.loads(r["book_trans"]) if isinstance(r["book_trans"], str) else r["book_trans"]
                if trans_data and isinstance(trans_data, list):
                    item = trans_data[0]
                    trans_text = f"{item.get('pos', '')}.{item.get('tranCn', '')}" if item.get('pos') else item.get('tranCn', '')
                    if trans_text and trans_text not in distractor_pool:
                        distractor_pool.append(trans_text)
            except Exception:
                continue

        # 4. 组装四选一测试题
        questions = []
        for word_row in target_words:
            # 提取正确释义
            correct_trans = "释义待补充"
            try:
                trans_data = json.loads(word_row["book_trans"]) if isinstance(word_row["book_trans"], str) else word_row["book_trans"]
                if trans_data and isinstance(trans_data, list):
                    item = trans_data[0]
                    correct_trans = f"{item.get('pos', '')}.{item.get('tranCn', '')}" if item.get('pos') else item.get('tranCn', '')
            except Exception:
                pass

            # 选 3 个与正确答案不同的干扰项
            wrong_choices = [d for d in distractor_pool if d != correct_trans]
            chosen_distractors = random.sample(wrong_choices, min(3, len(wrong_choices)))
            
            # 兜底：若干扰词不够，补齐默认项
            while len(chosen_distractors) < 3:
                chosen_distractors.append("其他未定义释义")

            # 打乱选项 A, B, C, D
            all_choices = [correct_trans] + chosen_distractors
            random.shuffle(all_choices)

            options = []
            correct_key = "A"
            for idx, key in enumerate(["A", "B", "C", "D"]):
                options.append({"key": key, "trans": all_choices[idx]})
                if all_choices[idx] == correct_trans:
                    correct_key = key

            questions.append({
                "word_id": word_row["id"],
                "word": word_row["word"],
                "us_phone": word_row.get("us_phone", ""),
                "uk_phone": word_row.get("uk_phone", ""),
                "correct_key": correct_key,
                "options": options
            })

        return True, "测验题组生成成功", {
            "total": len(questions),
            "questions": questions
        }




    @staticmethod
    def get_book_words_list(user_id: int, book_id: str = None, filter_type: str = "all", page: int = 1, page_size: int = 20):
        """
        2.5 获取词书总词表列表（支持已学/未学筛选与分页）
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20
        offset = (page - 1) * page_size

        with get_db() as cursor:
            # 1. 如果未传 book_id，则取当前用户正在学习的词书
            if not book_id:
                cursor.execute("SELECT current_book_id FROM users WHERE id = %s;", (user_id,))
                user = cursor.fetchone()
                book_id = user["current_book_id"] if user else "CET6luan_1"

            # 2. 构造过滤条件
            where_clauses = ["bw.book_id = %s"]
            params = [book_id]

            # 关联用户背词记录状态判断
            if filter_type == "learned":
                where_clauses.append("uwr.id IS NOT NULL")
            elif filter_type == "unlearned":
                where_clauses.append("uwr.id IS NULL")

            where_sql = " AND ".join(where_clauses)

            # 3. 统计总数
            count_sql = f"""
                SELECT COUNT(*) as total
                FROM book_words bw
                LEFT JOIN user_word_records uwr 
                    ON uwr.word_id = bw.word_id AND uwr.user_id = %s
                WHERE {where_sql};
            """
            cursor.execute(count_sql, [user_id] + params)
            total = cursor.fetchone()["total"]

            # 4. 分页拉取单词明细与当前用户学习/收藏状态
            query_sql = f"""
                SELECT 
                    w.id as word_id,
                    w.word,
                    w.us_phone,
                    w.uk_phone,
                    bw.book_trans,
                    bw.word_rank,
                    CASE WHEN uwr.id IS NOT NULL THEN TRUE ELSE FALSE END as is_learned,
                    CASE WHEN uwr.status = 'mastered' THEN TRUE ELSE FALSE END as is_mastered,
                    CASE WHEN uf.id IS NOT NULL THEN TRUE ELSE FALSE END as is_favorited
                FROM book_words bw
                JOIN words w ON w.id = bw.word_id
                LEFT JOIN user_word_records uwr 
                    ON uwr.word_id = bw.word_id AND uwr.user_id = %s
                LEFT JOIN user_favorite_words uf 
                    ON uf.word_id = bw.word_id AND uf.user_id = %s
                WHERE {where_sql}
                ORDER BY bw.word_rank ASC
                LIMIT %s OFFSET %s;
            """
            cursor.execute(query_sql, [user_id, user_id] + params + [page_size, offset])
            rows = cursor.fetchall()

        word_list = []
        for r in rows:
            trans_parsed = []
            if r.get("book_trans"):
                try:
                    trans_parsed = json.loads(r["book_trans"]) if isinstance(r["book_trans"], str) else r["book_trans"]
                except Exception:
                    trans_parsed = []

            word_list.append({
                "word_id": r["word_id"],
                "word": r["word"],
                "word_rank": r["word_rank"],
                "us_phone": r.get("us_phone", ""),
                "uk_phone": r.get("uk_phone", ""),
                "translations": trans_parsed,
                "is_learned": bool(r["is_learned"]),
                "is_mastered": bool(r["is_mastered"]),
                "is_favorited": bool(r["is_favorited"])
            })

        return True, "获取词书列表成功", {
            "book_id": book_id,
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": word_list
        }





