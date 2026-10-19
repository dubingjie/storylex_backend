# StoryLex 后端接口设计与开发路线

## 一、 项目工程目录结构

后端采用分层架构（蓝图路由 \+ 服务层 \+ 数据库层）：

Plaintext

```Plain Text
story_lex/
└── backend/
    ├── app.py                     # 应用入口：注册路由、全局 CORS、错误处理
    ├── config.py                  # 环境配置：数据库连接串、JWT 密钥、AI API Key
    ├── db.py                      # 数据库连接池与 Cursor 上下文管理
    ├── routes/                    # 路由表现层（只负责参数校验与响应封装）
    │   ├── __init__.py
    │   ├── auth.py                # 用户鉴权与配置路由
    │   ├── words.py               # 系统背单词（新学、做题、小结）路由
    │   ├── review.py              # 独立复习队列路由
    │   ├── stories.py             # 语境阅读、文库列表与文章练习路由
    │   ├── ai.py                  # AI 故事生成与本地 TXT 导入解析路由
    │   └── user.py                # 个人中心看板与生词收藏夹路由
    ├── services/                  # 核心业务逻辑层（算法、事务与数据组装）
    │   ├── word_service.py        # 10 词组抽题、动态干扰项生成与组内闭环判定
    │   ├── review_service.py      # 艾宾浩斯复习调度与阶段（Stage）升降逻辑
    │   ├── story_service.py       # 文章生词高亮解析、关联抽取与完读统计
    │   └── ai_service.py          # Prompt 组装与大模型接口调用封装
    ├── utils/                     # 公共工具库
    │   ├── response.py            # 统一 JSON 返回格式封装器（code, msg, data）
    │   └── auth_helper.py         # JWT Token 生成与登录拦截装饰器
    ├── data/                      # 静态资源、词书 JSON 与 PDF/TXT 待处理文件
    └── scripts/                   # 独立脚本工具（数据清洗、历史表初始化）
```

## 二、 统一接口交互协议规范

- **响应体统一格式**：

JSON

```Plain Text
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

- **状态码定义**：`200` 请求成功；`400` 参数错误；`401` 未登录/Token过期；`500` 服务端异常。

## 三、 API 接口说明

### 第一批上线与通用规则

- 先在后端实际数据库执行 `migrations/001_study_sessions.sql`，新增 study_groups 和 daily_review_words；服务不会自动修改数据库。历史学习数据不批量迁移排程。
- 所有正式学习接口需要 `Authorization: Bearer <token>`。北京时间用于任务日期、午夜失效和到期时间，不依赖服务器本地时区。
- 题组正确答案、请求回执仅存服务端 JSON；通过事务及用户行锁防止多端重复出题、结算、计数。
- 旧的无题组答题请求不能继续使用；更新Postman参数。旧组编号没有持久化记录，请重新获取。
- 跨日旧组拒绝新的答题/结算；成功答题的原request_id仍可读取原回执，已结算组可读取原结果。
- 错误响应沿用项目规范：JSON code=400，HTTP状态默认200。首次部署当天保留既有累计数；历史未记录的逐词复习去重无法追溯。
- 第一批实现正式新学与复习；第二批已实现阅读词表和阅读练习（见3.3～3.6）。第三批实现首页、个人统计、词书切换、收藏批量管理及阅读进度。第四批已实现AI预览编辑及保存，第五批已实现TXT导入替换预览及确认保存。

### 模块一：系统背单词与小结

#### 1.1 首页任务与继续阅读（已实现）

- 路由：`GET /api/words/dashboard/summary`；Bearer Token，无请求参数。
- 返回 current_book（book_id、title）；new_task（target_count、learned_today、is_completed、available_count、can_start）；review_task（target_count、reviewed_today、is_completed、due_count、can_start）。
- 今日计数按北京时间，切换词书不清空。is_completed 表示已达到用户设置目标；没有到期词不等于达到目标，can_start 用于控制是否有可进入的学习任务。
- 已有活动题组可继续，即使目标调低或组内全部点熟后没有剩余可学词。
- due_count与正式复习一致：到期、非已掌握、当天未复习、有可用释义，包含超纲词。
- last_story 为最近保存过阅读进度且尚未手动完读、当前仍有权访问的文章；没有时为null。
- last_story包含 story_id、title、embedded_word_count、progress（0～100数值）、position、version、last_read_at。progress是数值，替代旧设计中的"80%"字符串。
- 旧 `GET /api/user/dashboard` 保留原结构；其词书掌握分布和进度修正为仅统计当前词书，个人全局统计用5.1。

#### 1\.2 修改每日学习目标

- **路由**：`PUT /api/words/target/update`

- **功能**：点击首页卡片右上角“修改”，更新目标值\(\)。   

- **请求参数 \(JSON Body\)**：

JSON

```Plain Text
{
  "task_type": "new",
  "target_count": 20
}
```

- **返回数据**：`{"code": 200, "msg": "目标修改成功", "data": null}`

#### 1.3 拉取或恢复正式新学题组（已实现）

- 路由：`GET /api/words/learn/group`，需要 Bearer Token。
- 后端保存题组和答案；同一用户、词书、当天恢复已有活动题组。
- 每组 `min(10, 当日目标剩余词数, 可学词数)`；目标完成或无可学词时返回 total=0、group_id=null。
- 已有活动组不随目标调整截断；目标调整对下一组生效。
- 返回示例（options 实际有 A/B/C/D 四个不同释义）：

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "group_id": "服务端生成的题组编号",
    "total": 5,
    "passed_count": 0,
    "words": [{
      "word_id": 101,
      "question_id": "服务端生成的题目版本",
      "word": "blind",
      "us_phone": "blaɪnd",
      "uk_phone": "blaɪnd",
      "is_favorited": false,
      "is_mastered": false,
      "passed": false,
      "options": [{"key":"A","trans":"adj. 盲的，瞎的"},{"key":"B","trans":"v. 维持，保持"},{"key":"C","trans":"n. 景象，视线"},{"key":"D","trans":"adv. 逐渐地"}]
    }]
  }
}
```

