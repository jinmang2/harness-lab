/** Trajectory tab: DSH toolbar + Input/Model/Tools timeline + ledger table with a details pane. */
import { useMemo, useState } from 'react'
import { IconCloseOutline16, IconSearchOutline16 } from '../dsh/icons.tsx'
import views from '../dsh/css/views.module.css'
import bar from '../dsh/css/TrajectoryToolbar.module.css'
import tl from '../dsh/css/TrajectoryTimeline.module.css'
import tb from '../dsh/css/TrajectoryTable.module.css'
import type { PlayEvent, TraceEvent } from '../lib/api.ts'
import { cx, num } from '../lib/format.ts'

export interface TrajRow {
  id: string
  kind: 'system' | 'user' | 'context' | 'message' | 'tool' | 'subtool'
  tag: string
  content: string
  t0?: number
  t1?: number
  turn?: number
  error?: boolean
  /** Assistant request rows: the model it ran on (session start, then "model" switches) and its tool calls. */
  model?: string
  toolCalls?: number
  pending?: boolean
  detail: unknown
}

const TAG_CLASS: Record<string, string> = {
  system: 'systemNeutral', user: 'user', context: 'contextGreen', message: 'assistantVioletBright', tool: 'toolAmber', subtool: 'toolAmber',
}

/** Rows from a chat session's live events. */
export function rowsFromEvents(events: PlayEvent[]): TrajRow[] {
  const rows: TrajRow[] = []
  const open = new Map<string, TrajRow>()
  let turn = 0
  let model: string | undefined
  let request: TrajRow | undefined
  for (const ev of events) {
    const rid = String(ev.run_id ?? '')
    switch (ev.type) {
      case 'session': case 'model':
        if (typeof ev.model === 'string') model = ev.model
        break
      case 'request':
        rows.push({ id: 'sys', kind: 'system', tag: 'SYSTEM', content: 'Initial System Prompt', detail: { system: ev.system, tools: ev.tools } })
        break
      case 'user':
        turn += 1
        // A goal round's prompt is injected context, not a user message (DSH CONTEXT row).
        rows.push(ev.source === 'goal'
          ? { id: 'u' + ev.seq, kind: 'context', tag: 'CONTEXT', content: String(ev.text ?? ''), t0: ev.t, t1: ev.t + 0.05, turn, detail: { source: 'goal', text: ev.text } }
          : { id: 'u' + ev.seq, kind: 'user', tag: 'USER', content: String(ev.text ?? ''), t0: ev.t, t1: ev.t + 0.05, turn, detail: { text: ev.text, attachments: ev.attachments } })
        break
      case 'steer':
        rows.push({ id: 's' + ev.seq, kind: 'user', tag: 'USER', content: String(ev.text ?? ''), t0: ev.t, t1: ev.t + 0.05, detail: { text: ev.text, attachments: ev.attachments } })
        break
      case 'llm_start': {
        const r: TrajRow = { id: rid, kind: ev.nested ? 'subtool' : 'message', tag: ev.nested ? 'SUBAGENT' : 'ASSISTANT', content: '', t0: ev.t,
          model, toolCalls: 0, pending: true, detail: {} }
        open.set(rid, r); rows.push(r)
        if (!ev.nested) request = r
        break
      }
      case 'reasoning': case 'token': {
        const r = open.get(rid)
        if (r) {
          const d = r.detail as Record<string, string>
          const k = ev.type === 'reasoning' ? 'reasoning' : 'text'
          d[k] = (d[k] ?? '') + String(ev.text ?? '')
          r.content = (d.text || d.reasoning || '').replace(/\s+/g, ' ').slice(0, 200)
        }
        break
      }
      case 'llm_end': {
        const r = open.get(rid)
        if (r) { r.t1 = ev.t; r.pending = false; (r.detail as Record<string, unknown>).usage = ev.usage }
        break
      }
      case 'error':
        if (request?.pending) { request.pending = false; request.error = true }
        break
      case 'tool_start': {
        if (!ev.nested && request) request.toolCalls = (request.toolCalls ?? 0) + 1
        const r: TrajRow = { id: rid, kind: 'tool', tag: 'TOOL', content: `${ev.name} ${typeof ev.args === 'string' ? ev.args : JSON.stringify(ev.args)}`, t0: ev.t, detail: { name: ev.name, args: ev.args } }
        open.set(rid, r); rows.push(r)
        break
      }
      case 'tool_end': {
        const r = open.get(rid)
        if (r) {
          r.t1 = ev.t; r.error = Boolean(ev.error)
          ;(r.detail as Record<string, unknown>).result = ev.preview
          r.content += `  → ${String(ev.preview ?? '').replace(/\s+/g, ' ').slice(0, 120)}`
        }
        break
      }
      case 'interrupt': case 'decision':
        rows.push({ id: 'i' + ev.seq, kind: 'context', tag: 'APPROVAL', content: ev.type === 'decision' ? `decision: ${ev.decision}` : 'approval requested', t0: ev.t, t1: ev.t + 0.05, detail: ev })
        break
    }
  }
  return rows
}

