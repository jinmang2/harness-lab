/** Left column: DSH SidebarRoot (brand, New Session, panels, workspace browser, Settings). */
import { useMemo, useRef, useState } from 'react'
import {
  IconArchiveOutline20, IconChecklistOutline14, IconCodeOutline16, IconEllipsisOutline16, IconFolderClose16, IconFolderOpen16,
  IconNewChatOutline16, IconPanelLeftOutline16, IconPlayOutline16, IconPlusOutline16, IconProjectAddOutline16,
  IconSearchOutline16, IconSettingsOutline16, IconTriangleRightFill14,
} from '../dsh/icons.tsx'
import css from '../dsh/css/SidebarRoot.module.css'
import wb from '../dsh/css/WorkspaceBrowser.module.css'
import rows from '../dsh/css/Rows.module.css'
import settingsCss from '../dsh/css/SettingsRoot.module.css'
import heroCss from '../dsh/css/HeroShell.module.css'
import dotCss from '../dsh/css/StateDot.module.css'
import { post, type SessionInfo } from '../lib/api.ts'
import { ago, cx } from '../lib/format.ts'
import { useStore } from '../lib/store.tsx'
import { Button, Menu, MenuItem, MenuSeparator, Modal } from './primitives.tsx'

export function LabMark({ size = 24 }: { size?: number }) {
  // Our own mark (a flask); DSH's whale logo is DeepSeek's brand and is not reused.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M9 3h6M10 3v5.2L4.6 18.1A2 2 0 0 0 6.4 21h11.2a2 2 0 0 0 1.8-2.9L14 8.2V3" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M7.2 14.5h9.6" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="10.5" cy="17.5" r="1" fill="currentColor" /><circle cx="14" cy="16.6" r=".8" fill="currentColor" />
    </svg>
  )
}

const PANELS = [
  { id: 'runs', label: 'Runs', icon: IconChecklistOutline14 },
  { id: 'newrun', label: 'New run', icon: IconPlayOutline16 },
  { id: 'harness', label: 'Harnesses', icon: IconCodeOutline16 },
] as const

export function Sidebar() {
  const s = useStore()
  const wide = !s.sidebarCollapsed
  const panel = s.view.kind === 'runs' || s.view.kind === 'newrun' || s.view.kind === 'harness' ? s.view.kind : null
  return (
    <div className={cx(css.root, !wide && css.collapsed)}>
      <div className={css.logoRow}>
        {wide && (
          <button type="button" className={cx(css.brand, css.wide)} aria-label="New session" onClick={() => s.go({ kind: 'new' })}>
            <span className={css.brandIdentity} aria-hidden="true">
              <span className={css.brandMark}><LabMark /></span>
              <span className={css.brandName}><span className={css.fallbackBrandName}>harness-lab</span></span>
            </span>
          </button>
        )}
        <button type="button" className={cx(css.iconButton, css.toggle)} aria-label={wide ? 'Collapse sidebar' : 'Open sidebar'}
          onClick={() => s.setSidebarCollapsed(wide)}>
          {!wide && <span className={css.railMark} aria-hidden="true"><LabMark /></span>}
          <IconPanelLeftOutline16 className={css.panelIcon} size={wide ? 16 : 18} />
        </button>
      </div>
      {s.config?.play && (
        <button type="button" className={css.newSession} aria-label="New session" onClick={() => s.go({ kind: 'new' })}>
          <IconNewChatOutline16 size={wide ? 14 : 18} />
          {wide && <span className={cx(css.newSessionLabel, css.wide)}>New Session</span>}
        </button>
      )}
      <nav className={css.panelList} aria-label="Experiments">
        {PANELS.filter(p => s.config?.play || p.id !== 'newrun').map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" className={cx(css.panelRow, panel === id && css.panelActive)} aria-label={label}
            aria-current={panel === id ? 'page' : undefined} onClick={() => s.go({ kind: id } as never)}>
            <span className={css.panelGlyph} aria-hidden="true"><Icon size={wide ? 16 : 18} /></span>
            {wide && <span className={cx(css.panelTitle, css.wide)}>{label}</span>}
          </button>
        ))}
      </nav>
      <div className={css.regionArea}>{s.config?.play && wide && <WorkspaceBrowser />}</div>
      <div className={css.footArea}>
        <div className={css.footerActions} />
        <div className={css.settingsArea}>
          <div className={settingsCss.triggerRow}>
            <button type="button" className={cx(settingsCss.trigger, !wide && settingsCss.rail)} aria-label="Settings" onClick={() => s.openSettings()}>
              <IconSettingsOutline16 />
              {wide && <span className={settingsCss.triggerLabel}>Settings</span>}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