正确答案和错题次数保存在后端，不在出题包暴露。

#### 1.4 正式新学判题（已实现）

- 路由：`POST /api/words/learn/answer`。
- 请求不再提交 options；服务端不接受客户端对错结论。

```json
{
  "group_id": "从出题接口获取",
  "word_id": 101,
  "question_id": "从该词获取",
  "request_id": "客户端为本次作答生成的唯一编号",
  "selected_key": "A",
  "is_show_answer": false
}
```

- 看答案：is_show_answer=true，selected_key=null 或省略；看答案计一次未通过。
- 返回：is_correct、correct_key、word_detail、passed_count、total。
- 答错或看答案额外返回 retry_question（含新 question_id 和重新打乱的 options）。重测使用新版本、新 request_id。
- 网络重试必须使用原 request_id 和原请求内容，返回原结果；相同编号换答案拒绝。旧 question_id 换编号也不能重复计错。
- 已通过词不再接受新作答。用户/题组/单词不匹配、题组跨日或切换词书返回业务 code=400。
- request_id、group_id、question_id 为最多64字符的非空字符串；word_id 为正整数，is_show_answer 为布尔值。

#### 1.5 正式新学组结算（已实现）

- 路由：`POST /api/words/learn/group/complete`。

```json
{"group_id":"从出题接口获取"}
```

- 不再提交 word_mistakes，后端根据实际答题记录生成小结。
- 每词都通过（答对或点熟）才允许结算，不足10词的小组同样支持。
- 在同一事务内保存学习记录、增加当天新学数、标记题组已完成；重复和并发提交只结算一次，返回原 summary_list。
- 已有学习记录尤其是 mastered 保留，不重置阶段或排程；新记录阶段0，下次复习为北京时间次日00:00。
- data：group_id、summary_list；每项包含 word_id、word、trans、is_mastered、performance（一次通过/错N次/已掌握）。
- 已完成组跨日仍可查询原结算结果；未完成旧组跨日不能再结算。

#### 1.6 小结自主巩固练习（第七批补齐）

- `POST /api/words/learn/group/practice`，Bearer Token。

```json
{"word_ids":[101,102],"request_id":"learn-practice-001","mode":"mixed"}
```

- word_ids为1～20个正整数，自动去重，不再静默截断。必须全部是当前用户存在正式学习记录的词（包括mastered）。
- 可选group_id，提供时必须是本人已结算的新学题组，且所选词均属于该组；不提供时支持本人已学词自主练习。
- request_id必填，原有仅word_ids的请求需要更新。mode可选：mixed（默认混合）、en_to_zh（英选中）、zh_to_en（中选英）。
- 释义优先当前词书，缺失时回退其他词书；缺少释义或不同有效干扰项不足3个时拒绝出题，不返回虚假的占位选项。
- 出题、查询、提交结构和规则见5.6。小结练习不改变正式学习记录或复习统计。

### 模块二：独立复习模块（抗遗忘闭环）

#### 2.1 拉取或恢复正式复习题组（已实现）

- 正式路由：`GET /api/words/review/queue`；兼容原路径 `GET /api/words/review/group`。
- 返回结构同1.3，包含持久化的 group_id、question_id、passed_count、passed 和 options。
- 查询当前词书到期且非 mastered 的词，排除当天已经正式复习过的词。每组最多10词且不超过今日复习目标剩余数。
- 恢复当日活动组；没有到期词或目标完成时 total=0、group_id=null。
- 正式复习每词本次只作答一次；答错或看答案在次日重新进入正式复习，不在本组反复推进阶段。

#### 2.2 正式复习判题与统计（已实现）

- 路由：`POST /api/words/review/answer`。
- 请求格式同1.4，必须传 group_id、word_id、question_id、request_id；selected_key 与 is_show_answer 规则相同。
- 后端判题并更新阶段：答对阶段+1，阶段7掌握；答错/看答案回到阶段0，次日00:00到期。
- 阶段1～6间隔为2、4、7、15、30、60天，到期日均北京时间00:00；已掌握返回 next_review_at=null，队列排除 mastered。
- 同一事务更新学习记录、记录每日去重词和今日复习数；同一词每天只计一次，同一次请求不会重复推进阶段。
- 返回 is_correct、correct_key、new_stage、new_status、next_review_at、word_detail、passed_count、total。

##### 2.2.1 复习组结果查询（兼容旧结束入口，已实现）

- 路由：`POST /api/words/review/complete`。
- 请求：`{"group_id":"从复习出题接口获取"}`。旧 reviewed_count 参数不再参与统计。
- 只读查询本组 is_completed、reviewed_count、total，不累加任何统计；数量已在每次正式答题时记录。

#### 2\.3 切换生词收藏状态

- **路由**：`POST /api/words/favorite/toggle`

