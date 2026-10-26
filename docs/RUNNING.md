# 学生工作助手 · 启动、测试与配置

## 前提

- Python 3.12 及以上（本机实测 3.14.7），Node.js 20 及以上（实测 24.21）。
- 样本数据默认使用仓库内的**去隐私副本** `data/AI项目数据源_去隐私`（学校、课程号、人名、项目名均已替换为虚构内容，见其中的 `去隐私说明.md`）。读取 `selected_50.jsonl`、`date_candidates.jsonl`、`style_profile.json`、`reference_view.json`。原始文件夹 `AI项目数据源` 不被应用读取，也未被修改。
- 参考分组（主题类别、“重要”标记、摘要）来自副本中的 `reference_view.json`，记为“建议标注”。只有副本里缺这个文件时，才回退读取设计包 `软件设计与AI工作流/ui/index.html`。
- 两个路径都可以在 `.env` 里用 `SAMPLE_DATA_DIR` / `DESIGN_DIR` 修改。

## 一条命令启动（离线版，不需要任何 key）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run.ps1
```

浏览器打开 http://127.0.0.1:8000 ，到“邮件”页点“刷新邮件”，导入 40 封收件和 10 封语气参考。

## 开发模式（两个终端）

```powershell
# 终端 1：后端
cd src/backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt   # 锁定版本见 requirements.lock
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 2：前端（Vite 把 /api 代理到 8000）
cd src/frontend
npm ci
npm run dev        # http://127.0.0.1:5173
```

## 测试

```powershell
cd src/backend
.venv\Scripts\python -m pytest -q          # 后端 43 项，用临时数据库，不碰 local-data
cd ../frontend
npm run build                              # TypeScript 类型检查 + 生产构建
cd ../..
src/backend/.venv/Scripts/python scripts/smoke.py   # 对正在运行的服务做冒烟检查
```

## 本地数据

- `local-data/` 存放 SQLite 数据库和上传的 PDF 副本，已在 `.gitignore` 中，不要提交。
- 重置演示数据：停止服务，删除 `local-data/app.sqlite3*`。

## 接入真实服务（可选，缺配置时离线功能照常可用）

| 能力 | 需要配置 | 说明 |
|---|---|---|
| 模型分析 / 起草 | `LLM_PROVIDER=openai`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`ALLOW_MODEL_PROCESSING=true`，并在“设置”里勾选允许 | 使用 Responses API 的严格 JSON schema，设置 `store=false`；只发送主题、去标识正文、时间和时区 |
| Gmail 只读、Google 忙闲 | `GOOGLE_CLIENT_ID/SECRET`；在 Google Cloud 注册回调 `http://127.0.0.1:8000/api/connections/google/callback` | 只读权限 scope 为 `gmail.readonly` 和 `calendar.events.freebusy` |
| Outlook、Teams 聊天只读 | `MICROSOFT_CLIENT_ID`（以及 secret 或公共客户端）、`MICROSOFT_TENANT_ID` | 权限为 `Mail.Read`、`Calendars.ReadBasic`、`Chat.Read`；学校租户可能要求管理员同意 |
| 真实发送 / 写日历 | `APP_MODE=live`、`ENABLE_EXTERNAL_WRITES=true`、设置里打开真实写入、账号额外授权写入权限 | 每次操作仍需单独审阅确认；去标识的样本地址永远不能用于真实发送 |

OAuth token 保存在 Windows 凭据管理器（通过 keyring），数据库里只存引用，不会出现在浏览器、URL 或日志中。`APP_MODE=live` 时，服务启动会在控制台打印一次性本地会话码。