const SCRATCH = ''

function WorkspaceBrowser() {
  const s = useStore()
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [closed, setClosed] = useState<Record<string, boolean>>({})
  const groups = useMemo(() => {
    const byPath = new Map<string, SessionInfo[]>()
    const registered = new Set(s.workspaces.map(w => w.path))
    for (const x of s.sessions) {
      if (query && !(x.title || '').toLowerCase().includes(query.toLowerCase())) continue
      const key = registered.has(x.workdir) ? x.workdir : SCRATCH
      byPath.set(key, [...(byPath.get(key) ?? []), x])
    }
    const out = s.workspaces.map(w => ({ path: w.path, title: w.title, missing: !w.exists, sessions: byPath.get(w.path) ?? [] }))
    out.push({ path: SCRATCH, title: 'Scratch', missing: false, sessions: byPath.get(SCRATCH) ?? [] })
    return out
  }, [s.sessions, s.workspaces, query])
  const current = s.view.kind === 'session' ? s.view.id : null

  return (
    <div className={wb.root}>
      <div className={wb.sectionHeader}>
        <span className={cx(wb.sectionLabel, wb.wide, searching && wb.sectionLabelHidden)}>Workspaces</span>
        <div className={cx(wb.searchSlot, searching && wb.searchSlotExpanded)}>
          <div className={cx(wb.search, searching && wb.searchExpanded)}>
            <button type="button" className={wb.searchButton} aria-label="Search sessions" aria-expanded={searching}
              onClick={() => { setSearching(!searching); if (searching) setQuery('') }}><IconSearchOutline16 /></button>
            <input className={wb.searchInput} type="text" placeholder="Search sessions..." value={query}
              onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') { setSearching(false); setQuery('') } }} />
          </div>
        </div>
        <div className={cx(wb.headerActions, searching && wb.headerActionsHidden)}>
          <button type="button" className={wb.iconButton} aria-label="Add workspace" title="Add workspace" onClick={() => s.setAddingWorkspace(true)}>
            <IconProjectAddOutline16 />
          </button>
        </div>
      </div>
      <div className={wb.listArea}>
        <div className={cx(wb.treeBody, wb.wide)}>
          <div className={wb.list} role="tree" aria-label="Sessions">
            {groups.map(g => (
              <div key={g.path || 'scratch'} className={wb.groupSection}>
                <WorkspaceRow title={g.title} path={g.path} missing={g.missing} open={!closed[g.path]}
                  active={g.sessions.some(x => x.id === current)} onToggle={() => setClosed(c => ({ ...c, [g.path]: !c[g.path] }))} />
                {!closed[g.path] && g.sessions.map(x => <SessionRow key={x.id} session={x} selected={x.id === current} />)}
              </div>
            ))}
            {!s.sessions.length && <div className={wb.empty}>No sessions yet</div>}
          </div>
        </div>
        <span className={wb.fade} />
      </div>
    </div>
  )
}

function WorkspaceRow({ title, path, missing, open, active, onToggle }: {
  title: string; path: string; missing: boolean; open: boolean; active: boolean; onToggle: () => void
}) {
  const s = useStore()
  const more = useRef<HTMLButtonElement>(null)
  const [menu, setMenu] = useState(false)
  const Folder = open ? IconFolderOpen16 : IconFolderClose16
  return (
    <div className={rows.projectRow} role="treeitem" aria-expanded={open} onClick={onToggle}
      title={path ? `${path}${missing ? ' (missing)' : ''}` : 'A fresh folder under runs/ for each session'}>
      <span className={cx(rows.slot, rows.folder, active && rows.folderActive)}><Folder /></span>
      <span className={cx(rows.slot, rows.chevron)}><IconTriangleRightFill14 className={cx(rows.arrow, open && rows.arrowOpen)} /></span>
      <span className={rows.projectText}><span className={rows.title}>{title}</span></span>
      <span className={rows.rowActions} onClick={e => e.stopPropagation()}>
        {path && (
          <button ref={more} type="button" className={rows.iconButton} aria-label={`Workspace actions for ${title}`} onClick={() => setMenu(!menu)}>
            <IconEllipsisOutline16 />
          </button>
        )}
        <button type="button" className={rows.iconButton} aria-label={`New session in ${title}`}
          onClick={() => { s.setDraft({ workspace: path }); s.go({ kind: 'new' }) }}>
          <IconPlusOutline16 />
        </button>
      </span>
      <Menu open={menu} onClose={() => setMenu(false)} anchor={more}>
        <MenuItem onSelect={() => { navigator.clipboard?.writeText(path); setMenu(false) }}>Copy path</MenuItem>
        <MenuSeparator />
        <MenuItem danger onSelect={async () => {
          setMenu(false)
          try { await post('workspaces/remove', { path }); s.refreshWorkspaces() } catch (e) { alert((e as Error).message) }
        }}>Remove from list</MenuItem>
      </Menu>
    </div>
  )
}