/** Rows from a stored trace (lab/trace.py events): batch runs have no chat events. */
export function rowsFromTrace(events: TraceEvent[]): TrajRow[] {
  const rows: TrajRow[] = []
  const header = events.find(e => e.kind === 'run')
  if (header?.prompt) rows.push({ id: 'u0', kind: 'user', tag: 'USER', content: String(header.prompt), turn: 1, detail: header })
  let i = 0
  for (const e of events) {
    i += 1
    const t = typeof e.t === 'number' ? e.t : undefined
    const ms = typeof e.latency_ms === 'number' ? e.latency_ms : 0
    if (e.kind === 'llm') {
      const inp = Number(e.input_uncached ?? 0) + Number(e.cache_read ?? 0) + Number(e.cache_write ?? 0)
      const req = (e.requested_tools as string[] | undefined) ?? []
      rows.push({ id: 'l' + i, kind: 'message', tag: 'ASSISTANT', t0: t, t1: t !== undefined ? t + ms / 1000 : undefined,
        content: `step ${e.step} · in ${num(inp)} (cached ${num(e.cache_read)}) · out ${num(e.output)}${req.length ? ' · → ' + req.join(', ') : ''}`, detail: e })
    } else if (e.kind === 'tool') {
      rows.push({ id: 't' + i, kind: 'tool', tag: 'TOOL', error: Boolean(e.error), t0: t, t1: t !== undefined ? t + ms / 1000 : undefined,
        content: `${e.name} ${typeof e.args === 'string' ? e.args : JSON.stringify(e.args)}  → ${String(e.error || e.result_preview || '').replace(/\s+/g, ' ').slice(0, 120)}`, detail: e })
    } else if (e.kind === 'interrupt') {
      rows.push({ id: 'i' + i, kind: 'context', tag: 'APPROVAL', content: String(e.policy ?? ''), t0: t, detail: e })
    } else if (e.kind === 'hook') {
      rows.push({ id: 'h' + i, kind: 'context', tag: 'HOOK', content: `${e.label} ${e.hook}${e.tool ? ' ' + e.tool : ''}`, t0: t, detail: e })
    }
  }
  return rows
}

