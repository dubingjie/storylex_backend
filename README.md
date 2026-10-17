# StoryLex Backend

StoryLex 是一个结合“语境沉浸式阅读”与“艾宾浩斯抗遗忘算法”的智能背单词应用后端服务。系统通过动态抽题、智能复习调度以及大语言模型（LLM）定制生成故事，帮助用户在生动的情境中高效掌握词汇。

## 技术栈

- 语言与框架：Python 3.10+ / Flask 3.x
- 数据库与存储：MySQL 8.0+ / DBUtils 连接池
- 认证与授权：PyJWT (JSON Web Token)
- 大模型集成：OpenAI SDK (支持 DeepSeek 等兼容 OpenAI 协议的模型)
- 文本与发音处理：eng_to_ipa、正则表达式

## 项目目录结构



```
storylex_backend/
├── app.py              # 应用主入口，注册蓝图与跨域配置
├── config.py           # 环境与系统配置加载器
├── db.py               # 数据库连接池与 Cursor 上下文管理
├── data/               # 离线词书与语料数据目录
│   └── .gitkeep        # 目录占位文件
├── routes/             # 路由层：接口参数校验与响应封装
│   ├── __init__.py
│   ├── auth.py         # 用户认证相关路由
│   ├── words.py        # 背词、小结、复习与词表路由
│   ├── stories.py      # 文章阅读与 AI 故事生成路由
│   └── user.py         # 用户个人相关路由
├── services/           # 业务逻辑层：核心算法与数据处理
│   ├── auth_service.py # 鉴权与用户数据服务
│   ├── word_service.py # 出题、判题、复习算法服务
│   └── story_service.py# 文章解析与 AI 故事调度服务
├── utils/              # 公共工具库
│   ├── auth_helper.py  # JWT Token 生成与登录拦截装饰器
│   └── response.py     # 统一 JSON 响应封装
├── scripts/            # 离线数据清洗与入库脚本
│   ├── import_words.py
│   ├── import_zhenhuan_stories.py
│   └── enrich_words.py
├── requirements.txt    # 项目依赖清单
├── .env.example        # 环境变量模板
└── .gitignore          # Git 忽略文件配置
```

## 核心功能

### 1. 用户鉴权与安全

- 用户注册与密码安全哈希存储。
- 基于 JWT 的无状态登录认证与路由拦截保护。

### 2. 核心新学与动态出题

- 动态抽题：从词书中抽取未学新词，并从词库动态抽取干扰释义组装 A/B/C/D 四选一题组。
- 即时判题与解析：提交答案即时判定对错，并下发词义、英美音标与例句。
- 当堂小结结算：当堂单词掌握后批量入库，初始化艾宾浩斯复习周期。
- 巩固练习抽取：支持根据当堂完成的词汇快速抽取练习题。
- 目标调整：支持动态修改每日新学和复习目标。

### 3. 艾宾浩斯复习调度

- 动态复习队列：按艾宾浩斯周期提取当日到期复习词汇。
- 阶段流转：答对推进复习阶段并延长下一次复习间隔；答错回退低阶次日强制复习。
- 状态标记：支持生词一键标记为已掌握（斩词）及收藏状态切换。
- 全局词表浏览：支持按已学、未学状态分页检索词书完整词表。

### 4. 语境阅读与 AI 故事生成

- 文章详情渲染：支持中英文混排小说的段落渲染，解析内嵌高亮词汇标签并映射词表元数据。
- 完读打卡：记录用户文章完读状态。
- AI 定制故事生成：支持根据用户指定的单词列表与题材，调用大模型生成中英文混排故事，并自动解析生词入库。

## 快速启动

### 1. 创建并激活虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate  # Linux / macOS
# Windows: venv\Scripts\activate
```

### 2. 安装项目依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

从模板复制一份 `.env` 文件：

```bash
cp .env.example .env
```

根据实际环境编辑 `.env` 中的数据库与大模型配置：

```Ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=storylex_db

JWT_SECRET_KEY=your_jwt_secret_key

OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 4. 初始化数据库

新环境先创建并选中 `.env` 对应的数据库，然后依次执行：

1. [`database/schema.sql`](database/schema.sql)：10张基础表。
2. `migrations/001_*.sql` 到 `migrations/007_*.sql`：按编号升序执行全部7个迁移，共新增9张表。
3. [`database/seed.sql`](database/seed.sql)：注册必需的默认词书元数据，不含词汇或用户数据。

详细的TablePlus操作和命令行示例见 [数据库初始化说明](database/README.md)。完整初始化后共19张表；能注册不代表已经有可学词，词书数据需要另行导入。

**已有数据库只执行尚未执行的迁移；你已执行001～007时，本次无需再执行SQL。** IF NOT EXISTS不会升级已有表。

新版答题必须携带 `group_id`、`question_id`、`request_id`；不再通过客户端选项或错题次数判定成绩。完整参数见 [API 接口设计](data/StoryLex%20后端接口设计与开发路线.md)。

### 5. 启动服务

```bash
python3 app.py
```

服务默认运行在 http://127.0.0.1:5000](http://127.0.0.1:5000)。

## 统一响应规范

所有接口均遵循以下标准 JSON 响应结构：

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

- `200`：请求成功
- `400`：客户端参数错误
- `401`：未登录或 Token 失效
- `500`：服务端内部异常

## 第一批学习流程验证

测试使用独立临时 MySQL，仅在显式提供 socket 时创建随机测试库，结束后删除该测试库；不读取 `.env` 业务数据库连接。

```bash
STUDY_TEST_SOCKET=/tmp/storylex-study-live.sock venv/bin/python -m unittest discover -s tests -v
```

覆盖重复/并发出题、未通过拒绝结算、错词重测、标记掌握、并发结算、复习去重、次日零点、事务回滚和路由参数验证。不提供 socket 时数据库测试跳过。


## 第二批阅读词表与练习

在第一批基础上执行 `migrations/002_story_practice.sql`，新增阅读练习表后重启后端。无需重跑001，也不修改历史学习数据。

- `GET /api/stories/<story_id>/vocabulary`：文章词表。
- `GET /api/stories/<story_id>/practice`：获取或恢复阅读练习。
- `POST /api/stories/<story_id>/practice/submit`：携带session_id、request_id及全部题目选择，由后端判分并安排错词复习。

完整参数和错词保护规则见 [API接口设计](data/StoryLex%20后端接口设计与开发路线.md)。部署SQL不会由应用自动执行。测试仍使用上方隔离MySQL命令，包含阅读权限、重复/并发提交、回滚和跨词书复习的验证。


## 第三批首页、个人中心及阅读进度

在业务数据库执行 `migrations/003_reading_progress.sql` 并重启后端（无需重跑001、002）。新增：

- `GET /api/words/dashboard/summary`：首页任务及继续阅读。
- `GET /api/user/stats`：全局已学/已掌握/已读及累计学习天数。
- `GET /api/user/books`、`PUT /api/user/book`：词书列表与主修词书设置。
- `GET /api/user/favorites`、`POST /api/user/favorites/batch-delete`：收藏夹列表与批量取消。
- `GET /api/stories/<story_id>/progress`、`PUT /api/stories/<story_id>/progress`：读取、保存阅读位置。保存需携带最新version，百分比100不自动完读。

参数与统计口径已写入接口设计文档。第三批不包含AI预览编辑、TXT导入。


## 第四批AI故事预览、编辑、保存

执行 `migrations/004_ai_story_drafts.sql` 后重启后端，无需重跑001～003。

- `POST /api/ai/generate-story`：携带request_id、word_ids、story_type，可选title；仅生成草稿。
- `GET /api/ai/drafts/<draft_id>`：查询状态及预览。
- `PUT /api/ai/drafts/<draft_id>`：携带version、title、processed_content，编辑草稿。
- `POST /api/ai/drafts/<draft_id>/save`：携带request_id、version，确认入库。