- **功能**：做题或阅读卡片右上角点击“收藏”/取消收藏；只改变收藏夹，不进入复习队列、不改变已有排程。   

- **请求参数 \(JSON Body\)**：

JSON

```Plain Text
{
  "word_id": 101,
  "source_type": "flashcard" // "flashcard" 或 "story"
}
```

- **返回数据**：`{"code": 200, "msg": "收藏成功", "data": {"is_favorited": true}}`

#### 2.4 标记已掌握及组内直接通过（已实现）

- 路由：`POST /api/words/master`。
- 请求：`{"word_id":101}`；在新学组内点击时传 `{"word_id":101,"group_id":"当前新学组编号"}`。
- 保存 mastered、阶段7、熟练度100，并退出正式出题；不新增收藏，不增加正式复习数。
- 当前用户当天活动题组中包含该词时同步 passed=true、is_mastered=true；正式复习组标熟不算答题。
- 新学组标熟词在整组结算时计入新学数量；组外标熟本身不增加今日新学数量。
- 返回 word_id、is_mastered；传新学group_id时额外返回 group_id、passed_count、total。
- 重复标熟不会重复计数。主动重置掌握状态见第八批接口2.9。

#### 2\.5 获取词书总词表列表

- **路由**：`GET /api/words/book/list`

- **功能**：查看当前词书的全局词汇清单（支持已学/未学筛选）\(\)。   

- **查询参数 \(Query\)**：`book_id=CET6luan_1&filter=all&page=1&page_size=20`

- **返回数据**：当前词书的分页词单明细及用户的学习状态。

#### 2.6 暂停正式复习（第八批已实现）

- `POST /api/words/review/pause`，Bearer Token。

```json
{"word_id":101,"request_id":"pause-001"}
```

- 仅本人已学习、未掌握的单词可暂停；不删除学习记录，不修改阶段、熟练度、历史错误/复习次数及原排程。
- 暂停保存在review_pauses独立表，不占用mastered状态，也不增加掌握词数。
- 暂停词从新出正式复习队列和首页到期数量中排除；已在活动正式复习组中的未作答词标记passed=true、skipped=true、skip_reason=paused，不计为答题或今日复习。
- paused字段与passed不同：passed表示本组无需继续处理，真正复习数量以答题回执为准。原已处理答题请求仍可返回旧回执，不再改排程。
- 阅读测验答错也不会更新暂停词的学习记录或重新入队，wrong_words_queued不包含暂停词。自主练习不受暂停影响。

#### 2.7 已暂停词分页列表（已实现）

- `GET /api/words/review/paused?page=1&page_size=20`；page正整数、page_size为1～100。
- 只返回本人暂停词，跨词书，不局限当前词书；按暂停时间、word_id降序稳定分页。
- 返回total、page、page_size、list；每项含word_id、word、音标、translations、translation_book_id、status、stage、proficiency、paused_at、is_review_paused=true。
- 文章词表/详情的embedded_words、词书单词列表同步增加is_review_paused字段。

#### 2.8 恢复正式复习（已实现）

- `POST /api/words/review/resume`，JSON：`{"word_id":101,"request_id":"resume-001"}`。
- 仅操作本人学习记录，解除暂停并从北京时间次日00:00重新安排；保留阶段、熟练度和历史统计。
- 已经未暂停时不再次改动到期时间，changed=false，防止重复操作不断推迟复习。
- 恢复操作不把词重新插回旧题组；旧题组的跳过状态保留，下一个到期日由新题组抽取。

#### 2.9 重置已掌握状态（已实现）

- `POST /api/words/master/reset`，JSON：`{"word_id":101,"request_id":"reset-001"}`。
- 只允许当前mastered词，改为reviewing、阶段0、熟练度0，清除暂停标记，次日北京时间00:00复习。
- 保留历史错题/复习次数、学习记录创建时间、今日统计及每日逐词复习去重记录；不改收藏、已读状态或练习成绩。
- 尚未掌握或没有本人学习记录时返回code=400；不支持将任意未学词通过此接口加入队列。
- 活动新学组中先前点熟获得的通过资格保留，但更新is_mastered=false；后续结算仍保留现有reviewing记录和排程。
- 手动标记已掌握（2.4）会清除暂停标记，避免同一词同时显示“暂停”和“已掌握”。

##### 2.6～2.9 的重复请求与返回规则

- 三个修改接口都要求word_id为正整数、request_id为最多64字符非空字符串；暂停、恢复、重置共用用户范围内的request_id唯一空间。
- 同编号同操作同单词返回原操作回执，不再次改变状态；同编号换操作或单词拒绝。执行新的状态变化必须使用新编号。
- 即使先恢复、后再次暂停，迟到的旧恢复请求也只返回旧回执，不会撤销新的暂停。回执不代表最新状态，最新状态应查询词表/暂停列表。
- 返回word_id、action、changed、status、stage、proficiency、is_mastered、is_review_paused、next_review_at。暂停或已掌握时next_review_at=null。
- 同一用户的正式学习和状态更新共享事务锁；并发重试不重复操作，失败整体回滚。
- 部署前执行 `migrations/007_review_state.sql`，新增review_pauses和review_state_requests表，然后重启后端；无需重跑001～006，不批量改动历史学习记录。

### 模块三：语境小说与文章阅读模块

#### 3.1 文章库分类、搜索及分页（第六批已实现）

