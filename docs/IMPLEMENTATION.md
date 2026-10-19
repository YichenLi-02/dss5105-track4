# 实施记录（liyichen-deployment）

依据：`软件设计与AI工作流` v1.1（00–06、11、openapi.json、database.sql），以及用户在 2026-10-19 提出的实现要求。

## 结构

```text
src/backend/app/
  main.py config.py db.py schema.sql security.py errors.py
  api/        core messages tasks documents drafts plans connections
  services/   import_service task_service reference_view document_service doc_rules
              style_service draft_service proposal_service planner plan_service chat_service
              analysis_service preferences privacy jobs
  providers/  net(出站白名单) tokens(keyring) oauth mail_readers calendars teams writers
  llm/        adapter（Responses API，严格 JSON schema，无工具调用）
src/frontend/src/
  app/(App, i18n, context, time)  api/(client, types)  pages/(6 个主入口 + 设置)
  components/(Panel, MailDetail, DraftEditor, ReviewDialog, DocumentLibrary, StyleReferences, AccountConnections, Tags)
  locales/zh-CN.json en.json  styles/(tokens.css, prototype.css, app.css)
```

技术栈：单个 FastAPI 进程 + SQLite，共 11 张表，沿用设计中的 `database.sql`；前端为 React + TypeScript + Vite + 普通 CSS。没有引入 Redis、向量库、微服务或代理框架。

## 已实现（离线、无需任何 key）

- **样本导入**：40 封收件和 10 封语气参考分开存放；按 `(connection_id, provider_message_id)` 去重，重复导入不会增加记录。分类标签记为 `reference_annotation`（建议标注），不当作模型结果展示。
- **邮件页**：统计卡、主题类别、需回复 / 需行动 / 仅重要三个筛选（同时选中时取交集）、搜索、原文、来源与依据位置、人工纠正（记为 `user`）、处理记录。
- **任务**：按 `entity_key` 合并 32 条时间表达，每条都保留证据并逐字核对原文位置。日期冲突时保留所有候选，正式日期留空；未注明的时刻保持 null。提交回执只把对应的交付物标为完成；非任务时间（验证码有效期、促销到期等）不会生成任务。确认任务需要日期、时刻、时区或规划停止时刻，以及工作量，并带修订号防止旧页面覆盖。实际进度用幂等事件记录。
- **课程资料**：真实上传 PDF，后端用 pypdf 逐页解析并保留页码。扫描件、加密文件和解析失败分别标为 `needs_ocr`、`encrypted`、`failed`，并支持改为粘贴原文。粘贴文本单独记为 `user_pasted`，不会当成 PDF 解析结果。本地规则提取明确日期和时刻；“reading week 之后的周五”“Week N”这类相对日期，只用同一学期的学年日历解析，日历本身不生成任务。排除资料会让相关任务回到待核对、依赖它的计划过期；也可以删除本地数据。
- **学习计划**：确定性的“最早截止优先”规划，带独立校验器，检查每日上限、单段最短 / 最长、休息、截止缓冲、每周弹性和可用时段。只有在容量上界已经小于需求时才判为 `infeasible`；否则报 `needs_adjustment`。已完成的进度会扣减剩余量并计入当日上限。重新规划会给出前后差异，旧计划标为过期。日历读取失败不会被当作空闲时间。
- **小组协作**：粘贴讨论后按规则整理为建议、决定、行动项和未解决问题。只有明确的决定语句或被负责人确认的分工才算决定；负责人或日期未知时保持 null。可以从结果起草 Teams 跟进消息。
- **个人语气**：只使用本人撰写的部分（M49 只保留第一句，不含 Zoom 模板）。每份样本可以选用或排除；修改后，依赖它的待发送提案会失效，草稿正文不会被替换，需要用户重新核对。招聘场景和中文没有本人样本，明确改用通用语气。
- **草稿与审批**：没有核实的事实一律保留为 `[[待填]]`，不编造。提案保存不可变的载荷、SHA-256 哈希、修订号、过期时间，并绑定会话。确认时须提交相同的哈希和 Idempotency-Key，后端用条件 UPDATE 保证只执行一次。任何修改都会让旧批准失效。离线版只记为 `simulated`。
- **安全**：会话 cookie（HttpOnly、SameSite=Strict）、写请求校验 CSRF、Origin 白名单；出站请求只允许固定的官方域名，Canvas / instructure 一律拒绝；入库前去除邮件地址、链接、电话、验证码和长数字。
- **中英切换**：界面语言保存在偏好设置里；邮件、证据、样本和用户正文保持原语言。

