// Preferences are suggestions the user controls; nothing here is inferred from the mailbox.
import { useEffect, useState } from 'react'
import { patch } from '../api/client'
import { useApp } from '../app/context'
import { useI18n } from '../app/i18n'

const NUMS = ['daily_cap_minutes', 'session_min_minutes', 'session_target_minutes', 'session_max_minutes', 'break_minutes',
  'deadline_buffer_minutes', 'weekly_flex_minutes'] as const

export function SettingsPanel() {
  const { t } = useI18n()
  const app = useApp()
  const [f, setF] = useState<Record<string, any> | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (app.prefs) setF({ ...app.prefs })
  }, [app.prefs])
  if (!f) return <p>{t('common.loading')}</p>

  async function save() {
    setErr(null)
    try {
      const body: Record<string, any> = { expected_revision: app.prefs!.revision }
      for (const k of ['display_timezone', 'day_start', 'day_end', 'allow_model_processing', 'enable_external_writes', 'large_amount_threshold', ...NUMS]) {
        if (f![k] !== app.prefs![k]) body[k] = (NUMS.includes(k as any) || k === 'large_amount_threshold') ? Number(f![k]) : f![k]
      }
      if (f!.show_demo_data !== app.prefs!.show_demo_data) {
        if (f!.show_demo_data === null || f!.show_demo_data === undefined) body.show_demo_data_auto = true
        else body.show_demo_data = f!.show_demo_data
      }
      await patch('/api/preferences', body)
      await app.reloadPrefs()
      app.bump()
      app.toast(t('settings.saved'))
    } catch (e: any) {
      setErr(e.code === 'REVISION_CONFLICT' ? t('common.revision_conflict') : `${e.message} ${e.details?.join('; ') || ''}`)
    }
  }
  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  const go = (r: string) => { app.closePanel(); app.go(r) }

  return (
    <>
      <p className="description">{t('settings.intro')}</p>
      <h3>{t('settings.planning')}</h3>
      <div className="fields">
        <div className="field"><label htmlFor="s-tz">{t('settings.display_timezone')}</label><input id="s-tz" value={f.display_timezone} onChange={(e) => set('display_timezone', e.target.value)} /></div>
        <div className="field"><label htmlFor="s-ds">{t('settings.day_start')}</label><input id="s-ds" type="time" value={f.day_start} onChange={(e) => set('day_start', e.target.value)} /></div>
        <div className="field"><label htmlFor="s-de">{t('settings.day_end')}</label><input id="s-de" type="time" value={f.day_end} onChange={(e) => set('day_end', e.target.value)} /></div>
        {NUMS.map((k) => (
          <div className="field" key={k}><label htmlFor={'s-' + k}>{t('settings.' + k)}</label>
            <input id={'s-' + k} type="number" min={0} step={5} value={f[k]} onChange={(e) => set(k, e.target.value)} /></div>
        ))}
      </div>
      <p className="footnote">{t('settings.stale_note')}</p>
      <h3>{t('settings.demo_data')}</h3>
      <div className="field"><label htmlFor="s-demo">{t('settings.demo_data_label')}</label>
        <select id="s-demo" value={f.show_demo_data === null || f.show_demo_data === undefined ? 'auto' : f.show_demo_data ? 'show' : 'hide'}
          onChange={(e) => set('show_demo_data', e.target.value === 'auto' ? null : e.target.value === 'show')}>
          <option value="auto">{t('settings.demo_auto')}</option><option value="show">{t('settings.demo_show')}</option><option value="hide">{t('settings.demo_hide')}</option>
        </select><small>{t('settings.demo_hint')}</small></div>
      <h3>{t('settings.importance')}</h3>
      <p className="footnote">{t('settings.importance_rule')}</p>
      <div className="field"><label htmlFor="s-amt">{t('settings.large_amount_threshold')}</label>
        <input id="s-amt" type="number" min={0} step={50} value={f.large_amount_threshold ?? 200} onChange={(e) => set('large_amount_threshold', e.target.value)} /></div>
      <h3>{t('settings.processing')}</h3>
      <label className="checkline">
        <input type="checkbox" checked={!!f.allow_model_processing} onChange={(e) => set('allow_model_processing', e.target.checked)} />
        <span>{t('settings.allow_model')}<br /><small>{t('settings.allow_model_hint')}</small></span>
      </label>
      <label className="checkline">
        <input type="checkbox" checked={!!f.enable_external_writes} onChange={(e) => set('enable_external_writes', e.target.checked)} />
        <span>{t('settings.enable_writes')}<br /><small>{t('settings.enable_writes_hint')}</small></span>
      </label>
      {err && <div className="banner red" role="alert">{err}</div>}
      <div className="panel-actions"><button className="primary" onClick={save}>{t('settings.save')}</button></div>
      <h3 style={{ marginTop: 22 }}>{t('settings.shortcuts')}</h3>
      <div className="row">
        <button onClick={() => go('sources/documents')}>{t('sources.documents')}</button>
        <button onClick={() => go('sources/style')}>{t('sources.style')}</button>
        <button onClick={() => go('sources/connections')}>{t('sources.connections')}</button>
      </div>
    </>
  )
}
