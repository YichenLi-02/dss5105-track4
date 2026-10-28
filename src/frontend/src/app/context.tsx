import { createContext, useContext, type ReactNode } from 'react'

export type Health = {
  status: string
  version: string
  mode: 'demo' | 'live'
  capabilities: Record<string, any>
}

export type Prefs = Record<string, any> & { revision: number; ui_language: 'zh-CN' | 'en' }

export type AppCtx = {
  health: Health | null
  prefs: Prefs | null
  reloadPrefs: () => Promise<void>
  toast: (msg: string) => void
  openPanel: (title: string, render: () => ReactNode) => void
  closePanel: () => void
  go: (route: string) => void
  dataVersion: number
  bump: () => void
  reviewCount: number
}

export const AppContext = createContext<AppCtx | null>(null)

export function useApp(): AppCtx {
  const c = useContext(AppContext)
  if (!c) throw new Error('AppContext missing')
  return c
}
