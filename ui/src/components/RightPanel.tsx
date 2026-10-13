/** Right column: DSH SidebarRight with a Files tab (workspace tree) and file preview tabs. */
import { useEffect, useMemo, useState } from 'react'
import { IconCloseOutline16, IconFolderClose16, IconFolderOpen16, IconPanelLeftOutline16, IconRefreshOutline14 } from '../dsh/icons.tsx'
import side from '../dsh/css/SidebarRight.module.css'
import dock from '../dsh/css/dockkit.module.css'
import files from '../dsh/css/FilesBody.module.css'
import preview from '../dsh/css/TextPreview.module.css'
import { get, getText, type FileEntry, type SessionInfo } from '../lib/api.ts'
import { cx } from '../lib/format.ts'
import { useStore } from '../lib/store.tsx'

interface Node { name: string; path: string; dir: boolean; children: Node[]; bytes?: number }

function tree(entries: FileEntry[]): Node[] {
  const root: Node = { name: '', path: '', dir: true, children: [] }
  for (const e of entries) {
    const parts = e.path.split('/')
    let cur = root
    parts.forEach((p, i) => {
      const path = parts.slice(0, i + 1).join('/')
      let next = cur.children.find(c => c.name === p)
      if (!next) { next = { name: p, path, dir: i < parts.length - 1, children: [], bytes: i === parts.length - 1 ? e.bytes : undefined }; cur.children.push(next) }
      cur = next
    })
  }
  const sort = (n: Node) => { n.children.sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)); n.children.forEach(sort) }
  sort(root)
  return root.children
}

export function RightPanel({ session }: { session: SessionInfo | null }) {
  const s = useStore()
  const [list, setList] = useState<FileEntry[]>([])
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [tabs, setTabs] = useState<string[]>([])
  const [active, setActive] = useState<string>('files')
  const [content, setContent] = useState<Record<string, string | null>>({})
  const load = () => { if (session) get<FileEntry[]>(`play/${session.id}/files`).then(setList).catch(() => setList([])) }
  useEffect(() => { setTabs([]); setActive('files'); setContent({}); load() }, [session?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [session?.updated]) // eslint-disable-line react-hooks/exhaustive-deps
  const nodes = useMemo(() => tree(list), [list])
  const openFile = async (path: string) => {
    if (!tabs.includes(path)) setTabs([...tabs, path])
    setActive(path)
    const text = session ? await getText(`play/${session.id}/file?path=${encodeURIComponent(path)}`) : null
    setContent(c => ({ ...c, [path]: text }))
  }
  const closeTab = (path: string) => { setTabs(tabs.filter(t => t !== path)); if (active === path) setActive('files') }
  const level = (ns: Node[]) => ns.map(n => n.dir
    ? (
      <li key={n.path} className={files.item}>
        <button type="button" className={files.row} aria-expanded={!!open[n.path]} onClick={() => setOpen(o => ({ ...o, [n.path]: !o[n.path] }))}>
          {open[n.path] ? <IconFolderOpen16 className={files.icon} /> : <IconFolderClose16 className={files.icon} />}
          <span className={files.name}>{n.name}</span>
        </button>
        {open[n.path] && <ul className={files.level}>{level(n.children)}</ul>}
      </li>
    )
    : (
      <li key={n.path} className={files.item}>
        <button type="button" className={files.row} onClick={() => openFile(n.path)} title={`${n.bytes ?? 0} B`}>
          <span className={files.fileIcon} style={{ width: 16 }} />
          <span className={files.name}>{n.name}</span>
        </button>
      </li>
    ))
  const dir = session?.workdir ?? ''
  const name = dir.split('/').pop() ?? ''
  return (
    <div className={side.panel} data-sidebar-right-open="" style={{ width: 'min(400px, 34vw)' }}>
      <div className={side.panelBody}>
        <div className={dock.surface}>
          <section className={dock.pane}>
            <div className={dock.tabStrip} role="tablist">
              <div className={dock.stripTabs} role="presentation">
                {['files', ...tabs].map(t => (
                  <div key={t} className={cx(dock.tab, active === t && dock.tabActive)} role="tab" aria-selected={active === t} onClick={() => setActive(t)}>
                    <span className={dock.tabTitle}>{t === 'files' ? 'Files' : t.split('/').pop()}</span>
                    {t !== 'files' && <button type="button" className={dock.tabClose} aria-label="Close tab" onClick={e => { e.stopPropagation(); closeTab(t) }}><IconCloseOutline16 size={12} /></button>}
                  </div>
                ))}
              </div>
              <div className={dock.stripFill} />
              <div className={dock.stripChrome}>
                <button type="button" className={side.iconButton} aria-label="Collapse right sidebar" onClick={() => s.setRightOpen(false)}>
                  <IconPanelLeftOutline16 className={side.collapseGlyph} />
                </button>
              </div>
            </div>
            <div className={dock.paneBody}>
              {!session && <p className={dock.empty}>Open a session to see its workspace</p>}
              {session && active === 'files' && (
                <div className={files.root}>
                  <div className={files.header}>
                    <div className={files.path} title={dir}>
                      <span className={files.pathText}><span className={files.pathDirectory}>{dir.slice(0, dir.length - name.length)}</span><span className={files.pathName}>{name}</span></span>
                    </div>
                    <button type="button" className={files.tool} aria-label="Refresh" onClick={load}><IconRefreshOutline14 /></button>
                  </div>
                  <div className={files.body}>
                    <ul className={files.level}>{nodes.length ? level(nodes) : <li className={files.note}>Empty</li>}</ul>
                  </div>
                </div>
              )}
              {session && active !== 'files' && (
                <div className={preview.preview}>
                  <div className={preview.header}><div className={preview.path}><span className={preview.pathText}><span className={preview.pathName}>{active}</span></span></div></div>
                  <div className={preview.body}>
                    {content[active] === undefined ? <div className={preview.status}>Loading…</div>
                      : content[active] === null ? <div className={preview.status}>Cannot preview (binary or larger than 500 KB)</div>
                        : <pre className={preview.textDocument} style={{ margin: 0, padding: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12 }}>{content[active]}</pre>}
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
