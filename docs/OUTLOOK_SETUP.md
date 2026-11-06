# 接入真实 Outlook 邮箱

本文说明如何把真实的 Outlook / Microsoft 365 邮箱连到本应用：只读同步邮件、读取日历忙闲、经审阅后真实发送，以及（可选）把学习块写进本应用在 Outlook 里创建的专属学习日历。大约 15 分钟。

> 不配置也能完整演示离线版。下面的密钥只放在自己电脑的 `.env`，不要提交、截图或发到群里。

## 0. 先选演示账号

| 账号 | 能否使用 | 说明 |
|---|---|---|
| 个人 Outlook.com / Hotmail / Live | **推荐** | 登录时自己同意权限即可 |
| 学校账号（NUS / Microsoft 365） | 视学校策略 | 学校租户通常不允许学生自行授权第三方应用读邮件，会提示“需要管理员批准”（AADSTS90094 / 65001）。没有 IT 批准时不要用它答辩 |

Teams 聊天读取只支持工作 / 学校账号；个人账号只能用邮件和日历。

## 1. 在 Microsoft Entra 注册应用

1. 打开 <https://entra.microsoft.com>（或 Azure 门户 → Microsoft Entra ID），进入 **应用注册 → 新注册**。
   - 注册应用需要一个 Entra 目录。纯个人账号如果进不去，可以由已有 Azure 目录的组员来注册（注册后，任何个人 Outlook 账号都能登录使用），或用个人账号开通免费 Azure，系统会自动建立“默认目录”。
2. 填写：
   - **名称**：随意，例如 `Student Work Assistant`。
   - **支持的帐户类型**：选 **“任何组织目录中的帐户和个人 Microsoft 帐户”**，对应 `.env` 里的 `MICROSOFT_TENANT_ID=common`。
   - **重定向 URI**：平台选 **Web**，填 `http://localhost:8000/api/connections/microsoft/callback`。
     门户不接受 `http://127.0.0.1` 开头的地址，所以这里用 `localhost`。授权完成后，应用会自动跳回 `http://127.0.0.1:8000`。
3. 在 **概述** 页复制 **应用程序(客户端) ID**，填到 `MICROSOFT_CLIENT_ID`。
4. 进入 **证书和密码 → 新客户端密码**，创建后立即复制 **“值”(Value)**，填到 `MICROSOFT_CLIENT_SECRET`。
   这个值只显示一次。不要复制旁边的“密码 ID”，那是一个 GUID，填进去会报 AADSTS7000215。
5. 建议在 **API 权限 → 添加权限 → Microsoft Graph → 委托的权限** 里加上：`offline_access`、`User.Read`、`Mail.Read`、`Calendars.Read`，需要真实发送时再加 `Mail.Send`，要把学习块写进 Outlook 时再加 `Calendars.ReadWrite`。个人账号不需要点“授予管理员同意”。

## 2. 填写 `.env`（项目根目录）

```ini
MICROSOFT_CLIENT_ID=<应用程序(客户端) ID>
MICROSOFT_TENANT_ID=common
MICROSOFT_CLIENT_SECRET=<客户端密码的值>
MICROSOFT_REDIRECT_URI=http://localhost:8000/api/connections/microsoft/callback
APP_ORIGIN=http://127.0.0.1:8000
```

如果 `.env` 是从旧模板复制的，请把旧的 `MICROSOFT_TENANT_ID=organizations` 和 `127.0.0.1` 回调地址改成上面的值。
改完后重启服务：先双击 `Stop-Local.cmd`，再双击 `Start-Local.cmd`。

## 3. 检查配置

```powershell
src\backend\.venv\Scripts\python scripts\check-outlook.py
```

脚本会检查客户端 ID 格式、租户、密码是否误填成“密码 ID”、回调地址，以及能否访问微软登录服务。脚本不会打印密钥。

## 4. 在应用里连接

1. 打开 <http://127.0.0.1:8000>，进入 **来源 → 账号连接**，在 Microsoft 卡片点击 **读取邮件**。
2. 在微软登录页选择账号并同意权限，然后会自动回到应用，显示“已连接 · 你的邮箱地址”。
3. 在 **同步邮件** 里选时间范围（近 7 / 14 / 30 天）和最多封数，点击 **开始同步**。邮件页会出现真实邮件，演示样本自动隐藏。
4. 可选：点击 **读取日历空闲时间**，学习计划页即可选择 “Outlook Calendar”。
5. 可选，真实发送：在“额外写入权限”中授权 **发送邮件**。真实发送还需要 `APP_MODE=live`、`ENABLE_EXTERNAL_WRITES=true` 和设置页的真实写入开关，并且每封邮件都要在审阅界面单独确认。
6. 可选，写入 Outlook 学习日历：在“额外写入权限”中授权 **专属学习日历**（微软会请求 `Calendars.ReadWrite`），再点 **创建专属学习日历**，在审阅界面确认。之后用 Outlook 忙闲生成的计划，审阅页会写明“写入：Outlook 中本应用的学习日历”，确认后学习块出现在 Outlook 的这个日历里。
   - 微软没有“只能管理本应用创建的日历”这种权限，所以这一项权限本身能改所有日历。应用在代码里只往自己创建的那个日历写：新建事件只发到这个日历，移动时删除旧块也只在这个日历里删，不会动你的主日历或其他日历。不放心可以不开这一项，学习块照样可以写进 Google 学习日历。
   - 计划用哪个日历的忙闲生成，学习块就写进那个账号的学习日历；那个账号还没有学习日历时，写进已有学习日历的另一个账号。

