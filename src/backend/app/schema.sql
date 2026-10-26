-- Student Work Assistant SQLite schema (from design database.sql v1.1, 11 tables).
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  provider TEXT NOT NULL CHECK(provider IN ('local_jsonl','google','microsoft')),
  account_label TEXT NOT NULL,
  scopes_json TEXT NOT NULL DEFAULT '[]',
  credential_ref TEXT,
  cursor_json TEXT NOT NULL DEFAULT '{}',
  capabilities_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'disconnected',
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES connections(id),
  provider_message_id TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'email' CHECK(source_type IN ('email','chat','uploaded_pdf','academic_calendar')),
  source_id TEXT NOT NULL,
  thread_id TEXT,
  direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound','document')),
  subject TEXT NOT NULL DEFAULT '',
  sender_json TEXT NOT NULL DEFAULT '{}',
  recipients_json TEXT NOT NULL DEFAULT '{}',
  sent_at TEXT,
  source_timezone TEXT,
  body_view TEXT NOT NULL DEFAULT '',
  body_hash TEXT NOT NULL,
  locator_json TEXT NOT NULL DEFAULT '{}',
  attachments_json TEXT NOT NULL DEFAULT '[]',
  analysis_status TEXT NOT NULL DEFAULT 'pending',
  analysis_origin TEXT NOT NULL DEFAULT 'none' CHECK(analysis_origin IN ('none','reference_annotation','rule','model','user')),
  analysis_json TEXT,
  analysis_cache_key TEXT,
  excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0,1)),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(connection_id,provider_message_id)
);
CREATE INDEX IF NOT EXISTS ix_messages_source ON messages(source_id);
CREATE INDEX IF NOT EXISTS ix_messages_connection_date ON messages(connection_id,sent_at);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  parent_task_id TEXT REFERENCES tasks(id),
  entity_key TEXT NOT NULL,
  title TEXT NOT NULL,
  title_en TEXT,
  course TEXT,
  term TEXT,
  deliverable TEXT,
  required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0,1)),
  status TEXT NOT NULL CHECK(status IN ('candidate','needs_review','confirmed','in_progress','completed','ignored')),
  official_date TEXT,
  official_time TEXT,
  source_timezone TEXT,
  deadline_status TEXT NOT NULL DEFAULT 'missing',
  date_candidates_json TEXT NOT NULL DEFAULT '[]',
  user_planning_cutoff TEXT,
  planning_cutoff_utc TEXT,
  estimated_minutes INTEGER CHECK(estimated_minutes IS NULL OR estimated_minutes >= 0),
  completed_minutes INTEGER NOT NULL DEFAULT 0 CHECK(completed_minutes >= 0),
  progress_json TEXT NOT NULL DEFAULT '[]',
  missing_fields_json TEXT NOT NULL DEFAULT '[]',
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_entity ON tasks(entity_key);

CREATE TABLE IF NOT EXISTS task_evidence (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  message_id TEXT NOT NULL REFERENCES messages(id),
  field_name TEXT NOT NULL DEFAULT 'body_view',
  quote TEXT NOT NULL,
  start_char INTEGER,
  end_char INTEGER,
  relation TEXT NOT NULL DEFAULT 'supports',
  locator_json TEXT NOT NULL DEFAULT '{}',
  field_changes_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  CHECK(start_char IS NULL OR start_char >= 0),
  CHECK(end_char IS NULL OR (start_char IS NOT NULL AND end_char >= start_char))
);

CREATE TABLE IF NOT EXISTS calendar_snapshots (
  id TEXT PRIMARY KEY,
  connection_id TEXT REFERENCES connections(id),
  provider TEXT NOT NULL,
  source_version TEXT NOT NULL,
  display_timezone TEXT NOT NULL,
  time_min TEXT NOT NULL,
  time_max TEXT NOT NULL,
  selected_calendars_json TEXT NOT NULL DEFAULT '[]',
  busy_json TEXT NOT NULL DEFAULT '[]',
  errors_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK(status IN ('complete','partial','failed','expired')),
  fetched_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
  owner_id TEXT PRIMARY KEY DEFAULT 'local_user',
  value_json TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  previous_plan_id TEXT REFERENCES plans(id),
  snapshot_id TEXT REFERENCES calendar_snapshots(id),
  inputs_json TEXT NOT NULL,
  sessions_json TEXT NOT NULL DEFAULT '[]',
  reserved_flex_json TEXT NOT NULL DEFAULT '[]',
  changes_json TEXT NOT NULL DEFAULT '[]',
  validation_json TEXT NOT NULL DEFAULT '{}',
  unmet_minutes INTEGER NOT NULL DEFAULT 0 CHECK(unmet_minutes >= 0),
  status TEXT NOT NULL CHECK(status IN ('feasible','infeasible','needs_information','needs_adjustment','stale')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  source_message_id TEXT REFERENCES messages(id),
  purpose TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'email' CHECK(channel IN ('email','teams')),
  connection_id TEXT REFERENCES connections(id),
  recipients_json TEXT NOT NULL DEFAULT '{}',
  subject TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL,
  attachments_json TEXT NOT NULL DEFAULT '[]',
  verified_facts_json TEXT NOT NULL DEFAULT '{}',
  style_reference_ids_json TEXT NOT NULL DEFAULT '[]',
  missing_fields_json TEXT NOT NULL DEFAULT '[]',
  ready_for_review INTEGER NOT NULL DEFAULT 0 CHECK(ready_for_review IN (0,1)),
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  session_id_hash TEXT NOT NULL,
  operation TEXT NOT NULL CHECK(operation IN ('send_email','send_chat','create_study_calendar','create_study_events')),
  mode TEXT NOT NULL CHECK(mode IN ('demo','live')),
  connection_id TEXT REFERENCES connections(id),
  source_kind TEXT NOT NULL CHECK(source_kind IN ('draft','plan','connection')),
  source_object_id TEXT NOT NULL,
  source_revision INTEGER NOT NULL,
  dependencies_json TEXT NOT NULL DEFAULT '{}',
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
  nonce_hash TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('blocked','pending_review','executing','executed','accepted','unknown','failed','cancelled','invalidated','expired','simulated')),
  idempotency_key TEXT UNIQUE,
  execution_operation_id TEXT UNIQUE,
  approved_at TEXT,
  consumed_at TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_proposals_owner_status ON proposals(owner_id,status);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  connection_id TEXT REFERENCES connections(id),
  kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued','running','completed','partial','failed','cancelled','interrupted')),
  input_json TEXT NOT NULL,
  checkpoint_json TEXT NOT NULL DEFAULT '{}',
  total INTEGER,
  processed INTEGER NOT NULL DEFAULT 0 CHECK(processed >= 0),
  failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
  cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
  errors_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT 'local_user',
  event_type TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT,
  request_id TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
-- Audit summary must not include raw bodies, keys, OAuth tokens or full MIME.
PRAGMA user_version = 1;
