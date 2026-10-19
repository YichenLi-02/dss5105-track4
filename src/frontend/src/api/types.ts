// Mirrors the backend contract (see docs/IMPLEMENTATION.md for deviations from the design openapi.json).

export type Category = 'academic' | 'career' | 'events' | 'promotions' | 'other'
export type Origin = 'none' | 'reference_annotation' | 'rule' | 'model' | 'user'

export interface MessageSummary {
  id: string
  source_id: string
  direction: 'inbound' | 'outbound' | 'document'
  source_type: string
  subject: string
  sent_at: string | null
  sender_label: string
  category: Category | null
  summary: string
  needs_reply: boolean | null
  needs_action: boolean | null
  ignore: boolean | null
  important: boolean
  is_demo: boolean
  mail_language: 'en' | 'zh'
  account_security: boolean
  important_reason: string | null
  important_params: Record<string, string> | null
  attention_flags: string[]
  attention_label: string | null
  attention_label_en: string | null
  summary_en: string | null
  uncertainty_en: string | null
  uncertainty: string
  analysis_origin: Origin
  analysis_status: string
  excluded: boolean
  revision: number
  attachment_count: number
  split: string | null
}

export interface MessageDetail extends MessageSummary {
  body_view: string
  source_timezone: string | null
  recipients: { to?: string[] }
  attachments: { name: string; content_read: boolean }[]
  provenance: Record<string, any>
  analysis: Record<string, any> | null
  linked_tasks: { id: string; title: string; status: string; relation: string }[]
  expected_en: string | null
  source: { kind: string; provider_message_id: string; thread_id: string | null; received_at: string | null;
    account: string | null; open_url: string | null }
}

export interface Evidence {
  id: string
  source_id: string
  message_id: string
  source_type: string
  subject: string
  sent_at: string | null
  field: string
  quote: string
  start_char: number | null
  end_char: number | null
  relation: string
  locator: Record<string, any>
  field_changes: Record<string, any>
  source_excluded: boolean
}

export interface Task {
  id: string
  entity_key: string
  title: string
  title_en: string | null
  course: string | null
  term: string | null
  deliverable: string | null
  required: boolean
  status: 'candidate' | 'needs_review' | 'confirmed' | 'in_progress' | 'completed' | 'ignored'
  official_date: string | null
  official_time: string | null
  source_timezone: string | null
  deadline_status: string
  date_candidates: Record<string, any>[]
  user_planning_cutoff: string | null
  planning_cutoff_utc: string | null
  estimated_minutes: number | null
  completed_minutes: number
  progress: { client_event_id: string; minutes: number; occurred_at: string }[]
  missing_fields: string[]
  can_confirm: boolean
  evidence: Evidence[]
  revision: number
}

export interface Draft {
  id: string
  channel: 'email' | 'teams'
  purpose: string
  source_message_id: string | null
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  attachments: { id: string; name: string; size_bytes: number; sha256: string }[]
  style_reference_ids: string[]
  style_mode: string
  style_note: string
  missing_fields: string[]
  placeholders: string[]
  verified_facts: Record<string, any>
  ready_for_review: boolean
  revision: number
  requires_confirmation: boolean
  relationship: string
  language: string
  stale_style: boolean
  generation: "template" | "model"
  recipients_deidentified: boolean
}

export interface Proposal {
  id: string
  mode: 'demo' | 'live'
  operation: 'send_email' | 'send_chat' | 'create_study_calendar' | 'create_study_events'
  status: string
  source_kind: 'draft' | 'plan' | 'connection'
  source_object_id: string
  source_revision: number
  revision: number
  payload_hash: string
  payload: Record<string, any>
  expires_at: string
  blocking_fields: string[]
  result: Record<string, any> | null
  created_at: string
}

export interface SessionBlock {
  task_id: string
  task_title: string
  phase: string
  start: string
  end: string
  minutes: number
  kept?: boolean
}

export interface Plan {
  id: string
  status: 'feasible' | 'infeasible' | 'needs_information' | 'needs_adjustment' | 'stale'
  revision: number
  sessions: SessionBlock[]
  reserved_flex: { start: string; end: string; kind: string; source_id: string }[]
  unmet_minutes: number
  capacity_upper_bound_minutes: number | null
  demand_minutes: number
  missing_fields: string[]
  binding_constraints: string[]
  changes: Record<string, any>[]
  violations: string[]
  inputs: Record<string, any>
  per_task: { task_id: string; title: string; remaining: number; planned: number; unmet: number; cutoff: string | null }[]
  busy: { start: string; end: string; kind: string; source_id: string; label?: string; label_key?: string }[]
  days: { date: string; planned: number; completed: number; cap: number }[]
  stale_reasons: string[]
  previous_plan_id: string | null
  synthetic: boolean
}

export interface DocumentRec {
  id: string
  source_message_id: string
  kind: 'syllabus' | 'academic_calendar' | 'assignment_brief'
  title: string
  title_en: string | null
  course: string | null
  term: string
  source_timezone: string
  filename: string | null
  upload_id: string | null
  size_bytes: number
  page: number | null
  excerpt: string
  excerpt_origin: 'none' | 'parsed_pdf' | 'user_pasted'
  extraction_status: string
  extraction_error: string | null
  pages: { page: number; chars: number }[]
  page_count: number
  user_excerpt: string
  user_excerpt_page: number | null
  parsed_text: string
  excluded: boolean
  synthetic: boolean
  revision: number
  candidates: Task[]
}
