import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../api/client'
import type { Plan, SessionBlock, Task } from '../api/types'
import { useApp } from '../app/context'
import { pick, useI18n } from '../app/i18n'
import { nowIso, partsIn, uuid, zonedToIso } from '../app/time'
import { DateTimeInput } from '../components/DateTimeInputs'
import { DraftEditor } from '../components/DraftEditor'
import { BlockEditor, DemoMeeting, PlanRepair, StudyCheckins, useRuleText } from '../components/PlanRepair'
import { EstimateCalibration } from '../components/Calibration'
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
  const [reviewing, setReviewing] = useState(false)
  const [calendarProviders, setCalendarProviders] = useState<string[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<SessionBlock | null>(null)
  const [checkRun, setCheckRun] = useState(0) // bump to re-check the plan against the calendar
  const [openedId, setOpenedId] = useState<string | null>(null) // plan loaded when the page opened: checked by itself
  const [repairAsked, setRepairAsked] = useState(() => window.location.hash.endsWith('/repair'))
  // Progress is always logged on one explicitly chosen task, with the real number of minutes.
  const [prog, setProg] = useState<{ open: boolean; taskId: string; minutes: number; eventId: string; saving: boolean;
    saved: { title: string; minutes: number; remaining: number } | null; error: string | null }>(
    { open: false, taskId: '', minutes: 30, eventId: uuid(), saving: false, saved: null, error: null })

  useEffect(() => {
    get('/api/tasks?status=confirmed,in_progress').then((r) => {
      setTasks(r.items)
      setSelected((s) => (s.length ? s.filter((id) => r.items.some((x: Task) => x.id === id)) : r.items.map((x: Task) => x.id)))
    })
    get<Plan | null>('/api/plans/latest').then((p) => { setPlan(p); setOpenedId(p?.id ?? null) }).catch(() => undefined)
    get('/api/connections').then((r) => {
      const available = r.items.filter((c: any) => c.status === 'connected' && c.capabilities?.read_busy).map((c: any) => c.provider)
      setCalendarProviders(available)
      setProvider((current) => available.includes(current) ? current : available[0] || 'mock')
    }).catch(() => undefined)
  }, [app.dataVersion])

  // "#/plan/repair" (from a review that found a calendar conflict): check the current plan once it is loaded.
  useEffect(() => {
    const onHash = () => { if (window.location.hash.endsWith('/repair')) setRepairAsked(true) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    if (repairAsked && plan) {
      setRepairAsked(false)
      history.replaceState(null, '', '#/plan')
      setCheckRun((n) => n + 1)
    }
  }, [repairAsked, plan])
  useEffect(() => { setEditing(null) }, [plan?.id])

  const synthetic = tasks.find((x) => x.entity_key === 'synthetic_demo5105_report')
  // Demo controls only while demo data is shown; with a real mailbox the plan starts from now.
  const demo = !!app.prefs?.show_demo_data_effective
  const preferencesReady = !!app.prefs
  useEffect(() => {
    if (preferencesReady && !demo) {
      const n = new Date(Date.now() + 3600000)
      setStart(partsIn(n.toISOString(), tz).date + 'T' + partsIn(n.toISOString(), tz).time.slice(0, 2) + ':00')
      setDays(7)
    }
  }, [demo, preferencesReady, tz])

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

  function openProgress() {
    // Only one task ticked: that one is unambiguous. Otherwise the person must pick.
    const only = selected.length === 1 ? selected[0] : ''
    setProg({ open: true, taskId: only, minutes: 30, eventId: uuid(), saving: false, saved: null, error: null })
  }

  const progTask = tasks.find((x) => x.id === prog.taskId)
  const progValid = Number.isInteger(prog.minutes) && prog.minutes >= 5 && prog.minutes <= 600

  async function saveProgress() {
    if (!progTask || !progValid || prog.saving) return
    setProg({ ...prog, saving: true, error: null })
    // Synthetic scenario: progress is logged at the start of the synthetic week, real tasks use "now".
    const at = progTask.entity_key.startsWith('synthetic') ? zonedToIso(SYNTH_START.replace('08:00', '09:30'), tz) : nowIso()
    try {
      // The same client_event_id is reused if this request is retried, so a double submit is counted once.
      const r = await post<Task>(`/api/tasks/${progTask.id}/progress`, { expected_revision: progTask.revision,
        client_event_id: prog.eventId, minutes: prog.minutes, occurred_at: at })
      const remaining = Math.max(0, (r.estimated_minutes ?? 0) - r.completed_minutes)
      setProg({ ...prog, saving: false, eventId: uuid(), error: null,
        saved: { title: pick(locale, r.title, r.title_en), minutes: prog.minutes, remaining } })
      app.bump()
    } catch (e: any) {
      // A revision conflict means the task changed elsewhere: reload it, keep the same event id for the retry.
      if (e.code === 'REVISION_CONFLICT') app.bump()
      setProg({ ...prog, saving: false, error: e.code === 'REVISION_CONFLICT' ? t('plan.progress_conflict') : e.message })
    }
  }

  async function review() {
    if (!plan || !app.health || reviewing) return
    setReviewing(true)
    try {
      const p = await post('/api/proposals', { source_kind: 'plan', source_object_id: plan.id, expected_source_revision: plan.revision, mode: app.health.mode })
      app.bump()
      app.openPanel(t('review.title'), () => <ReviewDialog id={p.id} />)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setReviewing(false)
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
            <DateTimeInput id="p-start" value={start} onChange={(v) => { if (v) setStart(v) }} />
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
          <button onClick={openProgress} disabled={!tasks.length} aria-expanded={prog.open}>{t('plan.add_progress')}</button>
          {plan && <button onClick={() => generate(true)} disabled={busy}>{t('plan.replan')}</button>}
        </div>
        {prog.open && (
          <div className="box progress-box" style={{ marginTop: 12 }}>
            <h3>{t('plan.progress_title')}</h3>
            <div className="fields">
              <div className="field">
                <label htmlFor="pg-task">{t('plan.progress_task')}</label>
                <select id="pg-task" value={prog.taskId} onChange={(e) => setProg({ ...prog, taskId: e.target.value, saved: null, error: null })}>
                  <option value="">{t('plan.progress_choose')}</option>
                  {tasks.map((x) => (
                    <option key={x.id} value={x.id}>
                      {pick(locale, x.title, x.title_en)} · {t('task.remaining', { n: Math.max(0, (x.estimated_minutes ?? 0) - x.completed_minutes) })}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="pg-min">{t('plan.progress_minutes')}</label>
                <input id="pg-min" type="number" min={5} max={600} step={5} value={Number.isNaN(prog.minutes) ? '' : prog.minutes}
                  onChange={(e) => setProg({ ...prog, minutes: e.target.valueAsNumber, saved: null, error: null })} />
                {!progValid && <small>{t('plan.progress_minutes_hint')}</small>}
              </div>
            </div>
            {progTask && progValid && !prog.saved && (
              <p className="footnote" aria-live="polite">{t('plan.progress_summary', { task: pick(locale, progTask.title, progTask.title_en), n: prog.minutes })}</p>
            )}
            {prog.saved && (
              <div className="banner green" aria-live="polite">{t('plan.progress_saved', { task: prog.saved.title, n: prog.saved.minutes, remaining: prog.saved.remaining })}</div>
            )}
            {prog.error && <div className="banner red" role="alert">{prog.error}</div>}
            <div className="row">
              <button className="primary" onClick={saveProgress} disabled={!progTask || !progValid || prog.saving}>{t('plan.progress_save')}</button>
              <button onClick={() => setProg({ ...prog, open: false })}>{t('common.close')}</button>
            </div>
          </div>
        )}
      </div>

      <div className="banner channel-entry">
        {t('plan.calendar_source')}:{' '}
        <select aria-label={t('plan.calendar_source')} value={provider} onChange={(e) => setProvider(e.target.value as any)}>
          {(demo || calendarProviders.length === 0) && <option value="mock">{t('plan.provider_mock')}</option>}
          <option value="google" disabled={!calendarProviders.includes('google')}>Google Calendar ({t('plan.readonly')})</option>
          <option value="microsoft" disabled={!calendarProviders.includes('microsoft')}>Outlook Calendar ({t('plan.readonly')})</option>
        </select>{' '}
        <button className="link" onClick={() => app.go('sources/connections')}>{t('plan.connect_calendar')}</button>
      </div>
      {err && <div className="banner red" role="alert">{err}</div>}
      <StudyCheckins tz={tz} onReplan={() => generate(!!plan)} />
      <EstimateCalibration demo={demo} onReplan={() => generate(!!plan)} />
      {demo && (
        <DemoMeeting tz={tz} defaultStart={plan?.sessions[0] ? `${partsIn(plan.sessions[0].start, tz).date}T${partsIn(plan.sessions[0].start, tz).time}` : SYNTH_START.replace('08:00', '09:00')}
          onAdded={() => { if (plan) setCheckRun((n) => n + 1) }} />
      )}

      {plan && (
        <div aria-live="polite">
          <PlanStatus plan={plan} titleOf={titleOf} />
          <PlanRepair plan={plan} tz={tz} onPlan={setPlan} runKey={checkRun} auto={plan.id === openedId} titleOf={titleOf} />
          <div className="plan-metrics">
            <div className="mini" title={t('plan.demand_hint')}><span>{t('plan.demand')}</span><strong>{plan.demand_minutes} <small>{t('common.minutes')}</small></strong></div>
            <div className="mini"><span>{t('plan.capacity')}</span><strong>{plan.capacity_upper_bound_minutes ?? '—'} <small>{t('common.minutes')}</small></strong></div>
            <div className="mini"><span>{t('plan.unmet')}</span><strong>{plan.unmet_minutes} <small>{t('common.minutes')}</small></strong></div>
          </div>
          {plan.sessions.some((x) => x.kept || x.locked) && <p className="footnote">{t('plan.demand_hint')}</p>}
          <div className="week" style={{ gridTemplateColumns: `repeat(${Math.min(dayList.length, 5)}, minmax(0,1fr))` }}>
            {dayList.map((d) => (
              <div className="day" key={d.date}>
                <div className="day-head"><b>{weekday(d.date)}</b><small>{t('plan.day_planned', { n: d.planned, cap: d.cap })}</small></div>
                {d.completed > 0 && <div className="event"><b>{t('plan.completed_block', { n: d.completed })}</b><span>{t('plan.completed_note')}</span></div>}
                {(d.committed ?? 0) > 0 && <div className="event"><b>{t('plan.committed_block', { n: d.committed ?? 0 })}</b><span>{t('plan.committed_note')}</span></div>}
                {[...d.busy.map((b) => ({ k: 'b', s: b.start, e: b.end, label: (b.label_key ? t('busy.' + b.label_key) : b.label || t('plan.busy')) + ' · ' + t(plan.synthetic ? 'plan.synthetic_busy' : 'plan.real_busy'), cls: '' })),
                  ...d.sessions.map((s) => ({ k: 's', s: s.start, e: s.end, block: s,
                    label: `${titleOf(s.task_id, s.task_title)} · ${s.minutes} ${t('common.minutes')} · ${t(s.kept ? 'plan.kept' : s.locked ? 'plan.locked' : 'plan.suggestion')}`,
                    cls: 'study' + (s.locked ? ' locked' : '') + (editing === s ? ' editing' : '') })),
                  ...d.flex.map((f) => ({ k: 'f', s: f.start, e: f.end, label: t('plan.flex'), cls: 'flex' }))]
                  .sort((a, b) => new Date(a.s).getTime() - new Date(b.s).getTime())
                  .map((ev: { k: string; s: string; e: string; label: string; cls: string; block?: SessionBlock }, i) => (
                    <div key={i} className={`event ${ev.cls}`}><b>{hm(ev.s)}–{hm(ev.e)}</b><span>{ev.label}</span>
                      {ev.block && <button className="link event-edit" onClick={() => setEditing(ev.block!)} aria-label={t('edit.open_aria', { at: `${weekday(d.date)} ${hm(ev.s)}` })}>{t('edit.open')}</button>}
                    </div>
                  ))}
              </div>
            ))}
          </div>
          {editing && <BlockEditor plan={plan} block={editing} tz={tz} onPlan={setPlan} onClose={() => setEditing(null)} titleOf={titleOf} />}
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
              {plan.changes.map((c, i) => <div key={i} className="footnote">{t('change.' + c.change)} · {titleOf(c.task_id, c.task_title)} · {hm(c.start)}–{hm(c.end)} ({partsIn(c.start, tz).date})</div>)}
            </details>
          )}
          <div className="row" style={{ marginTop: 18 }}>
            <button className="primary" onClick={review} disabled={plan.status !== 'feasible' || !app.health || reviewing}>{t(app.health?.mode === 'live' ? 'plan.review_save_live' : 'plan.review_save')}</button>
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

function PlanStatus({ plan, titleOf }: { plan: Plan; titleOf: (id: string, fallback: string) => string }) {
  const { t } = useI18n()
  const app = useApp()
  const ruleText = useRuleText(app.prefs?.display_timezone || 'Asia/Singapore')
  const overrides: string[] = plan.inputs.overrides || []
  const accepted = plan.violations.filter((v) => overrides.includes(v))
  const unresolved = plan.violations.filter((v) => !overrides.includes(v))
  const withExceptions = plan.status === 'feasible' && accepted.length > 0
  const good = plan.status === 'feasible' && !accepted.length && !unresolved.length
  return (
    <div className={`banner ${good ? 'green' : withExceptions || plan.status === 'stale' || plan.status === 'needs_information' ? 'warning' : 'red'}`}>
      <b>{t(withExceptions ? 'plan.status.accepted_exceptions' : 'plan.status.' + plan.status)}</b> <StatusTag status={plan.status} /><br />
      {good && t('plan.feasible_detail')}
      {withExceptions && t('plan.accepted_exceptions_detail')}
      {plan.status === 'infeasible' && t('plan.infeasible_detail', { unmet: plan.unmet_minutes })}
      {plan.status === 'needs_adjustment' && t('plan.adjust_detail', { unmet: plan.unmet_minutes })}
      {plan.status === 'stale' && t('plan.stale_detail', { reasons: plan.stale_reasons.map((r) => t('stale.' + r.split(':')[0])).join(', ') })}
      {plan.missing_fields.length > 0 && <div>{t('plan.missing')}: {plan.missing_fields.join(' · ')}</div>}
      {plan.binding_constraints.filter((b) => b.startsWith('crunch')).map((b) => <div key={b}>{t('plan.crunch', { detail: b.split(':').slice(1).join(' ') })}</div>)}
      {plan.binding_constraints.filter((b) => b.startsWith('study_blocks_from_records')).map((b) => <div key={b}>{t('plan.study_from_records', { n: b.split(':')[1] })}</div>)}
      {plan.binding_constraints.includes('placement_order_changed_to_fit_all_work') && <div>{t('plan.reordered')}</div>}
      {plan.binding_constraints.filter((b) => b.startsWith('task_daily_cap:')).map((b) => {
        const [, id, need, own] = b.split(':')
        return <div key={b}>{t('plan.task_cap_binding', { task: titleOf(id, plan.per_task.find((p) => p.task_id === id)?.title || id), need, own })}</div>
      })}
      {plan.binding_constraints.some((b) => b.startsWith('study_block_removed_in_calendar')) && (
        <div>{t('plan.study_removed', { n: plan.binding_constraints.filter((b) => b.startsWith('study_block_removed_in_calendar')).length })}</div>
      )}
      {accepted.length > 0 && <div><b>{t('plan.accepted_exceptions')}</b><ul>{accepted.map((v) => <li key={v}>{ruleText(v)}</li>)}</ul></div>}
      {unresolved.length > 0 && <div>{t('plan.violations')}: {unresolved.map(ruleText).join(', ')}</div>}
    </div>
  )
}
