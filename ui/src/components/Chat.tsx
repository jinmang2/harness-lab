/** Chat tab: DSH ChatView flow (system prompt row, user rows, turn process, answer, turn tail). */
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import {
  IconBrowseOutline16, IconChevronDownOutline14, IconChevronRightOutline14, IconChevronUpOutline14, IconClockOutline16,
  IconCodeOutline16, IconContextInjectionOutline16, IconCopyOutline16, IconDatabaseOutline16, IconEditOutline16,
  IconChecklistOutline14, IconGlobeOutline14, IconSearchOutline16, IconThinkOutline14, IconUserOutline16, IconWarningOutline16,
} from '../dsh/icons.tsx'
import chat from '../dsh/css/ChatView.module.css'
import msg from '../dsh/css/MessageItem.module.css'
import actions from '../dsh/css/MessageIconActions.module.css'
import proc from '../dsh/css/TurnProcessNodeView.module.css'
import tail from '../dsh/css/TurnTailNodeView.module.css'
import usageCss from '../dsh/css/TurnUsagePanel.module.css'
import reason from '../dsh/css/ReasoningRow.module.css'
import ctxRow from '../dsh/css/ContextInjectionRow.module.css'
import ctxBody from '../dsh/css/ContextBody.module.css'
import card from '../dsh/css/bash-sample.module.css'
import term from '../dsh/css/TerminalBlock.module.css'
import dot from '../dsh/css/StateDot.module.css'
import diff from '../dsh/css/DiffBlock.module.css'
import md from '../dsh/css/AssistantMarkdown.module.css'
import approvalCss from '../dsh/css/ApprovalPanel.module.css'
import todoCss from '../dsh/css/TodoPanel.module.css'
import { clock, cx, duration } from '../lib/format.ts'
import { Markdown } from '../lib/markdown.tsx'
import { asArgs, toolSummary, toolTitle, type ApprovalItem, type Folded, type ProcessItem, type ToolItem, type Turn } from '../lib/turns.ts'
import { useStore } from '../lib/store.tsx'
import { Button, DisclosureRow, StatDialog } from './primitives.tsx'

export const CwdContext = createContext('')
const useCwd = () => useContext(CwdContext)

function copy(text: string) { navigator.clipboard?.writeText(text).catch(() => {}) }

export function ChatView({ folded, modelLabel, live }: { folded: Folded; modelLabel: string; live: boolean }) {
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  useEffect(() => {
    const el = scroller.current?.closest('[data-conversation-scroll]') as HTMLElement | null
    if (!el) return
    const on = () => { pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }
    el.addEventListener('scroll', on)
    return () => el.removeEventListener('scroll', on)
  }, [])
  useEffect(() => {
    const el = scroller.current?.closest('[data-conversation-scroll]') as HTMLElement | null
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  })
  return (
    <div className={chat.root} ref={scroller}>
      <div className={chat.scroll}>
        <div className={chat.column}>
          {folded.request && <div className={chat.flowItem}><SystemPromptRow request={folded.request} /></div>}
          {folded.turns.map(t => <TurnView key={t.index} turn={t} modelLabel={modelLabel} live={live} />)}
        </div>
      </div>
    </div>
  )
}

function SystemPromptRow({ request }: { request: { system: string; tools: string[] } }) {
  const [open, setOpen] = useState(false)
  return (
    <DisclosureRow className={ctxRow.root} icon={<IconContextInjectionOutline16 />} title="System prompt" open={open} onToggle={() => setOpen(!open)}>
      <span className={ctxRow.sep} />
      <span className={ctxRow.source}>{`${request.system.length.toLocaleString()} chars · ${request.tools.length} tools`}</span>
      {open && (
        <div className={ctxRow.body} onClick={e => e.stopPropagation()}>
          <div className={ctxBody.sections}>
            <div className={ctxBody.section}>
              <div className={ctxBody.sectionName}>Tools</div>
              <div className={ctxBody.sectionText}>{request.tools.join(', ') || 'none'}</div>
            </div>
            <div className={ctxBody.section}>
              <div className={ctxBody.sectionName}>Prompt</div>
              <div className={ctxBody.sectionText} style={{ whiteSpace: 'pre-wrap' }}>{request.system || '(empty)'}</div>
            </div>
          </div>
        </div>
      )}
    </DisclosureRow>
  )
}

