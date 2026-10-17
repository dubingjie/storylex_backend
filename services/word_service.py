import json
from db import get_db
from services.study_service import StudyService, positive_id

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
    # 正式学习统一由持久化题组服务处理；收藏与临时练习保持独立。
    @staticmethod
    def get_learn_group(user_id):
        return StudyService.get_group(user_id, 'learn')

    @staticmethod
    def check_learn_answer(user_id, **kwargs):
        return StudyService.answer(user_id, 'learn', **kwargs)

    @staticmethod
    def complete_learn_group(user_id, group_id):
        return StudyService.complete_learn_group(user_id, group_id)

    @staticmethod
    def get_review_group(user_id):
        return StudyService.get_group(user_id, 'review')

    @staticmethod
    def answer_review_word(user_id, **kwargs):
        return StudyService.answer(user_id, 'review', **kwargs)

    @staticmethod
    def complete_review_group(user_id, group_id):
        return StudyService.review_summary(user_id, group_id)

    @staticmethod
    def master_word(user_id, word_id, group_id=None):
        return StudyService.master(user_id, word_id, group_id)

    @staticmethod
    def toggle_favorite(user_id: int, word_id: int, source_type: str = 'flashcard'):
        """
        3.1 切换生词收藏状态（已收藏则取消，未收藏则新增）
        """
        if not positive_id(word_id) or source_type not in ('flashcard', 'story'):
            return False, "需要正整数word_id，source_type必须为flashcard或story", None
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
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 200:
            return False, "page必须为正整数，page_size必须为1到200", None
        if keyword is not None and (not isinstance(keyword, str) or len(keyword) > 150):
            return False, "keyword最多150字符", None
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
        
        if type(target_count) is not int or target_count <= 0 or target_count > 200:
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
    def get_group_practice_questions(user_id, word_ids, request_id, mode='mixed', group_id=None):
        from services.independent_practice_service import IndependentPracticeService
        return IndependentPracticeService.create(user_id, 'learn', word_ids, request_id, mode, group_id)

    @staticmethod
    def get_book_words_list(user_id: int, book_id: str = None, filter_type: str = "all", page: int = 1, page_size: int = 20):
        """
        2.5 获取词书总词表列表（支持已学/未学筛选与分页）
        """
        if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
            return False, "page必须为正整数，page_size必须为1到100", None
        if filter_type not in ('all', 'learned', 'unlearned'):
            return False, "filter必须为all、learned或unlearned", None
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
                    CASE WHEN uf.id IS NOT NULL THEN TRUE ELSE FALSE END as is_favorited,
                    EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = uwr.user_id AND p.word_id = uwr.word_id) AS is_review_paused
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
                "is_review_paused": bool(r["is_review_paused"]),
                "is_favorited": bool(r["is_favorited"])
            })

        return True, "获取词书列表成功", {
            "book_id": book_id,
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": word_list
        }





