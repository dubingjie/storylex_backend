from db import get_db
from services.story_reading_service import StoryReadingService, vocabulary_rows
from utils.study_time import study_now

class StoryService:
    
    @staticmethod
    def get_story_list(user_id, page=1, page_size=10, source_type=None, category='all', keyword=None, scope='all'):
        from services.library_service import LibraryService
        return LibraryService.list_stories(user_id, page, page_size, source_type, category, keyword, scope)

    @staticmethod
    def set_story_favorite(user_id, story_id, is_favorited):
        from services.library_service import LibraryService
        return LibraryService.set_favorite(user_id, story_id, is_favorited)

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
                    s.id AS story_id, s.title, s.source_type, s.target_book_id,
                    s.original_content, s.processed_content, s.word_count, s.embedded_word_count,
                    COALESCE(usr.is_completed, 0) AS is_completed,
                    usr.last_practice_score,
                    EXISTS(SELECT 1 FROM user_favorite_stories f WHERE f.user_id = %s AND f.story_id = s.id) AS is_favorited
                FROM stories s
                LEFT JOIN user_story_records usr
                    ON usr.story_id = s.id AND usr.user_id = %s
                WHERE s.id = %s AND (s.user_id = %s OR s.source_type = 'builtin')
                LIMIT 1;
            """
            cursor.execute(sql_story, (user_id, user_id, story_id, user_id))
            story = cursor.fetchone()
            if not story:
                return False, "文章不存在或无权访问", None

            # 详情和独立词表共用释义回退与状态查询。
            embedded_words = vocabulary_rows(cursor, user_id, book_id, {
                'id': story_id, 'target_book_id': story['target_book_id']
            })

            return True, "success", {
                "story_id": story["story_id"],
                "title": story["title"],
                "source_type": story["source_type"],
                "is_completed": bool(story["is_completed"]),
                "is_favorited": bool(story["is_favorited"]),
                "last_practice_score": story["last_practice_score"],
                "embedded_word_count": story["embedded_word_count"],
                "processed_content": story["processed_content"] or story["original_content"],
                "embedded_words": embedded_words
            }

    @staticmethod
    def get_story_vocabulary(user_id, story_id):
        return StoryReadingService.vocabulary(user_id, story_id)

    @staticmethod
    def get_story_practice(user_id, story_id):
        return StoryReadingService.practice(user_id, story_id)

    @staticmethod
    def submit_story_practice(user_id, story_id, session_id, request_id, answers):
        return StoryReadingService.submit(user_id, story_id, session_id, request_id, answers)

    @staticmethod
    def complete_story(user_id: int, story_id: int):
        """
        5.3 手动标记已阅读，仅首次完读时增加当日阅读数。
        """
        if type(story_id) is not int or story_id <= 0:
            return False, "story_id必须为正整数", None
        today = study_now().date()
        with get_db() as cursor:
            # 确认文章有效性
            cursor.execute("""
                SELECT id FROM stories
                WHERE id = %s AND (user_id = %s OR source_type = 'builtin');
            """, (story_id, user_id))
            if not cursor.fetchone():
                return False, "文章不存在或无权访问", None

            # 唯一键上的写锁串行化同一用户、文章的并发提交。
            cursor.execute("""
                INSERT INTO user_story_records (user_id, story_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE id = id;
            """, (user_id, story_id))
            cursor.execute("""
                SELECT is_completed FROM user_story_records
                WHERE user_id = %s AND story_id = %s FOR UPDATE;
            """, (user_id, story_id))
            if cursor.fetchone()["is_completed"]:
                return True, "文章已标记为已阅读", {
                    "story_id": story_id, "is_completed": True
                }

            cursor.execute("""
                UPDATE user_story_records
                SET is_completed = 1, completed_at = COALESCE(completed_at, NOW())
                WHERE user_id = %s AND story_id = %s;
            """, (user_id, story_id))

            # 累加今日文章阅读数
            cursor.execute("""
                INSERT INTO user_study_stats (user_id, study_date, new_learned_count, reviewed_count, read_story_count, created_at)
                VALUES (%s, %s, 0, 0, 1, NOW())
                ON DUPLICATE KEY UPDATE 
                    read_story_count = read_story_count + 1;
            """, (user_id, today))

        return True, "文章阅读完成，打卡成功！", {
            "story_id": story_id, "is_completed": True
        }




    @staticmethod
    def generate_ai_story(user_id, word_ids, request_id, theme="都市小说", title=None):
        """兼容服务入口：仅生成预览草稿，正式入库必须调用保存接口。"""
        from services.ai_draft_service import AIDraftService
        return AIDraftService.generate(user_id, word_ids, request_id, theme, title)
