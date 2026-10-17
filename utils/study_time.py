"""学习业务统一使用北京时间；数据库中的学习时间为北京时间无时区 DATETIME。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def study_now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)


def review_at(days=1, now=None):
    now = now or study_now()
    return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
