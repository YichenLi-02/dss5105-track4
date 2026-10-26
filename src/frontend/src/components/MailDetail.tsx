import { useEffect, useState } from 'react'
import { ConfirmButton } from './ConfirmButton'
import { get, patch, post, waitJob } from '../api/client'
import type { MessageDetail } from '../api/types'
import { useApp } from '../app/context'
import { fmtDateTime, mailSummary, pick, useI18n } from '../app/i18n'
import { DraftEditor } from './DraftEditor'
import { OriginTag, StatusTag } from './Tags'

// Flags follow the UI language: known codes use the interface dictionary, model notes their English copy.
function flagLabels(a: Record<string, any>, locale: string, t: (k: string) => string): string[] {
  const en: string[] = a.attention_flags_en || []
  return (a.attention_flags as string[]).map((f, i) => {
    if (/^[a-z_]+$/.test(f)) return t('mflag.' + f) !== 'mflag.' + f ? t('mflag.' + f) : f.replace(/_/g, ' ')
    return locale === 'en' && en[i] ? en[i] : f
  })
}

// Plain-text body only - never inject provider HTML.
// Display-only tidy-up (stored text and evidence offsets are untouched): drop CRs and stray leading spaces,
// and undo 'blank line after every line' exports so the measure reads as prose.
function tidyBody(s: string): string {
  const lines = s.replace(/\r/g, '').split('\n').map((l) => l.replace(/^ (?=\S)/, ''))
  const text = lines.join('\n')
  const nonEmpty = lines.filter((l) => l.trim()).length
  const doubled = (text.match(/\S\n\n(?=\S)/g) || []).length
  return (nonEmpty > 4 && doubled / nonEmpty > 0.6 ? text.replace(/\n\n(?=\S)/g, '\n') : text).replace(/\n{3,}/g, '\n\n').trim()
}
function useMessage(id: string) {
  const [m, setM] = useState<MessageDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    const ctl = new AbortController()
    get<MessageDetail>(`/api/messages/${id}`, ctl.signal).then(setM).catch((e) => e.name !== 'AbortError' && setErr(e.message))
    return () => ctl.abort()
  }, [id])
  return { m, setM, err }
}