## 已写代码、只用模拟 HTTP 验证（没有真实账号或 key）

- 模型适配器：OpenAI Responses 接口，`store=false`，严格 schema；本地校验来源 ID、逐字引文和日期格式，按内容哈希、prompt、schema 和模型版本缓存。未启用时返回 409，离线功能不受影响。
- Google OAuth（PKCE + state，增量授权）；Gmail 只读同步（分页、有界重试、Retry-After、单封失败计入部分完成）；Google freeBusy。
- Microsoft OAuth，以及 Graph 邮件、calendarView、Teams 聊天的读取（只读用户选中的聊天）。
- 真实写入执行器：Gmail send、Graph sendMail、Teams 聊天消息、Google 专属学习日历和事件。超时记为 `unknown`，不自动重发；202 记为 `accepted`，不等于已送达；事件 ID 确定性生成，部分成功逐项记录。

以上都没有对真实服务做过调用，需要在你自己的 OAuth 应用和测试账号上实测。

## 与设计契约（openapi.json）的差异

| 位置 | 差异 | 原因 |
|---|---|---|
| `GET /api/messages` | 响应增加 `counts` | 统计卡需要不受筛选影响的计数 |
| MessageSummary | 增加 `source_type`、`attention_label`、`uncertainty`、`analysis_status`、`excluded`、`attachment_count`、`split` | 卡片显示待核对项和来源 |
| `analysis_origin` | 增加 `rule` | 本地规则结果不能标成 model 或 none |
| 资料上传 | 改为 `POST /api/uploads` 加 `POST /api/documents`（JSON 元数据），不走 `/api/imports` | 元数据和权限声明需要一并校验；`/api/imports` 只用于样本 |
| Document | 增加 `pages`、`page_count`、`user_excerpt`、`parsed_text`、`extraction_error`、`upload_id`、`synthetic`、`candidates` | 页码可追溯，粘贴文本与解析文本分开 |
| `/documents/{id}/extract` | 同步返回结果；`use_model=true` 返回 422 | 本地规则很快；资料的模型提取不在本版范围 |
| Draft | 增加 `purpose`、`placeholders`、`style_mode`、`style_note`、`relationship`、`language`、`stale_style`、`generation`、`recipients_deidentified`；请求可带 `relationship`、`language`、`use_model` | 语气降级和待填项需要显式状态 |
| Plan | 增加 `per_task`、`busy`、`days`、`stale_reasons`、`synthetic`、`computed_status` | 界面需要展示每天的安排和过期原因 |
| ChatSummary | `analysis_origin` 可为 `rule`；增加 `followup_points`、`messages`；请求可传 `raw_text` | 粘贴文本由后端解析 |
| 新增接口 | `/api/plans/latest`、`/api/demo/planning-scenario`、`/api/demo/documents`、`/api/demo/chat`、`/api/model/status`、`/api/audit`、`/api/connections/microsoft/chats[/import]`、`/api/drafts`（列表）、`/api/tasks/{id}` | 演示用的合成数据、处理记录、Teams 选择聊天 |
| 会话 | demo 模式下 `bootstrap_code` 可省略 | 单机演示也能一条命令启动；live 模式必须提供 |

FastAPI 会在 `/docs` 和 `/openapi.json` 自动生成实际接口说明。

## 仍为模拟或合成的部分

- 学习计划使用的忙闲时间来自合成课表（`provider=mock`），报告任务也是合成的（DEMO5105，2026-10-23 17:00）。
- 合成课程大纲和学年日历（Demo Term A，不是 NUS 官方日历），以及合成的小组讨论。
- 所有发送和日历写入在离线版中都只记为 `simulated`。
- 邮件分类和日期候选来自 AI 辅助建议标注，没有经过人工复核，不是金标准，也没有计算任何准确率。

## 已知限制

- 小组讨论是关键词规则整理，复杂的中英文表述可能漏判；接入模型后，聊天整理仍需另外实现 P07 的结构化调用（本版只有邮件分析和起草接入了模型）。
- PDF 不做 OCR。
- 日历写入只会新建学习块，不会移动或删除事件。
- Asia/Singapore 没有夏令时；涉及夏令时的边界情况尚未测试。
