/** App state: server data (config, harnesses, sessions, workspaces), the current view, UI preferences. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { get, type Config, type HarnessInfo, type SessionInfo, type Workspace } from './api.ts'

export type View =
  | { kind: 'new'; workspace?: string }
  | { kind: 'session'; id: string }
  | { kind: 'runs'; batch?: string; run?: string }
  | { kind: 'newrun' }
  | { kind: 'harness'; engine?: string; name?: string }

export interface Prefs {
  theme: 'light' | 'dark' | 'system'
  fontSize: number
  /** DSH transcript view: completed turns fold their process ('compact', the default) or show it ('normal'). */
  display: 'normal' | 'compact'
  enter: 'send' | 'newline'
  approval: 'auto' | 'ask'
  /** DSH workspace browser View options: group by workspace or one flat list; manual or last-updated order. */
  groupBy: 'workspace' | 'flat'
  orderBy: 'manual' | 'updated'
}

const DEFAULT_PREFS: Prefs = { theme: 'system', fontSize: 14, display: 'compact', enter: 'send', approval: 'auto', groupBy: 'workspace', orderBy: 'manual' }

function loadPrefs(): Prefs {
  try {
    const stored = JSON.parse(localStorage.getItem('lab-prefs') || '{}') as Omit<Partial<Prefs>, 'display'> & { display?: string }
    return { ...DEFAULT_PREFS, ...stored,
      display: stored.display === 'full' || stored.display === 'normal' ? 'normal' : 'compact',
      theme: (localStorage.getItem('lab-theme') as Prefs['theme']) || 'system',
      fontSize: Number(localStorage.getItem('lab-font-size')) || 14 }
  } catch {
    return DEFAULT_PREFS
  }
}

export function applyTheme(theme: Prefs['theme'], fontSize: number) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  document.body.toggleAttribute('data-ds-dark-theme', dark)
  document.body.style.setProperty('--dsh-content-font-size', `${fontSize}px`)
}

function parseHash(): View {
  const parts = decodeURIComponent(location.hash.replace(/^#\/?/, '')).split('/').filter(Boolean)
  switch (parts[0]) {
    case 's': return parts[1] ? { kind: 'session', id: parts[1] } : { kind: 'new' }
    case 'runs': return { kind: 'runs', batch: parts[1], run: parts[2] }
    case 'new-run': return { kind: 'newrun' }
    case 'harness': return { kind: 'harness', engine: parts[1], name: parts[2] }
    default: return { kind: 'new' }
  }
}

export function viewHash(v: View): string {
  switch (v.kind) {
    case 'session': return `#/s/${v.id}`
    case 'runs': return '#/runs' + (v.batch ? `/${v.batch}` : '') + (v.run ? `/${v.run}` : '')
    case 'newrun': return '#/new-run'
    case 'harness': return '#/harness' + (v.engine ? `/${v.engine}/${v.name ?? ''}` : '')
    default: return '#/'
  }
}

export interface Draft { engine: 'lab' | 'dsh'; harness: string; model: string; effort: string; workspace: string }

interface Store {
  config: Config | null
  harnesses: HarnessInfo[]
  sessions: SessionInfo[]
  workspaces: Workspace[]
  view: View
  go: (v: View) => void
  refreshSessions: () => Promise<void>
  refreshWorkspaces: () => Promise<void>
  prefs: Prefs
  setPrefs: (p: Partial<Prefs>) => void
  settings: { open: boolean; section: string }
  openSettings: (section?: string) => void
  closeSettings: () => void
  draft: Draft
  setDraft: (d: Partial<Draft>) => void
  sidebarCollapsed: boolean
  setSidebarCollapsed: (v: boolean) => void
  rightOpen: boolean
  setRightOpen: (v: boolean) => void
  addingWorkspace: boolean
  setAddingWorkspace: (v: boolean) => void
}

const Ctx = createContext<Store | null>(null)

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('StoreProvider missing')
  return s
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null)
  const [harnesses, setHarnesses] = useState<HarnessInfo[]>([])
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [view, setView] = useState<View>(parseHash)
  const [prefs, setPrefsState] = useState<Prefs>(loadPrefs)
  const [settings, setSettings] = useState({ open: false, section: 'general' })
  const [draft, setDraftState] = useState<Draft>({ engine: 'lab', harness: 'standard', model: '', effort: '', workspace: '' })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.innerWidth < 900)
  const [rightOpen, setRightOpen] = useState(false)
  const [addingWorkspace, setAddingWorkspace] = useState(false)

  const refreshSessions = useCallback(async () => {
    if (!config?.play) return
    try { setSessions(await get<SessionInfo[]>('play/sessions')) } catch { /* server restarting */ }
  }, [config?.play])
  const refreshWorkspaces = useCallback(async () => {
    if (!config?.play) return
    try { setWorkspaces(await get<Workspace[]>('workspaces')) } catch { /* ignore */ }
  }, [config?.play])

  useEffect(() => {
    get<Config>('config').then(setConfig).catch(() => setConfig({ play: false } as Config))
    get<HarnessInfo[]>('harnesses').then(setHarnesses).catch(() => {})
    const onHash = () => setView(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    // Like DSH Web: narrow windows fold the sidebar into its 56px rail.
    const mq = matchMedia('(max-width: 899px)')
    const on = () => { if (mq.matches) setSidebarCollapsed(true) }
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  useEffect(() => {
    refreshSessions(); refreshWorkspaces()
    const t = setInterval(refreshSessions, 2500)
    return () => clearInterval(t)
  }, [refreshSessions, refreshWorkspaces])

  useEffect(() => {
    applyTheme(prefs.theme, prefs.fontSize)
    if (prefs.theme !== 'system') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const on = () => applyTheme('system', prefs.fontSize)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [prefs.theme, prefs.fontSize])

  const setPrefs = useCallback((p: Partial<Prefs>) => {
    setPrefsState(prev => {
      const next = { ...prev, ...p }
      try {
        localStorage.setItem('lab-theme', next.theme)
        localStorage.setItem('lab-font-size', String(next.fontSize))
        localStorage.setItem('lab-prefs', JSON.stringify({ display: next.display, enter: next.enter, approval: next.approval, groupBy: next.groupBy, orderBy: next.orderBy }))
      } catch { /* private mode */ }
      return next
    })
  }, [])

  const go = useCallback((v: View) => {
    const h = viewHash(v)
    if (location.hash !== h) location.hash = h
    setView(v)
  }, [])

  const value = useMemo<Store>(() => ({
    config, harnesses, sessions, workspaces, view, go, refreshSessions, refreshWorkspaces, prefs, setPrefs,
    settings,
    openSettings: (section = 'general') => setSettings({ open: true, section }),
    closeSettings: () => setSettings(s => ({ ...s, open: false })),
    draft, setDraft: d => setDraftState(prev => ({ ...prev, ...d })),
    sidebarCollapsed, setSidebarCollapsed, rightOpen, setRightOpen, addingWorkspace, setAddingWorkspace,
  }), [config, harnesses, sessions, workspaces, view, go, refreshSessions, refreshWorkspaces, prefs, setPrefs, settings, draft,
    sidebarCollapsed, rightOpen, addingWorkspace])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Display name of a harness, in DSH Web's "Minimal mode" style. */
export function modeLabel(engine: string, harness: string): string {
  const pretty = harness.charAt(0).toUpperCase() + harness.slice(1)
  return engine === 'dsh' ? `DSH · ${pretty} mode` : `${pretty} mode`
}
