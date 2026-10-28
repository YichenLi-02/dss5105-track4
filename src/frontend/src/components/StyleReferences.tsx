// Own-writing references: only the user's authored section is shown/used. Selection is the
// permission scope for drafting; changing it invalidates pending send proposals that used it.
import { useEffect, useState } from 'react'
import { get, patch } from '../api/client'
import { useApp } from '../app/context'
import { pick, useI18n } from '../app/i18n'

export function StyleReferences() {
  const { t, locale } = useI18n()
  const app = useApp()
  const [refs, setRefs] = useState<any[] | null>(null)
  const [profile, setProfile] = useState<any>(null)
  const [ctx, setCtx] = useState('all')
  const [err, setErr] = useState<string | null>(null)

  const reload = () => Promise.all([get('/api/style-references').then(setRefs), get('/api/style-profile').then(setProfile)]).catch((e) => setErr(e.message))
  useEffect(() => { reload() }, [app.dataVersion])

  async function toggle(r: any) {
    setErr(null)
    try {
      await patch(`/api/style-references/${r.message_id}`, { expected_profile_revision: profile.revision, included: !r.included })
      app.toast(t(r.included ? 'style.excluded_toast' : 'style.included_toast', { id: r.sample_id }))
      await reload(); app.bump(); app.reloadPrefs()
    } catch (e: any) {
      setErr(e.code === 'REVISION_CONFLICT' ? t('common.revision_conflict') : e.message)
      reload()
    }
  }

  async function setLength(v: string) {
    setProfile(await patch('/api/style-profile', { expected_revision: profile.revision, length_preference: v }))
    app.reloadPrefs()
  }

  if (!refs || !profile) return <p>{err || t('common.loading')}</p>
  if (refs.length === 0) return <div className="empty"><p>{t('style.empty')}</p><button onClick={() => app.go('mail')}>{t('tasks.go_mail')}</button></div>
  const shown = refs.filter((r) => ctx === 'all' || r.context === ctx)
  return (
    <>
      <div className="banner">{t('style.banner')}</div>
      <div className="grid2">
        <div className="box">
          <h2>{t('style.profile')}</h2>
          <div className="field">
            <label htmlFor="st-len">{t('style.length')}</label>
            <select id="st-len" value={profile.length_preference} onChange={(e) => setLength(e.target.value)}>
              <option value="short">{t('style.short')}</option><option value="normal">{t('style.normal')}</option>
            </select>
          </div>
          <p className="footnote">{t('style.selected', { n: profile.selected_reference_ids.length, total: refs.length })}</p>
          <h3>{t('style.limitations')}</h3>
          <ul className="footnote">{profile.limitations.map((l: any) => (
            <li key={l.context}>{pick(locale, l.context, l.context_en)}: {l.level === 'limited'
              ? t('style.limited', { n: l.samples })
              : pick(locale, l.fallback, l.fallback_en) || t('style.unsupported')}</li>
          ))}</ul>
          <p className="footnote">{t('style.no_facts')}</p>
        </div>
        <div className="box">
          <div className="filters" role="group" aria-label={t('style.filter')}>
            {['all', 'academic', 'peer', 'correction'].map((c) => (
              <button key={c} className={`pill ${ctx === c ? 'active' : ''}`} aria-pressed={ctx === c} onClick={() => setCtx(c)}>{t('style.ctx.' + c)}</button>
            ))}
          </div>
          {err && <div className="banner red" role="alert">{err}</div>}
          {shown.map((r) => (
            <div key={r.message_id} className="decision">
              <label className="checkline">
                <input type="checkbox" checked={r.included} onChange={() => toggle(r)} disabled={!r.authorship_verified} />
                <span><b>{r.sample_id}</b> · {t('style.ctx.' + r.context)} · {pick(locale, r.function, r.function_en)}<br /><small>{r.subject}</small></span>
              </label>
              <small className="footnote">{pick(locale, r.observations, r.observations_en)}</small>
              <details><summary className="footnote">{t('style.view_excerpt')}</summary><pre>{r.authored_excerpt}</pre></details>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
