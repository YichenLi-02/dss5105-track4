# Outlook 学习日历写入验收记录

验收日期：2026-11-06。项目：Studyspace / DSS5105 Group 09。

结论：本机正式 FastAPI 环境、前端正式构建和真实个人 Outlook 账号的核心写入链路均已验证。评测中发现并修复了两处跨日历忙闲时间混用问题，新增 4 项回归测试。最终后端为 **136 passed**。本记录不代表所有账号、所有异常分支或整个系统无缺陷。

## 1. 验证环境与范围

- 使用本机项目自己的 `src/backend/.venv/Scripts/python.exe`，不是替代版 FastAPI。
- 前端执行 `npm run build`，包含 `tsc -b` 和 Vite 正式构建。
- 本机服务以 live 模式运行在 `http://127.0.0.1:8000`。
- 使用个人 Outlook.com 账号；Google 连接及其原有学习日历同时存在。
- 真实操作经用户确认，只有专属学习日历创建、一个五分钟测试块的写入/移动/清理；无参与人、无邮件发送、无会议邀请。
- 检查了 Google 与 Outlook 的建日历、写入、旧事件删除、写前忙闲复查、已写入块读回和审核预览链路。

## 2. 自动验证结果

| 检查 | 结果 | 解释 |
| --- | --- | --- |
| 修改前完整后端测试 | 132 passed | 与本次收到的代码说明一致 |
| 新增跨账号回归测试，修复前 | 4 failed | Google→Outlook 和 Outlook→Google 两个方向均复现 |
| 新增跨账号回归测试，修复后 | 4 passed | 两处逻辑都按 provider 隔离 |
| 修复后完整后端测试 | **136 passed** | 1 条 Starlette/httpx 弃用警告，不影响本次测试结果 |
| 前端正式构建 | **通过** | 44 modules transformed，生成正式 dist |
| 固定排程样例 | **27/27 passed** | known gaps: none |
| 随机排程样例 | 200 个，硬规则违规 **0** | 含不可行及信息不全场景，不表示每个场景都能全部排完 |
| 新会议冲突修复 | 191 个，硬规则违规 **0** | 推荐修复放松规则次数 0；平均改动 1.29 块，完全重排为 1.67 块 |
| 估计校准模拟 | 24.2% → 17.8% | 200 名模拟学生的误差中位数，不能当作真实用户准确率 |
| Outlook 只读诊断 | **通过** | 邮箱、主日历可读；专属学习日历存在，canEdit=true |

复现命令（项目根目录，PowerShell）：

```powershell
Push-Location src\backend
.venv\Scripts\python.exe -m pytest -q
Pop-Location

Push-Location src\frontend
npm run build
Pop-Location

src\backend\.venv\Scripts\python.exe scripts\eval-planner.py
src\backend\.venv\Scripts\python.exe scripts\check-outlook.py --live
```

后两条会生成本地报告；`check-outlook.py --live` 是只读检查，不会创建日历或写事件。

## 3. 发现的问题及修复

### 3.1 写入前复查可能错误忽略另一个账号的忙碌时间

原逻辑把待移动旧块的全部时间区间，从每个学习日历的忙碌区间里扣除，没有区分旧块属于哪个 provider。

例如：Google 有 09:30–10:00 的旧学习块，Outlook 同时有 09:30–10:00 的另一事件。移动 Google 块时，原逻辑也会扣掉 Outlook 的忙碌时间，可能错误放行新写入。反方向同样存在。

修复：`proposal_service.recheck_busy_before_write()` 只扣除当前正在读取的 provider 中待移动旧块的时间；其他账号的忙碌区间完整保留。

### 3.2 重新规划的读回合并也可能抵消另一个账号的事件

原逻辑虽然在决定保留块时已比较 provider，但在计算学习日历剩余忙碌时间时，仍扣除了所有已保留块。

修复：`plan_service.reconcile_study_blocks()` 仅使用同一 provider 的保留块解释该 provider 的忙碌时间。另一个账号同一时段的事件继续占用时间。

这次需要合并的代码文件：

```text
src/backend/app/services/proposal_service.py
src/backend/app/services/plan_service.py
src/backend/tests/test_cross_provider_study_busy.py
```

新增测试覆盖两处逻辑及两个 provider 方向，共 4 项。不访问真实微软/Google 服务，也不修改正式数据库。

## 4. 真实 Outlook 验收

所有下列时间均为 Asia/Singapore（UTC+8，与本次北京时间相同）。

