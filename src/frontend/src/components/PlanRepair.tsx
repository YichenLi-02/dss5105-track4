// Conflict handling on the plan page: find conflicts, compare repair options, edit one block by hand,
// answer "did you do it?" for past study blocks, and (sample data only) simulate a new meeting.
// Nothing here writes to a calendar: a chosen or edited plan still goes through the normal review + confirm.
import { useEffect, useRef, useState } from 'react'
import { del, get, post } from '../api/client'
import type { Plan, SessionBlock } from '../api/types'
import { useApp } from '../app/context'
import { fmtDateTime, useI18n } from '../app/i18n'
import { partsIn, zonedToIso } from '../app/time'
import { DateTimeInput } from './DateTimeInputs'
import { DraftEditor } from './DraftEditor'

interface Snapshot { id: string; status: string; errors?: string[] }

/** Re-read the calendar exactly as the plan was made from it (same source, calendars and days), so a different
 *  source picked on the page for the next plan is never mixed into checks, fixes or edits of this one. */
const freshSnapshot = (planId: string) => post<Snapshot>(`/api/plans/${planId}/fresh-snapshot`, {})

interface Conflict { task_id: string; task_title: string; start: string; end: string; written: boolean; locked: boolean;
  busy: { start: string; end: string }[] }
interface CheckResult { plan_id: string; snapshot_id: string; conflicts: Conflict[]; unplaced_minutes: number | null;
  needs_attention: boolean; kind: 'calendar' | 'capacity' | null }
interface RepairOption { plan: Plan & { computed_status?: string }; strategy: string; changed: number; dropped: number;
  relaxed: string[]; unmet: number; min_slack_minutes: number | null; moves_written: number; recommended: boolean }
interface RepairResult { base_plan_id: string; conflicts: Conflict[]; options: RepairOption[]; kind: string | null;
  extension_suggested: boolean }

const key = (s: { task_id: string; start: string; end: string }) => `${s.task_id}|${new Date(s.start).getTime()}|${new Date(s.end).getTime()}`

function useSpan(tz: string) {
  const { locale } = useI18n()
  return (a: string, b: string) => `${fmtDateTime(locale, a, tz)}–${partsIn(b, tz).time}`
}

/** Translates a planner rule string such as "session_length:task_x@2026-10-23T11:15:00+08:00" or "daily_cap_plus:30". */
export function useRuleText(tz: string) {
  const { t, locale } = useI18n()
  return (rule: string) => {
    const [kind, ...rest] = rule.split(':')
    const tail = rest.join(':')
    const at = tail.includes('@') ? tail.split('@')[1] : ''
    const day = /^\d{4}-\d{2}-\d{2}$/
    const where = at ? (day.test(at) ? at : fmtDateTime(locale, at, tz)) : day.test(tail) ? tail : ''
    return t('rule.' + kind, { n: /^\d+$/.test(tail) ? tail : '', at: where })
  }
}

// ------------------------------------------------------------------ conflicts and repair options

