import { useEffect, useState } from 'react'
import { get, post } from '../api/client'
import { useApp } from '../app/context'
import { useI18n } from '../app/i18n'
import { DraftEditor } from '../components/DraftEditor'

type Item = { source_id: string; speaker: string | null; timestamp: string | null; quote: string; owner?: string | null;
  due_text?: string | null; acknowledged_by_owner?: boolean; kind?: string; basis?: string; reason?: string; status?: string; decision_source_id?: string }

export function CollaborationPage() {
  const { t } = useI18n()
  const app = useApp()
  const [raw, setRaw] = useState('')
  const [synthetic, setSynthetic] = useState(false)
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [teams, setTeams] = useState<{ connected: boolean; chats: { id: string; topic: string }[] | null }>({ connected: false, chats: null })

  useEffect(() => {
    get('/api/connections').then((r) => {
      const ms = r.items.find((c: any) => c.provider === 'microsoft')
      setTeams({ connected: !!ms?.capabilities?.read_chat, chats: null })
    }).catch(() => undefined)
  }, [])

  async function loadDemo() {
    const d = await get('/api/demo/chat')
    setRaw(d.raw_text)
    setSynthetic(true)
  }

  async function summarize() {
    setErr(null)
    try {
      setRes(await post('/api/chat-summaries', { raw_text: raw, synthetic }))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function listChats() {
    try {
      setTeams({ ...teams, chats: await get('/api/connections/microsoft/chats') })
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function importChat(id: string) {
    try {
      setRes(await post('/api/connections/microsoft/chats/import', { chat_id: id }))
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const followup = () => app.openPanel(t('draft.title'), () => (
    <DraftEditor create={{ source_message_id: res.id, purpose: 'followup', channel: 'teams', language: res.language,
      verified_facts: { summary_points: res.followup_points, ...(res.chat_id ? { chat_id: res.chat_id } : {}) } }} />
  ))

  const Section = ({ k, items, tag }: { k: string; items: Item[]; tag: string }) => (
    <div className="box">
      <h2>{t('collab.' + k)} <span className="tag">{items.length}</span></h2>
      {items.length === 0 ? <p className="footnote">{t('collab.none')}</p> : items.map((x, i) => (
        <div key={i} className="decision">
          <span className={`tag ${tag}`}>{t('collab.tag_' + k)}</span>{' '}
          <b>{x.speaker ?? '?'}</b> {x.timestamp && <small>[{x.timestamp}]</small>} <small>{x.source_id}</small>
          <div className="source-quote">{x.quote}</div>
          {k === 'actions' && (
            <small>{t('collab.owner')}: {x.owner ?? t('collab.unknown')} · {t('collab.due')}: {x.due_text ?? t('collab.unknown')} · {t(x.acknowledged_by_owner ? 'collab.acked' : 'collab.not_acked')}</small>
          )}
          {k === 'decisions' && x.basis && <small>{t('collab.basis')}: {t(x.basis.startsWith('assigned_by') ? 'collab.basis_assignment' : 'collab.basis_explicit')}</small>}
          {k === 'suggestions' && <small>{x.status === 'addressed_by_decision' ? t('collab.addressed', { id: x.decision_source_id || '' }) : t('collab.not_decided')}</small>}
          {k === 'questions' && x.reason && <small>{t('collab.reason.' + x.reason)}</small>}
        </div>
      ))}
    </div>
  )

  return (
    <section>
      <div className="section-head">
        <div>
          <div className="page-label">COLLABORATION</div>
          <h1>{t('collab.title')}</h1>
          <p className="description">{t('collab.description')}</p>
        </div>
      </div>
      <div className="box">
        <div className="field">
          <label htmlFor="chat-raw">{t('collab.paste')}</label>
          <textarea id="chat-raw" rows={8} value={raw} onChange={(e) => { setRaw(e.target.value); setSynthetic(false) }} placeholder={t('collab.paste_ph')} />
          <small>{t('collab.format')}</small>
        </div>
        <div className="row">
          <button className="primary" onClick={summarize} disabled={!raw.trim()}>{t('collab.summarize')}</button>
          {app.prefs?.show_demo_data_effective && <button onClick={loadDemo}>{t('collab.load_demo')}</button>}
        </div>
      </div>
      <div className="banner channel-entry">
        {t('collab.teams_entry')}{' '}
        {teams.connected ? (
          <button className="link" onClick={listChats}>{t('collab.list_chats')}</button>
        ) : (
          <button className="link" onClick={() => app.go('sources/connections')}>{t('collab.connect_teams')}</button>
        )}
        {teams.chats && teams.chats.map((c) => <button key={c.id} className="pill" onClick={() => importChat(c.id)}>{c.topic}</button>)}
      </div>
      {err && <div className="banner red" role="alert">{err}</div>}
      {res && (
        <div aria-live="polite">
          <div className="banner">{t('collab.rule_note')}{res.synthetic ? ' · ' + t('common.synthetic') : ''}</div>
          <div className="grid2">
            <Section k="suggestions" items={res.suggestions} tag="warn" />
            <Section k="decisions" items={res.confirmed_decisions} tag="green" />
            <Section k="actions" items={res.action_items} tag="" />
            <Section k="questions" items={res.open_questions} tag="" />
          </div>
          <div className="row"><button className="primary" onClick={followup}>{t('collab.followup')}</button></div>
          <p className="footnote">{t('collab.footnote')}</p>
        </div>
      )}
    </section>
  )
}
