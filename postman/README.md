# Postman导入和使用

导入本目录两个JSON文件：

- `StoryLex.postman_collection.json`：全部46个真实方法/路径，包括兼容路径。
- `StoryLex.local.postman_environment.json`：不含账号密码、Token或模型Key的环境模板。

导入后右上角选中该环境，将base_url设置为后端地址，填写专用测试账号的username/password，发送“登录并保存Token”。脚本会自动把登录Token保存到当前环境。

## 这份集合如何用

本集合用于逐项手动联调，不是一次点击就能自动通关的Runner脚本。正式新学必须逐词选择正确答案；隔离数据库里的完整自动流程由 `tests/test_end_to_end.py` 验证。不要将“跳过了请求”视为该接口通过。

所有修改操作都会改变当前登录账号数据；请使用独立测试账号。本次生成集合本身不发送任何请求。

- 注册默认关闭，确需新账号时设置enable_register=true，并确保username不重复；部署库必须有默认词书CET6luan_1。
- 真实AI默认关闭，需主动将enable_ai=true后调用，可能消耗服务额度。Key永远不填写到Postman集合里，模型Key只放后端。
- TXT默认关闭，先在上传请求里重新选择本地TXT文件，再设置enable_txt=true。仓库中samples/import_demo.txt只提供样例，词书字面匹配可能无命中，需按实际词书调整。
- 缺Token、文章/题组ID或选词等上下文时，预请求脚本会skipRequest并在控制台说明原因。若旧版Postman不支持skipRequest，请改为手动逐项发送，勿直接运行全目录。
- run_id默认manual-001。同一次业务重试保持它不变；重新开始一轮出题/生成/状态操作时改为新值，避免取回旧任务。

## 变量自动填充

| 发出请求 | 自动保存 |
|---|---|
| 登录/注册 | token、current_book_id（如果返回） |
| 词书单词列表 | word_id（第一项）、ai_word_ids（前两项）、mastered_word_id（页内第一项已掌握词） |
| 收藏列表 | favorite_word_ids（前两项） |
| 正式新学/复习题组 | group_id、第一道未通过题的word_id/question_id、进度；复习还保存pause_word_id |
| 新学答错 | learn_question_id更新为retry_question的新版本 |
| 新学组结算 | learn_word_ids |
| 文章列表 | story_id（第一项，可自行修改成指定文章） |
| 阅读/自主出题 | 对应session_id，及默认全选A的answers模板 |
| AI/TXT预览及草稿查询/编辑 | draft_id、draft_version、draft_title、draft_content |
| 阅读位置查询/保存 | progress_version |

选词变量和answers是JSON文本，例如 `[101,102]`，不是逗号分隔字符串。selected_key默认A，需要根据实际题目调整。自动生成的全部选A只用于组装请求格式，不代表正确答案。

## 推荐顺序

1. 登录 → 词书列表 → 词书单词列表 → 首页。要切换词书时先填写switch_book_id。
2. 新学：GET组 → 看选项设置selected_key → 提交该题 → 再GET组取下一道未通过题（答错可使用新版本重测）→ 全组通过 → 结算。
3. 正式复习：有到期词时GET组 → 逐题提交 → 查询组结果。不应为了测试而修改业务库日期；跨日自动验证已在隔离测试中完成。
4. 文库列表取得story_id → 阅读位置查询/保存 → 手动完读 → 阅读出题 → 修改reading_answers再提交。
5. 收藏列表取得选词 → 自主练习出题 → 修改independent_answers → 提交。小结练习使用结算返回的learn_word_ids。
6. AI/TXT预览 → GET草稿 → 可修改环境draft_title/draft_content → PUT编辑 → POST保存 → 详情/词表核对。
7. 暂停/恢复/重置使用对应有效ID和不同run_id进行新操作；重试保持旧run_id。标记掌握后可重新查询词表获取mastered_word_id。

正式答案的request_id由题目版本派生，同题原请求重试保持不变。答错后自动更新了question_id；再次发送将是重测，不是重放旧请求。如需测试网络重放，请从Postman历史复制原始完整Body，不使用已更新的环境变量。

## 自动检查及重建

响应脚本检查业务code=200，并保存上下文；AI请求还检查生成状态。手动测试通过才算验证，未发送、被跳过或模型失败不能计为通过。

```bash
venv/bin/python scripts/generate_postman.py
venv/bin/python -m unittest discover -s tests -p test_postman_artifacts.py -v
```

重建集合会覆盖本目录两个JSON模板和docs/实际路由清单.md，不会读取.env、调用后端或保存真实凭证。不要把已经填入凭证的个人环境导出并覆盖仓库模板。