export function MailDetail({ id }: { id: string }) {
  const { t, locale } = useI18n()
  const app = useApp()
  const { m, setM, err } = useMessage(id)
  const [form, setForm] = useState<{ category: string; needs_reply: boolean; needs_action: boolean; important: boolean } | null>(null)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [analysing, setAnalysing] = useState(false)

  useEffect(() => {
    if (m) setForm({ category: m.category ?? 'other', needs_reply: !!m.needs_reply, needs_action: !!m.needs_action, important: m.important })
  }, [m])

  if (err) return <div className="banner red">{err}</div>
  if (!m || !form) return <p>{t('common.loading')}</p>

  async function save() {
    setSaveErr(null)
    try {
      const updated = await patch<MessageDetail>(`/api/messages/${id}/analysis`, { expected_revision: m!.revision, ...form })
      setM({ ...updated, linked_tasks: m!.linked_tasks })
      app.toast(t('mail.correction_saved'))
      app.bump()
    } catch (e: any) {
      setSaveErr(e.code === 'REVISION_CONFLICT' ? t('common.revision_conflict') : e.message)
    }
  }

  async function analyseOne() {
    setSaveErr(null)
    setAnalysing(true)
    try {
      const j = await post('/api/analysis-jobs', { message_ids: [m!.id], force: m!.analysis_origin === 'model' })
      const done = await waitJob(j.id)
      if (done.failed_count) setSaveErr(t('mail.analysis_failed_one') + ' ' + done.errors.join(' · '))
      setM({ ...(await get<MessageDetail>(`/api/messages/${id}`)) })
      app.bump()
    } catch (e: any) {
      setSaveErr(e.code === 'MODEL_PROCESSING_UNAVAILABLE' ? t('mail.model_unavailable') + ' ' + e.details.map((d: string) => t('model.' + d)).join('；') : e.message)
    } finally {
      setAnalysing(false)
    }
  }

  async function newTask() {
    const quote = window.getSelection()?.toString().trim() || null
    const task = await post('/api/tasks', { title: m!.subject.slice(0, 120), source_id: m!.id, evidence_quote: quote })
    app.toast(t('mail.task_created', { title: task.title }))
    app.bump()
  }

  return (
    <>
      <dl className="kv">
        <dt>{t('mail.from')}</dt><dd>{m.sender_label}</dd>
        <dt>{t('mail.to')}</dt><dd>{(m.recipients.to || []).join(', ')}</dd>
        <dt>{t('mail.date')}</dt><dd title={m.sent_at || ''}>{fmtDateTime(locale, m.sent_at, app.prefs?.display_timezone)} · {app.prefs?.display_timezone}</dd>
        {m.is_demo && <><dt>{t('mail.sample')}</dt><dd>{m.source_id} · {m.split}</dd></>}
        <dt>{t('mail.attachments')}</dt>
        <dd>{m.attachments.length ? m.attachments.map((a) => a.name).join(', ') + ' · ' + t('mail.attachments_not_read') : t('common.none')}</dd>
      </dl>
      {m.provenance.source_capture_capped && <div className="banner warning">{t('mail.body_incomplete')}</div>}
      <div className="row between"><h3>{t('mail.original')}</h3><OpenOriginal url={m.source?.open_url} kind={m.source?.kind} /></div>
      <div className="mail-body">{tidyBody(m.body_view)}</div>

      <h3 style={{ marginTop: 20 }}>{t('mail.analysis')} <OriginTag origin={m.analysis_origin} /></h3>
      {m.analysis && (
        <div className="banner">
          <div><b>{t('mail.summary')}:</b> {mailSummary(locale, { ...m, summary: m.analysis.summary })}</div>
          {m.analysis.uncertainty && <div><b>{t('mail.to_check')}:</b> {pick(locale, m.analysis.uncertainty, m.uncertainty_en)}</div>}
          {m.analysis.expected_behavior && <div><b>{t('mail.expected')}:</b> {pick(locale, m.analysis.expected_behavior, m.expected_en)}</div>}
          {m.analysis.attention_flags?.length > 0 && <div><b>{t('mail.flags')}:</b> {flagLabels(m.analysis, locale, t).join(locale === 'en' ? '; ' : '；')}</div>}
        </div>
      )}
      <div className="fields">
        <div className="field">
          <label htmlFor="cat-sel">{t('mail.category')}</label>
          <select id="cat-sel" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
            {['academic', 'career', 'events', 'promotions', 'other'].map((c) => <option key={c} value={c}>{t('cat.' + c)}</option>)}
          </select>
        </div>
      </div>
      {(['needs_reply', 'needs_action', 'important'] as const).map((k) => (
        <label key={k} className="checkline">
          <input type="checkbox" checked={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.checked })} />
          {t('flag.' + k)}
        </label>
      ))}
      <p className="footnote">{t('mail.ignore_note')}</p>
      {saveErr && <div className="banner red" role="alert">{saveErr}</div>}
      <div className="panel-actions">
        <button className="primary" onClick={save}>{t('mail.save_correction')}</button>
        <button onClick={() => app.openPanel(t('draft.title'), () => <DraftEditor create={{ source_message_id: m.id, purpose: 'reply', channel: 'email' }} />)}>{t('mail.draft_reply')}</button>
        <button onClick={newTask}>{t('mail.new_task')}</button>
        <ConfirmButton label={t('mail.remove')} message={t('mail.remove_confirm_short')} confirmLabel={t('mail.remove_confirm_btn')}
          onConfirm={async () => {
            const r = await post('/api/messages/remove', { message_ids: [m.id] })
            app.toast(t('mail.removed', { n: r.removed, tasks: r.tasks_deleted }))
            app.bump()
            app.closePanel()
          }} />
        {m.direction === 'inbound' && (
          <button onClick={analyseOne} disabled={analysing}>{t(analysing ? 'mail.analysing' : (m.analysis_origin === 'model' ? 'mail.reanalyse_one' : 'mail.analyse_one'))}</button>
        )}
      </div>
      {m.linked_tasks.length > 0 && (
        <>
          <h3 style={{ marginTop: 20 }}>{t('mail.linked_tasks')}</h3>
          {m.linked_tasks.map((lt) => (
            <div key={lt.id + lt.relation} className="decision">{pick(locale, lt.title, (lt as any).title_en)} <StatusTag status={lt.status} /> <span className="tag">{t('relation.' + lt.relation)}</span></div>
          ))}
        </>
      )}
    </>
  )
}