- `GET /api/stories/list`，Bearer Token。
- page默认1、正整数；page_size默认10、范围1～100。
- scope：all（默认，全部可访问）、mine（本人创建文章及本人收藏的系统文章）、recommended（内置系统文章）。
- category：all（默认）、imported（导入）、ai_generated（AI生成）、favorites（当前用户收藏）。
- keyword：可选，最多150字符，标题包含搜索，去除首尾空白；百分号、下划线按普通字面字符，不作为通配符。
- source_type：兼容旧参数builtin/imported/ai_generated；与scope、category、keyword取交集，冲突时返回空列表，不擅自忽略条件。
- 无论如何组合参数，都只能看到本人文章或builtin文章，收藏不会开放他人的私有文章。
- 返回total、page、page_size、list；每篇含story_id、title、source_type、target_book_id、word_count、embedded_word_count、created_at、is_completed、last_practice_score、is_favorited。沿用已有story_id字段，不替换为id。
- 按story_id升序稳定分页；统计total与列表使用相同条件，超出页码返回空列表。

示例：

```http
GET /api/stories/list?scope=mine&category=all&page=1&page_size=10
GET /api/stories/list?scope=mine&category=imported&keyword=故事
GET /api/stories/list?scope=mine&category=ai_generated
GET /api/stories/list?scope=mine&category=favorites
GET /api/stories/list?scope=recommended
```

##### 3.1.1 收藏或取消收藏文章（已实现）

- `PUT /api/stories/<story_id>/favorite`，Bearer Token。

```json
{"is_favorited":true}
```

- true表示设为已收藏，false表示取消；必须为JSON布尔值，不接受字符串或数字。
- 只操作当前用户对可访问文章的收藏；不存在或他人私有文章返回code=400。
- 显式设置状态而非toggle，重复或并发同状态请求结果不变；每用户每文章最多一条收藏。
- 返回story_id、is_favorited；列表和详情同步返回文章级is_favorited（区别于词表中各单词的is_favorited）。
- 系统文章收藏后出现在“我的书库”，不复制文章；取消后不再显示在我的书库，但仍在系统推荐。本人创建文章取消收藏后仍保留在我的书库。
- 不影响单词收藏、已读状态、阅读进度、练习得分、学习数量或复习排程。
- 部署前执行 `migrations/005_story_favorites.sql`，新增user_favorite_stories表，然后重启后端；无需重跑前四个迁移。

#### 3.2 获取文章正文详情（已实现）

- 实际路由：`GET /api/stories/detail/<int:story_id>`；旧设计的 `/api/stories/<id>` 暂未提供。
- 需要 Bearer Token，只允许查看内置文章或当前用户自己的文章。
- 返回 story_id、title、source_type、is_completed、is_favorited、last_practice_score、embedded_word_count、processed_content、embedded_words。
- embedded_words 与3.3的 words 使用同一套词书释义回退和状态规则；保持原有列表字段，不改成 words_meta 对象。
- last_practice_score 未练习时为null，提交阅读练习后更新最近得分。

#### 3.3 获取本章词表（已实现）

- 路由：`GET /api/stories/<int:story_id>/vocabulary`，需要 Bearer Token。
- 访问权限同文章详情，按 word_order、word_id 排序，每个单词只出现一次（story_words唯一键保证）。
- data：story_id、total、words；无词文章返回 total=0、words=[]。
- words每项：word_id、word_order、word、us_phone、uk_phone、translations、is_favorited、is_mastered、is_learned、learning_status。
- learning_status 为 unlearned/learning/reviewing/mastered；有学习记录即 is_learned=true。
- 释义优先当前主修词书，其次文章目标词书，最后按词书ID稳定回退；额外返回 translation_book_id、translation_book_title。
- is_out_of_book 表示该词是否不属于当前主修词书，可用于显示“超纲”标签。没有任何可用释义时 translations=[]、释义来源为null，仍保留在词表。
- 单纯查词和完读不加入复习；收藏也不改变排程。

#### 3.4 手动完成阅读打卡（已实现）

- 实际路由：`POST /api/stories/complete`，JSON：`{"story_id":1}`；旧设计的路径参数形式暂未提供。
- 仅首次完读增加当日阅读数；返回 story_id、is_completed=true。
- 不把全文单词加入复习，不影响阅读练习得分。阅读练习也不会自动标记完读。

#### 3.5 抽取或恢复阅读练习题（已实现）

