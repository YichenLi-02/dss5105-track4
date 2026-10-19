import { useEffect, useState } from 'react'
import { get, patch, post } from '../api/client'
import type { Task } from '../api/types'
import { useApp } from '../app/context'
import { fmtDateTime, pick, useI18n } from '../app/i18n'
import { nowIso, uuid, zonedToIso } from '../app/time'
import { StatusTag } from '../components/Tags'

export function deadlineText(t: (k: string, p?: any) => string, x: Task): string {
  if (!x.official_date) return t('task.date_unresolved')
  return `${x.official_date} · ${x.official_time ?? t('task.time_not_stated')} · ${x.source_timezone ?? t('task.zone_not_stated')}`
}

export function TasksPage() {
  const { t } = useI18n()
  const app = useApp()
  const [items, setItems] = useState<Task[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    get('/api/tasks').then((r) => setItems(r.items)).catch((e) => setErr(e.message))
  }, [app.dataVersion])

  const [newTitle, setNewTitle] = useState<string | null>(null)
  async function newTask() {
    const title = (newTitle || '').trim()
    if (!title) return
    const task = await post<Task>('/api/tasks', { title, source_id: null, evidence_quote: null })
    setNewTitle(null)
    app.bump()
    app.openPanel(task.title, () => <TaskDetail id={task.id} />)
  }

  if (err) return <div className="banner red">{err}</div>
  if (!items) return <div className="empty"><p>{t('common.loading')}</p></div>
  const groups: [string, Task[]][] = [
    ['review', items.filter((x) => ['candidate', 'needs_review'].includes(x.status))],
    ['confirmed', items.filter((x) => ['confirmed', 'in_progress'].includes(x.status))],
    ['completed', items.filter((x) => x.status === 'completed')],
  ]
  const ignored = items.filter((x) => x.status === 'ignored')
  return (
    <section>
      <div className="section-head">
        <div>
          <div className="page-label">TASKS</div>
          <h1>{t('tasks.title')}</h1>
          <p className="description">{t('tasks.description')}</p>
        </div>
        {newTitle === null && <button className="primary" onClick={() => setNewTitle('')}>{t('tasks.new')}</button>}
      </div>
      {newTitle !== null && (
        <form className="box row" onSubmit={(e) => { e.preventDefault(); newTask() }}>
          <input className="search" autoFocus value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
            placeholder={t('tasks.new_prompt')} aria-label={t('tasks.new_prompt')} />
          <button className="primary" type="submit" disabled={!newTitle.trim()}>{t('tasks.new_create')}</button>
          <button type="button" onClick={() => setNewTitle(null)}>{t('common.cancel')}</button>
        </form>
      )}
      {items.length === 0 && (
        <div className="empty"><h3>{t('tasks.empty')}</h3><button onClick={() => app.go('mail')}>{t('tasks.go_mail')}</button></div>
      )}
      {groups.map(([key, list]) => list.length > 0 && (
        <div className="box" key={key}>
          <h2>{t('tasks.group.' + key)} <span className="tag">{list.length}</span></h2>
          {list.map((x) => <TaskRow key={x.id} x={x} />)}
        </div>
      ))}
      {ignored.length > 0 && (
        <details className="box">
          <summary><b>{t('tasks.group.ignored')}</b> <span className="tag">{ignored.length}</span></summary>
          <p className="footnote">{t('tasks.ignored_note')}</p>
          {ignored.map((x) => <TaskRow key={x.id} x={x} />)}
        </details>
      )}
    </section>
  )
}

function TaskRow({ x }: { x: Task }) {
  const { t, locale } = useI18n()
  const app = useApp()
  const remaining = x.estimated_minutes == null ? null : Math.max(0, x.estimated_minutes - x.completed_minutes)
  return (
    <div className="task-row">
      <div>
        <div className="task-title">{pick(locale, x.title, x.title_en)}</div>
        <div className="row" style={{ gap: 6 }}>
          {x.course && <span className="tag academic">{x.course}</span>}
          {!x.required && <span className="tag">{t('task.optional')}</span>}
          <StatusTag status={x.status} />
          {x.deadline_status && <span className={`tag ${['conflict', 'time_conflict'].includes(x.deadline_status) ? 'red' : x.deadline_status === 'explicit' || x.deadline_status === 'user_confirmed' ? '' : 'warn'}`}>{t('deadline.' + x.deadline_status)}</span>}
          {x.entity_key.startsWith('synthetic') && <span className="tag warn">{t('common.synthetic')}</span>}
        </div>
      </div>
      <div className="task-date">
        {deadlineText(t, x)}<br />
        {remaining == null ? t('task.effort_unknown') : t('task.remaining', { n: remaining })} · {t('task.sources', { n: x.evidence.length })}
      </div>
      <button onClick={() => app.openPanel(pick(locale, x.title, x.title_en), () => <TaskDetail id={x.id} />)}>{t(x.status === 'needs_review' ? 'task.check' : 'task.open')}</button>
    </div>
  )
}

