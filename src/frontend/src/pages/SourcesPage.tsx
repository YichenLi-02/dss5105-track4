import { useEffect } from 'react'
import { useApp } from '../app/context'
import { useI18n } from '../app/i18n'
import { AccountConnections } from '../components/AccountConnections'
import { DocumentLibrary } from '../components/DocumentLibrary'
import { StyleReferences } from '../components/StyleReferences'

const TABS = ['documents', 'style', 'connections'] as const

export function SourcesPage({ sub }: { sub: string }) {
  const { t } = useI18n()
  const app = useApp()
  const tab = (TABS as readonly string[]).includes(sub.split('?')[0]) ? sub.split('?')[0] : 'documents'

  useEffect(() => {
    // OAuth callback lands here with ?oauth=provider:outcome (never a token).
    const m = window.location.hash.match(/oauth=([a-z]+):([a-z_]+)/)
    if (m) {
      app.toast(t('conn.outcome.' + m[2], { provider: m[1] }))
      window.history.replaceState(null, '', '#/sources/connections')
      app.bump()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section>
      <div className="section-head">
        <div>
          <div className="page-label">SOURCES & PREFERENCES</div>
          <h1>{t('nav.sources')}</h1>
          <p className="description">{t('sources.description')}</p>
        </div>
      </div>
      <div className="filters source-tabs" role="tablist">
        {TABS.map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`pill ${tab === k ? 'active' : ''}`} onClick={() => app.go('sources/' + k)}>
            {t('sources.' + k)}
          </button>
        ))}
      </div>
      {tab === 'documents' && <DocumentLibrary />}
      {tab === 'style' && <StyleReferences />}
      {tab === 'connections' && <AccountConnections />}
    </section>
  )
}