旧 `/api/stories/generate` 也改为仅生成草稿，需增加request_id并调用保存接口才进入文库。检查status=ready后再编辑或保存；failed查看error。标签规则、重复请求及版本校验见API文档。

AI流程自动测试使用模拟模型响应，不调用真实模型或消耗额度；使用隔离MySQL命令可同时验证并发生成、防重复保存和事务回滚。真实模型连通性需配置好 `.env` 后以Postman验证。


## 第五批TXT导入与替换预览

复用004已创建的草稿表，本批无需新增SQL，更新代码后重启后端。

`POST /api/ai/import-txt` 使用form-data：file选择本地.txt文件，target_book_id选择实际词书，request_id填写本次导入唯一编号；可选title、max_replacements（默认20）、min_gap（默认30）。

最大200KB/40000字符，支持UTF-8、UTF-16 BOM、GB18030。按词书中文义项做长词优先替换，不调用模型；多义词需要在预览中检查。

返回draft_id后复用 `/api/ai/drafts/<draft_id>` 查询/编辑，再POST `/api/ai/drafts/<draft_id>/save` 保存。保存后来源为imported，可用文章列表source_type=imported筛选。


## 第六批文章收藏及文库筛选

执行 `migrations/005_story_favorites.sql` 并重启后端，无需重跑前四个迁移。

- `PUT /api/stories/<story_id>/favorite`：JSON传is_favorited=true/false，幂等设置文章收藏。
- `GET /api/stories/list`：新增scope=all/mine/recommended、category=all/imported/ai_generated/favorites、keyword标题搜索。原source_type和分页参数继续支持。
- 文章详情与列表返回文章级is_favorited；不影响单词收藏、阅读记录和复习排程。

我的书库包含本人文章及收藏的系统文章；推荐文章不复制，收藏后可同时出现在两个区域。


## 第七批收藏夹与小结自主练习

执行 `migrations/006_independent_practice.sql` 并重启后端，无需重跑001～005。

- `POST /api/user/favorites/practice`：本人收藏词出题，Body为word_ids、request_id、可选mode。
- `POST /api/words/learn/group/practice`：小结已学词出题，同上；可选group_id验证已结算组归属。
- `GET /api/words/practice/<session_id>`：恢复练习。
- `POST /api/words/practice/<session_id>/submit`：提交request_id和全部题目的answers，由后端判分。

mode支持mixed、en_to_zh、zh_to_en；统一用options[].text，出题不再返回correct_key。旧小结请求需要补request_id，所选词须为本人已学词。两类自主练习都不影响正式复习排程或学习数量。


## 第八批复习暂停、恢复与掌握重置

执行 `migrations/007_review_state.sql` 并重启后端，无需重跑001～006。

- `POST /api/words/review/pause`：word_id、request_id，暂停本人未掌握词。
- `GET /api/words/review/paused?page=1&page_size=20`：本人已暂停词列表。
- `POST /api/words/review/resume`：word_id、request_id，恢复暂停词，次日零点复习，保留阶段。
- `POST /api/words/master/reset`：word_id、request_id，重置已掌握词为阶段0、熟练度0，次日零点复习。

暂停词从正式队列及看板排除，活动复习组会跳过，阅读错词不会自动恢复它。标记掌握会清除暂停。重复请求返回原回执，迟到的旧请求不会撤销之后的新操作；新操作务必使用新request_id。


## 完整流程验收与前端交付

- [完整流程验收报告](docs/完整流程验收报告.md)：验证范围、证据及剩余事项。
- [前端对接指南](docs/前端对接指南.md)：页面映射、各类练习、重试及版本处理。
- [实际路由清单](docs/实际路由清单.md)：从代码生成的46个方法/路径。
- [Postman导入说明](postman/README.md)：集合和无凭证环境模板，含自动保存Token和上下文脚本。

本轮只补旧接口参数校验，不需要新的数据库迁移。完整HTTP验收通过真实应用蓝图/JWT及隔离MySQL进行，模型响应模拟，不消耗真实模型额度。