- 路由：`GET /api/stories/<int:story_id>/practice`，需要 Bearer Token，无Body。
- 不强制先点完读，可独立进入练习。按本文词表生成英选中四选一，每词一题，不受每日正式学习目标或10词组限制。
- 相同用户、文章、主修词书、北京时间当天恢复尚未提交的练习；已提交后再获取会生成新的练习。
- 正确答案仅存服务端，出题包不返回 correct_key。
- 缺少可用释义的词不出题，返回 skipped_word_ids；全部缺失或文章没有单词时 total=0、session_id=null，不创建空练习。

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "session_id": "从服务器返回的练习编号",
    "story_id": 1,
    "total": 1,
    "skipped_word_ids": [],
    "questions": [{
      "question_id": "从服务器返回的题目编号",
      "word_id": 101,
      "word": "blind",
      "us_phone": "blaɪnd",
      "uk_phone": "blaɪnd",
      "options": [{"key":"A","trans":"adj. 盲的，瞎的"},{"key":"B","trans":"v. 维持，保持"},{"key":"C","trans":"n. 景象，视线"},{"key":"D","trans":"adv. 逐渐地"}]
    }]
  }
}
```

#### 3.6 提交阅读练习并保存得分（已实现）

- 路由：`POST /api/stories/<int:story_id>/practice/submit`，需要 Bearer Token。
- 使用3.5同一份返回的 session_id、question_id、word_id；下列101只是示例。

```json
{
  "session_id": "实际练习编号",
  "request_id": "客户端本次提交唯一编号",
  "answers": [
    {"question_id":"实际题目编号","word_id":101,"selected_key":"A","is_show_answer":false}
  ]
}
```

- 必须一次提交本练习全部题目；不接受遗漏、重复、其他题目或客户端 is_correct。selected_key 为 A/B/C/D；看答案时 is_show_answer=true、selected_key=null或省略，按答错处理。
- session_id、request_id、question_id是最多64字符的非空字符串，word_id为正整数。
- 校验文章/用户/题目归属后，服务端判分；分数为正确题数/总题数×100，四舍五入取整数。
- 保存 user_story_records.last_practice_score；不改变 is_completed 或首次完读时间。
- 新错词：建立 reviewing、阶段0、wrong_count=1 的学习记录，下次复习为北京时间次日00:00。
- 已在学习的错词：wrong_count加1，保留阶段、状态和熟练度；复习时间取原时间与次日零点的较早值，避免推迟已有到期任务。
- 已掌握或已暂停词即使答错也不重新入队、不修改学习记录；已掌握词可通过2.9主动重置，暂停词可通过2.8恢复。
- 答对词不新增或修改正式学习记录；不自动收藏。
- 本接口不增加今日新学数、今日正式复习数或已读文章数，不写 daily_review_words。
- wrong_words_queued 表示本次错词中写入/更新正式复习安排的词数，包含已有学习词，不包含已掌握词。
- 同一练习只结算一次。相同答案重复/并发提交（即使换request_id或调整列表顺序）返回原结果；修改答案被拒绝，不能覆盖原成绩。
- 未提交练习跨日或切换主修词书后拒绝提交，请重新获取；已提交练习仍可重试读取原结果，前提是仍有文章访问权限。

返回data：session_id、story_id、total、correct_count、wrong_count、score、wrong_words_queued、results。results每项包含 question_id、word_id、is_correct、correct_key。

第二批部署：在业务数据库执行 `migrations/002_story_practice.sql`，仅新增 story_practice_sessions 表，第一批SQL无需重跑。阅读错词即使超出当前主修词书也参与正式复习，释义优先当前词书，否则回退其他词书。



### 模块四：AI 故事生成与本地文档导入模块

#### 4.1 AI生成预览草稿（第四批已实现）

- 正式路由：`POST /api/ai/generate-story`；旧路径 `POST /api/stories/generate` 保留，但现在也仅生成草稿，不直接写入正式文库。
- 需要Bearer Token，请求示例：

```json
{
  "request_id":"generate-001",
  "word_ids":[101,102],
  "story_type":"都市小说",
  "title":"可选自定义标题"
}
```

- word_ids为2到20个正整数，去重后至少2个词，必须全部存在；可以来自小结或收藏夹，也支持当前词书之外的全局单词。
- story_type为1到1000字符，默认“都市小说”；兼容theme字段，两个都提供时优先story_type。可选title为1到150字符单行文本。
- request_id为最多64字符的非空字符串。同一用户同编号同参数返回原任务，不重新调用模型；同编号改变参数返回code=400。失败后重试需新编号。
- 返回data：draft_id、status、version、target_book_id、story_id、story_type、target_words、title、processed_content、error。
- 失败时额外返回 error_code、http_status（没有HTTP响应时为null），仅含固定诊断信息，不回传密钥或供应商原始响应。常见：MODEL_AUTH_FAILED（401）、MODEL_QUOTA_EXHAUSTED（402）、MODEL_ACCESS_DENIED（403）、MODEL_NOT_FOUND（404）、MODEL_RATE_LIMITED（429）、MODEL_TIMEOUT、MODEL_CONNECTION_FAILED、MODEL_OUTPUT_INVALID、MODEL_CALL_FAILED。
- 修复配置后必须重启后端并使用新request_id；原失败任务重复请求只返回原失败回执，旧记录不会自动补充新错误分类。
- status：generating（生成中）、ready（可预览编辑）、failed（生成失败，查看error）、saved（已保存）。只有ready才能编辑/首次保存；生成接口返回code=200代表任务已处理，须继续检查status。
- 草稿就绪后还包含 original_content、word_count（中文字符数）、embedded_word_count（实际唯一词数）、embedded_occurrences（标签出现次数）、word_ids（正文首次出现顺序）、missing_word_ids。
- 模型需生成全部目标词。输出校验不通过则标记failed，不进入正式文库。API调用超时60秒，无自动网络重试；进程中断遗留的generating任务在超过5分钟后查询/重复生成时标记failed。
- 生成时不持有数据库事务或用户锁。并发重复请求可能先收到generating，可用draft_id轮询查询。
- 草稿绑定生成时的词书，之后切换主修词书不改变草稿的目标词书。

##### 4.1.1 查询预览草稿（已实现）

- `GET /api/ai/drafts/<draft_id>`，仅本人可访问。
- 返回与4.1相同的草稿数据；未保存的草稿不会出现在文章列表、阅读词表或个人已读统计里。

##### 4.1.2 编辑预览草稿（已实现）

- `PUT /api/ai/drafts/<draft_id>`，仅本人ready草稿可编辑；请求必须包含完整标题、正文及最新版本。

```json
{
  "version":1,
  "title":"修改后的标题",
  "processed_content":"她终于 <word id=\"101\">实际英文原词</word>。"
}
```

- 示例ID和英文须换为target_words中的实际值。正文最多50000字符，仅允许纯文本及不嵌套的 `<word id="ID">英文单词</word>`。
- 标签ID必须来自本草稿目标词；标签文本须与该ID词库原词一致（忽略大小写及空白差异，不支持词形变形）。不允许其他HTML、额外属性、注释、声明或嵌套；普通文本中的&须写为&amp;、<须写为&lt;。
- 编辑可删除部分目标词，但至少保留一个有效标签；missing_word_ids告知删除的目标词。相同词重复出现只在词表中记录一次。
- 成功后version加1。旧version改内容被拒绝；上一版本与完全相同内容的即时重试返回原编辑结果。已保存草稿不允许继续编辑。

##### 4.1.3 确认保存至文库（已实现）

- `POST /api/ai/drafts/<draft_id>/save`。

```json
{"request_id":"save-001","version":2}
```

- version使用最近查询/编辑返回的值。无需在保存请求里重复传正文，先PUT完成修改。
- 同一事务写stories、按正文实际有效标签写story_words、将草稿标记saved并关联story_id。
- source_type默认ai_generated（TXT导入草稿为imported），target_book_id沿用草稿词书；原文去除标签，词表按首次出现顺序去重，embedded_word_count等于实际唯一标签词数，不按输入词数硬填。
- 返回draft_id、story_id、title、word_count、embedded_word_count；可使用 `/api/stories/detail/<story_id>` 和 `/api/stories/<story_id>/vocabulary` 查询保存结果。
- AI和TXT导入每份草稿最多保存一篇文章。重复或并发保存，即使更换request_id，也返回原story_id，不创建重复文章、不覆盖原保存正文。若已保存文章被删除，草稿不能再保存成新文章。
- 生成、编辑、保存均不改变收藏、正式学习状态、复习排程或已读数量。
- 部署前执行 `migrations/004_ai_story_drafts.sql` 并重启后端，只新增ai_story_drafts表，无需重跑001～003。旧直接生成接口的Postman需增加request_id，改为检查草稿状态后显式保存。

#### 4.2 本地TXT导入、词书替换与预览（第五批已实现）

- 路由：`POST /api/ai/import-txt`，Bearer Token，Body选择multipart/form-data；不调用大模型，不消耗模型额度。
- 字段：file（File类型，必填）、target_book_id（必填）、request_id（必填）；title（可选）、max_replacements（可选，默认20）、min_gap（可选，默认30）。
- file只接收一个.txt文件，最大200KB；整个multipart请求最大300KB。支持UTF-8（含BOM）、带BOM的UTF-16、GB18030/GBK；统一换行，去除首尾空白。解码后最多40000字符，长篇请分章导入。
- 拒绝空文件、二进制控制字符、非中文正文、错误扩展名及未知词书；无匹配义项时返回code=400，不创建空草稿。
- title默认取不含扩展名的文件名；标题仍为1～150字符单行文本。文件名只用于显示，上传文件不落盘。
- max_replacements为1～100整数，控制标签总替换次数（同词重复也计数）；min_gap为0～1000整数，表示上一次匹配结束到下一次匹配开始之间保留的原文字符数。
- 匹配规则：只使用目标词书book_trans中的tranCn中文义项，按分隔符拆出2～12字纯中文词；从左向右同一位置最长匹配优先。同义项对应多个词时按word_rank、word_id选择靠前者，替换明细返回candidate_word_ids供检查。
- 按词书字面义项匹配，不做语境消歧或全篇机器翻译；匹配不到的原文保持不变。预览需要用户检查多义词和语句流畅度。
- 上传原文里的HTML或word标签只视为普通文本并转义，不作为客户端指定标签执行。
- request_id按用户与AI生成任务共享唯一空间；同文件同参数重试返回原草稿，同编号换文件/参数或与AI生成冲突返回code=400。
- 返回与4.1草稿相同的结构：draft_id、status=ready、version=1、source_type=imported、target_book_id、title、processed_content、target_words，以及唯一词数、标签出现次数和word_ids。
- 额外source_content保存上传的原始中文正文（规范化换行和首尾空白后）；import_info包含filename、encoding、max_replacements、min_gap、replacements、notice。
- replacements每项包含chinese、word_id、word、start、end、candidate_word_ids；位置相对于source_content，采用从0起的字符索引，end不包含自身。该明细是初次自动替换记录，后续手动编辑不重写明细。

##### 4.2.1 查询、编辑并保存导入草稿

复用第四批草稿接口，无需新路由：

1. `GET /api/ai/drafts/<draft_id>` 查询导入预览。
2. `PUT /api/ai/drafts/<draft_id>` 提交version、title、processed_content编辑；至少保留一个本草稿有效word标签，不能任意添加词ID。
3. `POST /api/ai/drafts/<draft_id>/save` 提交request_id、最新version，确认保存。

- 保存source_type=imported，可用 `/api/stories/list?source_type=imported&page=1&page_size=10` 查询“导入”分类。
- 正文及词表以最终编辑稿为准，词表按首次出现顺序去重；stories.original_content保留source_content的中文原文，processed_content保存最终混排正文。
- 草稿返回original_content仍表示当前混排正文去除标签后的预览文本，原始中文请使用source_content；word_count为混排正文中的中文字符数。
- 相同草稿重复/并发保存只创建一篇文章，事务失败不留下部分文章或词表。
- 不自动完读、收藏、入复习队列或增加学习统计。
- 本批复用已有ai_story_drafts表中的JSON状态，必须已执行004；无需新的迁移SQL，只需更新代码并重启后端。

### 模块五：个人中心与收藏夹模块

#### 5.1 个人中心统计（已实现）

- `GET /api/user/stats`，Bearer Token。
- data：total_study_days、total_learned_words、total_mastered_words、total_read_stories。
- 已学：当前用户有正式学习记录的全局去重单词数（包括已掌握）；已掌握：status=mastered子集；已读：is_completed=1的去重文章数。切换词书不改变全局统计。
- 学习天数按不同日期去重：正数每日统计、学习记录首次创建日、首次完读日、已提交阅读练习日的并集；只浏览或保存阅读位置不算学习日。历史缺失的活动日期无法补推，不使用连续打卡天数替代累计天数。

#### 5.2 生词收藏列表（已实现）

- `GET /api/user/favorites?page=1&page_size=50&keyword=`；兼容原 `/api/words/favorite/list`。
- page为正整数，page_size为1～200，keyword可选；返回 total、page、page_size、list。
- 收藏不加入复习，本接口只查询。旧路径及参数默认值保持原行为。

#### 5.3 批量取消收藏（已实现）

- `POST /api/user/favorites/batch-delete`，JSON：`{"word_ids":[101,102]}`。
- 列表长度1～200，元素必须为正整数；重复ID自动去重。
- 仅删除当前用户收藏，忽略未收藏或不存在的ID；返回 deleted_count（实际删除条数），重复提交返回0。
- 不删除学习记录、不改变排程、掌握状态或任何学习统计。

#### 5.4 词书列表（第三批新增，已实现）

- `GET /api/user/books`，Bearer Token，无参数。
- 返回 current_book_id、books；每本包含 book_id、title、description、total_words、learned_words、mastered_words、is_current。
- total_words按book_words实际条数统计，不依赖可能过期的books.word_count；已学和掌握按该词书单词范围计算。
- 注意 `/api/words/book/list` 仍是一本词书的单词列表，不是本接口。

#### 5.5 切换主修词书（第三批新增，已实现）

- `PUT /api/user/book`，JSON：`{"book_id":"KaoYan_2"}`（示例，必须使用5.4返回的实际ID）。
- 仅更新当前主修词书，返回 current_book_id；词书不存在或参数错误返回code=400。
- 不清空学习记录、今日数量、收藏或阅读记录，共享单词的掌握状态跨词书沿用。
- 旧词书活动题组在当前词书不匹配时拒绝新的作答/提交；切回原词书当天可恢复原组。已结算回执仍可读取。
- 正式复习继续包括已入队的其他词书或超纲词，切换词书不会丢失复习任务。

#### 5.6 收藏夹自主练习（第七批已实现）

- `POST /api/user/favorites/practice`，Bearer Token。

```json
{"word_ids":[101,102],"request_id":"favorite-practice-001","mode":"mixed"}
```

- 所选词必须全部属于当前用户收藏，最多20项，正整数，自动去重。mode与1.6一致。
- 同一用户、来源、request_id、参数重复请求返回原练习（包括已完成的练习）；同编号改参数返回code=400。重新出题需新request_id。
- mixed在至少2个不同单词时包含两种题型，约各半，每词一题；只选1个词时出英选中。
- 返回data：session_id、source（favorites/learn）、status（active/completed）、target_book_id、mode、total、questions。已完成时额外返回result。
- questions每项：question_id、word_id、question_type、prompt、options。options统一使用key、text（替代旧小结接口的trans字段），供两种题型共用。
- en_to_zh的prompt为英文，options为中文，另附us_phone、uk_phone；zh_to_en的prompt为中文、options为英文，不另附英文原词、音标或释义详情，避免直接泄露答案。
- active出题包不返回correct_key或word_detail；正确答案只在后端快照中保存。
- 取消收藏或切换词书不破坏已经创建的快照，允许跨日完成；新建练习仍按当前收藏/学习记录校验，不重新使用过期的选词权限。

##### 5.6.1 查询或恢复自主练习

- `GET /api/words/practice/<session_id>`，仅本人可访问，返回上述结构。已完成练习可读取原成绩及解析。

##### 5.6.2 逐题判定自主练习

- `POST /api/words/practice/<session_id>/answer`，Bearer Token。

```json
{
  "request_id":"favorite-answer-001",
  "answer":{"question_id":"实际题目编号","word_id":101,"selected_key":"A","is_show_answer":false}
}
```

- 每次只提交一道题；看答案时使用`is_show_answer=true`、`selected_key=null`。不接受客户端`is_correct`。
- 服务端立即返回本题`is_correct`、`correct_key`、`word_detail`及`completed`。最后一道题答完时额外返回`summary`，字段与下方整轮提交结果相同；该练习状态改为completed。
- 每题使用独立request_id；相同request_id和答案重试返回原判题结果，不能改答案或重复作答。答错和看答案均只记入自主练习结果，不改正式复习排程。

##### 5.6.3 整轮提交自主练习（兼容接口）

- `POST /api/words/practice/<session_id>/submit`，Bearer Token。

```json
{
  "request_id":"practice-submit-001",
  "answers":[
    {"question_id":"实际题目编号","word_id":101,"selected_key":"A","is_show_answer":false},
    {"question_id":"实际题目编号","word_id":102,"selected_key":"B","is_show_answer":false}
  ]
}
```

- 兼容一次提交本练习全部题目的方式；逐题判题后的练习不能再使用此接口。selected_key为A/B/C/D；看答案时is_show_answer=true、selected_key=null或省略，按答错处理。不接受客户端is_correct、重复题、其他题或word_id错配。
- 服务端判分（0～100四舍五入整数），返回session_id、total、correct_count、wrong_count、score、wrong_word_ids、results。
- results每项包含question_id、word_id、question_type、is_correct、correct_key、word_detail；解析包含英文、音标、释义、例句、记忆方法及释义来源词书。
- 同一练习只结算一次；相同答案重复提交（换request_id或调整答案顺序也一样）返回原结果，改变答案被拒绝。重新练习须重新出题。
- 收藏夹和小结自主练习不写user_word_records、user_study_stats、daily_review_words或文章阅读记录，不改变掌握状态、正式复习阶段/排程，不增加今日新学、今日正式复习或累计学习天数。与阅读练习错词入队规则不同。
- request_id、session_id、question_id均为最多64字符非空字符串。
- 部署前执行 `migrations/006_independent_practice.sql` 并重启后端，仅新增independent_practice_sessions表，无需重跑001～005。

### 第三批：跨设备阅读进度（已实现）

- `GET /api/stories/<story_id>/progress`：读取当前用户的阅读位置；无记录时返回progress=0、position=0、version=0、last_read_at=null。
- `PUT /api/stories/<story_id>/progress`：保存进度。需要Bearer Token，文章必须为内置或本人文章。

```json
{"progress":35.5,"position":120,"version":0}
```

- progress为0～100有限数值，保存两位小数；position为去除word标签后的正文字符偏移，非负整数；version必须使用GET或上次PUT返回值。
- 初次保存传version=0，成功后version加1。返回story_id、progress、position、version、last_read_at（北京时间）。
- 同一旧version、相同进度和位置的即时重试返回原保存结果；同一旧version改内容返回code=400，需GET最新版本后再提交，防止跨设备旧请求覆盖新位置。
- 可以主动往回阅读，progress允许降低；前端在正文打开、滚动或离开时调用保存接口，单纯读取详情不会更新最近阅读时间。
- progress=100不自动完读，不增加已读数；必须手动调用完读接口。首页继续阅读排除已手动完读文章。
- 第三批部署：执行 `migrations/003_reading_progress.sql`，只新增reading_progress表；无需重跑001、002，不自动执行数据库变更。

## 四、 敏捷开发路线

Plaintext

```Plain Text
阶段一：基础骨架与核心新学闭环 (当前目标)
  ├── 1. 配置 db.py (连接池) 与 app.py (主入口)
  ├── 2. 实现 GET /api/words/learn/group (10词动态出题与干扰项生成)
  ├── 3. 实现 POST /api/words/learn/answer (单题判题与详细解析下发)
  └── 4. 实现 POST /api/words/learn/group/complete (组结入库与小结数据生成)