export function TaskDetail({ id }: { id: string }) {
  const { t, locale } = useI18n()
  const app = useApp()
  const [x, setX] = useState<Task | null>(null)
  const [f, setF] = useState<Record<string, any>>({})
  const [err, setErr] = useState<string | null>(null)
  const tz = app.prefs?.display_timezone || 'Asia/Singapore'

  function load(task: Task) {
    setX(task)
    setF({
      official_date: task.official_date || '', official_time: task.official_time || '',
      source_timezone: task.source_timezone || (task.entity_key.startsWith('manual_') ? tz : ''),
      cutoff_local: '', cutoff_tz: task.source_timezone || tz,
      estimated_minutes: task.estimated_minutes ?? '', required: task.required,
    })
  }
  useEffect(() => {
    get<Task>(`/api/tasks/${id}`).then(load).catch((e) => setErr(e.message))
  }, [id])
  if (err && !x) return <div className="banner red">{err}</div>
  if (!x) return <p>{t('common.loading')}</p>

  async function save(extra: Record<string, any> = {}) {
    setErr(null)
    const body: Record<string, any> = { expected_revision: x!.revision, required: !!f.required }
    if (f.official_date !== (x!.official_date || '')) body.official_date = f.official_date || null
    if (f.official_time !== (x!.official_time || '')) body.official_time = f.official_time || null
    if (f.source_timezone !== (x!.source_timezone || '')) body.source_timezone = f.source_timezone || null
    if (f.cutoff_local) body.user_planning_cutoff = zonedToIso(f.cutoff_local, f.cutoff_tz)
    if (String(f.estimated_minutes) !== String(x!.estimated_minutes ?? '')) body.estimated_minutes = f.estimated_minutes === '' ? null : Number(f.estimated_minutes)
    try {
      load(await patch<Task>(`/api/tasks/${x!.id}`, { ...body, ...extra }))
      app.bump()
      return true
    } catch (e: any) {
      setErr(e.code === 'REVISION_CONFLICT' ? t('common.revision_conflict') : e.code === 'TASK_INCOMPLETE' ? t('task.incomplete', { fields: e.details.map((d: string) => t('missing.' + d)).join(', ') }) : e.message)
      return false
    }
  }

  async function progress(minutes: number) {
    try {
      load(await post<Task>(`/api/tasks/${x!.id}/progress`, { expected_revision: x!.revision, client_event_id: uuid(), minutes, occurred_at: nowIso() }))
      app.toast(t('task.progress_saved', { n: minutes }))
      app.bump()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  const hasCutoff = !!(f.cutoff_local || x.user_planning_cutoff)
  const conflictOpen = ['conflict', 'time_conflict'].includes(x.deadline_status) && !hasCutoff
    && f.official_date === (x.official_date || '') && f.official_time === (x.official_time || '')
  const missingLive = [
    ...(conflictOpen ? ['resolve_date_conflict'] : []),
    ...(!hasCutoff && !f.official_date ? ['deadline_date'] : []),
    ...(!hasCutoff && !f.official_time ? ['deadline_time_or_planning_cutoff'] : []),
    ...(!hasCutoff && !f.source_timezone ? ['source_timezone'] : []),
    ...(f.estimated_minutes === '' || f.estimated_minutes === null || Number(f.estimated_minutes) <= 0 ? ['estimated_minutes'] : []),
  ]
  return (
    <>
      <div className="row" style={{ gap: 6, marginBottom: 12 }}>
        <StatusTag status={x.status} />
        <span className="tag">{t('deadline.' + x.deadline_status)}</span>
        {x.course && <span className="tag academic">{x.course}</span>}
        {x.term && <span className="tag">{x.term}</span>}
      </div>
      <dl className="kv">
        <dt>{t('task.official')}</dt><dd>{deadlineText(t, x)}</dd>
        <dt>{t('task.user_cutoff')}</dt><dd>{x.user_planning_cutoff ? `${x.user_planning_cutoff} (${t('task.user_set')})` : t('common.none')}</dd>
        <dt>{t('task.cutoff_utc')}</dt><dd>{x.planning_cutoff_utc ? fmtDateTime(locale, x.planning_cutoff_utc, tz) + ' ' + tz : t('task.not_computable')}</dd>
        <dt>{t('task.progress')}</dt><dd>{t('task.progress_value', { done: x.completed_minutes, total: x.estimated_minutes ?? '?' })}</dd>
      </dl>

      <h3>{t('task.evidence')} ({x.evidence.length})</h3>
      {x.evidence.map((e) => (
        <div key={e.id} className="decision">
          <div className="row" style={{ gap: 6 }}>
            <span className="tag">{e.source_id}</span>
            <span className={`tag ${e.relation === 'conflict' ? 'red' : e.relation === 'completion_receipt' ? 'green' : ''}`}>{t('relation.' + e.relation)}</span>
            {e.locator.page != null && <span className="tag">{t('task.page', { n: e.locator.page })}</span>}
            {e.locator.excerpt_origin && <span className="tag">{t('excerpt.' + e.locator.excerpt_origin)}</span>}
            {e.locator.origin && <span className="tag">{t('origin.' + e.locator.origin)}</span>}
            {e.source_excluded && <span className="tag red">{t('task.source_excluded')}</span>}
          </div>
          <div className="source-quote">{e.quote}</div>
          <small className="footnote">{e.subject} · {e.sent_at?.slice(0, 10)}{e.start_char != null ? ` · chars ${e.start_char}–${e.end_char}` : ` · ${t('task.quote_unlocated')}`}{e.locator.note ? ` · ${e.locator.note}` : ''}</small>
        </div>
      ))}
      {x.date_candidates.length > 0 && (
        <details className="permission-details">
          <summary>{t('task.candidates', { n: x.date_candidates.length })}</summary>
          {x.date_candidates.map((c, i) => (
            <div key={i} className="footnote">
              {c.source_id} · {c.kind} · {c.official_date_candidate ?? '—'} {c.official_time_candidate ?? ''} {c.timezone ?? ''} · {c.status}
              {c.required_duration_minutes ? ` · ${c.required_duration_minutes} min` : ''}
            </div>
          ))}
        </details>
      )}

      {x.status !== 'ignored' && x.status !== 'completed' && (
        <>
          <h3 style={{ marginTop: 18 }}>{t('task.confirm_inputs')}</h3>
          <p className="footnote">{t('task.confirm_hint')}</p>
          <div className="fields">
            <div className="field"><label htmlFor="t-date">{t('task.f_date')}</label><input id="t-date" type="date" value={f.official_date} onChange={(e) => set('official_date', e.target.value)} /></div>
            <div className="field"><label htmlFor="t-time">{t('task.f_time')}</label><input id="t-time" type="time" value={f.official_time} onChange={(e) => set('official_time', e.target.value)} /><small>{t('task.f_time_hint')}</small></div>
            <div className="field"><label htmlFor="t-tz">{t('task.f_tz')}</label><input id="t-tz" list="tz-list" value={f.source_timezone} onChange={(e) => set('source_timezone', e.target.value)} placeholder="Asia/Singapore" />
              {!f.source_timezone && <button type="button" className="link" onClick={() => set('source_timezone', tz)}>{t('task.use_my_tz', { tz })}</button>}</div>
            <div className="field"><label htmlFor="t-cut">{t('task.f_cutoff')}</label><input id="t-cut" type="datetime-local" value={f.cutoff_local} onChange={(e) => set('cutoff_local', e.target.value)} /><small>{t('task.f_cutoff_hint', { tz: f.cutoff_tz })}</small>
              {f.official_date && !f.official_time && !f.cutoff_local && (
                <button type="button" className="link" onClick={() => setF({ ...f, cutoff_local: f.official_date + 'T23:59', cutoff_tz: f.source_timezone || tz })}>{t('task.use_end_of_day')}</button>
              )}</div>
            <div className="field"><label htmlFor="t-est">{t('task.f_estimate')}</label><input id="t-est" type="number" min={0} step={15} value={f.estimated_minutes} onChange={(e) => set('estimated_minutes', e.target.value)} /><small>{t('task.f_estimate_hint')}</small></div>
          </div>
          <datalist id="tz-list">{['Asia/Singapore', 'America/Phoenix', 'UTC', 'Asia/Shanghai', 'Europe/London', 'America/New_York'].map((z) => <option key={z} value={z} />)}</datalist>
          <label className="checkline"><input type="checkbox" checked={!!f.required} onChange={(e) => set('required', e.target.checked)} />{t('task.f_required')}</label>
          {missingLive.length > 0
            ? <div className="banner warning" aria-live="polite">{t('task.missing')}: {missingLive.map((m) => t('missing.' + m)).join(' · ')}</div>
            : <div className="banner green" aria-live="polite">{t('task.ready_to_confirm')}</div>}
          {err && <div className="banner red" role="alert">{err}</div>}
          <div className="panel-actions">
            <button onClick={() => save()}>{t('task.save')}</button>
            <button className="primary" disabled={missingLive.length > 0} onClick={() => save({ status: 'confirmed' })}>{t('task.confirm')}</button>
            <button onClick={() => save({ status: 'ignored' })}>{t('task.ignore')}</button>
          </div>
        </>
      )}
      {(x.status === 'confirmed' || x.status === 'in_progress') && (
        <div className="panel-actions">
          <button onClick={() => progress(30)}>{t('task.add30')}</button>
          <button onClick={() => progress(60)}>{t('task.add60')}</button>
          <button onClick={() => save({ status: 'completed' })}>{t('task.mark_done')}</button>
        </div>
      )}
      {x.status === 'ignored' && <div className="panel-actions"><button onClick={() => save({ status: 'needs_review' })}>{t('task.restore')}</button></div>}
    </>
  )
}
