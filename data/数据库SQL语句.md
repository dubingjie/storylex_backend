# 数据库结构说明

正式基础建表文件已整理到 [database/schema.sql](../database/schema.sql)，共10张基础表。
原文重复的 `user_story_records` 定义已去除，保留包含用户/文章外键的完整定义。

新环境依次执行基础结构、编号迁移和最低词书元数据，具体见 [数据库初始化说明](../database/README.md)。
已有数据库不要通过重跑基础结构来升级，只执行尚未执行的迁移。

本文件保留迁移索引，不再维护另一份容易与代码不同步的建表正文。

## 第一批学习题组新增表

部署新版学习接口前，在后端实际数据库执行 [001_study_sessions.sql](../migrations/001_study_sessions.sql)。新增 `study_groups`（持久化题组、答题回执及结算状态）和 `daily_review_words`（用户、自然日、单词唯一去重）。不重写历史学习记录。

## 第二批阅读练习新增表

在后端实际数据库执行 [002_story_practice.sql](../migrations/002_story_practice.sql)，新增 `story_practice_sessions` 保存阅读练习题目快照及结算回执。原有表及历史数据保持不变，第一批迁移无需重复执行。

## 第三批阅读进度表

执行 [003_reading_progress.sql](../migrations/003_reading_progress.sql)，新增 `reading_progress` 保存每用户每文章的百分比、正文字符位置、版本和最近阅读时间。不改动已有学习及完读记录。

## 第四批AI故事草稿表

执行 [004_ai_story_drafts.sql](../migrations/004_ai_story_drafts.sql)，仅新增 `ai_story_drafts` 存储个人预览草稿、生成请求及正式文章关联。无需重跑前面迁移，不改动已有文章。

## 第六批文章收藏表

执行 [005_story_favorites.sql](../migrations/005_story_favorites.sql)，新增 `user_favorite_stories`，以(user_id, story_id)作为唯一主键，与单词收藏及阅读记录独立。

## 第七批自主练习表

执行 [006_independent_practice.sql](../migrations/006_independent_practice.sql)，新增 `independent_practice_sessions` 存储收藏夹/小结临时题组及成绩，与正式学习、复习表独立。

## 第八批复习状态表

执行 [007_review_state.sql](../migrations/007_review_state.sql)，新增 `review_pauses`（复习暂停标记，关联已有学习记录）及 `review_state_requests`（状态修改回执），不改写已有学习记录。
