# Student Work Assistant

A local-first assistant that turns a student's inbox, course documents and group chats into reviewed tasks, a realistic study plan and ready-to-send drafts. Nothing is sent or written to a calendar until the user has checked it.

Built by Li Yichen for the DSS5105 capstone (Track 4).

---

## What it does

| Area | What the user gets |
| --- | --- |
| **Mail** | Imported mail is grouped by topic (academic, career, events, promotions, other) and filtered by *needs reply*, *needs action* or *important*. Each summary links to the exact quote in the original, and there is a one-click link to open the original in Gmail. |
| **Tasks** | Deadlines are extracted with their evidence. Conflicting dates stay as separate candidates, and an unstated time stays empty; it is never guessed as 23:59. A task can only be confirmed once its date, time zone and effort are known. |
| **Study plan** | A deterministic earliest-deadline-first planner, checked by an independent validator. It respects the daily cap, session lengths, breaks, the deadline buffer and calendar busy time. If the plan cannot fit, it says so and shows the shortfall in minutes. |
| **Group work** | A pasted chat is sorted into suggestions, decisions, action items and open questions. A suggestion is never promoted to a decision, and an unknown owner stays unknown. |
| **To confirm** | Every outgoing action waits here as a proposal: the exact payload, its SHA-256 hash, an expiry time and one-time execution. Editing anything invalidates the earlier approval. |
| **Sources & connections** | PDF syllabi with page numbers (scanned, encrypted or broken files are reported, and the text can be pasted instead). The user's own writing samples set the tone of drafts. Gmail, Google Calendar, Outlook and Teams connect with read-only access. |

The interface switches between English and Chinese. Mail bodies, quotes and the user's own text are never machine-translated.

### Design principles

- **Evidence over guesses.** Every extracted date and task keeps a verbatim quote and its position in the source. Unknown facts stay `null` or `[[placeholder]]`.
- **Content is data, not instructions.** Text inside mail, PDFs and chats can never trigger an action, so prompt-injection lines are shown as plain data.
- **The model is optional.** All features work offline with local rules. Turning on an OpenAI model improves classification and drafting, and its output is checked locally before use: the quotes must exist in the source, and dates and times must be well-formed.
- **Writes are gated.** Real sending requires four things: live mode, a server flag, a user setting and a separate write permission on the account. Each send is still reviewed one by one. By default every send is only simulated.
- **Secrets stay on the server.** OAuth tokens live in the OS credential store (Windows Credential Manager through `keyring`). The model key lives only in `.env`. Neither reaches the browser.

---

## Tech stack

- **Backend:** Python, FastAPI and SQLite (one process, 11 tables), with `pypdf` for documents, `httpx` for providers and `keyring` for tokens.
- **Frontend:** React, TypeScript and Vite with plain CSS and a small design-token scale. There is no UI framework.
- **Model (optional):** the OpenAI Responses API with strict JSON schemas and `store=false`.

There is no Redis, no vector database and no agent framework.

## Quick start

Requirements: **Python 3.11+** and **Node.js 20.19+** (or 22.12+).

```bash
git clone https://github.com/YichenLi-02/dss5105-track4.git
cd dss5105-track4
cp .env.example .env        # Windows: Copy-Item .env.example .env
```

**Windows (one command)** creates the virtual environment, installs dependencies, builds the frontend and starts the server:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run.ps1
```

**macOS / Linux:**

```bash
cd src/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cd ../frontend && npm ci && npm run build
cd ../backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **<http://127.0.0.1:8000>**.

> **About the sample data.** Development used 50 real mails, de-identified with fictional schools, courses, names and addresses. That sample is **not published**, because de-identified is not the same as anonymous. Without it the Mail page stays empty until you connect a mailbox. The built-in synthetic demos still work: the study-plan scenario, the course documents and the group chat.

### Development mode

```bash
# terminal 1
cd src/backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
# terminal 2 (Vite proxies /api to port 8000)
cd src/frontend && npm run dev     # http://127.0.0.1:5173
```

### Tests

```bash
cd src/backend && .venv/bin/python -m pytest -q    # uses a temporary database
cd src/frontend && npm run build                   # type-check and production build
```

Tests that need the private sample are skipped when it is absent. Provider and model paths are tested against mocked HTTP; no real account is contacted.

---

## Optional integrations

Every value goes in `.env`. A missing value only switches that feature off.

| Feature | Settings | Notes |
| --- | --- | --- |
| Smart classification and drafting | `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `ALLOW_MODEL_PROCESSING=true` | Also needs to be switched on in *Settings → Data processing*. Only the subject, the de-identified body and the time are sent. |
| Gmail and Google Calendar (read-only) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Create an OAuth client in Google Cloud with the redirect URI `http://127.0.0.1:8000/api/connections/google/callback`. Scopes: `gmail.readonly`, `calendar.events.freebusy`. |
| Outlook and Teams (read-only) | `MICROSOFT_CLIENT_ID`, `MICROSOFT_TENANT_ID` (plus a secret) | Scopes: `Mail.Read`, `Calendars.ReadBasic`, `Chat.Read`. School tenants may require admin consent. |
| Real sending | `APP_MODE=live`, `ENABLE_EXTERNAL_WRITES=true` | On start-up the server prints a one-time session code, which the browser asks for. Then enable *Allow real writes* in Settings and grant the send permission under *Account connections*. Gmail replies stay in the original thread. |

Without real sending, any draft can still be copied with one click and pasted into your own mail client.

## Project layout

```text
src/backend/app/
  api/         HTTP routes: messages, tasks, documents, drafts, plans, connections
  services/    import, tasks, planner and validator, documents, drafts, proposals, chat, importance
  providers/   outbound allow-list, OAuth (PKCE), token store, mail and calendar readers, writers
  llm/         model adapter (structured output only, no tools)
src/backend/tests/        pytest suite (54 tests)
src/frontend/src/
  pages/       Mail, Tasks, Study plan, Group work, To confirm, Sources & connections
  components/  side panel, mail detail, draft editor, review dialog, …
  locales/     en.json, zh-CN.json
docs/          implementation notes, run guide, UI audit
scripts/       run.ps1 (one-command start), smoke.py
```

## Known limitations

- Group-chat organising uses keyword rules; complex phrasing can be missed.
- PDFs are not OCR'd.
- Calendar writes only create new study blocks; existing events are never moved or deleted.
- The mail categories in the development sample came from AI-assisted reference labels that were not reviewed by hand, so no accuracy figure is claimed.

## More documentation

- [docs/RUNNING.md](docs/RUNNING.md): running, testing and configuration in detail
- [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md): what is implemented, where it differs from the original design contract, and what is still simulated
- [docs/UI_AUDIT.md](docs/UI_AUDIT.md): the interface audit against the vendored [`refactoring-ui`](.claude/skills/refactoring-ui) skill (MIT)
