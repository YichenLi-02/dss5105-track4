import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../api/client'
import type { Plan, Task } from '../api/types'
import { useApp } from '../app/context'
import { pick, useI18n } from '../app/i18n'
import { nowIso, partsIn, uuid, zonedToIso } from '../app/time'
import { DraftEditor } from '../components/DraftEditor'
import { ReviewDialog } from '../components/ReviewDialog'
import { StatusTag } from '../components/Tags'
import { SettingsPanel } from './SettingsPanel'

const SYNTH_START = '2026-10-19T08:00'
const SYNTH_DAYS = 5

export function PlanPage() {
  const { t, locale } = useI18n()
  const app = useApp()
  const tz = app.prefs?.display_timezone || 'Asia/Singapore'
  const [tasks, setTasks] = useState<Task[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [provider, setProvider] = useState<'mock' | 'google' | 'microsoft'>('mock')
  const [start, setStart] = useState(SYNTH_START)
  const [days, setDays] = useState(SYNTH_DAYS)
  const [effort, setEffort] = useState(360)
  const [busy, setBusy] = useState(false)
  const [calendarConnected, setCalendarConnected] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    get('/api/tasks?status=confirmed,in_progress').then((r) => {
      setTasks(r.items)
      setSelected((s) => (s.length ? s.filter((id) => r.items.some((x: Task) => x.id === id)) : r.items.map((x: Task) => x.id)))
    })
    get<Plan | null>('/api/plans/latest').then(setPlan).catch(() => undefined)
    get('/api/connections').then((r) => {
      const cal = r.items.find((c: any) => c.status === 'connected' && c.capabilities?.read_busy)
      setCalendarConnected(cal ? cal.provider : null)
      if (cal) setProvider(cal.provider)
    }).catch(() => undefined)
  }, [app.dataVersion])

  const synthetic = tasks.find((x) => x.entity_key === 'synthetic_demo5105_report')
  // Demo controls only while demo data is shown; with a real mailbox the plan starts from now.
  const demo = !!app.prefs?.show_demo_data_effective
  useEffect(() => {
    if (app.prefs && !demo) {
      const n = new Date(Date.now() + 3600000)
      setStart(partsIn(n.toISOString(), tz).date + 'T' + partsIn(n.toISOString(), tz).time.slice(0, 2) + ':00')
      setDays(7)
    }
  }, [demo, app.prefs, tz])

  async function loadScenario(minutes: number) {
    setEffort(minutes)
    const task = await post<Task>('/api/demo/planning-scenario', { effort_minutes: minutes })
    setSelected([task.id])
    setProvider('mock'); setStart(SYNTH_START); setDays(SYNTH_DAYS)
    app.bump()
    app.toast(t('plan.scenario_loaded', { h: minutes / 60 }))
  }

  async function snapshot() {
    const t0 = zonedToIso(start, tz)
    const end = new Date(new Date(t0).getTime() + days * 86400000)
    const t1 = zonedToIso(partsIn(end.toISOString(), tz).date + 'T00:00', tz)
    return post('/api/calendar/snapshots', { provider, connection_id: provider === 'mock' ? null : 'conn_' + provider, time_min: t0, time_max: t1,
      calendar_ids: provider === 'google' ? ['primary'] : [], display_timezone: tz })
  }

  async function generate(replan = false) {
    setBusy(true); setErr(null)
    try {
      await app.reloadPrefs()
      const prefs = await get('/api/preferences')
      const snap = await snapshot()
      if (snap.status !== 'complete') app.toast(t('plan.snapshot_failed'))
      const p = replan && plan
        ? await post<Plan>(`/api/plans/${plan.id}/replan`, { expected_revision: plan.revision, snapshot_id: snap.id, preferences_revision: prefs.revision })
        : await post<Plan>('/api/plans/preview', { task_ids: selected, snapshot_id: snap.id, preferences_revision: prefs.revision })
      setPlan(p)
      app.toast(t('plan.generated'))
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function addProgress() {
    const task = tasks.find((x) => selected.includes(x.id))
    if (!task) return
    // Synthetic scenario: progress is logged at the start of the synthetic week, real tasks use "now".
    const at = task.entity_key.startsWith('synthetic') ? zonedToIso(SYNTH_START.replace('08:00', '09:30'), tz) : nowIso()
    await post(`/api/tasks/${task.id}/progress`, { expected_revision: task.revision, client_event_id: uuid(), minutes: 30, occurred_at: at })
    app.bump()
    app.toast(t('plan.progress_logged'))
  }

  async function review() {
    try {
      const p = await post('/api/proposals', { source_kind: 'plan', source_object_id: plan!.id, expected_source_revision: plan!.revision, mode: 'demo' })
      app.bump()
      app.openPanel(t('review.title'), () => <ReviewDialog id={p.id} />)
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const dayList = useMemo(() => {
    if (!plan) return []
    return plan.days.map((d) => ({
      ...d,
      busy: plan.busy.filter((b) => partsIn(b.start, tz).date === d.date),
      sessions: plan.sessions.filter((s) => partsIn(s.start, tz).date === d.date),
      flex: plan.reserved_flex.filter((f) => partsIn(f.start, tz).date === d.date),
    }))
  }, [plan, tz])
  const hm = (iso: string) => partsIn(iso, tz).time
  const titleOf = (id: string, fallback: string) => { const x = tasks.find((k) => k.id === id); return x ? pick(locale, x.title, x.title_en) : fallback }
  const weekday = (date: string) => new Intl.DateTimeFormat(locale, { weekday: 'short', month: 'numeric', day: 'numeric', timeZone: 'UTC' }).format(new Date(date + 'T12:00:00Z'))
  const totalCompleted = synthetic?.completed_minutes ?? 0

  return (
    <section>
      <div className="section-head">
        <div>
          <div className="page-label">WEEKLY PLAN</div>
          <h1>{t('plan.title')}</h1>
          <p className="description">{t('plan.description', { tz })}</p>
        </div>
        <button onClick={() => app.openPanel(t('settings.title'), () => <SettingsPanel />)}>{t('plan.adjust_prefs')}</button>
      </div>
      {demo && <div className="banner">{t('plan.synthetic_banner')}</div>}

      <div className="box">
        <div className="fields">
          {demo && <div className="field">
            <label htmlFor="p-eff">{t('plan.synthetic_effort')}</label>
            <select id="p-eff" value={effort} onChange={(e) => loadScenario(Number(e.target.value))}>
              <option value={360}>{t('plan.effort_6')}</option>
              <option value={1080}>{t('plan.effort_18')}</option>
            </select>
            <small>{synthetic ? t('plan.scenario_active', { n: synthetic.estimated_minutes ?? 0, done: totalCompleted }) : t('plan.scenario_hint')}</small>
          </div>}
          <div className="field">
            <label htmlFor="p-start">{t('plan.start')}</label>
            <input id="p-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="p-days">{t('plan.days')}</label>
            <input id="p-days" type="number" min={1} max={14} value={days} onChange={(e) => setDays(Number(e.target.value))} />
          </div>
        </div>
        <fieldset className="field" style={{ border: 0, padding: 0 }}>
          <legend style={{ fontSize: 12, fontWeight: 600, marginBottom: 7 }}>{t('plan.tasks')}</legend>
          {tasks.length === 0 ? (
            <small>{t('plan.no_confirmed')} {demo
              ? <button className="link" onClick={() => loadScenario(360)}>{t('plan.load_scenario')}</button>
              : <button className="link" onClick={() => app.go('tasks')}>{t('plan.confirm_tasks_first')}</button>}</small>
          ) : tasks.map((x) => (
            <label key={x.id} className="checkline" style={{ margin: '4px 0' }}>
              <input type="checkbox" checked={selected.includes(x.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, x.id] : selected.filter((i) => i !== x.id))} />
              {pick(locale, x.title, x.title_en)} · {x.official_date ?? x.user_planning_cutoff?.slice(0, 16)} {x.official_time ?? ''} · {t('task.remaining', { n: Math.max(0, (x.estimated_minutes ?? 0) - x.completed_minutes) })}
            </label>
          ))}
        </fieldset>
        <div className="row">
          <button className="primary" onClick={() => generate(false)} disabled={busy || selected.length === 0}>{t('plan.generate')}</button>
          {selected.length === 0 && <small className="footnote" style={{ margin: 0 }}>{t(tasks.length ? 'plan.why_disabled_select' : 'plan.why_disabled_none')}</small>}
          <button onClick={addProgress} disabled={!selected.length}>{t('plan.add_progress')}</button>
          {plan && <button onClick={() => generate(true)} disabled={busy}>{t('plan.replan')}</button>}
        </div>
      </div>

      <div className="banner channel-entry">
        {t('plan.calendar_source')}:{' '}
        <select aria-label={t('plan.calendar_source')} value={provider} onChange={(e) => setProvider(e.target.value as any)}>
          {(demo || !calendarConnected) && <option value="mock">{t('plan.provider_mock')}</option>}
          <option value="google" disabled={calendarConnected !== 'google'}>Google Calendar ({t('plan.readonly')})</option>
          <option value="microsoft" disabled={calendarConnected !== 'microsoft'}>Outlook Calendar ({t('plan.readonly')})</option>
        </select>{' '}
        <button className="link" onClick={() => app.go('sources/connections')}>{t('plan.connect_calendar')}</button>
      </div>
      {err && <div className="banner red" role="alert">{err}</div>}

      {plan && (
        <div aria-live="polite">
          <PlanStatus plan={plan} />
          <div className="plan-metrics">
            <div className="mini"><span>{t('plan.demand')}</span><strong>{plan.demand_minutes} <small>{t('common.minutes')}</small></strong></div>
            <div className="mini"><span>{t('plan.capacity')}</span><strong>{plan.capacity_upper_bound_minutes ?? '—'} <small>{t('common.minutes')}</small></strong></div>
            <div className="mini"><span>{t('plan.unmet')}</span><strong>{plan.unmet_minutes} <small>{t('common.minutes')}</small></strong></div>
          </div>
          <div className="week" style={{ gridTemplateColumns: `repeat(${Math.min(dayList.length, 5)}, minmax(0,1fr))` }}>
            {dayList.map((d) => (
              <div className="day" key={d.date}>
                <div className="day-head"><b>{weekday(d.date)}</b><small>{t('plan.day_planned', { n: d.planned, cap: d.cap })}</small></div>
                {d.completed > 0 && <div className="event"><b>{t('plan.completed_block', { n: d.completed })}</b><span>{t('plan.completed_note')}</span></div>}
                {[...d.busy.map((b) => ({ k: 'b', s: b.start, e: b.end, label: (b.label_key ? t('busy.' + b.label_key) : b.label || t('plan.busy')) + ' · ' + t(plan.synthetic ? 'plan.synthetic_busy' : 'plan.real_busy'), cls: '' })),
                  ...d.sessions.map((s) => ({ k: 's', s: s.start, e: s.end, label: `${titleOf(s.task_id, s.task_title)} · ${s.minutes} ${t('common.minutes')} · ${t(s.kept ? 'plan.kept' : 'plan.suggestion')}`, cls: 'study' })),
                  ...d.flex.map((f) => ({ k: 'f', s: f.start, e: f.end, label: t('plan.flex'), cls: 'flex' }))]
                  .sort((a, b) => new Date(a.s).getTime() - new Date(b.s).getTime())
                  .map((ev, i) => (
                    <div key={i} className={`event ${ev.cls}`}><b>{hm(ev.s)}–{hm(ev.e)}</b><span>{ev.label}</span></div>
                  ))}
              </div>
            ))}
          </div>
          {plan.per_task.length > 0 && (
            <div className="box" style={{ marginTop: 16 }}>
              <h3>{t('plan.per_task')}</h3>
              {plan.per_task.map((p) => (
                <div key={p.task_id} className="decision">{titleOf(p.task_id, p.title)}: {t('plan.per_task_line', { remaining: p.remaining, planned: p.planned, unmet: p.unmet })}</div>
              ))}
            </div>
          )}
          {plan.changes.length > 0 && (
            <details className="box">
              <summary><b>{t('plan.changes', { n: plan.changes.length })}</b></summary>
              {plan.changes.map((c, i) => <div key={i} className="footnote">{t('change.' + c.change)} · {c.task_title} · {hm(c.start)}–{hm(c.end)} ({partsIn(c.start, tz).date})</div>)}
            </details>
          )}
          <div className="row" style={{ marginTop: 18 }}>
            <button className="primary" onClick={review} disabled={plan.status !== 'feasible'}>{t('plan.review_save')}</button>
            {plan.status !== 'feasible' && plan.status !== 'stale' && (
              <>
                <button onClick={() => app.openPanel(t('draft.title'), () => <DraftEditor create={{ source_message_id: null, purpose: 'extension', channel: 'email',
                  verified_facts: { task_title: plan.per_task.find((p) => p.unmet > 0)?.title || '' } }} />)}>{t('plan.draft_extension')}</button>
                <button onClick={() => app.openPanel(t('settings.title'), () => <SettingsPanel />)}>{t('plan.adjust_limits')}</button>
                <button onClick={() => app.go('tasks')}>{t('plan.adjust_scope')}</button>
              </>
            )}
          </div>
          <p className="footnote">{t('plan.footnote')}</p>
        </div>
      )}
    </section>
  )
}

function PlanStatus({ plan }: { plan: Plan }) {
  const { t } = useI18n()
  const good = plan.status === 'feasible'
  return (
    <div className={`banner ${good ? 'green' : plan.status === 'stale' || plan.status === 'needs_information' ? 'warning' : 'red'}`}>
      <b>{t('plan.status.' + plan.status)}</b> <StatusTag status={plan.status} /><br />
      {good && t('plan.feasible_detail')}
      {plan.status === 'infeasible' && t('plan.infeasible_detail', { unmet: plan.unmet_minutes })}
      {plan.status === 'needs_adjustment' && t('plan.adjust_detail', { unmet: plan.unmet_minutes })}
      {plan.status === 'stale' && t('plan.stale_detail', { reasons: plan.stale_reasons.map((r) => t('stale.' + r.split(':')[0])).join(', ') })}
      {plan.missing_fields.length > 0 && <div>{t('plan.missing')}: {plan.missing_fields.join(' · ')}</div>}
      {plan.binding_constraints.filter((b) => b.startsWith('crunch')).map((b) => <div key={b}>{t('plan.crunch', { detail: b.split(':').slice(1).join(' ') })}</div>)}
      {plan.violations.length > 0 && <div>{t('plan.violations')}: {plan.violations.join(', ')}</div>}
    </div>
  )
}
