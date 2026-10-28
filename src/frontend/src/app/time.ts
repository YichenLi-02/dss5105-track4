// Time-zone helpers. Source instants keep their own zone; display zone is separate from UI language.

function offsetMinutes(tz: string, at: Date): number {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'longOffset' }).formatToParts(at)
  const name = parts.find((p) => p.type === 'timeZoneName')?.value || 'GMT'
  const m = name.match(/GMT([+-])(\d{2}):?(\d{2})?/)
  if (!m) return 0
  return (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] || 0))
}

/** "2026-10-23T15:00" interpreted in `tz` -> ISO string with explicit offset. */
export function zonedToIso(local: string, tz: string): string {
  const [d, t] = local.split('T')
  const [y, mo, da] = d.split('-').map(Number)
  const [h, mi] = (t || '00:00').split(':').map(Number)
  const guess = new Date(Date.UTC(y, mo - 1, da, h, mi))
  const off = offsetMinutes(tz, new Date(guess.getTime() - offsetMinutes(tz, guess) * 60000))
  const sign = off < 0 ? '-' : '+'
  const abs = Math.abs(off)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d}T${pad(h)}:${pad(mi)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
}

/** Wall-clock parts of an instant in a zone. */
export function partsIn(iso: string, tz: string): { date: string; time: string; weekday: number } {
  const f = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, weekday: 'short',
  }).formatToParts(new Date(iso))
  const g = (t: string) => f.find((p) => p.type === t)?.value || ''
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(g('weekday'))
  return { date: `${g('year')}-${g('month')}-${g('day')}`, time: `${g('hour') === '24' ? '00' : g('hour')}:${g('minute')}`, weekday: wd }
}

export function nowIso(): string {
  return new Date().toISOString()
}

export function uuid(): string {
  return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36)
}
