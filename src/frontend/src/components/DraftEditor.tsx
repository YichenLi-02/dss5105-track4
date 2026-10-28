// Local draft editing. Unknown facts stay as [[placeholders]]; "Review" is disabled until every
// placeholder and recipient is filled. Saving never sends; sending needs a separate final review.
import { useEffect, useRef, useState } from 'react'
import { ConfirmButton } from './ConfirmButton'
import { CopyButton } from './CopyButton'
import { get, patch, post } from '../api/client'
import type { Draft, DocumentRec } from '../api/types'
import { useApp } from '../app/context'
import { useI18n } from '../app/i18n'
import { ReviewDialog } from './ReviewDialog'

type Create = {
  source_message_id: string | null
  purpose: 'reply' | 'extension' | 'followup'
  channel: 'email' | 'teams'
  verified_facts?: Record<string, any>
  relationship?: string
  language?: string
}

const FACT_FIELDS: Record<string, string[]> = {
  extension: ['task_title', 'reason', 'requested_new_date', 'recipient_name', 'signature'],
  reply: ['reply_points', 'recipient_name', 'signature'],
  followup: ['recipient_name', 'signature'],
}

export function DraftEditor({ create, draftId }: { create?: Create; draftId?: string }) {
  const { t } = useI18n()
  const app = useApp()
  const [d, setD] = useState<Draft | null>(null)
  const [form, setForm] = useState({ to: '', cc: '', bcc: '', subject: '', body: '', attachment_ids: [] as string[] })
  const [facts, setFacts] = useState<Record<string, string>>({})
  const [relationship, setRelationship] = useState(create?.relationship || '')
  const [language, setLanguage] = useState(create?.language || 'en')
  const [err, setErr] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [docs, setDocs] = useState<DocumentRec[]>([])
  const [modelOn, setModelOn] = useState(false)
  const [openUrl, setOpenUrl] = useState<string | null>(null)
  const started = useRef(false)

  function load(x: Draft) {
    setD(x)
    setForm({ to: x.to.join(', '), cc: x.cc.join(', '), bcc: x.bcc.join(', '), subject: x.subject, body: x.body,
      attachment_ids: x.attachments.map((a) => a.id) })
    setFacts(Object.fromEntries(Object.entries(x.verified_facts).map(([k, v]) => [k, Array.isArray(v) ? v.join('\n') : String(v)])))
    setRelationship(x.relationship)
    setLanguage(x.language)
    setDirty(false)
  }

  async function generate(c: Create, useModel = false) {
    setErr(null)
    try {
      load(await post<Draft>('/api/drafts', { attachment_ids: [], verified_facts: {}, ...c, use_model: useModel }))
      app.bump()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  useEffect(() => {
    if (started.current) return
    started.current = true
    if (draftId) get<Draft>(`/api/drafts/${draftId}`).then(load).catch((e) => setErr(e.message))
    else if (create) generate(create)
    get<DocumentRec[]>('/api/documents').then(setDocs).catch(() => undefined)
    get('/api/model/status').then((s) => setModelOn(s.enabled)).catch(() => undefined)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Link back to the original mail in Gmail/Outlook, so a copied reply can be pasted there by hand.
  useEffect(() => {
    if (!d?.source_message_id || d.channel !== 'email') return
    get(`/api/messages/${d.source_message_id}`).then((m) => setOpenUrl(m.source?.open_url || null)).catch(() => undefined)
  }, [d?.source_message_id, d?.channel])

  if (err && !d) return <div className="banner red">{err}</div>
  if (!d) return <p>{t('common.loading')}</p>

  const split = (s: string) => s.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean)
  const placeholdersNow = Array.from(new Set((form.subject + '\n' + form.body).match(/\[\[[^\]\n]{1,120}\]\]/g) || []))

  // Live, from what is on screen now (not from the last save), mirroring the server's draft check.
  const fieldsNow = d.channel !== 'email' ? [] : [
    ...(split(form.to).length ? [] : ['recipients']),
    ...(form.subject.trim() ? [] : ['subject']),
  ]
  const readyNow = placeholdersNow.length === 0 && fieldsNow.length === 0

  async function save(extra: Record<string, any> = {}): Promise<Draft | null> {
    setErr(null)
    try {
      const factsOut = Object.fromEntries(Object.entries(facts).filter(([, v]) => v.trim()).map(([k, v]) => [k, k === 'summary_points' ? split(v) : v.trim()]))
      const x = await patch<Draft>(`/api/drafts/${d!.id}`, {
        expected_revision: d!.revision, to: split(form.to), cc: split(form.cc), bcc: split(form.bcc),
        subject: form.subject, body: form.body, attachment_ids: form.attachment_ids, verified_facts: factsOut, ...extra,
      })
      load(x)
      app.bump()
      return x
    } catch (e: any) {
      setErr(e.code === 'REVISION_CONFLICT' ? t('common.revision_conflict') : e.message)
      return null
    }
  }

  async function review(mode: 'demo' | 'live') {
    const x = dirty ? await save() : d
    if (!x) return
    try {
      const p = await post('/api/proposals', { source_kind: 'draft', source_object_id: x.id, expected_source_revision: x.revision, mode })
      app.bump()
      app.openPanel(t('review.title'), () => <ReviewDialog id={p.id} />)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  function regenerate(useModel = false) {
    const f = Object.fromEntries(Object.entries(facts).filter(([, v]) => v.trim()).map(([k, v]) => [k, k === 'summary_points' ? split(v) : v.trim()]))
    generate({ source_message_id: d!.source_message_id, purpose: d!.purpose as Create['purpose'], channel: d!.channel,
      verified_facts: { ...d!.verified_facts, ...f }, relationship, language }, useModel)
  }

  const up = (k: keyof typeof form, v: any) => { setForm({ ...form, [k]: v }); setDirty(true) }
  const attachable = docs.filter((x) => x.upload_id && !x.excluded)

  return (
    <>
      <div className={`banner ${d.style_mode === 'personal' ? 'green' : 'warning'}`}>
        <b>{t(d.style_mode === 'personal' ? 'draft.style_personal' : 'draft.style_generic')}</b>
        {' · '}{t('draft.style_note.' + (d.style_note || 'none'))}
        {d.style_reference_ids.length > 0 && <> · {t('draft.style_refs', { n: d.style_reference_ids.length })}</>}
        <br />{t(d.generation === 'model' ? 'draft.generated_model' : 'draft.generated_template')}
      </div>
      {d.stale_style && (
        <div className="banner red" role="alert">
          {t('draft.style_changed')}{' '}
          <button className="link" onClick={() => save({ acknowledge_style_change: true })}>{t('draft.style_ack')}</button>
        </div>
      )}
      <div className="fields">
        <div className="field">
          <label htmlFor="d-rel">{t('draft.relationship')}</label>
          <select id="d-rel" value={relationship} onChange={(e) => setRelationship(e.target.value)}>
            {['professor', 'admin', 'peer', 'recruiter', 'correction'].map((r) => <option key={r} value={r}>{t('rel.' + r)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="d-lang">{t('draft.language')}</label>
          <select id="d-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option><option value="zh">中文</option>
          </select>
        </div>
      </div>
      <h3>{t('draft.facts')}</h3>
      <p className="footnote">{t('draft.facts_hint')}</p>
      {(FACT_FIELDS[d.purpose] || []).map((k) => (
        <div className="field" key={k}>
          <label htmlFor={'f-' + k}>{t('fact.' + k)}</label>
          {k === 'reason' || k === 'reply_points'
            ? <textarea id={'f-' + k} rows={3} value={facts[k] || ''} placeholder={t('fact.' + k + '_ph')} onChange={(e) => setFacts({ ...facts, [k]: e.target.value })} />
            : <input id={'f-' + k} value={facts[k] || ''} onChange={(e) => setFacts({ ...facts, [k]: e.target.value })} />}
        </div>
      ))}
      <div className="row">
        <ConfirmButton label={t('draft.regenerate')} message={t('draft.regenerate_confirm')} skip={!dirty} onConfirm={() => regenerate(false)} />
        {modelOn && <ConfirmButton label={t('draft.regenerate_model')} message={t('draft.regenerate_confirm')} skip={!dirty} onConfirm={() => regenerate(true)} />}
      </div>

      <h3 style={{ marginTop: 20 }}>{t('draft.content')}</h3>
      {d.channel === 'email' && (
        <>
          {(['to', 'cc', 'bcc'] as const).map((k) => (
            <div className="field" key={k}>
              <label htmlFor={'d-' + k}>{k.toUpperCase()}</label>
              <input id={'d-' + k} value={form[k]} onChange={(e) => up(k, e.target.value)} placeholder={k === 'to' ? t('draft.to_ph') : ''} />
            </div>
          ))}
          {d.recipients_deidentified && <p className="footnote">{t('draft.deidentified')}</p>}
          <div className="field">
            <label htmlFor="d-subj">{t('draft.subject')}</label>
            <input id="d-subj" value={form.subject} onChange={(e) => up('subject', e.target.value)} />
          </div>
        </>
      )}
      <div className="field">
        <label htmlFor="d-body">{t('draft.body')}</label>
        <textarea id="d-body" rows={12} value={form.body} onChange={(e) => up('body', e.target.value)} />
      </div>
      <div className="field">
      <div className="row">
        <CopyButton text={form.body} label={t('copy.body')} />
        {d.channel === 'email' && <CopyButton text={form.subject} label={t('copy.subject')} />}
        {openUrl && <a className="button-link" href={openUrl} target="_blank" rel="noopener noreferrer">{t('copy.open_original')} ↗</a>}
      </div>
      <small>{t(placeholdersNow.length ? 'copy.hint_placeholders' : 'copy.hint')}</small>
      </div>
      {d.channel === 'email' && (
        <div className="field">
          <label>{t('draft.attachments')}</label>
          {attachable.length === 0 ? <small>{t('draft.no_attachable')}</small> : attachable.map((x) => (
            <label key={x.upload_id} className="checkline">
              <input type="checkbox" checked={form.attachment_ids.includes(x.upload_id!)}
                onChange={(e) => up('attachment_ids', e.target.checked ? [...form.attachment_ids, x.upload_id!] : form.attachment_ids.filter((i) => i !== x.upload_id))} />
              {x.filename} ({Math.round(x.size_bytes / 1024)} KB)
            </label>
          ))}
          <small>{t('draft.attachments_hint')}</small>
        </div>
      )}
      {!readyNow && (
        <div className="banner warning">
          <b>{t('draft.missing')}</b>
          <ul>
            {placeholdersNow.map((p) => <li key={p}>{p}</li>)}
            {fieldsNow.map((m) => <li key={m}>{t('missing.' + m)}</li>)}
          </ul>
        </div>
      )}
      {err && <div className="banner red" role="alert">{err}</div>}
      <div className="panel-actions">
        <button onClick={() => save()} disabled={!dirty}>{t('draft.save')}</button>
        <button className="primary" onClick={() => review('demo')} disabled={!readyNow}>
          {t('draft.review_demo')}
        </button>
        {app.health?.mode === 'live' && <button onClick={() => review('live')} disabled={!readyNow}>{t('draft.review_live')}</button>}
      </div>
      <p className="footnote">{t('draft.footnote')}</p>
    </>
  )
}
