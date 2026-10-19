// Explicit t(key, params). Only interface text is translated: mail bodies, evidence quotes,
// style samples, chat text and anything the user typed stay in their original language.
import { createContext, useContext, useMemo, type ReactNode } from 'react'
import zh from '../locales/zh-CN.json'
import en from '../locales/en.json'

export type Locale = 'zh-CN' | 'en'
const DICTS: Record<Locale, Record<string, string>> = { 'zh-CN': zh, en }

type Ctx = { locale: Locale; t: (key: string, params?: Record<string, string | number>) => string; setLocale: (l: Locale) => void }
const I18nContext = createContext<Ctx | null>(null)

export function translate(locale: Locale, key: string, params?: Record<string, string | number>): string {
  let s = DICTS[locale][key] ?? DICTS['zh-CN'][key] ?? key
  if (params) for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v))
  return s
}

export function I18nProvider({ locale, setLocale, children }: { locale: Locale; setLocale: (l: Locale) => void; children: ReactNode }) {
  const value = useMemo<Ctx>(() => ({ locale, setLocale, t: (k, p) => translate(locale, k, p) }), [locale, setLocale])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): Ctx {
  const c = useContext(I18nContext)
  if (!c) throw new Error('I18nProvider missing')
  return c
}

// Dates/numbers via Intl; the time zone shown is explicit and independent of the UI language.
export function fmtDateTime(locale: Locale, iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone,
  }).format(d)
}

/** App-provided labels with an English version follow the UI language; source text never does. */
export function pick(locale: Locale, zh: string | null | undefined, en: string | null | undefined): string {
  return (locale === 'en' && en) || zh || en || ''
}

/** Summary of a mail: an English mail keeps its English summary (no translation); otherwise follow the UI. */
export function mailSummary(locale: Locale, m: { mail_language?: string; summary: string; summary_en?: string | null }): string {
  return m.mail_language === 'en' && m.summary_en ? m.summary_en : pick(locale, m.summary, m.summary_en)
}

export function fmtDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : ''
}