export function PlanRepair({ plan, tz, onPlan, runKey, auto, titleOf }: {
  plan: Plan; tz: string; onPlan: (p: Plan) => void; runKey: number
  auto: boolean // check once by itself (the plan was opened, not just made from a fresh calendar read)
  titleOf: (id: string, fallback: string) => string }) {
  const { t } = useI18n()
  const app = useApp()
  const span = useSpan(tz)
  const rule = useRuleText(tz)
  const [check, setCheck] = useState<CheckResult | null>(null)
  const [options, setOptions] = useState<RepairResult | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null) // could not check, but nothing is wrong with the plan itself
  const [checkedAt, setCheckedAt] = useState<{ at: string; auto: boolean } | null>(null)
  const autoDone = useRef(new Set<string>())

  useEffect(() => { setCheck(null); setOptions(null); setErr(null); setNote(null); setCheckedAt(null) }, [plan.id])
  useEffect(() => { if (runKey > 0) runCheck() }, [runKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (auto && !autoDone.current.has(plan.id)) {
      autoDone.current.add(plan.id) // once per plan per visit, never in a loop
      runCheck(true)
    }
  }, [auto, plan.id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function runCheck(automatic = false) {
    setBusy(true); setErr(null); setNote(null); setOptions(null)
    try {
      const snap = await freshSnapshot(plan.id)
      if (snap.status !== 'complete') {
        setCheck(null)
        setNote(t('repair.not_read', { err: (snap.errors || []).join('; ') || snap.status }))
        return
      }
      setCheck(await post<CheckResult>(`/api/plans/${plan.id}/conflicts`, { snapshot_id: snap.id }))
      setCheckedAt({ at: new Date().toISOString(), auto: automatic })
    } catch (e: any) {
      if (e.code === 'PLAN_WINDOW_OVER') setNote(t('repair.window_over'))
      else if (automatic) setNote(t('repair.auto_failed', { err: e.message }))
      else setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function loadOptions() {
    setBusy(true); setErr(null)
    try {
      const prefs = await get('/api/preferences')
      const snap = await freshSnapshot(plan.id) // always against the calendar as it is now
      if (snap.status !== 'complete') {
        setErr(t('repair.not_read', { err: (snap.errors || []).join('; ') || snap.status }))
        return
      }
      const r = await post<RepairResult>(`/api/plans/${plan.id}/repair-options`, { snapshot_id: snap.id, preferences_revision: prefs.revision })
      setOptions(r)
      setOpen(r.options[0]?.plan.id ?? null)
      if (!r.options.length) app.toast(t('repair.nothing_to_fix'))
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function adopt(o: RepairOption) {
    setBusy(true); setErr(null)
    try {
      const p = await post<Plan>(`/api/plans/${o.plan.id}/adopt`, { expected_revision: o.plan.revision })
      onPlan(p)
      app.toast(t('repair.adopted'))
    } catch (e: any) {
      setErr(['BASE_REPLACED', 'OPTION_STALE'].includes(e.code) ? t('repair.err.' + e.code) : e.message)
      setOptions(null)
    } finally {
      setBusy(false)
    }
  }

  const broken = plan.status === 'infeasible' || plan.status === 'needs_adjustment'
  const base = new Set(plan.sessions.map(key))

  return (
    <div className="box repair">
      <div className="row between">
        <div>
          <h3>{t('repair.title')}</h3>
          <small className="footnote" style={{ margin: 0 }}>{t('repair.intro')}</small>
          {checkedAt && <div><small className="footnote" style={{ margin: 0 }}>
            {t('repair.last_checked', { time: partsIn(checkedAt.at, tz).time, how: t(checkedAt.auto ? 'repair.checked_auto' : 'repair.checked_manual') })}
          </small></div>}
        </div>
        <div className="row">
          <button onClick={() => runCheck()} disabled={busy}>{busy ? t('repair.checking') : t('repair.check')}</button>
          {(broken || check?.needs_attention) && <button className="primary" onClick={loadOptions} disabled={busy}>{t('repair.show_options')}</button>}
        </div>
      </div>
      {err && <div className="banner red" role="alert" style={{ marginTop: 12 }}>{err}</div>}
      {note && <div className="banner warning" style={{ marginTop: 12 }}>{note}</div>}

      {check && !options && (
        <div aria-live="polite" style={{ marginTop: 12 }}>
          {!check.needs_attention && <div className="banner green">{t('repair.all_clear')}</div>}
          {check.kind === 'calendar' && (
            <div className="banner red">
              <b>{t('repair.found', { n: check.conflicts.length })}</b>
              <ul>{check.conflicts.map((c, i) => <ConflictLine key={i} c={c} span={span} titleOf={titleOf} />)}</ul>
            </div>
          )}
          {check.kind === 'capacity' && <div className="banner warning">{t('repair.capacity', { n: check.unplaced_minutes ?? 0 })}</div>}
          {check.kind === null && check.needs_attention && <div className="banner warning">{t('repair.still_short', { n: plan.unmet_minutes })}</div>}
        </div>
      )}

      {options && (
        <div style={{ marginTop: 12 }} aria-live="polite">
          {options.conflicts.length > 0 && (
            <div className="banner red">
              <b>{t('repair.found', { n: options.conflicts.length })}</b>
              <ul>{options.conflicts.map((c, i) => <ConflictLine key={i} c={c} span={span} titleOf={titleOf} />)}</ul>
            </div>
          )}
          {options.options.length === 0 && <div className="banner green">{t('repair.nothing_to_fix')}</div>}
          {options.options.map((o, i) => {
            const mine = new Set(o.plan.sessions.map(key))
            const added = o.plan.sessions.filter((s) => !base.has(key(s)))
            const removed = plan.sessions.filter((s) => !mine.has(key(s)))
            return (
              <div key={o.plan.id} className={`repair-option${o.recommended ? ' recommended' : ''}`}>
                <div className="row between">
                  <b>{i + 1}. {t('repair.strategy.' + o.strategy)}</b>
                  <span className="row" style={{ gap: 6 }}>
                    {o.recommended && <span className="tag green">{t('repair.recommended')}</span>}
                    {o.relaxed.map((r) => <span key={r} className="tag warn">{t('repair.relaxes')}: {rule(r)}</span>)}
                    {o.unmet > 0 ? <span className="tag red">{t('repair.unmet', { n: o.unmet })}</span>
                      : <span className="tag green">{t('repair.fits')}</span>}
                  </span>
                </div>
                <p className="footnote" style={{ margin: '6px 0' }}>{t('repair.desc.' + o.strategy)}</p>
                <div className="footnote" style={{ margin: 0 }}>
                  {t('repair.cost', { changed: o.changed, dropped: o.dropped })}
                  {o.min_slack_minutes !== null && <> · {t('repair.slack', { h: Math.round(o.min_slack_minutes / 6) / 10 })}</>}
                </div>
                {o.moves_written > 0 && <div className="banner warning" style={{ margin: '8px 0 0' }}>{t('repair.moves_written', { n: o.moves_written })}</div>}
                <div className="row" style={{ marginTop: 8 }}>
                  <button className={o.recommended ? 'primary' : ''} onClick={() => adopt(o)} disabled={busy}>{t('repair.choose')}</button>
                  <button className="link" onClick={() => setOpen(open === o.plan.id ? null : o.plan.id)} aria-expanded={open === o.plan.id}>
                    {t(open === o.plan.id ? 'repair.hide_changes' : 'repair.show_changes')}
                  </button>
                </div>
                {open === o.plan.id && (
                  <div className="repair-diff">
                    {removed.map((s, k) => <div key={'r' + k} className="event"><b>− {span(s.start, s.end)}</b><span>{titleOf(s.task_id, s.task_title)} · {t('repair.removed')}</span></div>)}
                    {added.map((s, k) => <div key={'a' + k} className="event study"><b>+ {span(s.start, s.end)}</b><span>{titleOf(s.task_id, s.task_title)} · {s.minutes} {t('common.minutes')}</span></div>)}
                    {!removed.length && !added.length && <small>{t('repair.no_block_changes')}</small>}
                  </div>
                )}
              </div>
            )
          })}
          {options.extension_suggested && (
            <div className="repair-option">
              <b>{t('repair.extension_title')}</b>
              <p className="footnote" style={{ margin: '6px 0' }}>{t('repair.extension_desc')}</p>
              <button onClick={() => app.openPanel(t('draft.title'), () => <DraftEditor create={{ source_message_id: null, purpose: 'extension', channel: 'email',
                verified_facts: { task_title: plan.per_task.find((p) => p.unmet > 0)?.title || '' } }} />)}>{t('plan.draft_extension')}</button>
            </div>
          )}
          <p className="footnote">{t('repair.choose_note')}</p>
        </div>
      )}
    </div>
  )
}

function ConflictLine({ c, span, titleOf }: { c: Conflict; span: (a: string, b: string) => string; titleOf: (id: string, f: string) => string }) {
  const { t } = useI18n()
  return (
    <li>
      {t('repair.conflict_line', { task: titleOf(c.task_id, c.task_title), study: span(c.start, c.end),
        busy: c.busy.map((b) => span(b.start, b.end)).join(', ') })}
      {c.written && <> · <b>{t('repair.already_written')}</b></>}
      {c.locked && <> · {t('plan.locked')}</>}
    </li>
  )
}

// ------------------------------------------------------------------ manual edit of one block

export function BlockEditor({ plan, block, tz, onPlan, onClose, titleOf }: {
  plan: Plan; block: SessionBlock; tz: string; onPlan: (p: Plan) => void; onClose: () => void
  titleOf: (id: string, fallback: string) => string }) {
  const { t } = useI18n()
  const app = useApp()
  const span = useSpan(tz)
  const rule = useRuleText(tz)
  const p0 = partsIn(block.start, tz)
  const [start, setStart] = useState(`${p0.date}T${p0.time}`)
  const [minutes, setMinutes] = useState(block.minutes)
  const [hard, setHard] = useState<string[] | null>(null)
  const [soft, setSoft] = useState<string[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const valid = Number.isInteger(minutes) && minutes >= 5 && minutes <= 240 && !!start

  async function save(extra: { remove?: boolean; unlock?: boolean; acknowledge?: string[] } = {}) {
    setBusy(true); setErr(null); setHard(null)
    if (!extra.acknowledge) setSoft(null)
    try {
      const prefs = await get('/api/preferences')
      const snap = await freshSnapshot(plan.id)
      const p = await post<Plan>(`/api/plans/${plan.id}/edit-block`, {
        expected_revision: plan.revision, snapshot_id: snap.id, preferences_revision: prefs.revision,
        task_id: block.task_id, start: block.start,
        new_start: extra.remove ? null : zonedToIso(start, tz), minutes: extra.remove ? null : minutes,
        remove: !!extra.remove, unlock: !!extra.unlock, acknowledge: extra.acknowledge ?? [] })
      onPlan(p)
      app.toast(t(extra.remove ? 'edit.removed' : extra.unlock ? 'edit.unlocked' : 'edit.saved'))
      onClose()
    } catch (e: any) {
      if (e.code === 'EDIT_NOT_ALLOWED') setHard(e.details)
      else if (e.code === 'SOFT_RULES') setSoft(e.details)
      else setErr(t('edit.err.' + e.code) !== 'edit.err.' + e.code ? t('edit.err.' + e.code) : e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="box block-editor" role="group" aria-label={t('edit.title')}>
      <div className="row between">
        <h3>{t('edit.title')}</h3>
        <button className="link" onClick={onClose}>{t('common.close')}</button>
      </div>
      <p className="footnote" style={{ marginTop: 0 }}>{titleOf(block.task_id, block.task_title)} · {span(block.start, block.end)}
        {block.locked && <> · {t('plan.locked')}</>}</p>
      {block.kept && <div className="banner warning">{t('edit.written_note')}</div>}
      <div className="fields">
        <div className="field field-wide">
          <label htmlFor="be-start">{t('edit.start')}</label>
          <DateTimeInput id="be-start" value={start} onChange={(v) => { if (v) { setStart(v); setSoft(null); setHard(null) } }} />
        </div>
        <div className="field">
          <label htmlFor="be-min">{t('edit.minutes')}</label>
          <input id="be-min" type="number" min={5} max={240} step={5} value={Number.isNaN(minutes) ? '' : minutes}
            onChange={(e) => { setMinutes(e.target.valueAsNumber); setSoft(null); setHard(null) }} />
          {!valid && <small>{t('edit.minutes_hint')}</small>}
        </div>
      </div>
      <p className="footnote">{t('edit.lock_note')}</p>
      {hard && (
        <div className="banner red" role="alert"><b>{t('edit.hard_title')}</b>
          <ul>{hard.map((h) => <li key={h}>{t('edit.hard.' + h)}</li>)}</ul></div>
      )}
      {soft && (
        <div className="banner warning" role="alert"><b>{t('edit.soft_title')}</b>
          <ul>{soft.map((s) => <li key={s}>{rule(s)}</li>)}</ul>
          <div className="row"><button onClick={() => save({ acknowledge: soft })} disabled={busy}>{t('edit.accept_anyway')}</button>
            <small>{t('edit.accept_note')}</small></div>
        </div>
      )}
      {err && <div className="banner red" role="alert">{err}</div>}
      <div className="row">
        <button className="primary" onClick={() => save()} disabled={busy || !valid}>{t('edit.save')}</button>
        <button onClick={() => save({ remove: true })} disabled={busy}>{t('edit.remove')}</button>
        {block.locked && <button onClick={() => save({ unlock: true })} disabled={busy}>{t('edit.unlock')}</button>}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ "did you do it?" for past written blocks

interface Checkin { key: string; task_id: string; task_title: string; start: string; end: string; minutes: number }

export function StudyCheckins({ tz, onReplan }: { tz: string; onReplan: () => void }) {
  const { t } = useI18n()
  const app = useApp()
  const span = useSpan(tz)
  const [items, setItems] = useState<Checkin[]>([])
  const [partial, setPartial] = useState<Record<string, number>>({})
  const [answered, setAnswered] = useState(0)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { get<{ items: Checkin[] }>('/api/study-checkins').then((r) => setItems(r.items)).catch(() => undefined) }, [app.dataVersion])

  async function answer(c: Checkin, outcome: 'done' | 'partial' | 'missed') {
    setErr(null)
    try {
      await post('/api/study-checkins', { key: c.key, outcome, minutes: outcome === 'partial' ? partial[c.key] : null })
      setAnswered((n) => n + 1)
      app.toast(t('checkin.saved.' + outcome))
      app.bump()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  if (!items.length && !answered) return null
  return (
    <div className="box checkins" aria-live="polite">
      <h3>{t('checkin.title')}</h3>
      {items.length === 0 && <p className="footnote">{t('checkin.all_answered')}</p>}
      {items.map((c) => {
        const m = partial[c.key] ?? Math.round(c.minutes / 2)
        const ok = Number.isInteger(m) && m >= 5 && m < c.minutes + 1
        return (
          <div key={c.key} className="decision">
            <div>{c.task_title} · {span(c.start, c.end)} · {c.minutes} {t('common.minutes')}</div>
            <div className="row" style={{ marginTop: 6 }}>
              <button onClick={() => answer(c, 'done')}>{t('checkin.done')}</button>
              <input aria-label={t('checkin.partial_minutes')} type="number" min={5} max={c.minutes} step={5} style={{ width: 80 }}
                value={Number.isNaN(m) ? '' : m} onChange={(e) => setPartial({ ...partial, [c.key]: e.target.valueAsNumber })} />
              <button onClick={() => answer(c, 'partial')} disabled={!ok}>{t('checkin.partial')}</button>
              <button onClick={() => answer(c, 'missed')}>{t('checkin.missed')}</button>
            </div>
          </div>
        )
      })}
      {answered > 0 && (
        <div className="row" style={{ marginTop: 8 }}>
          <small>{t('checkin.replan_hint')}</small>
          <button onClick={onReplan}>{t('plan.replan')}</button>
        </div>
      )}
      {err && <div className="banner red" role="alert">{err}</div>}
    </div>
  )
}

// ------------------------------------------------------------------ sample data: simulate a new meeting

export function DemoMeeting({ tz, defaultStart, onAdded }: { tz: string; defaultStart: string; onAdded: () => void }) {
  const { t } = useI18n()
  const app = useApp()
  const span = useSpan(tz)
  const [items, setItems] = useState<{ id: string; start: string; end: string; label: string }[]>([])
  const [start, setStart] = useState(defaultStart)
  const [minutes, setMinutes] = useState(60)
  const [label, setLabel] = useState('')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { setStart(defaultStart) }, [defaultStart])
  useEffect(() => { get('/api/demo/busy').then((r) => setItems(r.items)).catch(() => undefined) }, [app.dataVersion])

  async function add() {
    setErr(null)
    try {
      const r = await post('/api/demo/busy', { start: zonedToIso(start, tz), minutes, label: label || null })
      setItems(r.items)
      app.toast(t('demo_meeting.added'))
      onAdded()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function clear() {
    const r = await del('/api/demo/busy', {})
    setItems(r.items)
    app.toast(t('demo_meeting.cleared'))
  }

  const ok = Number.isInteger(minutes) && minutes >= 5 && minutes <= 600
  return (
    <details className="box demo-meeting">
      <summary><b>{t('demo_meeting.title')}</b> <small className="footnote">{t('demo_meeting.hint')}</small></summary>
      <div className="fields" style={{ marginTop: 10 }}>
        <div className="field field-wide">
          <label htmlFor="dm-start">{t('demo_meeting.start')}</label>
          <DateTimeInput id="dm-start" value={start} onChange={(v) => { if (v) setStart(v) }} />
        </div>
        <div className="field">
          <label htmlFor="dm-min">{t('demo_meeting.minutes')}</label>
          <input id="dm-min" type="number" min={5} max={600} step={15} value={Number.isNaN(minutes) ? '' : minutes}
            onChange={(e) => setMinutes(e.target.valueAsNumber)} />
        </div>
        <div className="field">
          <label htmlFor="dm-label">{t('demo_meeting.label')}</label>
          <input id="dm-label" maxLength={80} value={label} placeholder={t('demo_meeting.label_ph')} onChange={(e) => setLabel(e.target.value)} />
        </div>
      </div>
      {items.length > 0 && (
        <ul className="footnote">{items.map((m) => <li key={m.id}>{span(m.start, m.end)}{m.label ? ` · ${m.label}` : ''}</li>)}</ul>
      )}
      {err && <div className="banner red" role="alert">{err}</div>}
      <div className="row">
        <button className="primary" onClick={add} disabled={!ok}>{t('demo_meeting.add')}</button>
        {items.length > 0 && <button onClick={clear}>{t('demo_meeting.clear')}</button>}
      </div>
    </details>
  )
}
