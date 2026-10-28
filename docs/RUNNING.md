# Running, testing and configuration

## Requirements

- **Python:** 3.11 or newer; tested on 3.14.
- **Node.js:** 20.19+ or 22.12+; tested on 24.
- **Sample data (optional):** `SAMPLE_DATA_DIR` points to the de-identified development sample. It defaults to `data/AI项目数据源_去隐私` and is **not** part of the public repository. The app reads `selected_50.jsonl`, `date_candidates.jsonl`, `style_profile.json` and `reference_view.json` from it. Without the sample the app still starts; the Mail page then only shows mail from a connected account.
- **Design pack (optional):** reference groupings come from `reference_view.json` in the sample. Only if that file is missing does the app fall back to the original design pack, at the path set by `DESIGN_DIR`.

## One-command start (offline, no keys needed)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run.ps1
```

Open <http://127.0.0.1:8000>. If the sample is present, click **Refresh mail** on the Mail page to import its 40 inbound mails and 10 tone references.

## Development mode (two terminals)

```powershell
# terminal 1: backend
cd src/backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt   # pinned versions: requirements.lock
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# terminal 2: frontend (Vite proxies /api to port 8000)
cd src/frontend
npm ci
npm run dev        # http://127.0.0.1:5173
```

## Tests

```powershell
cd src/backend
.venv\Scripts\python -m pytest -q          # 54 tests on a temporary database; never touches local-data
cd ../frontend
npm run build                              # TypeScript type-check + production build
cd ../..
src/backend/.venv/Scripts/python scripts/smoke.py   # smoke check against a running server
```

Tests that need the private sample are skipped when it is not available.

## Local data

- `local-data/` holds the SQLite database and copies of uploaded PDFs. It is git-ignored; do not commit it.
- To reset: stop the server and delete `local-data/app.sqlite3*`.

## Real services (optional; offline features keep working without them)

| Capability | Configuration | Notes |
| --- | --- | --- |
| Model analysis and drafting | `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `ALLOW_MODEL_PROCESSING=true`, plus the switch in Settings | Responses API with strict JSON schemas and `store=false`. Only the subject, the de-identified body, the time and the time zone are sent. |
| Gmail and Google free/busy (read-only) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; register the redirect URI `http://127.0.0.1:8000/api/connections/google/callback` | Read scopes: `gmail.readonly`, `calendar.events.freebusy`. While the OAuth app is in *Testing*, add each user under *Audience → Test users*. |
| Outlook and Teams chat (read-only) | `MICROSOFT_CLIENT_ID` (with a secret, or as a public client), `MICROSOFT_TENANT_ID` | Scopes: `Mail.Read`, `Calendars.ReadBasic`, `Chat.Read`. School tenants may require admin consent. |
| Real sending and calendar writes | `APP_MODE=live`, `ENABLE_EXTERNAL_WRITES=true`, *Allow real writes* in Settings, and the extra write scope on the account | Every operation is still reviewed one by one. De-identified sample addresses can never receive a real message. |

OAuth tokens are stored in the OS credential store through `keyring`; the database only keeps a reference. Tokens never appear in the browser, in URLs or in logs.

With `APP_MODE=live` the server prints a one-time local session code at start-up, and the browser asks for it before opening a session. Each restart prints a new code.
