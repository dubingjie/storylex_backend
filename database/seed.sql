-- 最低必需的公共词书元数据：注册接口默认绑定 CET6luan_1。
-- 不包含单词、故事、账号、密码或学习记录。
-- 已有该词书时不覆盖名称、描述和词数；实际词书导入可更新这些信息。
INSERT INTO books (id, title, description, word_count)
VALUES ('CET6luan_1', '大学英语六级乱序核心词汇', '六级真题高频乱序核心词汇', 0)
ON DUPLICATE KEY UPDATE id = id;
