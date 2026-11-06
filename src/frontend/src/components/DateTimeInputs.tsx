// Date and time fields that follow the app's UI language. Native <input type="date|datetime-local|time"> draws
// its placeholder ("年/月/日") and calendar in the browser's / OS language and ignores <html lang>, so a Chinese
// Windows showed Chinese in English mode. These keep the same value formats as the native inputs
// ("YYYY-MM-DD", "HH:MM", "YYYY-MM-DDTHH:MM"), so callers only swap the element.
import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../app/i18n'

const pad = (n: number) => String(n).padStart(2, '0')

/** Accepts 2026-11-05, 2026/11/5, 2026.11.5; returns "YYYY-MM-DD" for a real calendar date, else null. */
export function parseDate(text: string): string | null {
  const m = text.trim().match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/)
  if (!m) return null
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const dt = new Date(Date.UTC(y, mo - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null
  return `${y}-${pad(mo)}-${pad(d)}`
}

/** Accepts 9:30, 09:30, 0930; returns "HH:MM" (24 h), else null. */
export function parseTime(text: string): string | null {
  const m = text.trim().match(/^(\d{1,2}):?(\d{2})$/)
  if (!m) return null
  const [h, mi] = [Number(m[1]), Number(m[2])]
  return h < 24 && mi < 60 ? `${pad(h)}:${pad(mi)}` : null
}

function todayIso(): string {
  const n = new Date()
  return `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}`
}

type DateProps = { id?: string; value: string; onChange: (v: string) => void; ariaLabel?: string }

export function DateInput({ id, value, onChange, ariaLabel }: DateProps) {
  const { t, locale } = useI18n()
  const [text, setText] = useState(value)
  const [open, setOpen] = useState(false)
  const [view, setView] = useState(() => (value || todayIso()).slice(0, 7)) // "YYYY-MM" shown in the popup
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => setText(value), [value])
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const invalid = text.trim() !== '' && parseDate(text) === null

  function typeText(v: string) {
    setText(v)
    if (v.trim() === '') onChange('')
    else if (parseDate(v)) onChange(parseDate(v)!)
  }

  function pickDay(iso: string) {
    onChange(iso)
    setText(iso)
    setOpen(false)
  }

  const [vy, vm] = view.split('-').map(Number)
  const first = new Date(Date.UTC(vy, vm - 1, 1))
  const lead = (first.getUTCDay() + 6) % 7 // weeks start on Monday, like the weekly plan
  const daysIn = new Date(Date.UTC(vy, vm, 0)).getUTCDate()
  const cells: (string | null)[] = [...Array(lead).fill(null),
    ...Array.from({ length: daysIn }, (_, i) => `${vy}-${pad(vm)}-${pad(i + 1)}`)]
  const monthTitle = new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long', timeZone: 'UTC' }).format(first)
  const weekdays = Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(locale, { weekday: 'narrow', timeZone: 'UTC' }).format(new Date(Date.UTC(2024, 0, 1 + i))))
  const fullDate = (iso: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeZone: 'UTC' }).format(new Date(iso + 'T00:00:00Z'))
  const shift = (n: number) => {
    const d = new Date(Date.UTC(vy, vm - 1 + n, 1))
    setView(`${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`)
  }
  const today = todayIso()

  return (
    <div className="dt-input" ref={wrap} onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}>
      <div className="dt-row">
        <input id={id} type="text" inputMode="numeric" autoComplete="off" value={text} placeholder={t('date.placeholder')}
          aria-label={ariaLabel} aria-invalid={invalid} onChange={(e) => typeText(e.target.value)}
          onBlur={() => { if (invalid) setText(value) }} />
        <button type="button" className="dt-toggle" aria-label={t('date.open_calendar')} aria-expanded={open}
          onClick={() => { setView((value || today).slice(0, 7)); setOpen(!open) }}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <rect x="2" y="3" width="12" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {invalid && <small className="dt-error">{t('date.invalid')}</small>}
      {open && (
        <div className="dt-pop" role="dialog" aria-label={t('date.open_calendar')}>
          <div className="dt-head">
            <button type="button" onClick={() => shift(-1)} aria-label={t('date.prev_month')}>‹</button>
            <b>{monthTitle}</b>
            <button type="button" onClick={() => shift(1)} aria-label={t('date.next_month')}>›</button>
          </div>
          <div className="dt-grid">
            {weekdays.map((w, i) => <span key={'w' + i} className="dt-wd" aria-hidden="true">{w}</span>)}
            {cells.map((iso, i) => iso === null ? <span key={i} /> : (
              <button type="button" key={iso} onClick={() => pickDay(iso)} aria-label={fullDate(iso)} aria-pressed={iso === value}
                className={`dt-day${iso === value ? ' selected' : ''}${iso === today ? ' today' : ''}`}>{Number(iso.slice(8))}</button>
            ))}
          </div>
          <div className="dt-foot">
            <button type="button" className="link" onClick={() => pickDay(today)}>{t('date.today')}</button>
            {value && <button type="button" className="link" onClick={() => { onChange(''); setText(''); setOpen(false) }}>{t('date.clear')}</button>}
          </div>
        </div>
      )}
    </div>
  )
}

const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => `${pad(Math.floor(i / 2))}:${i % 2 ? '30' : '00'}`)

type TimeProps = { id?: string; value: string; onChange: (v: string) => void; ariaLabel?: string }

export function TimeInput({ id, value, onChange, ariaLabel }: TimeProps) {
  const { t } = useI18n()
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  const invalid = text.trim() !== '' && parseTime(text) === null
  const listId = (id || 'time') + '-options'
  return (
    <div className="dt-input">
      <input id={id} type="text" inputMode="numeric" autoComplete="off" list={listId} value={text} placeholder={t('time.placeholder')}
        aria-label={ariaLabel} aria-invalid={invalid}
        onChange={(e) => {
          setText(e.target.value)
          if (e.target.value.trim() === '') onChange('')
          else if (/^\d{1,2}:\d{2}$/.test(e.target.value.trim()) && parseTime(e.target.value)) onChange(parseTime(e.target.value)!)
        }}
        onBlur={() => {
          const v = parseTime(text)
          if (v) { setText(v); if (v !== value) onChange(v) } else if (text.trim() !== '') setText(value)
        }} />
      <datalist id={listId}>{TIME_OPTIONS.map((o) => <option key={o} value={o} />)}</datalist>
      {invalid && <small className="dt-error">{t('time.invalid')}</small>}
    </div>
  )
}

type DateTimeProps = { id?: string; value: string; onChange: (v: string) => void; defaultTime?: string }

/** "YYYY-MM-DDTHH:MM" or "". Picking a date with no time yet uses defaultTime. */
export function DateTimeInput({ id, value, onChange, defaultTime = '09:00' }: DateTimeProps) {
  const { t } = useI18n()
  const [d, tm] = value ? [value.slice(0, 10), value.slice(11, 16)] : ['', '']
  return (
    <div className="dt-pair">
      <DateInput id={id} value={d} ariaLabel={t('date.date_part')}
        onChange={(nd) => onChange(nd ? `${nd}T${tm || defaultTime}` : '')} />
      <TimeInput id={id ? id + '-time' : undefined} value={tm} ariaLabel={t('date.time_part')}
        onChange={(nt) => { if (d && nt) onChange(`${d}T${nt}`) }} />
    </div>
  )
}