## 5. 用真实账号验证

```powershell
src\backend\.venv\Scripts\python scripts\check-outlook.py --live
```

这一步只读：脚本输出账号、收件箱近 30 天的邮件数、最新一封的时间，以及未来 7 天的日程数，并写入 `local-data/outlook-check.json`。不会输出邮件内容，也不会发信或写入日历。

## 数据怎么处理

- **读取范围**：只读收件箱。勾选“包含垃圾邮件/已删除”时，才同时读取“垃圾邮件”和“已删除邮件”。按所选时间范围过滤，已存过的邮件不会重复下载。
- **入库前最小化**：正文只保存纯文本（不加载远程图片），地址、电话、验证码、链接和长数字都会替换成占位符。附件只记录文件名和大小，不下载内容。
- **令牌**：保存在 Windows 凭据管理器，数据库只存引用。“断开”会删除本地令牌。如要在微软一侧撤销授权：个人账号到 <https://account.live.com/consent/Manage>，学校账号到 <https://myapps.microsoft.com>。
- **发送**：通过 Graph `sendMail` 一次调用，按审阅时的收件人、正文和附件原样发送，附件总大小不超过 3 MB。返回 202 只表示微软已受理，不等于已送达。

## 常见错误

连接失败时，账号连接卡片会显示微软返回的错误码和对应的修改办法。

| 错误码 | 原因 | 处理 |
|---|---|---|
| AADSTS50011 | 回调地址不一致 | Entra 里的重定向 URI 必须与 `MICROSOFT_REDIRECT_URI` 完全相同（包括 `localhost`、端口和路径） |
| AADSTS50020 / AADSTS500200 | 应用不接受这种账号 | 把支持的帐户类型改为包含个人帐户，并设 `MICROSOFT_TENANT_ID=common` |
| AADSTS50194 | 单租户应用用了 common | 把 `MICROSOFT_TENANT_ID` 改成目录(租户) ID，或把应用改为多租户 |
| AADSTS700016 | 找不到应用 | 客户端 ID 填错了，或应用不在所填的租户里 |
| AADSTS7000215 | 密码无效 | 填密码的“值”，不是“密码 ID”；也可能已过期，需要新建 |
| AADSTS7000218 | Web 应用缺少密码 | 在 `.env` 填写 `MICROSOFT_CLIENT_SECRET` |
| AADSTS700025 | 公共客户端不能带密码 | 清空 `MICROSOFT_CLIENT_SECRET`，或把回调地址改登记到 Web 平台 |
| AADSTS9002327 | 回调地址登记在 SPA 平台 | 删除后改登记到 **Web** 平台 |
| AADSTS65001 / 90094 / 90095 | 需要管理员同意 | 学校租户限制，改用个人 Outlook 账号 |
| 创建学习日历失败：已有同名日历 | Outlook 里已经有一个同名日历（比如之前手动建过） | 在 Outlook 里把它改名或删除，再在应用里点 **创建专属学习日历** |
| 日历 `calendarView http 403:ErrorAccessDenied` | 旧版本申请的是 `Calendars.ReadBasic`；个人 Outlook.com 账号用这个权限读日历会被微软拒绝 | 更新代码后，在账号连接卡片里重新点 **读取日历空闲时间**，在微软页面同意 `Calendars.Read`（仍然只读）；再运行 `scripts/check-outlook.py --live` 确认 |

## 已知限制

- 写入 Outlook 学习日历需要 `Calendars.ReadWrite`，这项权限的范围比实际用到的大（见第 4 步第 6 点）；只写本应用创建的日历是代码层面的限制。
- 如果在 Outlook 里删除了这个学习日历，需要在应用里重新创建；`scripts/check-outlook.py --live` 会提示。
- 发出的回复是一封主题为 “Re: …” 的新邮件，不会自动并入原会话。
- 自动化测试（`tests/test_connectors_outlook.py`）使用模拟的 Graph 接口，只能证明请求格式和错误处理正确。真实账号是否可用，以第 5 步和页面实测为准。
