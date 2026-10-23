# 学生工作助手 · Student Work Assistant（liyichen-deployment 分支）

DSS5105 Track 4 小组项目的可运行版本。

- **功能**：整理邮件、提取任务和截止日期、生成学习计划、整理小组讨论、起草回复。所有发送和写入日历的操作都要先审阅确认；离线版只做模拟。
- **组成**：后端 FastAPI + SQLite，前端 React + TypeScript + Vite，单机运行，不需要服务器。

本文档写给组员：照着做，约 15 分钟就能在自己电脑上跑起来。

---

## 1. 准备环境

| 软件 | 版本 | 检查命令 |
|---|---|---|
| Python | 3.11 或以上（已在 3.14 上测试） | `python --version` |
| Node.js | 20.19 以上，或 22.12 以上 | `node --version` |
| Git | 任意较新版本 | `git --version` |

没装的话：Python 从 python.org 安装，Windows 安装时勾选 "Add Python to PATH"；Node.js 从 nodejs.org 安装 LTS 版。

## 2. 获取代码

```bash
git clone https://github.com/YichenLi-02/dss5105-track4.git
cd dss5105-track4
git checkout liyichen-deployment
```

## 3. 准备样本数据（不在仓库里）

为了保护隐私，**邮件样本数据不放在 GitHub 上**。请向 Yichen 私下索取文件夹 `AI项目数据源_去隐私`（已把学校、课程和人名替换成虚构内容），放到任意位置，记下路径。

> 没有这份数据也能启动，只是"邮件"页没有样本，"刷新邮件"会提示找不到样本数据。

## 4. 配置 `.env`

在项目根目录复制模板：

```bash
# Windows PowerShell
Copy-Item .env.example .env
# macOS / Linux
cp .env.example .env
```

用编辑器打开 `.env`，**至少改这一行**，指向你在第 3 步放数据的位置：

```
SAMPLE_DATA_DIR=D:/你的路径/AI项目数据源_去隐私
```

其他项保持默认即可。`.env` 已被 git 忽略，**不要提交、不要发到群里**。

## 5. 启动

### Windows（一条命令）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run.ps1
```

第一次运行会自动创建 Python 虚拟环境、安装依赖、构建前端，需要几分钟。完成后会显示 `Uvicorn running on http://127.0.0.1:8000`。

### macOS / Linux（手动）

```bash
# 后端依赖
cd src/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 前端构建
cd ../frontend
npm ci
npm run build

# 启动（在 src/backend 目录）
cd ../backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 打开应用

浏览器访问 **http://127.0.0.1:8000** ，进入"邮件"页，点 **刷新邮件** 导入样本。

建议用 Chrome 或 Edge 正常打开；VS Code 内置预览浏览器的部分功能可能不完整。

## 6. 开发时（改代码实时生效）

开两个终端：

```bash
# 终端 1：后端（自动重载）
cd src/backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload   # Windows
# .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload    # macOS / Linux

# 终端 2：前端（热更新）
cd src/frontend
npm run dev
```

开发时访问 **http://127.0.0.1:5173** 。

## 7. 运行测试

```bash
cd src/backend
.venv\Scripts\python -m pytest -q     # macOS / Linux: .venv/bin/python -m pytest -q
cd ../frontend
npm run build                          # 同时做 TypeScript 类型检查
```

后端测试应全部通过。没有样本数据时，依赖样本的测试会自动跳过。

## 8. 可选：接入真实服务

**不配置也能完整演示离线版。** 需要时再看下面三项：

| 功能 | 需要什么 | 说明 |
|---|---|---|
| 智能分类（AI 模型） | 自己的 OpenAI API key | 在 `.env` 填 `LLM_PROVIDER=openai`、`OPENAI_API_KEY`、`OPENAI_MODEL`，并设 `ALLOW_MODEL_PROCESSING=true`；然后在应用的 **设置 → 数据处理** 里勾选开启。分析 50 封邮件通常不到 1 美元，建议先在 OpenAI 后台设消费上限 |
| 读取 Gmail / Google 日历（只读） | Google OAuth 客户端 ID 和密钥 | 二选一：① 请 Yichen 把你的 Gmail 加为 Cloud 项目 `dss5105-student` 的**测试用户**，再私下拿客户端 ID 和密钥；② 用自己的 Google Cloud 项目创建，步骤见 `docs/RUNNING.md`。回调地址必须是 `http://127.0.0.1:8000/api/connections/google/callback` |
| Outlook / Teams | Microsoft Entra 应用注册 | 学校账号可能需要管理员同意，非必需 |

key 和密钥只能放在自己电脑的 `.env` 里，不要写进代码、不要截图、不要上传。连接后的登录凭证保存在系统凭据库（Windows 凭据管理器），不在项目文件里。

## 9. 注意事项

- **不要提交这些内容**：`.env`、`local-data/`（本地数据库和上传文件）、样本数据文件夹。它们都已在 `.gitignore` 中，提交前用 `git status` 再确认一次。
- **真实写入默认关闭**：发送邮件、Teams 消息和写入日历在离线版里都只是模拟，界面会写明"未实际发送"。
- **重置本地数据**：停止服务后删除 `local-data/app.sqlite3*`，重新启动即可。
- **想看演示样本**：如果连接了真实邮箱，样本会自动隐藏。可以在 **设置 → 演示数据** 里改为"显示"。

## 10. 常见问题

| 现象 | 解决 |
|---|---|
| `python` 不是内部或外部命令 | 重新安装 Python 并勾选 Add to PATH，或改用 `py` 命令 |
| PowerShell 提示禁止运行脚本 | 按第 5 步原样使用 `-ExecutionPolicy Bypass` |
| 端口 8000 被占用 | 关掉之前启动的服务（终端里按 Ctrl+C），或换端口启动 |
| 页面还是旧样子 | 顶部出现"界面已更新"时点 **刷新**，或按 Ctrl+F5 |
| "刷新邮件"提示找不到样本数据 | 检查 `.env` 里 `SAMPLE_DATA_DIR` 的路径，Windows 路径用 `/` 或 `\\` |
| Google 授权页显示"此应用未经验证" | 测试模式下的正常提示，点"继续"即可；如果提示无权访问，说明你还不是测试用户 |
| `npm ci` 报 Node 版本错误 | 升级到 Node 20.19+ 或 22.12+ |

## 更多文档

- `docs/RUNNING.md`：启动、测试和外部服务配置的细节
- `docs/IMPLEMENTATION.md`：已实现的功能、与设计接口的差异、仍为模拟的部分
- `docs/UI_AUDIT.md`：界面设计审查记录（依据 `.claude/skills/refactoring-ui`）
