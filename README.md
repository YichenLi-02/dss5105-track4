# DSS5105 Track 4：学生效率助手 / Student Productivity Agent

六人小组项目，Sprint 1 已完成，目前在开发阶段。  
A six-person team project. Sprint 1 is done; development is under way.

## 大概要做什么 / What we are building

整理 Outlook / Teams 消息 → 提取待办和截止日期 → 生成每周计划。先把这条流程做通，不接 Canvas / LMS。  
Organise Outlook / Teams messages → extract tasks and deadlines → generate a weekly plan. Get this workflow working first; Canvas / LMS integration is excluded.

最终要有可用界面、完整代码、演示视频和 PPT、项目文档及效果评估。可评估节省的时间和提取准确率，并逐个分析至少 10 个失败案例。  
Deliver a usable interface, complete code, demo video and slides, documentation, and evaluation. Possible measures include time saved and extraction accuracy; analyse at least 10 failure cases individually.

## 怎么运行 / Run it

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。  
Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # 安装依赖 / install dependencies
uv run studyspace       # 启动 / start: http://127.0.0.1:8000
uv run pytest           # 运行测试 / run the tests
uv run studyspace evaluate   # 抽取与排程评估报告 / extraction and planner evaluation report
```

打开 http://127.0.0.1:8000 ，在收件箱页点 **Load demo student** 载入虚构学生（时钟固定在 2026-10-12 08:00，第 9 周），然后按左侧顺序走一遍。接口文档在 `/docs`。  
Open http://127.0.0.1:8000 and click **Load demo student** on the Inbox page (a fictional student; clock fixed at Mon 12 Oct 2026, 08:00, Week 9), then follow the pages in the sidebar. API docs are at `/docs`.

| 页面 / Page | 做什么 / What it does |
| --- | --- |
| 01 Inbox | 上传 .eml / .csv / .ics / 空闲时间 .json 或粘贴文本；每封消息标注“有任务 / 需回复 / 活动 / 通知 / 群发”。<br>Upload or paste messages; each one is labelled task / reply needed / event / info / newsletter. |
| 02 Review tasks | 第一道关口：看原文依据，改日期和用时，处理“改期”和“midnight”二选一，确认后才进入排程。<br>Gate 1: check the source sentence, fix dates and effort, resolve deadline changes and "midnight" choices. |
| 03 Study plan | 按 4 号的规则生成草稿（不撞课、每天 ≤3 小时、单段 ≤90 分钟、截止前留 24 小时）；第二道关口：采用后才保存。可锁定、标记完成、重排、导出 .ics。<br>Gate 2: a checked draft is saved only when adopted. Lock or finish sessions, re-plan, export to your calendar. |
| 04 Replies | 第三道关口：按学生自己的语气起草回复，读过并勾选后才能复制或在邮件程序中打开；系统从不发送。<br>Gate 3: drafts in the student's style; copy or open in the mail app only after review. Nothing is ever sent by the app. |
| 05 Find a meeting time | 避开课程、考试、会议、锁定时段，可加入组员的 .ics 忙碌时间。<br>Free times around classes, exams, meetings, locked sessions and groupmates' busy times. |
| 06 Privacy & data | 并排显示“本机原文”和“模型会收到的内容”（清洗 + 脱敏），列出每次模型调用，可删除全部数据。<br>Original next to what a model would receive; every model call is listed; delete all data. |

网页前端在 `src/studyspace/web/`：不需要 Node 或构建步骤，由同一个服务提供；界面沿用 1 号的设计稿。  
The web front end lives in `src/studyspace/web/`: no Node or build step, served by the same process, following member 1's UI design.

目前没有接入大模型，抽取和回复草稿走本地规则与模板（离线模式），不会向外发送任何内容。真实邮件只存在本机的 `.studyspace/` 数据库里，已被 git 忽略。  
No language model is connected yet: extraction and reply drafts use local rules and templates (offline mode), and nothing is sent anywhere. Real messages stay in the local `.studyspace/` database, which git ignores.

<details><summary>macOS：报 “No module named studyspace” / macOS: “No module named studyspace”</summary>

项目放在 iCloud 同步的桌面或文稿里时，iCloud 会把 `.venv` 里的文件标成隐藏，Python 会跳过它们。把环境放到 iCloud 不同步的目录：  
When the project sits in an iCloud-synced Desktop or Documents folder, iCloud marks files inside `.venv` as hidden and Python skips them. Keep the environment in a folder iCloud does not sync:

```bash
rm -rf .venv && UV_PROJECT_ENVIRONMENT=.venv.nosync uv sync && ln -s .venv.nosync .venv
```
</details>

## 代码结构 / Code layout

| 路径 / Path | 内容 / Contents | 负责 / Owner |
| --- | --- | --- |
| `src/studyspace/models.py` | 模块之间传递的数据结构 / shared data objects | 全组 / all |
| `src/studyspace/ingest/` | 导入 .eml / .csv / .ics / 空闲时间 / 粘贴文本 / importers | 2 |
| `src/studyspace/extraction/` | 抽取任务与截止时间、跨邮件合并 / task and deadline extraction, merging | 3 |
| `src/studyspace/planner/` | 排程引擎 `engine.py` 与独立检查 `check.py`（移植自 4 号的检查脚本）/ planner and independent checker | 4 |
| `src/studyspace/triage.py`, `drafts.py`, `meetings.py` | 收件箱分类、回复草稿、找会议时间 / triage, reply drafts, meeting finder | 5 |
| `src/studyspace/llm.py` | 唯一的模型出口：清洗 → 脱敏 → 调用 → 记录 / the only path to a model | 5 |
| `src/studyspace/api/`, `storage/` | 接口与本地数据库 / API and local SQLite database | 5 |
| `src/studyspace/web/` | 网页前端（基于 1 号的设计）/ web front end (member 1's design) | 1, 5 |
| `src/studyspace/evaluation.py` | 抽取评分、失败案例列表、排程参考用例检查 / evaluation and failure cases | 6 |
| `src/studyspace/synthetic/`, `data/synthetic/` | 虚构的开发数据及标注 / fictional development data and labels | 2, 6 |
| `data/calendar/` | 学期周次日历 / academic calendar (verify against the official one) | 2 |
| `tests/` | 测试；`tests/fixtures/` 含 4 号的排程参考用例 / tests, incl. member 4's planner reference cases | 6 |

用真实样本评估（数据放在被 git 忽略的 `data/private/`）/ Evaluate on the real set (kept in the git-ignored `data/private/`):

```bash
uv run studyspace evaluate --sources data/private/sprint1_core10.csv --gold data/private/member3_labels.xlsx --out report.md
```

`data/synthetic/` 由 `uv run studyspace synth` 生成，全部为虚构内容，仅用于开发和演示；最终报告的准确率用另行保留的真实样本评估。  
`data/synthetic/` is generated by `uv run studyspace synth`. It is entirely fictional and only for development and demos; the accuracy reported at the end comes from a separate held-out real set.

## 什么时候干什么 / Timeline

| 时间 / Date (2026) | 要完成什么 / What to finish |
| --- | --- |
| 现在至 10 月上旬 / Now–early Oct（建议 / suggested） | 定分工、选技术和数据来源，做出“消息 → 待办”初版。<br>Assign roles, choose the stack and data sources, and prototype message-to-task extraction. |
| **10 月 16 日 / 16 Oct — Sprint 1** | 讲清问题、价值、架构、风险和后续计划。15:00 前交 PPT/PDF；19:00 开始展示，现场讲解 5 分钟 + 问答 2 分钟。<br>Explain the problem, value, architecture, risks and roadmap. Submit slides by 15:00; session starts at 19:00, with a 5-minute live presentation + 2-minute Q&A. |
| **10 月 30 日 / 30 Oct — Sprint 2** | 展示能跑的初版，说明分工、进度和测试计划。15:00 前交 5 分钟视频和幻灯片；19:00 展示与问答。<br>Demo a working prototype; show ownership, progress and the validation plan. Submit a 5-minute video and slides by 15:00; presentation and Q&A at 19:00. |
| **11 月 13 日 / 13 Nov — Sprint 3** | 展示最终系统、测试结果和不足。15:00 前交 5 分钟视频和幻灯片；19:00 展示与问答。<br>Show the final system, evaluation results and limitations. Submit a 5-minute video and slides by 15:00; presentation and Q&A at 19:00. |
| **11 月 15 日 / 15 Nov — 23:59** | 交最终 `GroupNN.zip`，检查代码能按说明运行、材料齐全。<br>Submit the final `GroupNN.zip`; check that setup instructions work and all deliverables are included. |

三次展示全员到场。Sprint 2 起，幻灯片首页放组号、成员及学号、公开 GitHub 链接和 demo 链接。  
Everyone attends all three reviews. From Sprint 2, the first slide must show the group number, members and student IDs, public GitHub link, and demo link.

## 六人分工 / Six-person roles

建议分工，可调整；每人补充自己负责部分的文档。  
Suggested roles, open to adjustment; everyone documents their own work.

1. 使用步骤与页面 / Usage steps and pages.
2. 资料与数据准备 / Materials and data preparation.
3. 信息整理规则 / Information organisation rules (task and deadline extraction).
4. 学习安排规则 / Study scheduling rules (weekly planning).
5. 程序实现与连接 / Program implementation and integration.
6. 检查效果与演示 / Evaluation, testing and demo.

## 最后交什么 / Final submission

`GroupNN.zip` 包含以下文件 / Include these files in `GroupNN.zip`:

- `Readme.pdf` — 运行说明 / Setup and run instructions.
- `Slide.pdf` 或 / or `Slide.pptx` — 最终幻灯片 / Final slides.
- `Video.mp4` — 系统 demo / System demo.
- `Documentation.pdf` — 项目文档，最多 15 页 / Project documentation, maximum 15 pages.
- `Evaluation.pdf` — 效果评估 / Evaluation report.
- `Teams.pdf` — 分工与贡献 / Roles and contributions.
- `Strategic_Recommendations.pdf` — 战略建议 / Strategic recommendations.

展示文件名依次为 `Presentation_GroupNN_Sprint1`、`Presentation_GroupNN_Sprint2`、`Presentation_GroupNN`，加对应扩展名；NN 是两位组号，例如 01。  
Use these presentation filenames respectively, with the appropriate extension: `Presentation_GroupNN_Sprint1`, `Presentation_GroupNN_Sprint2`, `Presentation_GroupNN`. NN is the two-digit group number, e.g. 01.

日期及要求依据课程说明 v4，更新以老师通知为准。代码放 `src/`，测试放 `tests/`，示例数据放 `data/synthetic/`；不要上传密钥或真实私人邮件。  
Dates and requirements follow the course specification v4; later instructor announcements take precedence. Use `src/` for code, `tests/` for tests and `data/synthetic/` for sample data. Do not upload secrets or real private emails.
