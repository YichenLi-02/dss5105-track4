import { useEffect, useMemo, useState } from 'react'
import { ConfirmButton } from '../components/ConfirmButton'
import { get, post, waitJob } from '../api/client'
import type { MessageSummary } from '../api/types'
import { useApp } from '../app/context'
import { fmtDate, mailSummary, pick, useI18n } from '../app/i18n'
import { MailDetail, SourceDetail } from '../components/MailDetail'
import { DraftEditor } from '../components/DraftEditor'
import { OriginTag } from '../components/Tags'
import { SettingsPanel } from './SettingsPanel'

type Counts = Record<string, number>
const CATS = ['academic', 'career', 'events', 'promotions', 'other'] as const

export function MailPage() {
  const { t } = useI18n()
  const app = useApp()
  const [items, setItems] = useState<MessageSummary[] | null>(null)
  const [counts, setCounts] = useState<Counts>({})
  const [outboundCount, setOutboundCount] = useState(0)
  const [category, setCategory] = useState('all')
  const [reply, setReply] = useState(false)
  const [action, setAction] = useState(false)
  const [important, setImportant] = useState(false)
  const [q, setQ] = useState('')
  const [job, setJob] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    get('/api/messages?limit=500', ctl.signal)
      .then((r) => { setItems(r.items); setCounts(r.counts) })
      .catch((e) => { if (e.name !== 'AbortError') setError(e.message) })
    get('/api/messages?direction=outbound&limit=1', ctl.signal).then((r) => setOutboundCount(r.total)).catch(() => undefined)
    return () => ctl.abort()
  }, [app.dataVersion])

  const shown = useMemo(() => {
    if (!items) return []
    const needle = q.trim().toLowerCase()
    return items.filter((m) =>
      (category === 'all' || (m.category ?? 'uncategorized') === category) &&
      (!reply || m.needs_reply === true) && (!action || m.needs_action === true) && (!important || m.important) &&
      (!needle || `${m.subject} ${m.summary} ${m.source_id} ${m.sender_label}`.toLowerCase().includes(needle)))
  }, [items, category, reply, action, important, q])

  async function refresh() {
    setError(null)
    try {
      const conns = await get('/api/connections')
      const real = conns.items.find((c: any) => c.provider !== 'local_jsonl' && c.status === 'connected' && c.capabilities?.read_mail)
      const j = real
        ? await post('/api/sync-jobs', { connection_id: real.id, lookback_days: 7, max_messages: 50, include_spam_trash: false })
        : await post('/api/imports', { source: 'selected_50', upload_id: null })
      setJob(j)
      const done = await waitJob(j.id, setJob)
      setJob(done)
      if (done.status === 'completed' || done.status === 'partial') {
        app.toast(real
          ? ((done.result?.created ?? 0) === 0 && !done.failed_count
            ? t('mail.sync_uptodate', { checked: (done.result?.fetched ?? 0) + (done.result?.already_had ?? 0) })
            : t('mail.sync_done', { created: done.result?.created ?? 0, fetched: (done.result?.fetched ?? 0) + (done.result?.already_had ?? 0), failed: done.failed_count }))
          : t('mail.refresh_done', { created: done.result?.messages_created ?? 0 }))
      } else app.toast(t('mail.refresh_failed') + (done.errors?.length ? ' · ' + done.errors.slice(-1)[0] : ''))
      app.bump()
    } catch (e: any) {
      setError(e.message)
      setJob(null)
    }
  }

  const [model, setModel] = useState<{ enabled: boolean; reasons: string[]; model: string | null } | null>(null)
  const [aJob, setAJob] = useState<any>(null)
  useEffect(() => {
    get('/api/model/status').then(setModel).catch(() => undefined)
  }, [app.dataVersion, app.prefs?.revision])
  const unanalysed = (items || []).filter((m) => m.analysis_origin === 'none')

  async function analyse() {
    setError(null)
    try {
      const j = await post('/api/analysis-jobs', { message_ids: unanalysed.map((m) => m.id), force: false })
      setAJob(j)
      const done = await waitJob(j.id, setAJob)
      setAJob(done)
      app.toast(t('mail.analysis_done', { ok: done.result?.analysed ?? 0, failed: done.failed_count, cached: done.result?.cached ?? 0 }))
      app.bump()
    } catch (e: any) {
      setError(e.code === 'MODEL_PROCESSING_UNAVAILABLE' ? t('mail.model_unavailable') + ' ' + e.details.map((d: string) => t('model.' + d)).join('；') : e.message)
      setAJob(null)
    }
  }
  const aRunning = aJob && ['queued', 'running'].includes(aJob.status)

  const filtered = category !== 'all' || reply || action || important || !!q.trim()
  async function removeShown() {
    const r = await post('/api/messages/remove', { message_ids: shown.map((m) => m.id) })
    app.toast(t('mail.removed', { n: r.removed, tasks: r.tasks_deleted }))
    app.bump()
  }

  const running = job && ['queued', 'running'].includes(job.status)
  const statCards = [
    { key: 'all', n: counts.all ?? 0 },
    { key: 'important', n: counts.important ?? 0, alert: true },
    ...CATS.slice(0, 4).map((c) => ({ key: c, n: counts[c] ?? 0 })),
  ]
  const clear = () => { setCategory('all'); setReply(false); setAction(false); setImportant(false); setQ('') }

  return (
    <section aria-labelledby="mail-h">
      <h1 id="mail-h" className="sr-only">{t('nav.mail')}</h1>
      <div className="stats">
        {statCards.map((s) => (
          <button key={s.key} className={`stat ${s.alert ? 'alert' : ''}`}
            aria-pressed={s.key === 'important' ? important : category === s.key}
            onClick={() => (s.key === 'important' ? setImportant(!important) : setCategory(s.key))}>
            <strong>{s.n}</strong>
            <span>{t('cat.' + s.key)}</span>
          </button>
        ))}
      </div>

      <div className="statusbar" role="status">
        <span className="dot" style={{ color: 'var(--accent)' }} aria-hidden="true" />
        <span>
          {running
            ? t(job.kind === 'sync' ? 'mail.job_syncing' : 'mail.job_running', { processed: job.processed, total: job.total ?? '?' })
            : items && items.length
              ? t('mail.loaded', { inbound: counts.all ?? 0, outbound: outboundCount })
              : t('mail.not_loaded')}
        </span>
        {job?.status === 'failed' && <span className="tag red">{t('mail.refresh_failed')}</span>}
        <span className="spacer" />
        <button onClick={refresh} disabled={!!running}>{t(running ? 'mail.refreshing' : 'mail.refresh')}</button>
      </div>
      {error && <div className="banner red" role="alert">{error}</div>}
      {unanalysed.length > 0 && (
        <div className={`banner ${model?.enabled ? '' : 'warning'}`} role="status">
          <div className="row between">
            <span>
              {t('mail.unanalysed', { n: unanalysed.length })}
              {!model?.enabled && t('mail.model_off_hint')}
              {aJob && <> · {t('mail.analysis_progress', { n: aJob.processed, total: aJob.total ?? unanalysed.length, failed: aJob.failed_count })}</>}
            </span>
            {model?.enabled
              ? <button className="primary" onClick={analyse} disabled={!!aRunning}
                  title={t('mail.model_ready_hint', { model: model.model || '' })}>{t(aRunning ? 'mail.analysing' : 'mail.analyse_btn')}</button>
              : <button onClick={() => app.openPanel(t('settings.title'), () => <SettingsPanel />)}>{t('mail.model_setup')}</button>}
          </div>
          {aJob?.errors?.length > 0 && <small className="footnote">{aJob.errors.slice(-3).join(' · ')}</small>}
        </div>
      )}

      <div className="filters" role="group" aria-label={t('mail.category_filter')}>
        {['all', ...CATS, ...(counts.uncategorized ? ['uncategorized'] : [])].map((c) => (
          <button key={c} className={`pill ${category === c ? 'active' : ''}`} aria-pressed={category === c} onClick={() => setCategory(c)}>
            {t('cat.' + c)} {counts[c] ?? 0}
          </button>
        ))}
      </div>
      <div className="searchrow">
        <input className="search" type="search" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder={t('mail.search_placeholder')} aria-label={t('mail.search_placeholder')} />
        <div className="filters" role="group" aria-label={t('mail.need_filter')}>
          <button className={`pill ${reply ? 'active' : ''}`} aria-pressed={reply} onClick={() => setReply(!reply)}>{t('flag.needs_reply')}</button>
          <button className={`pill ${action ? 'active' : ''}`} aria-pressed={action} onClick={() => setAction(!action)}>{t('flag.needs_action')}</button>
          <button className={`pill ${important ? 'active' : ''}`} aria-pressed={important} onClick={() => setImportant(!important)}>{t('flag.important_only')}</button>
        </div>
        <span className="result-count">{t('mail.showing', { shown: shown.length, total: items?.length ?? 0 })}</span>
        {filtered && shown.length > 0 && <ConfirmButton className="link" label={t('mail.remove_shown', { n: shown.length })}
          message={t('mail.remove_confirm_many', { n: shown.length })} confirmLabel={t('mail.remove_confirm_btn')} onConfirm={removeShown} />}
      </div>

      {items === null ? (
        <div className="empty"><p>{t('common.loading')}</p></div>
      ) : items.length === 0 ? (
        <div className="empty">
          <h3>{t('mail.empty_title')}</h3>
          <p>{t('mail.empty_body')}</p>
          <div className="row" style={{ justifyContent: 'center' }}>
            <button className="primary" onClick={refresh} disabled={!!running}>{t('mail.import_samples')}</button>
            <button onClick={() => app.go('sources/connections')}>{t('mail.connect_readonly')}</button>
          </div>
        </div>
      ) : shown.length === 0 ? (
        <div className="empty"><h3>{t('mail.no_match')}</h3><button onClick={clear}>{t('mail.clear_filters')}</button></div>
      ) : (
        <div className="mail-list">{shown.map((m) => <MailCard key={m.id} m={m} />)}</div>
      )}
      <p className="footnote">{t('mail.footnote')}</p>
    </section>
  )
}

