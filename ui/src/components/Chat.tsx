/**
 * Chat tab: the DSH ChatView flow (system prompt row, user and steering bubbles, turn process, answer,
 * turn tail, turn navigation) ported from DeepSeek Harness ui-chat / ui-tool / ui-goal (MIT).
 */
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  IconApiOutline14, IconBranchOutline16, IconBrowseOutline16, IconCheckOutline16, IconChecklistOutline14, IconChevronDownOutline14,
  IconChevronUpOutline14, IconClockOutline16, IconCodeOutline16, IconContextInjectionOutline16, IconCopyOutline16, IconDatabaseOutline16,
  IconDislikeFill16, IconDislikeOutline16, IconEditOutline16, IconLikeFill16, IconLikeOutline16, IconQuestionOutline14, IconSearchOutline16,
  IconSkillOutline16, IconSparkle16, IconThinkOutline14,
} from '../dsh/icons.tsx'
import { askQuestionView } from './Questions.tsx'
import chat from '../dsh/css/ChatView.module.css'
import msg from '../dsh/css/MessageItem.module.css'
import actions from '../dsh/css/MessageIconActions.module.css'
import feedback from '../dsh/css/MessageFeedbackActions.module.css'
import proc from '../dsh/css/TurnProcessNodeView.module.css'
import tail from '../dsh/css/TurnTailNodeView.module.css'
import usageCss from '../dsh/css/TurnUsagePanel.module.css'
import dialogCss from '../dsh/css/stat-dialog.module.css'
import navCss from '../dsh/css/TurnNavigator.module.css'
import reason from '../dsh/css/ReasoningRow.module.css'
import ctxRow from '../dsh/css/ContextInjectionRow.module.css'
import ctxBody from '../dsh/css/ContextBody.module.css'
import cmdCss from '../dsh/css/GenericCommandCard.module.css'
import goalInput from '../dsh/css/GoalCommandInputView.module.css'
import userText from '../dsh/css/user-text.module.css'
import a11y from '../dsh/css/accessibility.module.css'
import bashCss from '../dsh/css/bash-sample.module.css'
import rowCss from '../dsh/css/ToolRow.module.css'
import term from '../dsh/css/TerminalBlock.module.css'
import dot from '../dsh/css/StateDot.module.css'
import diff from '../dsh/css/DiffBlock.module.css'
import md from '../dsh/css/AssistantMarkdown.module.css'
import approvalCss from '../dsh/css/ApprovalPanel.module.css'
import todoCss from '../dsh/css/TodoPanel.module.css'
import { post, type Attachment, type SessionInfo } from '../lib/api.ts'
import { cx, latencySeconds, messageClock, runDuration, tok } from '../lib/format.ts'
import { Markdown } from '../lib/markdown.tsx'
import {
  asArgs, branchable, isSubagentTool, isTodoTool, relativizeToCwd, toolRow, toolVariant,
  type ApprovalItem, type CommandItem, type ContextItem, type Folded, type ProcessItem, type SteerItem, type ToolItem, type Turn,
} from '../lib/turns.ts'
import { useStore } from '../lib/store.tsx'
import { Button, DisclosureRow, StatDialog, StateDot } from './primitives.tsx'
import { MessageAttachments } from './MessageAttachments.tsx'

/** Workspace folder name shown in terminal prompts. */
export const CwdContext = createContext('')
const useCwd = () => useContext(CwdContext)

/** The open session's info from the store (ChatView renders inside a session view). */
export function useCurrentSession(): SessionInfo | undefined {
  const { view, sessions } = useStore()
  return view.kind === 'session' ? sessions.find(x => x.id === view.id) : undefined
}

function writeClipboard(text: string): Promise<boolean> {
  if (!navigator.clipboard) return Promise.resolve(false)
  return navigator.clipboard.writeText(text).then(() => true, () => false)
}

interface ChatViewProps {
  folded: Folded
  modelLabel: string
  live: boolean
  /** Defaults to the session in the current view. */
  sessionId?: string
  /** Fork at a settled turn; defaults to POST play/<id>/fork and opening the child. */
  onFork?: (turn: Turn) => void
}

export function ChatView({ folded, modelLabel, live, sessionId, onFork }: ChatViewProps) {
  const s = useStore()
  const info = useCurrentSession()
  const sid = sessionId ?? info?.id ?? ''
  const columnRef = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const scroller = () => columnRef.current?.closest('[data-conversation-scroll]') as HTMLElement | null
  useEffect(() => {
    const el = scroller()
    if (!el) return
    const on = () => { pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }
    el.addEventListener('scroll', on)
    return () => el.removeEventListener('scroll', on)
  }, [])
  useEffect(() => {
    const el = scroller()
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  })

  const fork = useCallback(async (turn: Turn) => {
    if (onFork) { onFork(turn); return }
    if (!sid) return
    // Server turn marks: one per settled turn (lab drops failed turns; headless DSH keeps them).
    const mark = folded.turns.slice(0, turn.index + 1)
      .filter(t => t.endT !== undefined && (t.status !== 'error' || info?.engine === 'dsh')).length - 1
    try {
      const child = await post<SessionInfo>(`play/${sid}/fork`, { turn: mark })
      await s.refreshSessions()
      s.go({ kind: 'session', id: child.id })
    } catch (e) { alert((e as Error).message) }
  }, [onFork, sid, folded.turns, info?.engine, s])

  const last = folded.turns[folded.turns.length - 1]
  const running = live && last !== undefined && (last.status === 'running' || last.status === 'waiting')
  const canBranch = info?.branchable !== false
  return (
    <div className={chat.root}>
      <div className={chat.scroll}>
        <TurnNavigator turns={folded.turns} column={columnRef} />
        <div ref={columnRef} className={chat.column} data-chat-flow="">
          {folded.turns.length === 0 && folded.request && <div className={chat.flowItem}><SystemPromptRow text={folded.request.system} /></div>}
          {folded.turns.map((t, i) => (
            <TurnView key={t.index} turn={t} sessionId={sid} modelLabel={modelLabel} latest={i === folded.turns.length - 1}
              systemPrompt={i === 0 ? folded.request?.system : undefined} canBranch={canBranch} onFork={fork} />
          ))}
          {folded.after.map(c => <CommandFlow key={c.key} item={c} />)}
          {running && <TurnStatus startTime={last.userT} />}
        </div>
      </div>
    </div>
  )
}

