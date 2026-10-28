# Implementation notes

The build follows the project's software design pack v1.1 (product brief, workflows, `openapi.json` and `database.sql`) and the implementation requirements set on 2026-10-19.

## Structure

```text
src/backend/app/
  main.py config.py db.py schema.sql security.py errors.py
  api/        core messages tasks documents drafts plans connections
  services/   import_service task_service reference_view document_service doc_rules
              style_service draft_service proposal_service planner plan_service chat_service
              analysis_service importance removal preferences privacy jobs
  providers/  net (outbound allow-list), tokens (keyring), oauth, mail_readers, calendars, teams, writers
  llm/        adapter (Responses API, strict JSON schema, no tool calls)
src/frontend/src/
  app/ (App, i18n, context, time)   api/ (client, types)   pages/ (six main areas + settings)
  components/ (Panel, MailDetail, DraftEditor, ReviewDialog, DocumentLibrary, StyleReferences,
               AccountConnections, Tags, ConfirmButton, CopyButton)
  locales/ zh-CN.json en.json   styles/ (tokens.css, prototype.css, app.css)
```

**Stack:**

- One FastAPI process with SQLite: 11 tables, taken from the design's `database.sql`.
- React, TypeScript and Vite with plain CSS.
- No Redis, vector database, microservices or agent framework.

## Implemented and working offline (no keys)

- **Sample import.**
  - Inbound mail and tone references are stored separately and de-duplicated by `(connection_id, provider_message_id)`, so re-importing adds nothing.
  - Reference categories are labelled `reference_annotation`, never shown as model output.
- **Mail.**
  - Count cards, topic categories, and the filters *needs reply*, *needs action* and *important* (combined filters intersect). There is also search.
  - Each mail shows its original text, its source, and evidence positions. User corrections are recorded as `user`.
  - Important mail is decided by a deterministic rule: academic or career mail that needs a reply or action, payments above a threshold, and account-security notices that need action. The user's override always wins.
- **Tasks.**
  - Date expressions are merged per `entity_key`. Each keeps its evidence, checked character by character against the source.
  - When dates conflict, every candidate is kept and the official date stays empty. An unstated time stays `null`.
  - A submission receipt only completes its own deliverable. Non-task times, such as code expiry or promotion end dates, never create tasks.
  - Confirming a task needs a date, a time and time zone (or a planning cut-off), and an effort estimate. Revision numbers stop a stale page from overwriting newer data.
  - Progress is recorded as idempotent events.
- **Course documents.**
  - Real PDF uploads are parsed page by page with `pypdf`, keeping page numbers.
  - Scanned, encrypted and broken files are marked `needs_ocr`, `encrypted` or `failed`, and the user can paste the text instead. Pasted text is a separate `user_pasted` source and is never presented as parsed PDF text.
  - Local rules extract explicit dates and times. Relative dates ("the Friday after reading week", "Week N") are resolved only against an academic calendar for the same term; the calendar itself never creates tasks.
  - Excluding a document sends related tasks back to review and marks dependent plans stale.
- **Study plan.**
  - Deterministic earliest-deadline-first planning.
  - An independent validator checks the daily cap, minimum and maximum session length, breaks, the deadline buffer, weekly flex time and the available windows.
  - `infeasible` is reported only when the capacity upper bound is already below demand; otherwise the status is `needs_adjustment`.
  - Logged progress reduces the remaining work and counts toward that day's cap.
  - Re-planning reports the differences and marks the old plan stale. A failed calendar read is never treated as free time.
- **Group work.**
  - A pasted chat is organised by rules into suggestions, decisions, action items and open questions.
  - Only an explicit decision statement, or an assignment acknowledged by its owner, counts as a decision. A suggestion that is later decided is marked *decided in Lxx*.
  - Unknown owners or dates stay `null`. A Teams follow-up can be drafted from the result.
- **Personal tone.**
  - Only text the user wrote is used. Each sample can be included or excluded; changing a sample invalidates pending proposals that relied on it.
  - Where no own sample exists (recruiting, Chinese), a generic tone is used and labelled as such.
- **Drafts and approval.**
  - Unverified facts always stay as `[[placeholders]]`.
  - A proposal stores an immutable payload, its SHA-256 hash, a revision, an expiry time and the session that created it.
  - Confirming requires the same hash and an `Idempotency-Key`; a single conditional UPDATE guarantees one execution. Any edit invalidates the earlier approval.
  - Offline, results are recorded as `simulated`. Drafts and simulated results can be copied with one click.
- **Security.**
  - The session cookie is HttpOnly and SameSite=Strict. Mutations require a CSRF token, and the Origin is checked against an allow-list.
  - Outbound requests may only go to fixed provider domains; Canvas and Instructure are always refused.
  - Addresses, links, phone numbers, one-time codes and long numbers are removed before storage.
