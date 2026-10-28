// One reusable side panel (details / sources / drafts / review). Escape only closes the view;
// it never approves or executes anything. Focus returns to the element that opened it.
import { useEffect, useRef, type ReactNode } from 'react'
import { useI18n } from '../app/i18n'

export function Panel({ title, open, onClose, children, toast }: { title: string; open: boolean; onClose: () => void; children: ReactNode; toast?: string | null }) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<Element | null>(null)
  const { t } = useI18n()

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) {
      opener.current = document.activeElement
      d.showModal()
      d.querySelector<HTMLElement>('.panel-body')?.scrollTo(0, 0)
    } else if (!open && d.open) {
      d.close()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="panel"
      aria-labelledby="panel-title"
      onClose={() => {
        onClose()
        if (opener.current instanceof HTMLElement) opener.current.focus()
      }}
    >
      <div className="panel-top">
        <h2 id="panel-title">{title}</h2>
        <button className="subtle" onClick={() => ref.current?.close()} autoFocus>
          {t('common.close')}
        </button>
      </div>
      <div className="panel-body">{open ? children : null}</div>
      {/* The modal sits in the top layer, so toasts are shown inside it while it is open. */}
      {open && toast && <div className="toast panel-toast" role="status">{toast}</div>}
    </dialog>
  )
}