/** DSH TurnStatus: "Deep diving..." for the whole running turn; a clock once it passes 15s. */
function TurnStatus({ startTime }: { startTime: number }) {
  const [elapsed, setElapsed] = useState(() => Math.max(0, Date.now() - startTime * 1000))
  useEffect(() => {
    const tick = () => setElapsed(Math.max(0, Date.now() - startTime * 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [startTime])
  return (
    <div className={chat.flowItem}>
      <div className={chat.turnStatus} role="status" aria-live="polite">
        Deep diving...
        {elapsed >= 15_000 && <span className={chat.turnStatusClock} aria-hidden>{runDuration(elapsed)}</span>}
      </div>
    </div>
  )
}

// ── Turn navigation (DSH TurnNavigator.tsx) ─────────────────────────────────

const TURN_SPACING_PX = 10
const RAIL_INSET_PX = 6

function TurnNavigator({ turns, column }: { turns: Turn[]; column: React.RefObject<HTMLDivElement | null> }) {
  const [active, setActive] = useState<number | null>(null)
  const [preview, setPreview] = useState<number | null>(null)
  const [scroll, setScroll] = useState({ top: 0, up: false, down: false })
  const scrollerRef = useRef<HTMLDivElement>(null)
  const previewId = useId()
  const items = useMemo(() => turns.map(t => ({
    turn: t.index + 1,
    prompt: (t.source === 'goal' ? '' : t.user).slice(0, 200),
    response: t.answer.slice(0, 200),
  })), [turns])

  const rowOf = useCallback((turn: number) => column.current?.querySelector(`[data-chat-turn="${turn}"]`) as HTMLElement | null, [column])
  useEffect(() => {
    const el = column.current?.closest('[data-conversation-scroll]') as HTMLElement | null
    if (!el) return
    const on = () => {
      const top = el.getBoundingClientRect().top + el.clientHeight / 3
      let current: number | null = items[0]?.turn ?? null
      for (const it of items) {
        const row = rowOf(it.turn)
        if (row && row.getBoundingClientRect().top <= top) current = it.turn
      }
      setActive(current)
    }
    on()
    el.addEventListener('scroll', on, { passive: true })
    return () => el.removeEventListener('scroll', on)
  }, [column, items, rowOf])

  const sync = () => {
    const sc = scrollerRef.current
    if (!sc) return
    const next = { top: sc.scrollTop, up: sc.scrollTop > 1, down: sc.scrollTop < sc.scrollHeight - sc.clientHeight - 1 }
    setScroll(cur => (cur.top === next.top && cur.up === next.up && cur.down === next.down ? cur : next))
  }
  useEffect(sync, [items.length])

  if (items.length < 2) return null
  const navigate = (turn: number) => {
    const row = rowOf(turn)
    const el = column.current?.closest('[data-conversation-scroll]') as HTMLElement | null
    if (!row || !el) return
    el.scrollTo({ top: el.scrollTop + row.getBoundingClientRect().top - el.getBoundingClientRect().top - 16, behavior: 'smooth' })
    setActive(turn)
  }
  const atPointer = (target: HTMLElement, clientY: number) => {
    const offset = clientY - target.getBoundingClientRect().top + (scrollerRef.current?.scrollTop ?? 0) - RAIL_INSET_PX
    return items[Math.max(0, Math.min(items.length - 1, Math.round(offset / TURN_SPACING_PX)))]
  }
  const pos = (i: number) => ({ ['--turn-natural-position' as string]: `${i * TURN_SPACING_PX}px` })
  const pi = items.findIndex(it => it.turn === preview)
  const shown = pi < 0 ? undefined : items[pi]
  return (
    <div className={navCss.slot}>
      <nav className={navCss.frame} aria-label="Turn navigation"
        style={{
          ['--turn-natural-height' as string]: `${(items.length - 1) * TURN_SPACING_PX + 2 * RAIL_INSET_PX}px`,
          ['--turn-rail-inset' as string]: `${RAIL_INSET_PX}px`, ['--turn-scroll-top' as string]: `${scroll.top}px`,
        }}
        onClick={e => { const it = atPointer(e.currentTarget, e.clientY); if (it) navigate(it.turn) }}
        onPointerMove={e => setPreview(atPointer(e.currentTarget, e.clientY)?.turn ?? null)}
        onPointerLeave={() => setPreview(null)}>
        <div ref={scrollerRef} className={cx(navCss.scroller, scroll.up && navCss.fadeTop, scroll.down && navCss.fadeBottom)} onScroll={sync}>
          <div className={navCss.marks}>
            {items.map((it, i) => (
              <div key={it.turn} className={navCss.markPosition} style={pos(i)}>
                <button type="button" aria-label={`Jump to turn ${it.turn}`} aria-current={it.turn === active ? 'true' : undefined}
                  aria-describedby={it.turn === preview ? previewId : undefined}
                  className={cx(navCss.mark, it.turn === active ? navCss.markActive : it.turn === preview && navCss.markPreview)}
                  onClick={e => { e.stopPropagation(); navigate(it.turn) }}
                  onFocus={() => setPreview(it.turn)} onBlur={() => setPreview(null)} />
              </div>
            ))}
          </div>
        </div>
        {shown && (
          <div id={previewId} role="tooltip" className={navCss.preview} style={pos(pi)}>
            <div className={navCss.previewPrompt}>{shown.prompt || `Turn ${shown.turn}`}</div>
            {shown.response !== '' && <div className={navCss.previewResponse}>{shown.response}</div>}
          </div>
        )}
      </nav>
    </div>
  )
}

// ── Rows ────────────────────────────────────────────────────────────────────

/** DSH SystemPromptRow: collapsed disclosure, the prompt as opaque context text. */
function SystemPromptRow({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <DisclosureRow className={ctxRow.root} icon={<IconBrowseOutline16 size={14} />} chevronClassName={ctxRow.chevron}
      title="System prompt" open={open} expandable onToggle={() => setOpen(!open)}>
      <div className={ctxRow.body} data-system-prompt-body="">
        {text !== '' && <pre className={ctxBody.text} data-context-text="">{text}</pre>}
      </div>
    </DisclosureRow>
  )
}

/** DSH ContextInjectionRow (opaque body): a goal round's prompt. */
function ContextInjectionRow({ item }: { item: ContextItem }) {
  const [open, setOpen] = useState(false)
  return (
    <DisclosureRow className={ctxRow.root} icon={<IconContextInjectionOutline16 size={14} />} chevronClassName={ctxRow.chevron}
      title="Context injection" open={open} expandable keepContentWhenOpen onToggle={() => setOpen(!open)}
      collapsedContent={<><span className={ctxRow.sep} aria-hidden /><span className={ctxRow.source} data-context-source="">{item.source}</span></>}>
      <div className={ctxRow.body} data-context-injection-body="">
        <pre className={ctxBody.text} data-context-text="">{item.text}</pre>
      </div>
    </DisclosureRow>
  )
}

/** DSH MessageIconActions: clock (user: before, assistant: after), Copy, extra actions, Branch, usage pills. */
function MessageIconActions({ text, time, clock, className, extra, branch, usage }: {
  text: string; time?: number; clock: 'start' | 'end'; className?: string; extra?: ReactNode
  branch?: { unavailable: boolean; onBranch: () => void }; usage?: ReactNode
}) {
  const reasonId = useId()
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  const onCopy = () => {
    if (copied) return
    void writeClipboard(text).then(ok => {
      if (!ok) return
      setCopied(true)
      timer.current = setTimeout(() => setCopied(false), 1000)
    })
  }
  const clockEl = time === undefined ? null : <span className={clock === 'start' ? actions.timeStart : actions.timeEnd}>{messageClock(time)}</span>
  return (
    <div className={cx(actions.actions, className)}>
      {clock === 'start' && clockEl}
      <button type="button" className={actions.action} aria-label={copied ? 'Copied' : 'Copy'} title={copied ? 'Copied' : 'Copy'} onClick={onCopy}>
        {copied ? <IconCheckOutline16 /> : <IconCopyOutline16 />}
      </button>
      {extra}
      {branch && (
        <button type="button" className={actions.action} aria-label="Branch into a new conversation"
          title={branch.unavailable ? 'Available only on the last message of a completed turn' : 'Branch into a new conversation'}
          aria-disabled={branch.unavailable || undefined} aria-describedby={branch.unavailable ? reasonId : undefined}
          data-unavailable={branch.unavailable || undefined} onClick={branch.unavailable ? undefined : branch.onBranch}>
          <IconBranchOutline16 />
        </button>
      )}
      {branch?.unavailable && <span id={reasonId} className={actions.visuallyHidden}>Available only on the last message of a completed turn</span>}
      {usage}
      {clock === 'end' && clockEl}
    </div>
  )
}

/** DSH UserStyleBubble: attachments, the text bubble, then the user-side actions. */
function UserBubble({ text, attachments, time, sessionId }: { text: string; attachments: Attachment[]; time?: number; sessionId: string }) {
  return (
    <div className={msg.userRow}>
      <div className={msg.userStack}>
        <MessageAttachments attachments={attachments} sessionId={sessionId} />
        {text !== '' && <div className={msg.bubble}><span className={userText.plainRun}>{text}</span></div>}
      </div>
      <MessageIconActions text={text} time={time} clock="start" />
    </div>
  )
}

/** DSH GoalCommandInputView: the `/goal` line as a right-aligned bubble with a command chip. */
function CommandInput({ text }: { text: string }) {
  const split = text.search(/\s/u)
  const head = split === -1 ? text : text.slice(0, split)
  const rest = split === -1 ? '' : text.slice(split)
  return (
    <div className={goalInput.row} data-command-input="" role="group" aria-label="Command input">
      <div className={goalInput.stack}>
        <div className={goalInput.bubble}>
          <span className={cx(userText.refChip, userText.slashChip)} data-ref-chip="command" title={head}>{head}</span>
          {rest !== '' && <span className={userText.plainRun}>{rest}</span>}
        </div>
      </div>
    </div>
  )
}

/** DSH GenericCommandCard: title is the command name; a multi-line result expands; error state. */
function CommandCard({ item }: { item: CommandItem }) {
  const [expanded, setExpanded] = useState(false)
  const state = item.outcome === 'error' ? 'error' : 'ok'
  const summary = item.text || (state === 'error' ? 'Command failed' : 'Completed')
  const body = item.text.includes('\n') ? item.text : null
  return (
    <div className={cmdCss.root} data-variant="others" data-state={state}>
      {state === 'error' && <span className={a11y.visuallyHidden}>Failed</span>}
      <DisclosureRow rowClassName={cmdCss.row} leadingClassName={cmdCss.leading} titleClassName={cmdCss.title} chevronClassName={cmdCss.chevron}
        icon={state === 'error' ? <StateDot state="error" /> : <IconApiOutline14 size={14} />}
        title={item.name || 'Command'} open={expanded && body !== null} expandable={body !== null} keepContentWhenOpen
        onToggle={() => setExpanded(!expanded)}
        collapsedContent={<><span className={cmdCss.separator} aria-hidden /><span className={cmdCss.summary} data-error={state === 'error' || undefined}>{summary}</span></>}>
        <pre className={cmdCss.body} data-error={state === 'error' || undefined}>{body}</pre>
      </DisclosureRow>
    </div>
  )
}

/** A folded command: the `/goal` input bubble (when echoed) and its result card, as two flow items. */
function CommandFlow({ item }: { item: CommandItem }) {
  return (
    <>
      {item.input && <div className={chat.flowItem} data-chat-flow-kind="command-input"><CommandInput text={item.input} /></div>}
      <div className={chat.flowItem} data-chat-flow-kind="command"><div className={chat.callRow}><CommandCard item={item} /></div></div>
    </>
  )
}

function processLabel(turn: Turn): string {
  const top = turn.items.filter(i => !('nested' in i) || !i.nested)
  const tools = top.filter((i): i is ToolItem => i.kind === 'tool')
  const subagents = tools.filter(i => isSubagentTool(i.name)).length
  const toolCalls = tools.length - subagents
  const messages = top.filter(i => i.kind === 'text' && i.key !== turn.answerKey).length
  const parts: string[] = []
  if (toolCalls > 0) parts.push(`${toolCalls} tool call${toolCalls === 1 ? '' : 's'}`)
  if (messages > 0) parts.push(`${messages} message${messages === 1 ? '' : 's'}`)
  if (subagents > 0) parts.push(`${subagents} subagent${subagents === 1 ? '' : 's'}`)
  return parts.length === 0 ? 'Thought for a while' : parts.join(' · ')
}

function TurnView({ turn, sessionId, modelLabel, latest, systemPrompt, canBranch, onFork }: {
  turn: Turn; sessionId: string; modelLabel: string; latest: boolean; systemPrompt?: string; canBranch: boolean; onFork: (t: Turn) => void
}) {
  const { prefs } = useStore()
  const settled = turn.status === 'done' || turn.status === 'stopped' || turn.status === 'error'
  const n = turn.index + 1
  const process = turn.items.filter(i => i.key !== turn.answerKey && i.kind !== 'question')
  // DSH: a closed turn with an answer folds its process (when there is any) under one summary control.
  const foldable = prefs.display === 'compact' && settled && turn.answerKey !== null && process.some(i => i.kind !== 'steer')
  const [open, setOpen] = useState(false)
  const hidden = foldable && !open
  const flow = (key: string, kind: string, node: ReactNode, extra?: Record<string, unknown>) => (
    <div key={key} className={chat.flowItem} data-chat-turn={n} data-chat-flow-kind={kind} {...extra}>{node}</div>
  )
  return (
    <>
      {turn.before.map(c => <CommandFlow key={c.key} item={c} />)}
      {systemPrompt !== undefined && flow('sys', 'system-prompt', <SystemPromptRow text={systemPrompt} />)}
      {turn.source === 'user' && flow('user', 'user', <UserBubble text={turn.user} attachments={turn.attachments} time={turn.userT} sessionId={sessionId} />)}
      {foldable && flow('process', 'turn-process', (
        <button type="button" className={proc.root} data-open={open || undefined} data-turn-process={n} aria-expanded={open}
          onClick={e => { e.currentTarget.focus(); setOpen(!open) }}>
          <span className={proc.label}>{processLabel(turn)}</span>
          <IconChevronDownOutline14 className={proc.chevron} />
        </button>
      ))}
      {process.map(item => (hidden && item.kind !== 'steer') ? null
        : flow(item.key, item.kind, <ProcessRow item={item} sessionId={sessionId} />, foldable && item.kind !== 'steer' ? { 'data-turn-process-member': true } : undefined))}
      {(turn.answer || (turn.status === 'stopped' && turn.answerKey)) && flow('answer', 'assistant', (
        <div className={md.root}>
          <div className={md.body}>
            <Markdown text={turn.answer} />
            {turn.status === 'stopped' && <span className={md.stopped}>Stopped</span>}
          </div>
        </div>
      ), foldable && !open ? { 'data-turn-process-answer': true } : undefined)}
      {turn.error && flow('error', 'turn-error', (
        <div className={msg.turnErrorRow} role="status">
          <StateDot state="error" className={msg.turnErrorDot} />
          <div className={msg.turnErrorCopy}>
            <span className={msg.turnErrorTitle}>This turn failed</span>
            <span className={msg.turnErrorMessage}>{turn.error.slice(0, 600)}</span>
          </div>
        </div>
      ))}
      {settled && turn.answerKey !== null && flow('tail', 'turn-tail', (
        <TurnTail turn={turn} modelLabel={modelLabel} latest={latest} unavailable={!canBranch || !branchable(turn)} onFork={() => onFork(turn)} />
      ))}
    </>
  )
}

function ProcessRow({ item, sessionId }: { item: ProcessItem; sessionId: string }) {
  const indent = 'nested' in item && item.nested ? { marginLeft: 22 } : undefined
  switch (item.kind) {
    case 'think':
      return <div style={indent}><ReasoningRow text={item.text} running={!item.done} /></div>
    case 'text':
      return <div className={md.root} style={indent} data-streaming={!item.done || undefined}><div className={md.body}><Markdown text={item.text} /></div></div>
    case 'tool':
      return <div className={chat.callRow} style={indent}><ToolCard item={item} /></div>
    case 'steer':
      return <SteerBubble item={item} sessionId={sessionId} />
    case 'context':
      return <ContextInjectionRow item={item} />
    case 'approval':
      return (
        <div className={chat.turnStatus}>
          {`Approval ${item.decision ? (item.decision === 'approve' ? 'allowed' : 'rejected') : 'requested'}: ${item.actions.map(a => a.name).join(', ')}`}
        </div>
      )
    case 'note':
      return <div className={chat.turnStatus}>{item.text}</div>
    case 'question':
      return null
  }
}

function SteerBubble({ item, sessionId }: { item: SteerItem; sessionId: string }) {
  return <UserBubble text={item.text} attachments={item.attachments} time={item.t} sessionId={sessionId} />
}

/** DSH ReasoningRow: Think disclosure; the summary follows the latest line while streaming. */
function ReasoningRow({ text, running }: { text: string; running: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const visible = text.trimEnd()
  const nl = running ? visible.lastIndexOf('\n') : text.indexOf('\n')
  const line = running ? (nl === -1 ? visible : visible.slice(nl + 1)) : (nl === -1 ? text : text.slice(0, nl))
  return (
    <div className={reason.root} data-variant="think" data-state={running ? 'running' : 'ok'} data-expanded={expanded || undefined}>
      {running && <span className={a11y.visuallyHidden}>Running</span>}
      <DisclosureRow rowClassName={reason.row} leadingClassName={reason.leading} titleClassName={reason.title} chevronClassName={reason.chevron}
        icon={<IconThinkOutline14 size={14} />} title="Think" open={expanded} expandable onToggle={() => setExpanded(!expanded)}
        collapsedContent={(
          <>
            <span className={reason.separator} aria-hidden />
            <span className={reason.summary} data-follow-end={running || undefined}><span className={reason.summaryText}>{line.replaceAll('**', '')}</span></span>
          </>
        )}>
        <div className={reason.thinkBody}>{text}</div>
      </DisclosureRow>
    </div>
  )
}

function variantIcon(item: ToolItem): ReactNode {
  if (isTodoTool(item.name)) return <IconChecklistOutline14 />
  if (item.name === 'ask_user_question') return <IconQuestionOutline14 size={14} />
  if (item.name === 'skill') return <IconSkillOutline16 size={14} />
  switch (toolVariant(item.name)) {
    case 'search': return <IconSearchOutline16 size={14} />
    case 'read': return <IconBrowseOutline16 size={14} />
    case 'bash': return <IconApiOutline14 size={14} />
    case 'write': case 'edit': return <IconEditOutline16 size={14} />
    case 'code': return <IconCodeOutline16 size={14} />
    default: return <IconSparkle16 size={14} />
  }
}

const errorDot = <StateDot state="error" />

function ToolCard({ item }: { item: ToolItem }) {
  const info = useCurrentSession()
  const model = toolRow(item, info?.workdir)
  if (model.variant === 'bash') return <BashRow item={item} title={model.title} summary={model.summary} failure={model.errorSummary} />
  return <ToolRow item={item} model={model} />
}

/** DSH bash-sample BashRow: terminal card chrome with an accessible lifecycle label. */
function BashRow({ item, title, summary, failure }: { item: ToolItem; title: string; summary: string; failure: string | null }) {
  const [expanded, setExpanded] = useState(false)
  const state = !item.done ? 'running' : item.error ? 'error' : 'ok'
  const status = state === 'running' ? 'Running' : state === 'error' ? 'Failed' : null
  const leading = state === 'error' ? errorDot : <IconApiOutline14 size={14} />
  const expandable = true
  const toggle = () => setExpanded(!expanded)
  return (
    <div className={bashCss.card}>
      <div className={bashCss.root} data-sample="bash" data-variant="bash" data-state={state} data-expandable={expandable || undefined}
        role="button" tabIndex={0} aria-expanded={expanded} onClick={toggle}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}>
        <span className={bashCss.leading}>
          {expanded ? <IconChevronDownOutline14 className={bashCss.chevron} />
            : <><span className={bashCss.iconIdle}>{leading}</span><IconChevronDownOutline14 className={cx(bashCss.chevron, bashCss.chevronHover)} /></>}
        </span>
        {status !== null && <span className={bashCss.visuallyHidden}>{status}</span>}
        <span className={bashCss.title}>{title}</span>
        <span className={bashCss.sep} aria-hidden />
        <span className={cx(bashCss.summary, failure !== null && bashCss.errorSummary)}>{failure ?? summary}</span>
      </div>
      {expanded && <div className={bashCss.bodyWrap}><TerminalBody item={item} /></div>}
    </div>
  )
}

function TerminalBody({ item }: { item: ToolItem }) {
  const cwd = useCwd()
  const a = asArgs(item.args)
  const command = typeof a.command === 'string' ? a.command : JSON.stringify(item.args)
  const state = !item.done ? 'running' : item.error ? 'error' : 'done'
  return (
    <div className={cx(term.block, bashCss.terminal)} data-running={!item.done || undefined}>
      <div className={term.header}>
        <div className={term.prompt}>
          <span className={term.runStateLabel}>{!item.done ? 'Running' : item.error ? 'Failed' : 'Done'}</span>
          <div className={term.promptLine}>
            <span className={cx(dot.dot, term.runState)} data-state={state} style={{ width: 10, height: 10 }} />
            {cwd && <span className={term.cwd}>{cwd}</span>}
            <span className={term.command}>{command}</span>
          </div>
        </div>
        <button type="button" className={term.copyButton} onClick={() => { void writeClipboard(command) }}>Copy</button>
      </div>
      {item.done && (
        <div className={term.output}>
          {(item.preview || '').split('\n').map((l, i) => <div key={i} className={term.line}>{l || ' '}</div>)}
        </div>
      )}
    </div>
  )
}

/** DSH ToolRow: state-aware leading icon, title, summary (or first error line), suffix, expandable body. */
function ToolRow({ item, model }: { item: ToolItem; model: ReturnType<typeof toolRow> }) {
  const [expanded, setExpanded] = useState(false)
  const ask = item.name === 'ask_user_question' ? askQuestionView(item.args, item.preview, item.done, item.error) : null
  // A cancelled question set is the user's choice, not a failure (DSH: ASK_CANCELLED renders ok).
  const state = ask && ask.summary === 'cancelled' ? 'ok' : model.state
  const summary = ask ? ask.summary : model.summary
  const failure = state === 'error' ? model.errorSummary : null
  const shown = failure ?? summary
  const status = state === 'running' ? 'Running' : state === 'error' ? 'Failed' : null
  const body = ask?.body ?? <ToolBody item={item} />
  const expandable = ask ? ask.body !== null : hasToolBody(item)
  const open = expanded && expandable
  return (
    <div className={rowCss.root} data-variant={model.variant} data-tool={item.name} data-state={state}>
      {status !== null && <span className={rowCss.visuallyHidden}>{status}</span>}
      <DisclosureRow rowClassName={rowCss.row} leadingClassName={rowCss.leading} titleClassName={rowCss.title} chevronClassName={rowCss.chevron}
        icon={state === 'error' ? errorDot : variantIcon(item)} title={model.title} open={open} expandable={expandable} keepContentWhenOpen
        onToggle={() => setExpanded(!expanded)}
        collapsedContent={shown !== '' && (
          <>
            <span className={rowCss.sep} aria-hidden />
            <span className={cx(rowCss.summary, failure !== null && rowCss.errorSummary)}>{shown}</span>
            {failure === null && model.suffix !== null && <span className={cx(rowCss.summarySuffix, model.diff && rowCss.diffStat)}>{model.suffix}</span>}
          </>
        )}>
        <div className={rowCss.bodyWrap}>{body}</div>
      </DisclosureRow>
    </div>
  )
}

function IoCard({ input, output, error }: { input: string | null; output: string | null; error?: boolean }) {
  if (input === null && output === null) return null
  return (
    <div className={rowCss.ioCard}>
      {input !== null && <div className={rowCss.ioSection}><span className={rowCss.ioLabel}>IN</span><span className={rowCss.ioText}>{input}</span></div>}
      {input !== null && output !== null && <span className={rowCss.ioDivider} aria-hidden />}
      {output !== null && (
        <div className={rowCss.ioSection}><span className={rowCss.ioLabel}>OUT</span><span className={rowCss.ioText} data-error={error || undefined}>{output}</span></div>
      )}
    </div>
  )
}

const isDiffCard = (item: ToolItem, a: Record<string, unknown>) => !item.error
  && ((toolVariant(item.name) === 'edit' && (a.old_string != null || a.new_string != null)) || (toolVariant(item.name) === 'write' && a.content != null))
const isSingleFile = (item: ToolItem) => ['read', 'write', 'edit'].includes(toolVariant(item.name))

/** DSH ToolRow expandability: an args body (not for single-file tools), result output, or a card. */
function hasToolBody(item: ToolItem): boolean {
  const a = asArgs(item.args)
  return isDiffCard(item, a) || (item.done && !!item.preview) || (!isSingleFile(item) && item.args !== undefined)
    || (item.name === 'exit_plan_mode' && typeof a.plan === 'string')
}

function ToolBody({ item }: { item: ToolItem }) {
  const info = useCurrentSession()
  const a = asArgs(item.args)
  const variant = toolVariant(item.name)
  const output = item.done && item.preview ? item.preview : null
  if (isDiffCard(item, a)) {
    const del = variant === 'edit' ? String(a.old_string ?? '').split('\n') : []
    const add = String((variant === 'edit' ? a.new_string : a.content) ?? '').split('\n')
    return (
      <div className={cx(diff.block, rowCss.diffBody)}>
        <div className={diff.body}>
          <div className={cx(diff.line, diff.path)}>{relativizeToCwd(String(a.file_path ?? a.path ?? ''), info?.workdir)}</div>
          {del.map((l, i) => <div key={'d' + i} className={cx(diff.line, diff.del)}>{l}</div>)}
          {add.map((l, i) => <div key={'a' + i} className={cx(diff.line, diff.add)}>{l}</div>)}
        </div>
      </div>
    )
  }
  if (item.name === 'exit_plan_mode' && typeof a.plan === 'string') {
    return (
      <>
        <div className={md.root}><div className={md.body}><Markdown text={a.plan} /></div></div>
        <IoCard input={null} output={output} error={item.error} />
      </>
    )
  }
  // Single-file tools expose no args body (DSH GenericToolCard); every other row shows IN/OUT.
  const input = isSingleFile(item) || item.args === undefined ? null : JSON.stringify(item.args, null, 2)
  return <IoCard input={input} output={output} error={item.error} />
}

// ── Turn tail (DSH TurnTailNodeView + MessageFeedbackActions + TurnUsagePanel) ─

function FeedbackActions() {
  const [rating, setRating] = useState<'positive' | 'negative' | null>(null)
  const like = rating === 'positive' ? 'Remove rating' : 'Good response'
  const dislike = rating === 'negative' ? 'Remove rating' : 'Bad response'
  return (
    <>
      <button type="button" className={feedback.action} aria-label={like} title={like} aria-pressed={rating === 'positive'}
        data-active={rating === 'positive' || undefined} onClick={() => setRating(rating === 'positive' ? null : 'positive')}>
        {rating === 'positive' ? <IconLikeFill16 /> : <IconLikeOutline16 />}
      </button>
      <button type="button" className={feedback.action} aria-label={dislike} title={dislike} aria-pressed={rating === 'negative'}
        data-active={rating === 'negative' || undefined} onClick={() => setRating(rating === 'negative' ? null : 'negative')}>
        {rating === 'negative' ? <IconDislikeFill16 /> : <IconDislikeOutline16 />}
      </button>
    </>
  )
}

/** DSH formatCacheHitPercent (one decimal) without rounding a partial hit up to 100%. */
function cacheHitPercent(cached: number, prompt: number): string | null {
  if (prompt === 0) return null
  if (cached >= prompt) return '100'
  const v = Math.round((1000 * cached) / prompt) / 10
  return v >= 100 ? '99.9' : String(v)
}

function TurnTail({ turn, modelLabel, latest, unavailable, onFork }: {
  turn: Turn; modelLabel: string; latest: boolean; unavailable: boolean; onFork: () => void
}) {
  const u = useRef<HTMLButtonElement>(null)
  const r = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState<'' | 'usage' | 'time'>('')
  const total = turn.usage.input + turn.usage.output
  const hit = cacheHitPercent(turn.usage.cached, turn.usage.input)
  const runMs = turn.stats?.wall_ms ?? (turn.endT !== undefined ? (turn.endT - turn.userT) * 1000 : undefined)
  const ttft = turn.stats?.ttft_ms ?? undefined
  const decodeMs = turn.llmMs - (ttft ?? 0)
  const tps = turn.usage.output > 0 && decodeMs > 0 ? turn.usage.output / (decodeMs / 1000) : undefined
  const exact = (v: number) => `${v.toLocaleString('en-US')} tok`
  const route = turn.models.length > 0 ? turn.models.join(', ') : modelLabel
  const usage = (
    <>
      {turn.usage.steps > 0 && (
        <span className={usageCss.root}>
          <button ref={u} type="button" className={usageCss.trigger} aria-haspopup="dialog" aria-expanded={open === 'usage'} onClick={() => setOpen(open === 'usage' ? '' : 'usage')}>
            <IconDatabaseOutline16 /><span className={usageCss.label}>{`Usage ${tok(total)} tok`}</span>
          </button>
        </span>
      )}
      {runMs !== undefined && (
        <span className={usageCss.root}>
          <button ref={r} type="button" className={usageCss.trigger} aria-haspopup="dialog" aria-expanded={open === 'time'} onClick={() => setOpen(open === 'time' ? '' : 'time')}>
            <IconClockOutline16 /><span className={usageCss.label}>{`Ran for ${runDuration(runMs)}`}</span>
          </button>
        </span>
      )}
    </>
  )
  return (
    <div className={tail.root} data-turn-tail={turn.index + 1} data-actions-reveal={latest ? 'always' : 'hover'}>
      <MessageIconActions text={turn.answer} time={turn.endT} clock="end" className={tail.actions} extra={<FeedbackActions />}
        branch={{ unavailable, onBranch: onFork }} usage={usage} />
      <StatDialog open={open === 'usage'} onClose={() => setOpen('')} anchor={u} title="Turn usage" icon={<IconDatabaseOutline16 />} value={exact(total)}>
        {route !== '' && <><dt>Provider / model</dt><dd className={dialogCss.route}>{route}</dd></>}
        {hit !== null && <><dt>Cache hit</dt><dd>{`${hit}%`}</dd></>}
        <dt>Uncached input</dt><dd>{exact(turn.usage.input - turn.usage.cached)}</dd>
        <dt>Cached input</dt><dd>{exact(turn.usage.cached)}</dd>
        <dt>Output</dt>
        <dd>{exact(turn.usage.output)}{turn.usage.reasoning > 0 && <span className={dialogCss.reasoning}>{` (${exact(turn.usage.reasoning)} reasoning)`}</span>}</dd>
      </StatDialog>
      <StatDialog open={open === 'time'} onClose={() => setOpen('')} anchor={r} title="Turn time and speed" icon={<IconClockOutline16 />}>
        <dt>Total run time</dt><dd>{runDuration(runMs)}</dd>
        {tps !== undefined && <><dt>Tokens per second (TPS)</dt><dd>{`${tps >= 10 ? Math.round(tps) : Math.round(tps * 10) / 10} tok/s`}</dd></>}
        {ttft !== undefined && <><dt>Time to first token (TTFT)</dt><dd>{`${latencySeconds(ttft)}s`}</dd></>}
      </StatDialog>
    </div>
  )
}

// ── Composer-seat panels used by Conversation.tsx ───────────────────────────

export function ApprovalPanel({ item, onAnswer }: { item: ApprovalItem; onAnswer: (d: 'approve' | 'reject') => Promise<boolean> }) {
  const [answered, setAnswered] = useState(false)
  const a = item.actions[0]
  const args = asArgs(a?.args)
  const detail = typeof args.command === 'string' ? args.command : String(args.file_path ?? args.path ?? JSON.stringify(a?.args ?? {}, null, 2))
  const answer = async (d: 'approve' | 'reject') => { setAnswered(true); if (!(await onAnswer(d))) setAnswered(false) }
  const title = (name: string) => toolRow({ kind: 'tool', key: '', name, args: {}, done: true, nested: false }).title
  return (
    <div className={approvalCss.root}>
      <div className={approvalCss.card}>
        <div className={approvalCss.strip}><span className={approvalCss.dot} />Waiting for approval</div>
        <div className={approvalCss.body} tabIndex={0} role="group" aria-label="Approval detail">
          <div className={approvalCss.headline}>
            {item.actions.length > 1 ? `${item.actions.length} actions need approval` : `${title(a?.name ?? '')} wants to run`}
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

/** DSH TodoPanel status glyphs (14px artboard). */
function Glyph({ status }: { status: Todo['status'] }) {
  const gradientId = useId()
  if (status === 'completed') {
    return (
      <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden="true" className={todoCss.glyphCompleted}>
        <circle cx="7" cy="7" r="6.4" stroke="currentColor" strokeWidth="1.2" />
        <path
          d="M10.9631 5.71411L7.70154 8.97571C7.48011 9.19714 7.27736 9.40099 7.09229 9.54993C6.89742 9.70669 6.66314 9.85279 6.3634 9.90027C6.2049 9.92534 6.04339 9.92534 5.88489 9.90027C5.58515 9.85279 5.35087 9.70669 5.15601 9.54993C4.97093 9.40099 4.76818 9.19714 4.54675 8.97571L3.03516 7.46411L3.96313 6.53613L5.47473 8.04773C5.7169 8.28989 5.86196 8.43389 5.97888 8.52795C6.08597 8.61409 6.10875 8.60701 6.08997 8.604C6.11259 8.60758 6.13571 8.60758 6.15833 8.604C6.13954 8.60701 6.16232 8.61409 6.26941 8.52795C6.38633 8.43389 6.53139 8.28989 6.77356 8.04773L10.0352 4.78613L10.9631 5.71411Z"
          fill="currentColor"
        />
      </svg>
    )
  }
  if (status === 'in_progress') {
    return (
      <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden="true" className={todoCss.glyphProgress}>
        <defs>
          <linearGradient id={gradientId} x1="2.5" y1="12" x2="10.5" y2="3.5" gradientUnits="userSpaceOnUse">
            <stop stopColor="currentColor" /><stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <circle cx="7" cy="7" r="6.4" stroke={`url(#${gradientId})`} strokeWidth="1.2" />
      </svg>
    )
  }
  return (
    <svg width={14} height={14} viewBox="0 0 14 14" fill="none" aria-hidden="true" className={todoCss.glyphPending}>
      <circle cx="7" cy="7" r="6.4" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2.4 2.4" />
    </svg>
  )
}

function TodoList({ todos }: { todos: Todo[] }) {
  return (
    <ul className={todoCss.list}>
      {todos.map((t, i) => (
        <li key={`${t.content}:${i}`} className={todoCss.item} data-status={t.status}>
          <span className={todoCss.glyph} aria-hidden><Glyph status={t.status} /></span>
          <span className={todoCss.content}>{t.content}</span>
        </li>
      ))}
    </ul>
  )
}

/** DSH TodoPanel docked above the composer: the latest to-do list, collapsed by default. */
export function TodoPanel({ todos }: { todos: Todo[] }) {
  const [collapsed, setCollapsed] = useState(true)
  if (todos.length === 0) return null
  const done = todos.filter(t => t.status === 'completed').length
  const active = todos.filter(t => t.status === 'in_progress').length
  const pending = todos.length - done - active
  // En spaces (U+2002) around the dot, as DSH: HTML collapses ASCII runs.
  const progress = [
    ...done > 0 ? [`${done} completed`] : [],
    ...active > 0 ? [`${active} in progress`] : [],
    ...pending > 0 ? [`${pending} pending`] : [],
  ].join(' · ')
  return (
    <section className={todoCss.root} data-testid="todo-panel" aria-label="To-dos">
      <div className={todoCss.body}>
        <button type="button" className={todoCss.header} aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
          <span className={todoCss.lead} aria-hidden><IconChecklistOutline14 /></span>
          <span className={todoCss.title}>To-dos</span>
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
      if (it.kind === 'tool' && isTodoTool(it.name) && !it.error) {
        const a = asArgs(it.args)
        if (Array.isArray(a.todos)) return a.todos as Todo[]
      }
    }
  }
  return null
}