function OpenOriginal({ url, kind }: { url: string | null | undefined; kind?: string }) {
  const { t } = useI18n()
  if (!url) return null
  return (
    <a className="button-link" href={url} target="_blank" rel="noopener noreferrer">
      {t(kind === 'microsoft' ? 'source.open_outlook' : 'source.open_gmail')} ↗
    </a>
  )
}

export function SourceDetail({ id }: { id: string }) {
  const { t } = useI18n()
  const { m, err } = useMessage(id)
  if (err) return <div className="banner red">{err}</div>
  if (!m) return <p>{t('common.loading')}</p>
  const hint = m.analysis?.evidence_hint as string | undefined
  const idx = hint ? m.body_view.indexOf(hint) : -1
  const p = m.provenance
  const s = m.source
  if (s && s.kind !== 'sample') {
    return (
      <>
        <div className="banner">{t('source.real_explain')}</div>
        <dl className="kv">
          <dt>{t('source.account')}</dt><dd>{s.account || '—'}</dd>
          <dt>{t('source.provider')}</dt><dd>{s.kind === 'google' ? 'Gmail' : 'Outlook'}</dd>
          <dt>{t('source.message_id')}</dt><dd>{s.provider_message_id}</dd>
          <dt>{t('source.received')}</dt><dd>{s.received_at}</dd>
          <dt>{t('source.stored_as')}</dt><dd>{t('source.stored_as_value')}</dd>
        </dl>
        <div className="panel-actions"><OpenOriginal url={s.open_url} kind={s.kind} /></div>
        <p className="footnote">{t('source.links_note')}</p>
      </>
    )
  }
  return (
    <>
      <div className="banner">{t('source.explain')}</div>
      <dl className="kv">
        <dt>{t('source.dataset')}</dt><dd>{p.dataset}</dd>
        <dt>{t('source.sample')}</dt><dd>{p.sample_id} · {p.split} · {p.case_group}</dd>
        <dt>{t('source.ordinal')}</dt><dd>{p.original_mbox_ordinal_1based}</dd>
        <dt>{t('source.view')}</dt><dd>{p.provenance?.body_view}</dd>
        <dt>{t('source.offsets')}</dt><dd>{p.provenance?.source_offset_bytes} / {p.provenance?.source_message_length_bytes} bytes</dd>
        <dt>{t('source.context')}</dt><dd>{p.evaluation_context?.mode} · {p.evaluation_context?.reference_datetime}</dd>
        <dt>{t('source.labels')}</dt><dd>{m.analysis?.annotation_status || m.analysis_origin}</dd>
      </dl>
      <h3>{t('source.evidence')}</h3>
      {hint ? (
        <>
          <blockquote>{hint}</blockquote>
          <p className="footnote">{idx >= 0 ? t('source.quote_found', { start: idx, end: idx + hint.length }) : t('source.quote_not_found')}</p>
        </>
      ) : <p className="footnote">{t('source.no_evidence')}</p>}
      <p className="footnote">{t('source.no_links')}</p>
    </>
  )
}
