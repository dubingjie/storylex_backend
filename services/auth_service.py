from db import get_db
from utils.auth_helper import hash_password, verify_password, generate_token

class AuthService:
    @staticmethod
    def register(username, password):
        """用户注册逻辑"""
        if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or not password:
            return False, "用户名和密码不能为空", None
        
        username = username.strip()
        if not 3 <= len(username) <= 50 or len(password) < 6:
            return False, "用户名须为3到50位，密码至少6位", None

        with get_db() as cursor:
            # 检查用户名是否已存在
            cursor.execute("SELECT id FROM users WHERE username = %s LIMIT 1;", (username,))
            if cursor.fetchone():
                return False, "该用户名已被注册", None

            # 插入新用户，默认主修词书为 CET6luan_1
            pwd_hash = hash_password(password)
            sql = """
                INSERT INTO users (username, password_hash, current_book_id, daily_new_target, daily_review_target)
                VALUES (%s, %s, 'CET6luan_1', 10, 10);
            """
            cursor.execute(sql, (username, pwd_hash))
            user_id = cursor.lastrowid

            token = generate_token(user_id, username)
            return True, "注册成功", {
                "user_id": user_id,
                "username": username,
                "token": token
            }

    @staticmethod
    def login(username, password):
        """用户登录逻辑"""
        if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or not password:
            return False, "用户名和密码不能为空", None

        with get_db() as cursor:
            cursor.execute("""
                SELECT id, username, password_hash, current_book_id, daily_new_target, daily_review_target 
                FROM users WHERE username = %s LIMIT 1;
            """, (username.strip(),))
            user = cursor.fetchone()

            if not user or not verify_password(password, user["password_hash"]):
                return False, "用户名或密码错误", None

            # 更新最后登录时间
            cursor.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s;", (user["id"],))

            token = generate_token(user["id"], user["username"])
            return True, "登录成功", {
                "user_id": user["id"],
                "username": user["username"],
                "current_book_id": user["current_book_id"],
                "daily_new_target": user["daily_new_target"],
                "daily_review_target": user["daily_review_target"],
                "token": token
            }