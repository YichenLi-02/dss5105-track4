// In-page two-step confirmation. Native window.confirm()/prompt() are avoided: embedded browsers
// (e.g. the VS Code preview) and "block dialogs" settings make them silently return "cancel".
import { useState, type ReactNode } from 'react'
import { useI18n } from '../app/i18n'

export function ConfirmButton({ label, message, onConfirm, className = '', confirmLabel, skip = false }: {
  label: ReactNode
  message: string
  onConfirm: () => void | Promise<void>
  className?: string
  confirmLabel?: string
  skip?: boolean // confirm without asking (e.g. nothing would be lost)
}) {
  const { t } = useI18n()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    try {
      await onConfirm()
    } finally {
      setBusy(false)
      setAsking(false)
    }
  }

  if (!asking) {
    return <button className={className} onClick={() => (skip ? run() : setAsking(true))} disabled={busy}>{label}</button>
  }
  return (
    <span className="confirm-inline" role="alertdialog" aria-label={message}>
      <span className="confirm-message">{message}</span>
      <button className="danger-btn" onClick={run} disabled={busy} autoFocus>{confirmLabel || t('common.confirm')}</button>
      <button onClick={() => setAsking(false)} disabled={busy}>{t('common.cancel')}</button>
    </span>
  )
}