function MailCard({ m }: { m: MessageSummary }) {
  const { t, locale } = useI18n()
  const app = useApp()
  // The backend decides (model flag, or a keyword fallback for older analyses); the UI does not guess.
  const security = m.account_security || m.attention_label === '安全提醒'
  const attention = security || m.attention_label === '日期待核对' || m.attention_flags.includes('date_conflict')
  const why = m.important_reason ? t('imp.' + m.important_reason, m.important_params || {}) : ''
  const openMail = () => app.openPanel(m.subject, () => <MailDetail id={m.id} />)
  const openSource = () => app.openPanel(t('mail.source_title', { id: m.source_id }), () => <SourceDetail id={m.id} />)
  const openDraft = () => app.openPanel(t('draft.title'), () => <DraftEditor create={{ source_message_id: m.id, purpose: 'reply', channel: 'email' }} />)
  const remove = async () => {
    const r = await post('/api/messages/remove', { message_ids: [m.id] })
    app.toast(t('mail.removed', { n: r.removed, tasks: r.tasks_deleted }))
    app.bump()
  }
  return (
    <article className={`mail-card ${attention ? 'attention' : m.important ? 'important' : ''}`}>
      <div className="mail-head">
        <span className={`tag ${m.category ?? ''}`}>{t('cat.' + (m.category ?? 'uncategorized'))}</span>
        {m.attention_label && <span className={`tag ${attention ? 'red' : 'warn'}`}>{pick(locale, labelFor(m.attention_label, t), m.attention_label_en)}</span>}
        {m.important && <span className="tag ink" title={why}>{t('flag.important')} · {why}</span>}
        {m.needs_reply && <span className="tag green">{t('flag.needs_reply')}</span>}
        {m.needs_action && <span className="tag warn">{t('flag.needs_action')}</span>}
        {m.ignore && <span className="tag">{t('flag.ignore')}</span>}
        <span className="mail-subject">{m.subject}</span>
        <span className="mail-meta">{m.is_demo && <span>{m.source_id}</span>}<span>{fmtDate(m.sent_at)}</span></span>
      </div>
      <p className="summary">{mailSummary(locale, m)}</p>
      {m.uncertainty && (m.needs_action || m.needs_reply || attention) && (
        <div className="action-line">{t('mail.to_check')}: {pick(locale, m.uncertainty, m.uncertainty_en)}</div>
      )}
      <div className="mail-footer">
        <button className="link" onClick={openMail}>{t('mail.view')}</button>
        <button className="link" onClick={openSource}>{t('mail.view_source')}</button>
        <ConfirmButton className="link link-muted" label={t('mail.remove')} message={t('mail.remove_confirm_short')}
          confirmLabel={t('mail.remove_confirm_btn')} onConfirm={remove} />
        {m.needs_reply && <button className="link" onClick={openDraft}>{t('mail.draft_reply')}</button>}
        <span style={{ marginLeft: 'auto' }}><OriginTag origin={m.analysis_origin} /></span>
      </div>
    </article>
  )
}

// Attention labels in the reference view are stored in Chinese; map known ones to interface keys.
function labelFor(label: string, t: (k: string) => string): string {
  const known: Record<string, string> = { '安全提醒': 'flag.security', '日期待核对': 'flag.date_check', '信息不足': 'flag.incomplete' }
  return known[label] ? t(known[label]) : label
}