| 步骤 | 实际操作与证据 | 结果 |
| --- | --- | --- |
| 权限 | 微软返回的连接权限包含 Calendars.ReadWrite | 通过 |
| 创建日历 | 在应用审核页确认创建“Track4 学习计划 / study plan”；微软接口返回成功；重新读取日历得到 canEdit=true | 通过 |
| 计划输入 | 仅选一个新建五分钟验收任务，忙闲来源为 Outlook；没有把其他真实任务纳入写入 | 通过 |
| 写入审核 | 审核页显示“the app's study calendar in Outlook”、17:20–17:25、无参与人 | 通过 |
| 真实写入 | 在应用点击确认后，从 Graph 读回对应事件；17:20–17:25、五分钟、attendees=[] | 通过 |
| 再次规划 | 通过界面重新规划，已写入的块被保留，显示 already written, kept；本次待新安排变为 0 分钟 | 通过 |
| 移动审核 | 在应用编辑为 17:25–17:30；审核页同时列出新块和待移除的 17:20–17:25 旧块 | 通过 |
| 移动执行 | 新事件存在且时间正确；旧事件读取返回 404；学习日历窗口内只有一个本次测试事件 | 通过 |
| Outlook 网页验证 | 打开 Outlook 网页日历，选中专属学习日历，实际看到测试事件及 17:25–17:30 的详情 | 通过 |
| 主日历对比 | 固定未来七天查询窗口，对主日历事件 id/changeKey/start/end/showAs/isCancelled 规范化后计算摘要；写入、移动、清理后的摘要均与基线相同 | 通过 |
| 清理 | 在 Outlook 网页删除本次测试事件；Graph 再读返回 404，窗口内本次测试事件数为 0；本地验收任务标记 ignored | 通过 |

专属学习日历保留，可继续正常使用。仅清理了本次验收事件；正式任务、原有学习块、他人日程均未修改。本次主日历基线在查询窗口内为 0 个事件，因此“主日历未变”是对该窗口的检查，不能替代所有日历、全部历史数据的全量审计。

测试块已经清理，不能在最终日历里继续看到它。真实显示过的截图、审核记录及接口读回结果已保存到本地证据目录。

## 5. 权限说明与验收边界

1. `Calendars.ReadWrite` 本身能够读写用户日历。限制“只写本应用的学习日历”由后端保存的专属日历 ID 和写入路径控制，不是微软提供的窄权限。本次实际操作只涉及这个专属日历。
2. 写前复查缩小了“预览后日历变化”的风险窗口，不能让外部日历的读取与写入成为一个原子事务。复查完成后、真正写入前的并发变化仍可能发生。
3. 本轮真实测试的是 Outlook 内五分钟块的创建、读回、移动、删除；Google↔Outlook 的真实跨账号迁移未执行。现有自动测试覆盖目标日历选择；本次新增测试覆盖跨 provider 忙闲隔离，不应称为跨账号迁移的真实验收。
4. 没有为了测试而伪造系统时间或真实完成进度。本次新 Outlook 块在结束前已清理，因此“结束后完成了吗？”没有用这个真实 Outlook 块现场触发；完成反馈不是本轮新增的真实验收结果。
5. 学习日历读回仍以时间区间对照本地写入记录。用户在 Outlook/Google 网站中另行改时间、添加重叠事件等情况，不等同于逐事件 ID 对账；本轮验证的是应用内移动路径。
6. 未对真实账号故意制造限流、网络中断、撤销权限或删除整个专属日历。单次成功不能证明这些恢复分支全都可用。
7. 之前记录的模型密钥过期问题未在本轮修复；日历链路和上述排程测试不依赖模型成功调用。不能把本报告当成模型处理验收通过。

## 6. 证据位置与交接

本报告可随代码共享。本机私有证据位于：

```text
local-data/outlook-write-qa-20261106/state.json
local-data/outlook-write-qa-20261106/create-calendar-review.png
local-data/outlook-write-qa-20261106/write-review.png
local-data/outlook-write-qa-20261106/write-executed.png
local-data/outlook-write-qa-20261106/readback-kept.png
local-data/outlook-write-qa-20261106/move-review.png
local-data/outlook-write-qa-20261106/move-executed.png
local-data/outlook-write-qa-20261106/outlook-event-proof.png
local-data/outlook-check.json
local-data/planner-eval/report.md
```

这些本地文件可能含账号、内部事件 ID 或用户任务信息，保留在被忽略的 `local-data/`，不要整目录提交到公共仓库。用于复核的本地脚本不会发送邮件或代为确认应用提案。

改动已保存到本机项目并重启生效；没有替用户推送 GitHub。代码目录是 ZIP 解压目录，不会自动更新远程仓库或原 ZIP。
