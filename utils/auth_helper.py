import jwt
import datetime
from functools import wraps
from flask import request, g
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from utils.response import error_response

def hash_password(password: str) -> str:
    """生成加盐密码散列串"""
    return generate_password_hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验密码"""
    return check_password_hash(hashed_password, plain_password)

def generate_token(user_id: int, username: str) -> str:
    """颁发 JWT Token（有效期为 Config.JWT_EXPIRE_DAYS 天）"""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=Config.JWT_EXPIRE_DAYS),
        "iat": datetime.datetime.utcnow()
    }
    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm="HS256")
    return token

def login_required(f):
    """
    登录拦截装饰器：
    从 Header 'Authorization: Bearer <token>' 提取 Token，
    验证通过后将 user_id 和 username 挂载到 flask.g 上。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return error_response(msg="未携带身份凭证，请登录", code=401)
        
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return error_response(msg="身份凭证格式错误 (应为 Bearer <token>)", code=401)
        
        token = parts[1]
        try:
            payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=["HS256"])
            g.user_id = payload["user_id"]
            g.username = payload["username"]
        except jwt.ExpiredSignatureError:
            return error_response(msg="登录已过期，请重新登录", code=401)
        except jwt.InvalidTokenError:
            return error_response(msg="无效的身份凭证", code=401)
        
        return f(*args, **kwargs)
    return decorated_function