function SessionRow({ session, selected }: { session: SessionInfo; selected: boolean }) {
  const s = useStore()
  const more = useRef<HTMLButtonElement>(null)
  const [menu, setMenu] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(session.title)
  const running = session.status === 'running' || session.status === 'waiting'
  const rename = async () => {
    setRenaming(false)
    if (title.trim() && title !== session.title) { await post(`play/${session.id}/rename`, { title }); s.refreshSessions() }
  }
  return (
    <div className={cx(rows.sessionRow, selected && rows.selected)} role="treeitem" onClick={() => s.go({ kind: 'session', id: session.id })}
      title={`${session.engine}/${session.harness} · ${session.model}${session.status === 'archived' ? ' · read-only (earlier run)' : ''}`}>
      <span className={rows.slot}>
        {running && <span className={dotCss.dot} data-state={session.status === 'waiting' ? 'warning' : 'running'} style={{ width: 8, height: 8, color: session.status === 'waiting' ? undefined : 'var(--dsw-static-deepseek-450)' }} />}
        {session.status === 'archived' && <IconArchiveOutline20 size={12} />}
      </span>
      {renaming
        ? <input className={rows.renameInput} autoFocus value={title} onClick={e => e.stopPropagation()} onChange={e => setTitle(e.target.value)}
            onBlur={rename} onKeyDown={e => { if (e.key === 'Enter') rename(); if (e.key === 'Escape') setRenaming(false) }} />
        : <span className={rows.title}>{session.title || 'New Session'}</span>}
      <span className={rows.time}>{ago(session.updated)}</span>
      <span className={rows.rowActions} onClick={e => e.stopPropagation()}>
        <button ref={more} type="button" className={rows.iconButton} aria-label={`Session actions for ${session.title}`} onClick={() => setMenu(!menu)}>
          <IconEllipsisOutline16 />
        </button>
      </span>
      <Menu open={menu} onClose={() => setMenu(false)} anchor={more}>
        <MenuItem onSelect={() => { setMenu(false); setTitle(session.title); setRenaming(true) }}>Rename</MenuItem>
        <MenuItem onSelect={() => { setMenu(false); s.go({ kind: 'runs', batch: session.batch, run: session.run_id }) }}>Open in Runs</MenuItem>
        <MenuItem onSelect={() => { setMenu(false); location.href = `/api/export/${session.batch}/${session.run_id}` }}>Download session log</MenuItem>
      </Menu>
    </div>
  )
}

export function AddWorkspaceModal() {
  const { addingWorkspace: open, setAddingWorkspace } = useStore()
  const onClose = () => setAddingWorkspace(false)
  return <AddWorkspaceForm open={open} onClose={onClose} />
}

function AddWorkspaceForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useStore()
  const [path, setPath] = useState('')
  const [error, setError] = useState('')
  const submit = async () => {
    try {
      await post('workspaces/add', { path })
      await s.refreshWorkspaces()
      setPath(''); setError(''); onClose()
    } catch (e) { setError((e as Error).message) }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add workspace" description="Sessions in a workspace run with that folder as their working directory."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" className={heroCss.modalAction} onClick={submit} disabled={!path.trim()}>Add</Button></>}>
      <input className={heroCss.modalInput} autoFocus placeholder="/absolute/path or ~/project" value={path}
        onChange={e => setPath(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') submit() }} />
      {error && <div className={heroCss.modalError}>{error}</div>}
    </Modal>
  )
}
