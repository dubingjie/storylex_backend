# 数据库初始化与升级

## 文件分工

| 文件 | 用途 |
|---|---|
| schema.sql | 10张基础表的完整定义，按外键依赖顺序排列 |
| ../migrations/001～007 | 基础表之上的7次功能迁移，共9张新增表 |
| seed.sql | 默认词书CET6luan_1的最低元数据，保证注册外键可用 |

SQL中不包含数据库密码、API Key、账号或个人学习数据，建议与代码一起提交Git。初始化后的结构共19张表。

`schema.sql`不硬编码库名，不会创建或删除数据库，也不会删除表。`CREATE TABLE IF NOT EXISTS`不会修改已有结构，因此它不是数据库升级工具。仅存元数据的seed也不能代替真正的词汇导入。

## 新环境：TablePlus执行顺序

1. 连接目标MySQL实例，地址与后端.env中DB_HOST、DB_PORT一致。
2. 创建一个新数据库，例如storylex_db，字符集utf8mb4、排序规则utf8mb4_unicode_ci，并选中这个数据库。也可以在查询编辑器执行：

```sql
CREATE DATABASE IF NOT EXISTS storylex_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE storylex_db;
```

3. 新建SQL查询，将schema.sql全文复制进去执行。
4. 依次打开并执行以下迁移的全文：

```text
migrations/001_study_sessions.sql
migrations/002_story_practice.sql
migrations/003_reading_progress.sql
migrations/004_ai_story_drafts.sql
migrations/005_story_favorites.sql
migrations/006_independent_practice.sql
migrations/007_review_state.sql
```

5. 执行seed.sql，补上注册所需的默认词书元数据。
6. 刷新表列表，确认19张表；将.env的DB_NAME设置为这个库名，重启后端。
7. 另行导入词书及需要的系统文章，再测试学习/阅读。大型原始资源被.gitignore忽略，不会因建表自动出现。

不要一次将所有文件粘贴后忽略中间错误；每步成功后再执行下一步。上述SQL操作只应用于你选中的目标库。

## 新环境：命令行示例

先创建目标数据库，再从backend目录执行。替换地址、端口、账号和库名，`-p`会交互询问密码，不把密码写进命令或文件。

```bash
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < database/schema.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/001_study_sessions.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/002_story_practice.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/003_reading_progress.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/004_ai_story_drafts.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/005_story_favorites.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/006_independent_practice.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < migrations/007_review_state.sql
mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p <DB_NAME> < database/seed.sql
```

## 已有数据库

你已经建好基础表、执行001～007且接口正常，本次只整理文件，不需要重跑任何SQL。

之后的版本只执行新增且尚未执行的迁移。项目目前没有自动迁移器或数据库迁移记录表，已执行编号需要自行在部署记录中保留；不能仅凭IF NOT EXISTS认为旧表与最新结构一致。

如果原库的user_story_records是以前无外键的简化版本，整理schema.sql不会自动添加外键。应先核对实际结构，确需修正时另做迁移，不直接重建有数据的表。

## 资源和导入脚本

seed只建立一本默认词书的空元数据。CET6/KaoYan等JSON、小说语料需要自行准备，不能提交真实用户数据库备份代替基础结构。

三个资源处理脚本（`import_words.py`、`import_zhenhuan_stories.py`、`enrich_words.py`）统一通过`config.py`读取backend根目录的`.env`数据库配置。运行前请核对其中的目标地址、账号和库名；脚本会写入数据库，整理Git文件时无需运行这些脚本。原始词库和语料仅保存在本地，换电脑后需要另行复制。
