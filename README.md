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

### 4. 启动服务

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