// Account connections: real OAuth only when configured on the server; otherwise "not configured".
// Read-only capabilities first; write capabilities are separate, extra and still need per-action review.
import { useEffect, useState } from 'react'
import { ConfirmButton } from './ConfirmButton'
import { get, post, waitJob } from '../api/client'
import { useApp } from '../app/context'
import { useI18n } from '../app/i18n'
import { ReviewDialog } from './ReviewDialog'

const READ = { google: ['read_mail', 'read_busy'], microsoft: ['read_mail', 'read_busy', 'read_chat'] } as const
const WRITE = { google: ['send_mail', 'study_calendar'], microsoft: ['send_mail', 'send_chat', 'study_calendar'] } as const

export function AccountConnections() {
  const { t } = useI18n()
  const app = useApp()
  const [conns, setConns] = useState<any[] | null>(null)
  const [model, setModel] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sync, setSync] = useState({ days: 7, max: 50, spam: false })
  const [job, setJob] = useState<any>(null)

  const reload = () => Promise.all([get('/api/connections').then((r) => setConns(r.items)), get('/api/model/status').then(setModel)])
    .catch((e) => setErr(e.message))
  useEffect(() => { reload() }, [app.dataVersion])

  async function authorize(provider: string, capability: string) {
    setErr(null)
    try {
      const r = await post(`/api/connections/${provider}/authorize`, { capability })
      window.location.assign(r.authorization_url) // provider consent screen; the token stays on the server
    } catch (e: any) {
      setErr(t('conn.error.' + e.code) !== 'conn.error.' + e.code ? t('conn.error.' + e.code) : e.message)
    }
  }

  async function disconnect(id: string) {
    await post(`/api/connections/${id}/disconnect`)
    reload(); app.bump()
  }

  async function runSync(id: string) {
    setErr(null)
    try {
      const j = await post('/api/sync-jobs', { connection_id: id, lookback_days: sync.days, max_messages: sync.max, include_spam_trash: sync.spam })
      setJob(await waitJob(j.id, setJob))
      app.bump()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function createCalendar() {
    const c = conns!.find((x) => x.id === 'conn_google')
    const p = await post('/api/proposals', { source_kind: 'connection', source_object_id: 'conn_google', expected_source_revision: c.revision,
      mode: app.health?.mode === 'live' ? 'live' : 'demo' })
    app.openPanel(t('review.title'), () => <ReviewDialog id={p.id} />)
  }

  if (!conns) return <p>{err || t('common.loading')}</p>
  const local = conns.filter((c) => c.provider === 'local_jsonl')
  return (
    <>
      <div className="banner">{t('conn.banner')}</div>
      {err && <div className="banner red" role="alert">{err}</div>}
      <div className="grid2">
        {conns.filter((c) => c.provider !== 'local_jsonl').map((c) => (
          <div key={c.id} className="box">
            <div className="row between">
              <h2>{c.provider === 'google' ? 'Google (Gmail · Calendar)' : 'Microsoft (Outlook · Calendar · Teams)'}</h2>
              <span className={`tag ${c.status === 'connected' ? 'green' : ['denied', 'needs_admin', 'expired', 'error'].includes(c.status) ? 'red' : 'warn'}`}>{t('conn.status.' + c.status)}</span>
            </div>
            <p className="footnote">{t('conn.status_hint.' + c.status)}{c.account_label ? ` · ${c.account_label}` : ''}{c.last_error ? ` · ${c.last_error}` : ''}</p>
            <h3>{t('conn.read_caps')}</h3>
            <div className="row">
              {READ[c.provider as 'google' | 'microsoft'].map((cap) => (
                <button key={cap} disabled={c.status === 'not_configured' || c.capabilities[cap]} onClick={() => authorize(c.provider, cap)}>
                  {c.capabilities[cap] ? '✓ ' : ''}{t('cap.' + cap)}
                </button>
              ))}
            </div>
            <details className="permission-details">
              <summary>{t('conn.write_caps')}</summary>
              <p className="footnote">{t('conn.write_hint')}</p>
              <div className="row">
                {WRITE[c.provider as 'google' | 'microsoft'].map((cap) => (
                  <button key={cap} disabled={c.status === 'not_configured' || c.capabilities[cap]} onClick={() => authorize(c.provider, cap)}>
                    {c.capabilities[cap] ? '✓ ' : ''}{t('cap.' + cap)}
                  </button>
                ))}
                {c.provider === 'google' && c.capabilities.study_calendar && <button onClick={createCalendar}>{t('conn.create_calendar')}</button>}
              </div>
            </details>
            {c.capabilities.read_mail && (
              <div className="box" style={{ marginTop: 12 }}>
                <h3>{t('conn.sync')}</h3>
                <div className="fields">
                  <div className="field"><label htmlFor={c.id + '-days'}>{t('conn.lookback')}</label>
                    <select id={c.id + '-days'} value={sync.days} onChange={(e) => setSync({ ...sync, days: Number(e.target.value) })}>
                      {[7, 14, 30].map((d) => <option key={d} value={d}>{t('conn.days', { n: d })}</option>)}</select></div>
                  <div className="field"><label htmlFor={c.id + '-max'}>{t('conn.max')}</label>
                    <input id={c.id + '-max'} type="number" min={1} max={500} value={sync.max} onChange={(e) => setSync({ ...sync, max: Number(e.target.value) })} /></div>
                </div>
                <label className="checkline"><input type="checkbox" checked={sync.spam} onChange={(e) => setSync({ ...sync, spam: e.target.checked })} />{t('conn.include_spam')}</label>
                <button className="primary" onClick={() => runSync(c.id)} disabled={job && ['queued', 'running'].includes(job.status)}>{t('conn.sync_now')}</button>
                {job && <p className="footnote">{t('conn.job', { status: t('status.' + job.status), n: job.processed, failed: job.failed_count })}</p>}
              </div>
            )}
            {c.status !== 'not_configured' && c.status !== 'disconnected' && <ConfirmButton label={t('conn.disconnect')} message={t('conn.disconnect_confirm')} onConfirm={() => disconnect(c.id)} />}
          </div>
        ))}
      </div>
      <div className="grid2">
        <div className="box">
          <h2>{t('conn.local')}</h2>
          {local.map((c) => <div key={c.id} className="decision">{t('conn.label.' + c.id) !== 'conn.label.' + c.id ? t('conn.label.' + c.id) : c.account_label} <span className="tag green">{t('conn.status.' + c.status)}</span></div>)}
          <p className="footnote">{t('conn.local_note')}</p>
        </div>
        <div className="box">
          <h2>{t('conn.model')}</h2>
          {model && (
            <>
              <span className={`tag ${model.enabled ? 'green' : 'warn'}`}>{t(model.enabled ? 'conn.model_on' : 'conn.model_off')}</span>
              {model.reasons.length > 0 && <ul className="footnote">{model.reasons.map((r: string) => <li key={r}>{t('model.' + r)}</li>)}</ul>}
              <p className="footnote">{t('conn.model_data')}</p>
            </>
          )}
        </div>
      </div>
    </>
  )
}