function Timeline({ rows, selected, onPick, equal }: { rows: TrajRow[]; selected: string | null; onPick: (id: string) => void; equal: boolean }) {
  const timed = rows.filter(r => r.t0 !== undefined)
  if (!timed.length) return null
  const lane = (r: TrajRow) => (r.kind === 'user' || r.kind === 'system' || r.kind === 'context' ? 0 : r.kind === 'message' ? 1 : 2)
  const t0 = Math.min(...timed.map(r => r.t0!))
  const t1 = Math.max(...timed.map(r => r.t1 ?? r.t0!))
  const span = Math.max(1e-6, t1 - t0)
  return (
    <section className={tl.root} aria-label="Trajectory timeline">
      <div className={tl.plot}>
        <div className={tl.labels}><span>Input</span><span>Model</span><span>Tools</span></div>
        <div className={tl.track}>
          <div className={tl.lanes} style={{ ['--trajectory-domain-left' as string]: '0px', ['--trajectory-domain-width' as string]: '100%' }}>
            {timed.map((r, i) => {
              const left = equal ? (100 * i) / timed.length : (100 * (r.t0! - t0)) / span
              const width = equal ? 100 / timed.length : (100 * ((r.t1 ?? r.t0!) - r.t0!)) / span
              return (
                <span key={r.id} className={tl.span} title={`${r.tag} · ${r.content.slice(0, 80)}`} onClick={() => onPick(r.id)}
                  data-timeline-span={r.kind === 'system' ? 'context' : r.kind} data-error={r.error || undefined}
                  data-current={selected === r.id || undefined} data-selected={selected && selected !== r.id ? 'false' : undefined}
                  style={{ ['--trajectory-span-lane' as string]: lane(r), ['--trajectory-span-left' as string]: `${left}%`,
                    ['--trajectory-span-width' as string]: `${width}%`, ['--trajectory-span-gap' as string]: '1px' }} />
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

export function Trajectory({ rows }: { rows: TrajRow[] }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [equal, setEqual] = useState(false)
  const shown = useMemo(() => (query ? rows.filter(r => r.content.toLowerCase().includes(query.toLowerCase()) || r.tag.toLowerCase().includes(query.toLowerCase())) : rows), [rows, query])
  const sel = rows.find(r => r.id === selected)
  let lastTurn = 0
  return (
    <div className={views.root} style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <div className={bar.root} role="toolbar" aria-label="Trajectory toolbar">
        <div className={bar.inner}>
          <div className={bar.actions}>
            <button type="button" className={bar.control} role="switch" aria-checked={!equal} onClick={() => setEqual(!equal)}>
              <span style={{ whiteSpace: 'nowrap' }}>{equal ? 'Equal width' : 'Actual time'}</span>
              <span className={bar.controlTrack}><span className={bar.controlThumb} /></span>
            </button>
          </div>
          <div className={bar.search}>
            <IconSearchOutline16 className={bar.searchIcon} />
            <input className={bar.searchInput} type="search" placeholder="Search" aria-label="Search trajectory" value={query} onChange={e => setQuery(e.target.value)} />
          </div>
        </div>
      </div>
      <Timeline rows={rows} selected={selected} onPick={setSelected} equal={equal} />
      <div className={views.ledger} style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <div className={tb.split}>
          <div className={tb.tablePane}>
            <table className={tb.table} data-scroll-ready="true">
              <colgroup><col className={tb.eventColumn} /><col className={tb.contentColumn} /></colgroup>
              <tbody>
                {shown.map(r => {
                  const turnStart = r.turn !== undefined && r.turn !== lastTurn
                  if (r.turn !== undefined) lastTurn = r.turn
                  return (
                    <tr key={r.id} data-kind={r.kind} data-selected={selected === r.id ? 'true' : undefined} data-error={r.error || undefined}
                      data-turn-start={turnStart || undefined} tabIndex={0} onClick={() => setSelected(selected === r.id ? null : r.id)}>
                      <td className={tb.event}>
                        {turnStart && <span className={tb.turnLabel}><span className={tb.turnLabelFull}>{`Turn ${r.turn}`}</span><span className={tb.turnLabelCompact}>{`#${r.turn}`}</span></span>}
                        <div className={tb.eventInner}>
                          <span className={tb.kindSlot}>
                            <span className={cx(tb.kindTag, tb[TAG_CLASS[r.kind]])}><span className={tb.kindTagLabel}>{r.tag}</span></span>
                          </span>
                        </div>
                      </td>
                      <td className={tb.content}><span className={tb.contentText} title={r.content}><span>{r.content || '…'}</span></span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {sel && (
            <aside className={tb.details} aria-label="Record details">
              <div className={tb.detailsHeader}>
                <div className={tb.detailsTitle}>{sel.tag}</div>
                <button type="button" className={tb.close} aria-label="Close" onClick={() => setSelected(null)}><IconCloseOutline16 size={14} /></button>
              </div>
              <div className={tb.detailBody} style={{ overflow: 'auto', padding: 12 }}>
                {sel.kind === 'message' && (
                  // DSH request overview: Status, Model, Tool calls.
                  <dl className={cx(tb.overview, tb.summaryScrollRegion)} data-summary-scroll-region="">
                    <div><dt>Status</dt><dd className={sel.error ? tb.error : undefined}>{sel.error ? 'Failed' : sel.pending ? 'Pending' : 'Completed'}</dd></div>
                    {sel.model && <div><dt>Model</dt><dd>{sel.model}</dd></div>}
                    <div><dt>Tool calls</dt><dd>{sel.toolCalls ?? 0}</dd></div>
                  </dl>
                )}
                <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12, margin: 0 }}>{JSON.stringify(sel.detail, null, 2)}</pre>
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}
