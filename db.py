import ssl

import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB
from config import Config


def _ssl_context():
    """DB_SSL 开启时返回加密连接上下文（不校验 CA，适用于 Aiven 等托管库）。"""
    if Config.DB_SSL:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


# 初始化全局连接池
# mincached=0：导入时不预建连接。托管 MySQL（如 Aiven 免费实例）会因不活动
# 自动关机，若启动时就建连接，数据库不可用时进程会直接崩溃并反复重启，
# 且数据库恢复后也无法自愈；改为懒连接后进程可先正常启动，连接在首次
# 请求时按需创建，数据库恢复后自动接上，无需人工重启后端。
pool = PooledDB(
    creator=pymysql,
    mincached=0,
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
    autocommit=False,
    ssl=_ssl_context()
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