function TurnView({ turn, modelLabel, live }: { turn: Turn; modelLabel: string; live: boolean }) {
  const { prefs } = useStore()
  const settled = turn.status === 'done' || turn.status === 'stopped' || turn.status === 'error'
  const top = turn.items.filter(i => !(i.kind === 'text' && i.key === turn.answerKey))
  const toolCount = top.filter(i => i.kind === 'tool' && !i.nested).length
  const compact = prefs.display === 'compact' && settled && top.length > 0
  const [open, setOpen] = useState(false)
  return (
    <>
      <div className={chat.flowItem}>
        <div className={msg.userRow}>
          <div className={msg.userStack}><div className={msg.bubble}><span style={{ whiteSpace: 'pre-wrap' }}>{turn.user}</span></div></div>
          <div className={actions.actions}>
            <span className={actions.timeStart}>{clock(turn.userT)}</span>
            <button type="button" className={actions.action} aria-label="Copy" onClick={() => copy(turn.user)}><IconCopyOutline16 /></button>
          </div>
        </div>
      </div>
      {compact && (
        <div className={chat.flowItem}>
          <button type="button" className={proc.root} data-open={open || undefined} aria-expanded={open} onClick={() => setOpen(!open)}>
            <span className={proc.label}>{toolCount > 0 ? `${toolCount} tool call${toolCount === 1 ? '' : 's'}` : 'Thought for a while'}</span>
            <IconChevronDownOutline14 className={proc.chevron} />
          </button>
        </div>
      )}
      {(!compact || open) && top.map(item => <div key={item.key} className={chat.flowItem}><ProcessRow item={item} /></div>)}
      {turn.answer && <div className={chat.flowItem}><div className={md.root}><div className={md.body}><Markdown text={turn.answer} /></div></div></div>}
      {turn.status === 'stopped' && <div className={chat.flowItem}><div className={chat.turnStatus}>Stopped</div></div>}
      {turn.error && (
        <div className={chat.flowItem}>
          <div className={msg.turnErrorRow}>
            <span className={msg.turnErrorDot} />
            <span className={msg.turnErrorTitle}>Turn failed</span>
            <span className={msg.turnErrorMessage}>{turn.error.slice(0, 600)}</span>
          </div>
        </div>
      )}
      {settled && <div className={chat.flowItem}><TurnTail turn={turn} modelLabel={modelLabel} /></div>}
      {!settled && live && turn.status === 'running' && <div className={chat.flowItem}><div className={chat.turnStatus}>Working…</div></div>}
    </>
  )
}

function ProcessRow({ item }: { item: ProcessItem }) {
  const [open, setOpen] = useState(false)
  const indent = 'nested' in item && item.nested ? { marginLeft: 22 } : undefined
  switch (item.kind) {
    case 'think': {
      const first = item.text.trim().split('\n')[0] ?? ''
      return (
        <div className={reason.root} data-state={item.done ? 'ok' : 'running'} style={indent}>
          <DisclosureRow icon={<IconThinkOutline14 />} title="Think" open={open} onToggle={() => setOpen(!open)}
            rowClassName={reason.row} leadingClassName={reason.leading} titleClassName={reason.title}>
            {!open && <><span className={reason.separator} /><span className={reason.summary}><span className={reason.summaryText}>{first}</span></span></>}
          </DisclosureRow>
          {open && <div className={reason.thinkBody} style={{ whiteSpace: 'pre-wrap' }}>{item.text}</div>}
        </div>
      )
    }
    case 'text':
      return <div className={md.root} style={indent}><div className={md.body}><Markdown text={item.text} /></div></div>
    case 'tool':
      return <div className={chat.callRow} style={indent}><ToolCard item={item} /></div>
    case 'approval':
      return (
        <div className={cx(chat.turnStatus)}>
          {`Approval ${item.decision ? (item.decision === 'approve' ? 'allowed' : 'rejected') : 'requested'}: ${item.actions.map(a => a.name).join(', ')}`}
        </div>
      )
    case 'note':
      return <div className={chat.turnStatus}>{item.text}</div>
  }
}

