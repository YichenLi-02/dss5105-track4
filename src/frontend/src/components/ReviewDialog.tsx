// Final review of one proposal. Shows the payload the BACKEND stored (not a cached copy),
// confirms with revision + hash + Idempotency-Key, and reports the real outcome.
import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../api/client'
import type { Proposal } from '../api/types'
import { useApp } from '../app/context'
import { fmtDateTime, useI18n } from '../app/i18n'
import { uuid } from '../app/time'
import { CopyButton } from './CopyButton'
import { DraftEditor } from './DraftEditor'
import { StatusTag } from './Tags'

export function ReviewDialog({ id }: { id: string }) {
  const { t, locale } = useI18n()
  const app = useApp()
  const [p, setP] = useState<Proposal | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const idemKey = useMemo(() => uuid(), [id]) // reused on retry so a double click cannot execute twice

  useEffect(() => {
    get<Proposal>(`/api/proposals/${id}`).then(setP).catch((e) => setErr(e.message))
  }, [id])

  if (err && !p) return <div className="banner red">{err}</div>
  if (!p) return <p>{t('common.loading')}</p>
  const isPlan = p.source_kind === 'plan' || p.operation.startsWith('create_')
  const demo = p.mode === 'demo'
  const tz = p.payload.timezone || app.prefs?.display_timezone

  async function confirm() {
    setBusy(true)
    setErr(null)
    try {
      const r = await post<Proposal>(`/api/proposals/${p!.id}/confirm`, { expected_revision: p!.revision, payload_hash: p!.payload_hash },
        { 'Idempotency-Key': idemKey })
      setP(r)
      app.toast(t('review.outcome.' + r.status))
      app.bump()
    } catch (e: any) {
      setErr(t('review.error.' + e.code, {}) !== 'review.error.' + e.code ? t('review.error.' + e.code) : e.message)
      setP(await get<Proposal>(`/api/proposals/${p!.id}`))
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    setP(await post<Proposal>(`/api/proposals/${p!.id}/cancel`, { expected_revision: p!.revision }))
    app.bump()
  }

  return (
    <>
      <div className={`banner ${demo ? 'warning' : 'red'}`}>
        <b>{t(demo ? 'review.demo_banner_title' : 'review.live_banner_title')}</b><br />
        {t(demo ? 'review.demo_banner' : 'review.live_banner')}
      </div>
      <div className="row between"><h3>{t('op.' + p.operation)}</h3><StatusTag status={p.status} /></div>
      {p.operation === 'send_email' && (
        <dl className="kv">
          <dt>To</dt><dd>{p.payload.to?.join(', ') || '—'}</dd>
          <dt>Cc</dt><dd>{p.payload.cc?.join(', ') || '—'}</dd>
          <dt>Bcc</dt><dd>{p.payload.bcc?.join(', ') || '—'}</dd>
          <dt>{t('draft.subject')}</dt><dd>{p.payload.subject}</dd>
          <dt>{t('draft.attachments')}</dt>
          <dd>{p.payload.attachments?.length ? p.payload.attachments.map((a: any) => `${a.name} (${a.size_bytes} B, sha256 ${a.sha256.slice(0, 12)}…)`).join('; ') : t('common.none')}</dd>
        </dl>
      )}
      {p.operation === 'send_chat' && <dl className="kv"><dt>{t('review.chat')}</dt><dd>{p.payload.chat_id}</dd></dl>}
      {(p.operation === 'send_email' || p.operation === 'send_chat') && <pre>{p.payload.body}</pre>}
      {p.operation === 'create_study_events' && (
        <>
          <dl className="kv">
            <dt>{t('review.calendar')}</dt><dd>{p.payload.calendar} · {tz}</dd>
            <dt>{t('review.attendees')}</dt><dd>{t('review.no_attendees')}</dd>
          </dl>
          {p.payload.events.map((ev: any, i: number) => (
            <div key={i} className="event study">
              <b>{fmtDateTime(locale, ev.start, tz)} – {fmtDateTime(locale, ev.end, tz).slice(-5)}</b>
              <span>{ev.title} · {t('review.new_event')}</span>
            </div>
          ))}
        </>
      )}
      {p.operation === 'create_study_calendar' && <dl className="kv"><dt>{t('review.calendar')}</dt><dd>{p.payload.summary} · {p.payload.timezone}</dd></dl>}
      {p.blocking_fields.length > 0 && (
        <div className="banner red" role="alert"><b>{t('review.blocked')}</b><ul>{p.blocking_fields.map((b) => <li key={b}>{t('block.' + b.split(':')[0])}{b.includes(':') ? ` — ${b.split(':').slice(1).join(':')}` : ''}</li>)}</ul></div>
      )}
      {p.status === 'invalidated' && <div className="banner red">{t('review.invalidated')} {p.result?.reason ? `(${t('reason.' + p.result.reason)})` : ''}</div>}
      {p.result && p.status !== 'invalidated' && (
        <div className={`banner ${p.status === 'simulated' || p.status === 'executed' ? 'green' : 'warning'}`} aria-live="polite">
          {t('review.outcome.' + p.status)}
          {p.status === 'simulated' && (p.operation === 'send_email' || p.operation === 'send_chat') && (
            <div className="row" style={{ marginTop: 8 }}>
              <CopyButton primary text={p.payload.body || ''} label={t('copy.body')} />
              {p.operation === 'send_email' && <CopyButton text={p.payload.subject || ''} label={t('copy.subject')} />}
              <small>{t('copy.after_simulated')}</small>
            </div>
          )}
        </div>
      )}
      <p className="footnote">
        {p.id} · {t('review.source_revision')} {p.source_revision}<br />
        {t('review.hash')} {p.payload_hash}<br />
        {t('review.expires')} {fmtDateTime(locale, p.expires_at)}
      </p>
      {err && <div className="banner red" role="alert">{err}</div>}
      <div className="panel-actions">
        <button className="primary" onClick={confirm} disabled={busy || p.status !== 'pending_review'}>
          {t(demo ? (isPlan ? 'review.confirm_demo_save' : 'review.confirm_demo_send') : (isPlan ? 'review.confirm_live_save' : 'review.confirm_live_send'))}
        </button>
        {p.source_kind === 'draft' && (
          <button onClick={() => app.openPanel(t('draft.title'), () => <DraftEditor draftId={p.source_object_id} />)}>{t('review.back_to_edit')}</button>
        )}
        <button onClick={cancel} disabled={!['pending_review', 'blocked'].includes(p.status)}>{t('review.cancel')}</button>
      </div>
    </>
  )
}
