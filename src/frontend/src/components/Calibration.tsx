// Estimate calibration on the plan page: suggestions from the student's own history. Nothing changes until the
// student accepts; an accepted change makes the current plan stale, so re-planning is offered right away.
import { useEffect, useState } from 'react'
import { del, get, patch, post } from '../api/client'
import { useApp } from '../app/context'
import { pick, useI18n } from '../app/i18n'

interface Named { task_id: string; title: string; title_en: string | null }
interface Evidence extends Named { estimate: number; actual: number; confirmed: boolean }
interface Suggestion extends Named {
  revision: number; current: number; suggested: number; ratio: number
  group: 'course' | 'deliverable' | 'all'; group_value: string | null; n: number; evidence: Evidence[]
}
interface Overrun extends Named { revision: number; estimate: number; completed: number }
interface Completion {
  checkins: number; planned_minutes: number; done_minutes: number; rate: number | null; enough: boolean
  flex_now: number; flex_suggested: number | null
}
interface Overview {
  finished_tasks: number; min_samples: number; suggestions: Suggestion[]; overruns: Overrun[]
  completion: Completion; window_days: number
}

export function EstimateCalibration({ demo, onReplan }: { demo: boolean; onReplan: () => void }) {
  const { t, locale } = useI18n()
  const app = useApp()
  const [ov, setOv] = useState<Overview | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [more, setMore] = useState<Record<string, number>>({})
  const [changed, setChanged] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { get<Overview>('/api/calibration').then(setOv).catch(() => undefined) }, [app.dataVersion])

  const name = (x: Named) => pick(locale, x.title, x.title_en)

  async function act(run: () => Promise<unknown>, message: string, affectsPlan = true) {
    setBusy(true); setErr(null)
    try {
      await run()
      app.toast(message)
      if (affectsPlan) setChanged(true)
      app.bump()
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  const decide = (s: Suggestion, decision: 'accept' | 'keep') => act(
    () => post('/api/calibration/decide', { task_id: s.task_id, expected_revision: s.revision, decision }),
    t(decision === 'accept' ? 'calib.accepted' : 'calib.kept', { task: name(s), n: s.suggested }), decision === 'accept')

  const overrun = (o: Overrun, finished: boolean) => act(
    () => post('/api/calibration/overrun', { task_id: o.task_id, expected_revision: o.revision, finished,
      more_minutes: finished ? null : more[o.task_id] ?? 60 }),
    t(finished ? 'calib.overrun_finished' : 'calib.overrun_more', { task: name(o) }))

  const applyFlex = (to: number) => act(async () => {
    const prefs = await get('/api/preferences')
    await patch('/api/preferences', { expected_revision: prefs.revision, weekly_flex_minutes: to })
    await app.reloadPrefs()
  }, t('calib.flex_applied', { n: to }))

  const history = (on: boolean) => act(
    () => (on ? post('/api/demo/calibration-history', {}) : del('/api/demo/calibration-history', {})),
    t(on ? 'calib.demo_loaded' : 'calib.demo_cleared'), false)

  if (!ov) return null
  const c = ov.completion
  const anything = ov.suggestions.length > 0 || ov.overruns.length > 0 || ov.finished_tasks > 0 || c.checkins > 0
  if (!anything && !demo) return null // nothing to say yet: keep the page quiet

  return (
    <div className="box calibration" aria-live="polite">
      <div className="row between">
        <h3>{t('calib.title')}</h3>
        {demo && (
          <span className="row">
            <button onClick={() => history(true)} disabled={busy}>{t('calib.demo_load')}</button>
            {ov.finished_tasks > 0 && <button onClick={() => history(false)} disabled={busy}>{t('calib.demo_clear')}</button>}
          </span>
        )}
      </div>
      <p className="footnote" style={{ marginTop: 0 }}>{t('calib.intro')}</p>

      {ov.overruns.map((o) => {
        const m = more[o.task_id] ?? 60
        const ok = Number.isInteger(m) && m >= 5 && m <= 6000
        return (
          <div key={o.task_id} className="decision">
            <div>{t('calib.overrun', { task: name(o), done: o.completed, est: o.estimate })}</div>
            <div className="row" style={{ marginTop: 6 }}>
              <button onClick={() => overrun(o, true)} disabled={busy}>{t('calib.finished')}</button>
              <input type="number" min={5} max={6000} step={15} style={{ width: 90 }} aria-label={t('calib.more_minutes')}
                value={Number.isNaN(m) ? '' : m} onChange={(e) => setMore({ ...more, [o.task_id]: e.target.valueAsNumber })} />
              <button onClick={() => overrun(o, false)} disabled={busy || !ok}>{t('calib.not_finished', { n: ok ? m : '…' })}</button>
            </div>
          </div>
        )
      })}

      {ov.suggestions.map((s) => {
        const pct = Math.round(Math.abs(s.ratio - 1) * 100)
        return (
          <div key={s.task_id} className="decision">
            <div><b>{name(s)}</b>: {t('calib.suggest', { from: s.current, to: s.suggested })}</div>
            <small className="footnote" style={{ margin: 0 }}>
              {t('calib.basis.' + s.group, { n: s.n, value: s.group_value ?? '' })}
              {' '}{t(s.ratio > 1 ? 'calib.longer' : 'calib.shorter', { pct, ratio: s.ratio })}
            </small>
            <div className="row" style={{ marginTop: 6 }}>
              <button className="primary" onClick={() => decide(s, 'accept')} disabled={busy}>{t('calib.accept', { n: s.suggested })}</button>
              <button onClick={() => decide(s, 'keep')} disabled={busy}>{t('calib.keep', { n: s.current })}</button>
              <button className="link" onClick={() => setOpen(open === s.task_id ? null : s.task_id)} aria-expanded={open === s.task_id}>
                {t(open === s.task_id ? 'calib.hide_basis' : 'calib.show_basis')}
              </button>
            </div>
            {open === s.task_id && (
              <ul className="footnote">
                {s.evidence.map((e) => (
                  <li key={e.task_id}>{name(e)}: {t('calib.evidence_line', { est: e.estimate, actual: e.actual })}
                    {!e.confirmed && <> · {t('calib.logged_only')}</>}</li>
                ))}
              </ul>
            )}
          </div>
        )
      })}

      {ov.suggestions.length === 0 && ov.finished_tasks < ov.min_samples && (
        <p className="footnote">{t('calib.need_more', { n: ov.finished_tasks, min: ov.min_samples })}</p>
      )}

      {c.checkins > 0 && c.rate !== null && (
        <div className="decision">
          <div>{t('calib.completion', { n: c.checkins, days: ov.window_days, pct: Math.round(c.rate * 100), done: c.done_minutes, planned: c.planned_minutes })}</div>
          {c.flex_suggested !== null ? (
            <div className="row" style={{ marginTop: 6 }}>
              <small>{t('calib.flex_suggest', { from: c.flex_now, to: c.flex_suggested })}</small>
              <button onClick={() => applyFlex(c.flex_suggested!)} disabled={busy}>{t('calib.flex_accept', { n: c.flex_suggested })}</button>
            </div>
          ) : !c.enough && <small className="footnote" style={{ margin: 0 }}>{t('calib.completion_need_more')}</small>}
        </div>
      )}

      {changed && (
        <div className="row" style={{ marginTop: 8 }}>
          <small>{t('calib.replan_hint')}</small>
          <button onClick={() => { setChanged(false); onReplan() }}>{t('plan.replan')}</button>
        </div>
      )}
      {err && <div className="banner red" role="alert">{err}</div>}
    </div>
  )
}