function ToolIcon({ name }: { name: string }) {
  switch (toolTitle(name)) {
    case 'Bash': return <IconCodeOutline16 />
    case 'Read': case 'List': case 'Glob': return <IconBrowseOutline16 />
    case 'Grep': return <IconSearchOutline16 />
    case 'Write': case 'Edit': return <IconEditOutline16 />
    case 'Fetch': case 'Search': return <IconGlobeOutline14 />
    case 'Todo': return <IconChecklistOutline14 />
    case 'Subagent': return <IconUserOutline16 />
    default: return <IconCodeOutline16 />
  }
}

function ToolCard({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState(false)
  const [inspect, setInspect] = useState(false)
  const state = !item.done ? 'running' : item.error ? 'error' : 'ok'
  const summary = toolSummary(item.name, item.args)
  return (
    <div className={card.card}>
      <div className={card.root} role="button" tabIndex={0} data-state={state} aria-expanded={open} onClick={() => setOpen(!open)}
        onKeyDown={e => { if (e.key === 'Enter') setOpen(!open) }}>
        <span className={card.leading}>
          {open ? <IconChevronDownOutline14 className={card.chevron} />
            : <><span className={card.iconIdle}><ToolIcon name={item.name} /></span><IconChevronRightOutline14 className={cx(card.chevron, card.chevronHover)} /></>}
        </span>
        <span className={card.title}>{toolTitle(item.name)}</span>
        {summary && <><span className={card.sep} /><span className={card.summary}>{summary}</span></>}
        {item.error && !open && <span className={card.errorSummary}><IconWarningOutline16 size={12} /></span>}
      </div>
      {open && (
        <div className={card.bodyWrap}>
          <ToolBody item={item} />
          <button type="button" className={card.inspectButton} onClick={() => setInspect(!inspect)}><IconCodeOutline16 size={12} />Inspect</button>
          {inspect && (
            <div className={card.ioCard}>
              <div className={card.ioSection}><div className={card.ioLabel}>Input</div><pre className={card.ioText}>{JSON.stringify(item.args, null, 2)}</pre></div>
              <div className={card.ioDivider} />
              <div className={card.ioSection}><div className={card.ioLabel}>Output</div><pre className={card.ioText}>{item.preview ?? ''}</pre></div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ToolBody({ item }: { item: ToolItem }) {
  const cwd = useCwd()
  const a = asArgs(item.args)
  const title = toolTitle(item.name)
  if (title === 'Bash' && typeof a.command === 'string') {
    const state = !item.done ? 'running' : item.error ? 'error' : 'done'
    return (
      <div className={cx(term.block, card.terminal)} data-running={!item.done || undefined}>
        <div className={term.header}>
          <div className={term.prompt}>
            <span className={term.runStateLabel}>{!item.done ? 'Running' : item.error ? 'Failed' : 'Done'}</span>
            <div className={term.promptLine}>
              <span className={cx(dot.dot, term.runState)} data-state={state} style={{ width: 10, height: 10 }} />
              {cwd && <span className={term.cwd}>{cwd}</span>}
              <span className={term.command}>{a.command}</span>
            </div>
          </div>
          <button type="button" className={term.copyButton} onClick={() => copy(String(a.command))}>Copy</button>
        </div>
        {item.done && (
          <div className={term.output}>
            {(item.preview || '').split('\n').map((l, i) => <div key={i} className={term.line}>{l || ' '}</div>)}
          </div>
        )}
      </div>
    )
  }
  if ((title === 'Edit' && (a.old_string != null || a.new_string != null)) || (title === 'Write' && a.content != null)) {
    const del = title === 'Edit' ? String(a.old_string ?? '').split('\n') : []
    const add = String((title === 'Edit' ? a.new_string : a.content) ?? '').split('\n')
    return (
      <div className={diff.block}>
        <div className={diff.path}>{String(a.file_path ?? a.path ?? '')}</div>
        <div className={diff.body}>
          {del.map((l, i) => <div key={'d' + i} className={cx(diff.line, diff.del)}>{l}</div>)}
          {add.map((l, i) => <div key={'a' + i} className={cx(diff.line, diff.add)}>{l}</div>)}
        </div>
        {item.done && item.preview && <div className={diff.footer}>{item.preview.slice(0, 300)}</div>}
      </div>
    )
  }
  if (title === 'Todo' && Array.isArray(a.todos)) return <TodoList todos={a.todos as Todo[]} />
  return (
    <div className={card.ioCard}>
      <div className={card.ioSection}><pre className={card.ioText}>{item.done ? item.preview : 'Running…'}</pre></div>
    </div>
  )
}

function TurnTail({ turn, modelLabel }: { turn: Turn; modelLabel: string }) {
  const u = useRef<HTMLButtonElement>(null)
  const r = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState<'' | 'usage' | 'time'>('')
  const total = turn.usage.input + turn.usage.output
  const hit = turn.usage.input ? Math.round((100 * turn.usage.cached) / turn.usage.input) : 0
  const runMs = turn.stats?.wall_ms ?? 0
  return (
    <div className={tail.root}>
      <div className={cx(actions.actions, tail.actions)}>
        <button type="button" className={actions.action} aria-label="Copy" onClick={() => copy(turn.answer)}><IconCopyOutline16 /></button>
        <span className={usageCss.root}>
          <button ref={u} type="button" className={usageCss.trigger} aria-expanded={open === 'usage'} onClick={() => setOpen(open === 'usage' ? '' : 'usage')}>
            <IconDatabaseOutline16 /><span className={usageCss.label}>{`Usage ${total >= 1000 ? (total / 1000).toFixed(1) + 'K' : total} tok`}</span>
          </button>
        </span>
        <span className={usageCss.root}>
          <button ref={r} type="button" className={usageCss.trigger} aria-expanded={open === 'time'} onClick={() => setOpen(open === 'time' ? '' : 'time')}>
            <IconClockOutline16 /><span className={usageCss.label}>{`Ran for ${duration(runMs)}`}</span>
          </button>
        </span>
        {turn.endT && <span className={actions.timeEnd}>{clock(turn.endT)}</span>}
      </div>
      <StatDialog open={open === 'usage'} onClose={() => setOpen('')} anchor={u} title="Turn usage" icon={<IconDatabaseOutline16 />} value={`${total.toLocaleString()} tok`}>
        <dt>Model</dt><dd>{modelLabel}</dd>
        <dt>Cache hit</dt><dd>{`${hit}%`}</dd>
        <dt>Uncached input</dt><dd>{`${(turn.usage.input - turn.usage.cached).toLocaleString()} tok`}</dd>
        <dt>Cached input</dt><dd>{`${turn.usage.cached.toLocaleString()} tok`}</dd>
        <dt>Output</dt><dd>{`${turn.usage.output.toLocaleString()} tok`}{turn.usage.reasoning > 0 && ` (${turn.usage.reasoning.toLocaleString()} tok reasoning)`}</dd>
        <dt>Model calls</dt><dd>{turn.usage.steps}</dd>
      </StatDialog>
      <StatDialog open={open === 'time'} onClose={() => setOpen('')} anchor={r} title="Turn time" icon={<IconClockOutline16 />} value={duration(runMs)}>
        {turn.stats?.ttft_ms != null && <><dt>Time to first token</dt><dd>{`${(turn.stats.ttft_ms / 1000).toFixed(2)}s`}</dd></>}
        <dt>Model time</dt><dd>{duration(turn.llmMs)}</dd>
        <dt>Tool time</dt><dd>{duration(turn.toolMs)}</dd>
      </StatDialog>
    </div>
  )
}

export function ApprovalPanel({ item, onAnswer }: { item: ApprovalItem; onAnswer: (d: 'approve' | 'reject') => Promise<boolean> }) {
  const [answered, setAnswered] = useState(false)
  const a = item.actions[0]
  const args = asArgs(a?.args)
  const detail = typeof args.command === 'string' ? args.command : String(args.file_path ?? args.path ?? JSON.stringify(a?.args ?? {}, null, 2))
  const answer = async (d: 'approve' | 'reject') => { setAnswered(true); if (!(await onAnswer(d))) setAnswered(false) }
  return (
    <div className={approvalCss.root}>
      <div className={approvalCss.card}>
        <div className={approvalCss.strip}><span className={approvalCss.dot} />Waiting for approval</div>
        <div className={approvalCss.body} tabIndex={0} role="group" aria-label="Approval detail">
          <div className={approvalCss.headline}>
            {item.actions.length > 1 ? `${item.actions.length} actions need approval` : `${toolTitle(a?.name ?? '')} wants to run`}
          </div>
          {item.actions.map((x, i) => {
            const ax = asArgs(x.args)
            const d = i === 0 ? detail : typeof ax.command === 'string' ? ax.command : String(ax.file_path ?? ax.path ?? '')
            return <div key={i} className={approvalCss.command}>{d}</div>
          })}
        </div>
        <div className={approvalCss.actionRow}>
          <Button className={approvalCss.reject} disabled={answered} onClick={() => answer('reject')}>Reject</Button>
          <Button variant="primary" disabled={answered} onClick={() => answer('approve')}>Allow once</Button>
        </div>
      </div>
    </div>
  )
}

interface Todo { content: string; status: 'pending' | 'in_progress' | 'completed' }

function Glyph({ status }: { status: Todo['status'] }) {
  if (status === 'completed') {
    return <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden className={todoCss.glyphCompleted}><circle cx="7" cy="7" r="6.4" stroke="currentColor" strokeWidth="1.2" /><path d="M4 7.2l2 2 4-4.2" stroke="currentColor" strokeWidth="1.3" fill="none" /></svg>
  }
  if (status === 'in_progress') {
    return <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden className={todoCss.glyphProgress}><circle cx="7" cy="7" r="6.4" stroke="currentColor" strokeWidth="1.2" strokeDasharray="28 12" /></svg>
  }
  return <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden className={todoCss.glyphPending}><circle cx="7" cy="7" r="6.4" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2.4 2.4" /></svg>
}

function TodoList({ todos }: { todos: Todo[] }) {
  return (
    <ul className={todoCss.list}>
      {todos.map((t, i) => (
        <li key={i} className={todoCss.item} data-status={t.status}>
          <span className={todoCss.glyph} aria-hidden><Glyph status={t.status} /></span>
          <span className={todoCss.content}>{t.content}</span>
        </li>
      ))}
    </ul>
  )
}

/** DSH TodoPanel docked above the composer: the latest write_todos list. */
export function TodoPanel({ todos }: { todos: Todo[] }) {
  const [collapsed, setCollapsed] = useState(false)
  const done = todos.filter(t => t.status === 'completed').length
  const active = todos.filter(t => t.status === 'in_progress').length
  const pending = todos.length - done - active
  const progress = [done && `${done} done`, active && `${active} in progress`, pending && `${pending} pending`].filter(Boolean).join(' · ')
  return (
    <section className={todoCss.root} aria-label="Todos">
      <div className={todoCss.body}>
        <button type="button" className={todoCss.header} aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
          <span className={todoCss.lead} aria-hidden><IconChecklistOutline14 /></span>
          <span className={todoCss.title}>Todos</span>
          <span className={todoCss.progress}>{progress}</span>
          <span className={todoCss.chevron} aria-hidden>{collapsed ? <IconChevronUpOutline14 /> : <IconChevronDownOutline14 />}</span>
        </button>
        {!collapsed && <TodoList todos={todos} />}
      </div>
    </section>
  )
}

export function latestTodos(folded: Folded): Todo[] | null {
  for (let i = folded.turns.length - 1; i >= 0; i--) {
    const items = folded.turns[i].items
    for (let j = items.length - 1; j >= 0; j--) {
      const it = items[j]
      if (it.kind === 'tool' && (it.name === 'write_todos' || it.name === 'todo_write')) {
        const a = asArgs(it.args)
        if (Array.isArray(a.todos)) return a.todos as Todo[]
      }
    }
  }
  return null
}
