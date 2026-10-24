import os
from dotenv import load_dotenv

# 1. 显式锁定当前 config.py 同级目录下的 .env 文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    # --- 基础数据库配置 ---
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_USER = os.getenv("DB_USER", "root")
    # 彻底去掉明文密码，强制从环境变量读取
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "storylex_db")
    DB_CHARSET = "utf8mb4"
    # 云端托管 MySQL（如 Aiven）强制要求 SSL 连接；本地开发默认关闭
    DB_SSL = os.getenv("DB_SSL", "False").lower() in ("true", "1", "yes")

    # --- 连接池配置 ---
    DB_POOL_MIN_CACHED = int(os.getenv("DB_POOL_MIN_CACHED", 5))
    DB_POOL_MAX_CACHED = int(os.getenv("DB_POOL_MAX_CACHED", 20))
    DB_POOL_MAX_CONNECTIONS = int(os.getenv("DB_POOL_MAX_CONNECTIONS", 50))

    # --- JWT 鉴权配置 ---
    # 生产环境中 JWT 密钥也应该由 .env 提供，避免使用写死的默认密钥
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", 7))

    # --- 服务运行配置 ---
    DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
    PORT = int(os.getenv("PORT", 5000))

    # --- LLM 大模型配置 ---
    # 强制从 .env 读取
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
