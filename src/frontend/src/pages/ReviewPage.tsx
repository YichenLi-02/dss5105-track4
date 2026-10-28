import { useEffect, useState } from 'react'
import { get } from '../api/client'
import type { Proposal } from '../api/types'
import { useApp } from '../app/context'
import { fmtDateTime, useI18n } from '../app/i18n'
import { ReviewDialog } from '../components/ReviewDialog'
import { StatusTag } from '../components/Tags'

export function ReviewPage() {
  const { t, locale } = useI18n()
  const app = useApp()
  const [items, setItems] = useState<Proposal[] | null>(null)

  useEffect(() => {
    get('/api/proposals').then((r) => setItems(r.items)).catch(() => setItems([]))
  }, [app.dataVersion])

  if (!items) return <div className="empty"><p>{t('common.loading')}</p></div>
  const open = items.filter((p) => ['pending_review', 'blocked'].includes(p.status))
  const done = items.filter((p) => !['pending_review', 'blocked'].includes(p.status))
  const Row = ({ p }: { p: Proposal }) => (
    <div className="review-row">
      <div>
        <b>{t('op.' + p.operation)}</b> <span className="tag">{t(p.mode === 'demo' ? 'review.mode_demo' : 'review.mode_live')}</span><br />
        <small className="footnote">
          {p.operation === 'send_email' && `${p.payload.subject} → ${(p.payload.to || []).join(', ') || '—'}`}
          {p.operation === 'send_chat' && p.payload.body?.slice(0, 80)}
          {p.operation === 'create_study_events' && t('review.events_n', { n: p.payload.events?.length ?? 0 })}
          {' · '}{fmtDateTime(locale, p.created_at)}
        </small>
      </div>
      <StatusTag status={p.status} />
      <button onClick={() => app.openPanel(t('review.title'), () => <ReviewDialog id={p.id} />)}>{t('review.open')}</button>
    </div>
  )
  return (
    <section>
      <div className="section-head">
        <div>
          <div className="page-label">REVIEW</div>
          <h1>{t('review.page_title')}</h1>
          <p className="description">{t('review.page_description')}</p>
        </div>
      </div>
      <div className="box">
        <h2>{t('review.open_list')} <span className="tag">{open.length}</span></h2>
        {open.length === 0 ? <p className="footnote">{t('review.none_open')}</p> : open.map((p) => <Row key={p.id} p={p} />)}
      </div>
      {done.length > 0 && (
        <details className="box">
          <summary><b>{t('review.history')}</b> <span className="tag">{done.length}</span></summary>
          {done.map((p) => <Row key={p.id} p={p} />)}
        </details>
      )}
    </section>
  )
}