阶段二：首页看板与独立复习调度
  ├── 1. 实现 GET /api/words/dashboard/summary (首页双卡片状态汇总)
  ├── 2. 实现 POST /api/words/favorite/toggle 与 POST /api/words/master (做题即时操作)
  └── 3. 实现 GET /api/words/review/queue 与 POST /api/words/review/answer (艾宾浩斯复习流转)

阶段三：语境小说阅读与词表抽屉
  ├── 1. 跑通基础样板文章的渲染与词汇映射 (GET /api/stories/<id>)
  ├── 2. 实现阅读界面的本章词表抽屉 (GET /api/stories/<id>/vocabulary)
  └── 3. 实现读完去练习与错词自动排入复习 (POST /api/stories/<id>/practice/submit)

阶段四：用户中心与生词收藏夹
  ├── 1. 聚合查询个人中心三大看板数据 (GET /api/user/stats)
  └── 2. 实现收藏夹的列表展示与批量移出操作

阶段五：大模型 AI 故事生成与 TXT 本地清洗导入
  ├── 1. 接入大模型 API 编写 Prompt 模板生成定制爽文
  └── 2. 实现本地中文 TXT 的分词匹配与自动化英文生词嵌入
```











## 完整流程验收补充（2026-10-17）

当前实际方法/路径、前端对接说明和Postman集合见 [验收报告](../docs/完整流程验收报告.md)。文档中旧目录拆分建议不代表必须存在同名模块，实际蓝图注册以app.py为准。

- 注册/登录必须提交JSON对象，username/password为字符串；注册用户名3～50字符、密码至少6字符。
- 单词收藏word_id、完读story_id必须为正整数；收藏来源仅flashcard/story；非对象JSON和无效参数返回业务400。
- 词书单词列表page正整数、page_size为1～100、filter仅all/learned/unlearned；收藏列表page正整数、page_size为1～200、keyword最多150字符。
- 发音音频来源、全部到期词分页查询和具体离线/同步设置仍需后续决定，不属于当前已实现接口。
- 本轮验收修复无需新SQL，更新后重启后端。
