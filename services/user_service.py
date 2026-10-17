from datetime import timedelta
from utils.study_time import study_now
from db import get_db

class UserService:
    @staticmethod
    def get_dashboard_stats(user_id: int):
        """
        4.1 首页全局统计看板数据获取
        """
        with get_db() as cursor:
            # 1. 查询用户基础配置与当前绑定的词书
            sql_user = """
                SELECT 
                    u.id, u.username, u.avatar_url, u.current_book_id,
                    u.daily_new_target, u.daily_review_target,
                    b.title AS book_title, b.word_count AS book_total_words
                FROM users u
                LEFT JOIN books b ON u.current_book_id = b.id
                WHERE u.id = %s;
            """
            cursor.execute(sql_user, (user_id,))
            user_info = cursor.fetchone()
            if not user_info:
                return False, "用户不存在", None

            book_id = user_info["current_book_id"]
            cursor.execute("SELECT COUNT(*) AS n FROM book_words WHERE book_id = %s", (book_id,))
            book_total = cursor.fetchone()["n"]

            # 2. 查询今日学习统计（新学量、复习量）
            today = study_now().date()
            cursor.execute("""
                SELECT new_learned_count, reviewed_count, read_story_count
                FROM user_study_stats
                WHERE user_id = %s AND study_date = %s;
            """, (user_id, today))
            today_stat = cursor.fetchone() or {
                "new_learned_count": 0,
                "reviewed_count": 0,
                "read_story_count": 0
            }

            # 3. 统计当前到期待复习词数（next_review_at <= %s）
            cursor.execute("""
                SELECT COUNT(*) AS pending_review_count
                FROM user_word_records
                WHERE user_id = %s AND status != 'mastered' AND next_review_at <= %s
                    AND NOT EXISTS(SELECT 1 FROM review_pauses p WHERE p.user_id = user_word_records.user_id AND p.word_id = user_word_records.word_id);
            """, (user_id, study_now()))
            pending_review = cursor.fetchone()["pending_review_count"]

            # 4. 词库整体掌握分布
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN status = 'mastered' THEN 1 END) AS mastered_count,
                    COUNT(CASE WHEN status IN ('learning', 'reviewing') THEN 1 END) AS learning_count
                FROM book_words bw
                JOIN user_word_records r ON r.word_id = bw.word_id AND r.user_id = %s
                WHERE bw.book_id = %s;
            """, (user_id, book_id))
            distribution = cursor.fetchone()
            mastered_count = distribution["mastered_count"]
            learning_count = distribution["learning_count"]
            unlearned_count = max(0, book_total - mastered_count - learning_count)

            # 5. 计算连续打卡天数 (Streak)
            cursor.execute("""
                SELECT study_date 
                FROM user_study_stats
                WHERE user_id = %s AND (new_learned_count > 0 OR reviewed_count > 0 OR read_story_count > 0)
                ORDER BY study_date DESC
                ;
            """, (user_id,))
            stat_dates = [row["study_date"] for row in cursor.fetchall()]

            streak_days = 0
            check_date = today
            # 如果今天还没开始背，允许从昨天开始向前计算连续天数
            if stat_dates and stat_dates[0] < today:
                if stat_dates[0] == today - timedelta(days=1):
                    check_date = today - timedelta(days=1)
                else:
                    check_date = None

            if check_date:
                date_set = set(stat_dates)
                curr = check_date
                while curr in date_set:
                    streak_days += 1
                    curr -= timedelta(days=1)

            # 6. 组装返回数据结构
            dashboard_data = {
                "user": {
                    "user_id": user_info["id"],
                    "username": user_info["username"],
                    "avatar_url": user_info["avatar_url"],
                    "streak_days": streak_days
                },
                "book": {
                    "book_id": book_id,
                    "title": user_info["book_title"],
                    "total_words": book_total,
                    "progress_percent": round((mastered_count + learning_count) / book_total * 100, 1) if book_total > 0 else 0
                },
                "today_task": {
                    "new_learned": {
                        "finished": today_stat["new_learned_count"],
                        "target": user_info["daily_new_target"]
                    },
                    "review": {
                        "finished": today_stat["reviewed_count"],
                        "pending": pending_review,
                        "target": user_info["daily_review_target"]
                    },
                    "story_read": today_stat["read_story_count"]
                },
                "word_distribution": {
                    "mastered": mastered_count,
                    "learning": learning_count,
                    "unlearned": unlearned_count
                }
            }

            return True, "success", dashboard_data