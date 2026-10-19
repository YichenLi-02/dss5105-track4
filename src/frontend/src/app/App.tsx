import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { get, patch } from '../api/client'
import { Panel } from '../components/Panel'
import { MailPage } from '../pages/MailPage'
import { TasksPage } from '../pages/TasksPage'
import { PlanPage } from '../pages/PlanPage'
import { CollaborationPage } from '../pages/CollaborationPage'
import { ReviewPage } from '../pages/ReviewPage'
import { SourcesPage } from '../pages/SourcesPage'
import { SettingsPanel } from '../pages/SettingsPanel'
import { AppContext, type Health, type Prefs } from './context'
import { I18nProvider, translate, type Locale } from './i18n'

const PAGES = ['mail', 'tasks', 'plan', 'collaboration', 'review', 'sources'] as const
type Page = (typeof PAGES)[number]

function parseHash(): { page: Page; sub: string } {
  const [, page, sub] = (window.location.hash || '#/mail').split('/')
  return { page: (PAGES as readonly string[]).includes(page) ? (page as Page) : 'mail', sub: sub || '' }
}

export function App() {
  const [route, setRoute] = useState(parseHash)
  const [health, setHealth] = useState<Health | null>(null)
  const [prefs, setPrefs] = useState<Prefs | null>(null)
  const [locale, setLocaleState] = useState<Locale>('zh-CN')
  const [panel, setPanel] = useState<{ title: string; render: () => ReactNode } | null>(null)
  const [toastMsg, setToast] = useState<string | null>(null)
  const [dataVersion, setDataVersion] = useState(0)
  const [reviewCount, setReviewCount] = useState(0)
  const [bootError, setBootError] = useState<string | null>(null)
  const toastTimer = useRef<number>(0)

  useEffect(() => {
    const onHash = () => { setRoute(parseHash()); setPanel(null) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const reloadPrefs = useCallback(async () => {
    const p = await get<Prefs>('/api/preferences')
    setPrefs(p)
    setLocaleState(p.ui_language)
  }, [])

  useEffect(() => {
    get<Health>('/api/health').then(setHealth).catch((e) => setBootError(String(e.message || e)))
    reloadPrefs().catch((e) => setBootError(String(e.message || e)))
  }, [reloadPrefs])

  useEffect(() => {
    get('/api/proposals?status=pending_review,blocked')
      .then((r) => setReviewCount(r.total))
      .catch(() => undefined)
  }, [dataVersion])

  // Header status reflects what is really connected, not a fixed "offline" label.
  const [live, setLive] = useState<{ mail: string[]; model: string | null }>({ mail: [], model: null })
  useEffect(() => {
    Promise.all([get('/api/connections'), get('/api/model/status')])
      .then(([c, m]) => setLive({
        mail: c.items.filter((x: any) => x.provider !== 'local_jsonl' && x.status === 'connected' && x.capabilities?.read_mail)
          .map((x: any) => `${x.provider === 'google' ? 'Gmail' : 'Outlook'} · ${x.account_label}`),
        model: m.enabled ? m.model : null,
      }))
      .catch(() => undefined)
  }, [dataVersion, prefs?.revision])
  // Tell an open tab when the server has a newer UI build (otherwise old code keeps running until a hard refresh).
  const [staleUi, setStaleUi] = useState(false)
  useEffect(() => {
    const mine = (document.querySelector('script[type="module"][src*="/assets/index-"]') as HTMLScriptElement | null)?.src || ''
    if (!mine) return // Vite dev server: hot reload handles this
    const check = () => get<Health>('/api/health').then((h) => {
      const b = h.capabilities.ui_build
      if (b && !mine.endsWith(b)) setStaleUi(true)
    }).catch(() => undefined)
    const id = window.setInterval(check, 60000)
    window.addEventListener('focus', check)
    return () => { window.clearInterval(id); window.removeEventListener('focus', check) }
  }, [])
  const writesOn = health?.mode === 'live' && !!health?.capabilities.external_writes_env_enabled && !!prefs?.enable_external_writes

  useEffect(() => {
    document.documentElement.lang = locale
    document.title = translate(locale, 'app.title')
  }, [locale])

  const setLocale = useCallback(
    async (l: Locale) => {
      setLocaleState(l)
      if (prefs) {
        try {
          setPrefs(await patch<Prefs>('/api/preferences', { expected_revision: prefs.revision, ui_language: l }))
        } catch {
          await reloadPrefs()
        }
      }
    },
    [prefs, reloadPrefs],
  )

  const toast = useCallback((msg: string) => {
    setToast(msg)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 4200)
  }, [])

  const ctx = useMemo(
    () => ({
      health, prefs, reloadPrefs, toast, reviewCount, dataVersion,
      openPanel: (title: string, render: () => ReactNode) => setPanel({ title, render }),
      closePanel: () => setPanel(null),
      go: (r: string) => { window.location.hash = '#/' + r },
      bump: () => setDataVersion((v) => v + 1),
    }),
    [health, prefs, reloadPrefs, toast, reviewCount, dataVersion],
  )
  const t = (k: string, p?: Record<string, string | number>) => translate(locale, k, p)

  return (
    <I18nProvider locale={locale} setLocale={setLocale}>
      <AppContext.Provider value={ctx}>
        <div className="app">
          <header className="topbar">
            <div className="brand">
              {t('app.title')}
              <small>Beta</small>
            </div>
            <div className="account" role="status">
              <span className="dot" aria-hidden="true" />
              {!health ? t('common.loading')
                : live.mail.length ? t('header.connected_readonly', { accounts: live.mail.join(' / ') })
                : t('header.mode_demo')}
              {live.model && <> · {t('header.smart_on')}</>}
            </div>
            <div className="top-actions">
              <button onClick={() => setPanel({ title: t('settings.title'), render: () => <SettingsPanel /> })}>{t('header.settings')}</button>
              <button onClick={() => setLocale(locale === 'zh-CN' ? 'en' : 'zh-CN')} aria-label={t('header.switch_language')}>
                {locale === 'zh-CN' ? 'EN' : '中文'}
              </button>
            </div>
          </header>
          <nav className="nav" aria-label={t('nav.label')}>
            {PAGES.map((p) => (
              <button key={p} className={route.page === p ? 'active' : ''} aria-current={route.page === p ? 'page' : undefined}
                onClick={() => ctx.go(p)}>
                {t('nav.' + p)}
                {p === 'review' && <span className="count">{reviewCount}</span>}
              </button>
            ))}
            <span className="mode mode-note">{t(writesOn ? 'header.mode_note_live' : 'header.mode_note_demo')}</span>
          </nav>
          {bootError && <div className="banner red" role="alert">{t('app.boot_error')}: {bootError}</div>}
          {staleUi && (
            <div className="banner warning row between" role="status">
              <span>{t('app.ui_updated')}</span>
              <button className="primary" onClick={() => window.location.reload()}>{t('app.reload')}</button>
            </div>
          )}
          <main>
            {route.page === 'mail' && <MailPage />}
            {route.page === 'tasks' && <TasksPage />}
            {route.page === 'plan' && <PlanPage />}
            {route.page === 'collaboration' && <CollaborationPage />}
            {route.page === 'review' && <ReviewPage />}
            {route.page === 'sources' && <SourcesPage sub={route.sub} />}
          </main>
        </div>
        <Panel title={panel?.title || ''} open={!!panel} onClose={() => setPanel(null)} toast={toastMsg}>
          {panel?.render()}
        </Panel>
        <div aria-live="polite" className="sr-live">
          {toastMsg && !panel && <div className="toast">{toastMsg}</div>}
        </div>
      </AppContext.Provider>
    </I18nProvider>
  )
}
