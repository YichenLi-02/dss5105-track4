import { useI18n } from '../app/i18n'

// Where a label came from is always visible: reference annotations are suggestions, not model output.
export function OriginTag({ origin }: { origin: string }) {
  const { t } = useI18n()
  return <span className={`tag ${origin === 'user' ? 'green' : ''}`} title={t('origin.' + origin + '_hint')}>{t('origin.' + origin)}</span>
}

export function StatusTag({ status }: { status: string }) {
  const { t } = useI18n()
  const cls = ['confirmed', 'completed', 'simulated', 'executed', 'feasible'].includes(status)
    ? 'green'
    : ['blocked', 'invalidated', 'failed', 'unknown', 'infeasible', 'expired', 'conflict'].includes(status)
      ? 'red'
      : 'warn'
  return <span className={`tag ${cls}`}>{t('status.' + status)}</span>
}
