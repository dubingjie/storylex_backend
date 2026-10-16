import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB
from config import Config

# 初始化全局连接池
pool = PooledDB(
    creator=pymysql,
    mincached=Config.DB_POOL_MIN_CACHED,
    maxcached=Config.DB_POOL_MAX_CACHED,
    maxconnections=Config.DB_POOL_MAX_CONNECTIONS,
    blocking=True,
    host=Config.DB_HOST,
    port=Config.DB_PORT,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,
    database=Config.DB_NAME,
    charset=Config.DB_CHARSET,
    cursorclass=DictCursor,
    autocommit=False
)

class DBConnection:
    """数据库连接与游标上下文管理器"""
    def __enter__(self):
        self.conn = pool.connection()
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # 发生异常，自动回滚事务
            self.conn.rollback()
        else:
            # 无异常，自动提交事务
            self.conn.commit()
        self.cursor.close()
        self.conn.close()

def get_db():
    """获取上下文管理器实例"""
    return DBConnection()