- **Interface language.**
  - Switches between English and Chinese and is saved in preferences.
  - Model output (summaries, flags, task titles) is stored in both languages.
  - Mail, evidence, samples and user text keep their original language.

## Written and tested against mocked HTTP; real use needs your own OAuth app

- **Model adapter:** OpenAI Responses API with `store=false` and a strict schema. Source IDs, verbatim quotes and date formats are checked locally. Results are cached by content hash, prompt, schema and model version. When the model is off, the endpoint returns 409 and offline features are unaffected.
- **Google:** OAuth with PKCE and state, plus incremental consent. Gmail read-only sync with paging, bounded retries, `Retry-After`, and a single failing message counted as a partial result. Google free/busy.
- **Microsoft:** OAuth plus Graph mail, `calendarView`, and Teams chat reads (only the chats the user selects).
- **Real writers:** Gmail send (replies stay in the original thread through `threadId` and `In-Reply-To`/`References`), Graph `sendMail`, Teams chat messages, and a dedicated Google study calendar with its events.
  - A timeout is recorded as `unknown` and never retried automatically.
  - A 202 response is `accepted`, which does not mean delivered.
  - Event IDs are deterministic, and partial success is recorded item by item.
- **Use with a real account:** Gmail read-only sync, model analysis and Google free/busy have been used with a real test account. Real sending needs live mode and is off by default.

## Differences from the design contract (`openapi.json`)

| Place | Difference | Reason |
| --- | --- | --- |
| `GET /api/messages` | Adds `counts` to the response | Count cards need totals that ignore filters |
| MessageSummary | Adds `source_type`, `attention_label`, `uncertainty`, `analysis_status`, `excluded`, `attachment_count`, `split`, `summary_en`, `attention_flags_en` | Cards show review items, sources and both languages |
| `analysis_origin` | Adds `rule` | Local rule results must not be labelled `model` or `none` |
| Document upload | `POST /api/uploads` plus `POST /api/documents` (JSON metadata) instead of `/api/imports` | Metadata and the permission statement are validated together; `/api/imports` is only for the sample |
| Document | Adds `pages`, `page_count`, `user_excerpt`, `parsed_text`, `extraction_error`, `upload_id`, `synthetic`, `candidates` | Traceable page numbers; pasted and parsed text kept apart |
| `/documents/{id}/extract` | Returns synchronously; `use_model=true` returns 422 | Local rules are fast; model extraction of documents is out of scope |
| Draft | Adds `purpose`, `placeholders`, `style_mode`, `style_note`, `relationship`, `language`, `stale_style`, `generation`, `recipients_deidentified`; requests may pass `relationship`, `language`, `use_model` | Tone fallback and open placeholders need explicit state |
| Task | Adds `title_en` | Model-made titles are shown in the interface language |
| Plan | Adds `per_task`, `busy`, `days`, `stale_reasons`, `synthetic`, `computed_status` | The UI shows each day and why a plan went stale |
| ChatSummary | `analysis_origin` may be `rule`; adds `followup_points`, `messages`; requests may pass `raw_text` | Pasted text is parsed on the server |
| New endpoints | `/api/plans/latest`, `/api/demo/planning-scenario`, `/api/demo/documents`, `/api/demo/chat`, `/api/model/status`, `/api/translation-jobs`, `/api/messages/remove`, `/api/audit`, `/api/connections/microsoft/chats[/import]`, `/api/drafts` (list), `/api/tasks/{id}` | Synthetic demos, removal, background translation, Teams chat selection |
| Session | `bootstrap_code` may be omitted in demo mode | One-command start; live mode requires the code |

FastAPI generates the actual API description at `/docs` and `/openapi.json`.

## Still simulated or synthetic

- **Study plan inputs:** without a connected calendar, busy times come from a synthetic timetable (`provider=mock`). The demo report task is synthetic (DEMO5105, 2026-10-23 17:00).
- **Synthetic demos:** the syllabus, the academic calendar ("Demo Term A", not an official calendar) and the group chat.
- **Sends offline:** all sends and calendar writes are recorded as `simulated` unless live mode is enabled.
- **Reference labels:** the mail categories and date candidates in the development sample are AI-assisted reference labels, not reviewed by hand. They are not a gold standard, and no accuracy figure is reported.

## Known limitations

- Group-chat organising uses keyword rules, so complex Chinese or English phrasing can be missed. With the model enabled, only mail analysis and drafting use it; chat organising would need its own structured call.
- PDFs are not OCR'd.
- Calendar writes only create new study blocks; events are never moved or deleted.
- Asia/Singapore has no daylight saving time; DST edge cases are not tested.
