// Copies text to the clipboard so the user can paste a reply into their own mail client.
// Falls back to a hidden textarea where the Clipboard API is unavailable (embedded browsers, http).
import { useState, type MouseEvent } from 'react'
import { useI18n } from '../app/i18n'

async function writeClipboard(text: string, near: HTMLElement): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    // Inside the open modal dialog: anything outside it is inert and cannot be selected.
    near.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  }
}

export function CopyButton({ text, label, primary }: { text: string; label: string; primary?: boolean }) {
  const { t } = useI18n()
  const [state, setState] = useState<'idle' | 'done' | 'failed'>('idle')
  async function copy(e: MouseEvent<HTMLButtonElement>) {
    setState((await writeClipboard(text, e.currentTarget.parentElement || document.body)) ? 'done' : 'failed')
    window.setTimeout(() => setState('idle'), 2000)
  }
  return (
    <button type="button" className={primary ? 'primary' : undefined} onClick={copy} disabled={!text.trim()} aria-live="polite">
      {state === 'done' ? t('copy.done') : state === 'failed' ? t('copy.failed') : label}
    </button>
  )
}
