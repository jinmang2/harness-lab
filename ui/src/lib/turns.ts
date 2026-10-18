/**
 * Fold a session's event stream (lab/viewer/play.py) into DSH-style turns, plus the DSH Web
 * tool-row presentation (title, summary, diff stat) ported from DeepSeek Harness ui-tool
 * (tool-call-model.ts, todo-row.tsx, plan-summary.ts; MIT).
 */
import type { Attachment, PlayEvent, Usage } from './api.ts'

export interface ThinkItem { kind: 'think'; key: string; text: string; nested: boolean; done: boolean }
export interface TextItem { kind: 'text'; key: string; text: string; nested: boolean; done: boolean }
export interface ToolItem { kind: 'tool'; key: string; name: string; args: unknown; preview?: string; error?: boolean; done: boolean; nested: boolean }
export interface NoteItem { kind: 'note'; key: string; text: string; tone?: 'error' | 'muted' }
export interface ApprovalItem { kind: 'approval'; key: string; actions: { name: string; args: unknown; description?: string }[]; decision?: string }
export interface QuestionOption { label: string; description?: string }
export interface Question { id: string; question: string; header?: string; detail?: string; options?: QuestionOption[]; multiSelect?: boolean; intent?: { kind: string; approve: string } }
export interface QuestionAnswer { id: string; selected: string[]; custom?: string }
/** A pending ask_user_question / plan review (lab/middleware/collaboration.py); the composer seat renders it. */
export interface QuestionItem { kind: 'question'; key: string; qkind: 'question' | 'plan-review'; questions: Question[]; title?: string; answered?: boolean }
/** A slash command (DSH GenericCommandCard); `/goal` also echoes its input line (GoalCommandInputView). */
export interface CommandItem { kind: 'command'; key: string; name: string; text: string; input?: string; outcome?: 'success' | 'error'; t?: number }
/** A message steered into the running turn (DSH steering node: a user bubble inside the turn). */
export interface SteerItem { kind: 'steer'; key: string; text: string; attachments: Attachment[]; t: number }
/** Logged model-facing context that is not a user message (DSH ContextInjectionRow), e.g. a goal round prompt. */
export interface ContextItem { kind: 'context'; key: string; source: string; text: string }
export type ProcessItem = ThinkItem | TextItem | ToolItem | NoteItem | ApprovalItem | QuestionItem | SteerItem | ContextItem

export interface Turn {
  index: number
  /** Commands run between the previous turn and this one (e.g. /plan, /goal). */
  before: CommandItem[]
  /** 'goal': a round sent by the goal driver; DSH shows its prompt as a context row, not a user bubble. */
  source: 'user' | 'goal'
  user: string
  userT: number
  attachments: Attachment[]
  /** Models the turn's requests ran on (a mid-turn switch adds one). */
  models: string[]
  items: ProcessItem[]
  answer: string
  answerKey: string | null
  status: 'running' | 'waiting' | 'done' | 'stopped' | 'error'
  usage: { input: number; cached: number; output: number; reasoning: number; steps: number; lastInput: number }
  stats?: { wall_ms: number; ttft_ms: number | null; steps: number; input: number; cached: number; output: number }
  endT?: number
  llmMs: number
  toolMs: number
  error?: string
}

export interface Folded {
  session?: Record<string, unknown>
  request?: { system: string; tools: string[] }
  turns: Turn[]
  /** Commands after the last turn. */
  after: CommandItem[]
  /** Current model (session start, then "model" events). */
  model?: string
  effort?: string
  /** Latest goal snapshot from "goal" events. */
  goal?: unknown
  /** Forked from this session id. */
  parent?: string
  /** Child agents a loop tool started (ralph rounds), in start order. */
  children: ChildAgent[]
}

/**
 * A child agent on its own thread (lab/middleware/ralph.py `_run_child`), announced by `child_start`.
 * Its events are kept here, not in the parent turn: DSH Web opens a child as its own conversation.
 */
export interface ChildAgent {
  id: string
  /** The spawner's label (verified_ralph names its rounds); DSH lists a child by its label, else its title. */
  label: string | null
  title: string
  depth: number
  /** The enclosing child, for a child started inside another child. */
  parent: string | null
  /** UI id of the tool call that started it. */
  toolRunId: string | null
  prompt: string
  t0: number
  t1?: number
  status: 'running' | 'done' | 'error'
  error?: string
  usage: { input: number; cached: number; output: number; steps: number }
  events: PlayEvent[]
}

export const childName = (c: ChildAgent): string => c.label ?? c.title

/** A child's own event stream: its round prompt as the user message, then its runs (nested relative to the child). */
export function childEvents(c: ChildAgent): PlayEvent[] {
  const events: PlayEvent[] = [{ seq: -1, type: 'user', t: c.t0, text: c.prompt, source: 'user' }]
  for (const ev of c.events) events.push({ ...ev, nested: Boolean(ev.child_nested) })
  if (c.status === 'error') events.push({ seq: -2, type: 'error', t: c.t1 ?? c.t0, text: c.error || 'The child stopped with an error' })
  if (c.status !== 'running') events.push({ seq: -3, type: 'turn_end', t: c.t1 ?? c.t0 })
  return events
}

export const foldChild = (c: ChildAgent): Folded => fold(childEvents(c))

const emptyUsage = () => ({ input: 0, cached: 0, output: 0, reasoning: 0, steps: 0, lastInput: 0 })

const asAttachments = (v: unknown): Attachment[] => (Array.isArray(v) ? v as Attachment[] : [])

export function fold(events: PlayEvent[]): Folded {
  const out: Folded = { turns: [], after: [], children: [] }
  const children = new Map<string, ChildAgent>()
  let turn: Turn | null = null
  const llm = new Map<string, { think?: ThinkItem; text?: TextItem; nested: boolean; t0: number }>()
  const tools = new Map<string, ToolItem & { t0: number }>()
  for (const ev of events) {
    switch (ev.type) {
      case 'session':
        out.session = ev
        if (typeof ev.model === 'string') out.model = ev.model
        if (typeof ev.effort === 'string') out.effort = ev.effort
        break
      case 'request': out.request = { system: String(ev.system ?? ''), tools: (ev.tools as string[]) ?? [] }; break
      case 'model':
        out.model = String(ev.model ?? out.model ?? '')
        out.effort = String(ev.effort ?? '')
        if (turn && (turn.status === 'running' || turn.status === 'waiting') && !turn.models.includes(out.model)) turn.models.push(out.model)
        break
      case 'goal': out.goal = ev.goal; break
      case 'forked': out.parent = String(ev.parent ?? ''); break
      case 'user':
        turn = {
          index: out.turns.length, before: out.after, source: ev.source === 'goal' ? 'goal' : 'user', user: String(ev.text ?? ''), userT: ev.t,
          attachments: asAttachments(ev.attachments), models: out.model ? [out.model] : [], items: [], answer: '', answerKey: null,
          status: 'running', usage: emptyUsage(), llmMs: 0, toolMs: 0,
        }
        if (turn.source === 'goal') turn.items.push({ kind: 'context', key: 'ctx' + ev.seq, source: 'goal', text: turn.user })
        out.turns.push(turn)
        out.after = []
        break
      case 'command':
        out.after.push({
          kind: 'command', key: 'cmd' + ev.seq, name: String(ev.name ?? ''), text: String(ev.text ?? ''), t: ev.t,
          ...(typeof ev.input === 'string' ? { input: ev.input } : {}),
          ...(ev.outcome === 'success' || ev.outcome === 'error' ? { outcome: ev.outcome } : {}),
        })
        break
      case 'child_start': {
        const c: ChildAgent = {
          id: String(ev.child_id ?? ''), label: typeof ev.label === 'string' && ev.label !== '' ? ev.label : null,
          title: String(ev.title ?? ev.child_id ?? ''), depth: Number(ev.depth ?? 1),
          parent: typeof ev.parent === 'string' ? ev.parent : null, toolRunId: typeof ev.parent_tool_run_id === 'string' ? ev.parent_tool_run_id : null,
          prompt: String(ev.prompt ?? ''), t0: ev.t, status: 'running', usage: { input: 0, cached: 0, output: 0, steps: 0 }, events: [],
        }
        if (!children.has(c.id)) { children.set(c.id, c); out.children.push(c) }
        break
      }
      case 'child_end': {
        const c = children.get(String(ev.child_id ?? ''))
        if (c) {
          c.status = ev.error ? 'error' : 'done'
          c.t1 = ev.t
          if (ev.error) c.error = String(ev.text ?? '')
        }
        break
      }
      default: {
        const owner = typeof ev.child === 'string' ? children.get(ev.child) : undefined
        if (owner) {
          owner.events.push(ev)
          const u = (ev.usage ?? {}) as Usage
          if (ev.type === 'llm_end' && u.input_tokens != null) {
            owner.usage.input += u.input_tokens ?? 0
            owner.usage.cached += u.input_token_details?.cache_read ?? 0
            owner.usage.output += u.output_tokens ?? 0
            owner.usage.steps += 1
          }
          break
        }
        if (!turn) break
        const t = turn
        const rid = String(ev.run_id ?? '')
        if (ev.type === 'llm_start') {
          llm.set(rid, { nested: Boolean(ev.nested), t0: ev.t })
        } else if (ev.type === 'reasoning') {
          const l = llm.get(rid) ?? { nested: false, t0: ev.t }
          if (!l.think) { l.think = { kind: 'think', key: rid + ':think', text: '', nested: l.nested, done: false }; t.items.push(l.think) }
          l.think.text += String(ev.text ?? '')
          llm.set(rid, l)
        } else if (ev.type === 'token') {
          const l = llm.get(rid) ?? { nested: false, t0: ev.t }
          if (!l.text) { l.text = { kind: 'text', key: rid + ':text', text: '', nested: l.nested, done: false }; t.items.push(l.text) }
          l.text.text += String(ev.text ?? '')
          llm.set(rid, l)
        } else if (ev.type === 'llm_end') {
          const l = llm.get(rid)
          if (l?.think) l.think.done = true
          if (l?.text) l.text.done = true
          const u = (ev.usage ?? {}) as Usage
          if (l && !l.nested && u.input_tokens != null) {
            t.usage.input += u.input_tokens ?? 0
            t.usage.cached += u.input_token_details?.cache_read ?? 0
            t.usage.output += u.output_tokens ?? 0
            t.usage.reasoning += u.output_token_details?.reasoning ?? 0
            t.usage.steps += u.steps ?? 1
            t.usage.lastInput = u.last_input ?? u.input_tokens ?? 0
            t.llmMs += Math.max(0, (ev.t - l.t0) * 1000)
          }
        } else if (ev.type === 'tool_start') {
          // The server marks tools that run inside a subagent (it knows the run tree).
          const nested = Boolean(ev.nested)
          const item: ToolItem & { t0: number } = { kind: 'tool', key: rid, name: String(ev.name ?? '?'), args: ev.args, done: false, nested, t0: ev.t }
          tools.set(rid, item)
          t.items.push(item)
        } else if (ev.type === 'tool_end') {
          const item = tools.get(rid)
          if (item) {
            Object.assign(item, { preview: String(ev.preview ?? ''), error: Boolean(ev.error), done: true })
            if (!item.nested) t.toolMs += Math.max(0, (ev.t - item.t0) * 1000)
          }
        } else if (ev.type === 'steer') {
          t.items.push({ kind: 'steer', key: 'steer' + ev.seq, text: String(ev.text ?? ''), attachments: asAttachments(ev.attachments), t: ev.t })
        } else if (ev.type === 'interrupt') {
          t.items.push({ kind: 'approval', key: 'appr' + ev.seq, actions: (ev.actions as ApprovalItem['actions']) ?? [] })
          t.status = 'waiting'
        } else if (ev.type === 'decision') {
          const last = [...t.items].reverse().find(i => i.kind === 'approval') as ApprovalItem | undefined
          if (last) last.decision = String(ev.decision)
          t.status = 'running'
        } else if (ev.type === 'question') {
          t.items.push({ kind: 'question', key: String(ev.key), qkind: ev.qkind === 'plan-review' ? 'plan-review' : 'question',
            questions: (ev.questions as Question[]) ?? [], ...(typeof ev.title === 'string' ? { title: ev.title } : {}) })
          t.status = 'waiting'
        } else if (ev.type === 'answered') {
          const q = t.items.find(i => i.kind === 'question' && i.key === String(ev.key)) as QuestionItem | undefined
          if (q) q.answered = true
          t.status = 'running'
        } else if (ev.type === 'note' || ev.type === 'warning') {
          t.items.push({ kind: 'note', key: 'n' + ev.seq, text: String(ev.text ?? ''), tone: 'muted' })
        } else if (ev.type === 'error') {
          t.error = String(ev.text ?? '')
          t.status = 'error'
        } else if (ev.type === 'cancelled') {
          t.status = 'stopped'
        } else if (ev.type === 'final') {
          t.status = 'done'
        } else if (ev.type === 'turn_end') {
          t.stats = ev.stats as Turn['stats']
          t.endT = ev.t
          if (t.status === 'running') t.status = 'done'
        }
      }
    }
  }
  // A turn that ended (stop, error) without the child's end event settles its children.
  const last = out.turns[out.turns.length - 1]
  if (last && last.status !== 'running' && last.status !== 'waiting') {
    for (const c of out.children) if (c.status === 'running') { c.status = 'error'; c.t1 = last.endT ?? c.t0; c.error = 'The turn ended before this child finished.' }
  }
  // The answer is the last top-level text of a finished turn; earlier texts stay in the process.
  for (const t of out.turns) {
    if (t.status === 'running' || t.status === 'waiting') continue
    const last = [...t.items].reverse().find(i => i.kind === 'text' && !i.nested) as TextItem | undefined
    if (last) {
      const idx = t.items.indexOf(last)
      const after = t.items.slice(idx + 1)
      if (!after.some(i => i.kind === 'tool' && !i.nested)) {
        t.answer = last.text
        t.answerKey = last.key
      }
    }
  }
  return out
}

/**
 * DSH "Branch into a new conversation" availability (ui-chat turn-tail.ts): only a completed turn whose
 * closing answer is its last transcript item can be branched.
 */
export function branchable(t: Turn): boolean {
  if (t.status !== 'done' && t.status !== 'stopped') return false
  if (!t.answerKey || t.error) return false
  const idx = t.items.findIndex(i => i.key === t.answerKey)
  return !t.items.slice(idx + 1).some(i => i.kind === 'tool' || i.kind === 'steer')
}

/** DSH isSubagentDelegationTool, plus the deepagents `task` delegation tool. */
export function isSubagentTool(name: string): boolean {
  return name === 'subagent' || name.startsWith('subagent_') || name === 'task'
}

// ── DSH ui-tool row model ─────────────────────────────────────────────────

/** Tool-call row variants (DSH ToolRowVariant). */
export type ToolVariant = 'search' | 'read' | 'bash' | 'write' | 'edit' | 'code' | 'others'

/** DSH TOOL_VARIANTS, with the deepagents aliases lab harnesses register (read_file, execute, …). */
const TOOL_VARIANTS: Record<string, ToolVariant> = {
  bash: 'bash', pwsh: 'bash', execute: 'bash',
  read: 'read', read_file: 'read', read_image: 'read', web_fetch: 'read',
  web_search: 'search', grep: 'search', glob: 'search',
  write: 'write', write_file: 'write',
  edit: 'edit', edit_file: 'edit',
  run_code: 'code',
}

const VARIANT_TITLES: Record<ToolVariant, string> = {
  search: 'Search', read: 'Read', bash: 'Bash', write: 'Write', edit: 'Edit', code: 'Code', others: 'Tool call',
}

/** Tool-owned titles (DSH TOOL_TITLE_KEYS + the keyed toolviews: search-row, web-row, todo-row, ask-question-row, ui-skill). */
const TOOL_TITLES: Record<string, string> = {
  pwsh: 'Pwsh', read_image: 'Read image', grep: 'Grep', glob: 'Glob', web_search: 'Search', web_fetch: 'Fetch',
  todo_write: 'Update to-do list', write_todos: 'Update to-do list', ask_user_question: 'Ask question', skill: 'Skill',
  ralph: 'Run ralph loop', verified_ralph: 'verified_ralph',
}

const SUMMARY_KEYS: Record<ToolVariant, readonly string[]> = {
  bash: ['description', 'command'],
  read: ['path', 'file_path', 'url'],
  search: ['query', 'pattern', 'url'],
  write: ['path', 'file_path'],
  edit: ['path', 'file_path'],
  code: ['description'],
  others: [],
}

export function toolVariant(name: string): ToolVariant {
  return TOOL_VARIANTS[name] ?? 'others'
}

export function isTodoTool(name: string): boolean {
  return name === 'todo_write' || name === 'write_todos'
}

export function asArgs(args: unknown): Record<string, unknown> {
  if (args && typeof args === 'object') return args as Record<string, unknown>
  if (typeof args === 'string') {
    try { const v = JSON.parse(args); if (v && typeof v === 'object') return v } catch { /* plain string */ }
    return { input: args }
  }
  return {}
}

const firstLine = (text: string) => { const nl = text.indexOf('\n'); return nl === -1 ? text : text.slice(0, nl) }

function rawArgs(args: unknown): string {
  if (typeof args === 'string') return args
  try { return JSON.stringify(args ?? {}) } catch { return '' }
}

/** DSH relativizeToCwd: a workspace-rooted path displays relative to the session cwd. */
export function relativizeToCwd(path: string, cwd?: string): string {
  if (!cwd) return path
  const root = cwd.endsWith('/') ? cwd.slice(0, -1) : cwd
  if (path === root) return '.'
  return path.startsWith(root + '/') ? path.slice(root.length + 1) : path
}

function deriveSummary(variant: ToolVariant, args: unknown): string {
  const raw = rawArgs(args)
  let parsed: unknown = args
  if (typeof args === 'string') { try { parsed = JSON.parse(args) } catch { return firstLine(raw) } }
  if (typeof parsed !== 'object' || parsed === null) return firstLine(raw)
  const a = parsed as Record<string, unknown>
  if (variant === 'search' && Array.isArray(a.queries)) {
    const queries = a.queries.filter((q): q is string => typeof q === 'string' && q !== '')
    if (queries.length > 0) return queries.map(firstLine).join(', ')
  }
  for (const k of SUMMARY_KEYS[variant]) if (typeof a[k] === 'string' && a[k] !== '') return firstLine(String(a[k]))
  for (const v of Object.values(a)) if (typeof v === 'string' && v !== '') return firstLine(v)
  return firstLine(raw)
}

/** DSH diffTotals over the call's intended hunk: write adds its content, edit swaps old for new. */
function diffStat(variant: ToolVariant, a: Record<string, unknown>): string | null {
  const lines = (text: string) => { if (text === '') return 0; return (text.endsWith('\n') ? text.slice(0, -1) : text).split('\n').length }
  if (variant === 'write' && typeof a.content === 'string') return `+${lines(a.content)} -0`
  if (variant === 'edit' && typeof a.new_string === 'string') {
    return `+${lines(a.new_string)} -${typeof a.old_string === 'string' ? lines(a.old_string) : 0}`
  }
  return null
}

/** DSH planSummary (todo-row): "{done}/{total} completed · <first in-progress>" plus the parallel-active count. */
function todoSummary(a: Record<string, unknown>): { text: string; extra: number } | null {
  if (!Array.isArray(a.todos) || !a.todos.every(x => typeof x === 'object' && x !== null)) return null
  const todos = a.todos as { content?: unknown; status?: unknown }[]
  const active = todos.filter(x => x.status === 'in_progress')
  const first = active[0]?.content
  const named = typeof first === 'string' && first.trim() !== ''
  const head = `${todos.filter(x => x.status === 'completed').length}/${todos.length} completed`
  return { text: named ? `${head} · ${first}` : head, extra: named ? active.length - 1 : 0 }
}

export interface ToolRowModel {
  variant: ToolVariant
  title: string
  summary: string
  /** Trailing non-truncating fragment: a diff's "+N -N", or the todo row's "+N" parallel count. */
  suffix: string | null
  /** The suffix is a diff stat (DSH css.diffStat). */
  diff: boolean
  state: 'running' | 'ok' | 'error'
  /** First line of the result on an error row; replaces the summary. */
  errorSummary: string | null
}

/** DSH toolRowModel plus the keyed toolviews' titles and summaries. */
export function toolRow(item: ToolItem, cwd?: string): ToolRowModel {
  const variant = toolVariant(item.name)
  const a = asArgs(item.args)
  const state = !item.done ? 'running' : item.error ? 'error' : 'ok'
  const own = TOOL_TITLES[item.name]
  let summary = relativizeToCwd(deriveSummary(variant, item.args), cwd)
  let suffix: string | null = null
  let diff = false
  if (isTodoTool(item.name)) {
    const todo = todoSummary(a)
    if (todo) { summary = todo.text; suffix = todo.extra > 0 ? `+${todo.extra}` : null }
  } else if (variant === 'others' && !own) {
    // Others keeps the static "Tool call" title; the real tool name rides the summary slot.
    summary = `${item.name} · ${summary}`
  } else {
    suffix = diffStat(variant, a)
    diff = suffix !== null
  }
  const output = item.done ? item.preview ?? '' : ''
  const errorSummary = state === 'error' && output !== '' ? firstLine(output) : null
  return { variant, title: own ?? VARIANT_TITLES[variant], summary, suffix: errorSummary === null ? suffix : null, diff, state, errorSummary }
}

// ── Loop tool result cards (DSH ui-tool ToolDetails; workflowDetails for `ralph`) ──

/** One recorded entity in a detail card (DSH ToolDetailItem, the parts lab uses). */
export interface ToolDetailItem {
  title?: string
  badge?: { label: string; tone: 'neutral' | 'info' | 'success' | 'warning' | 'error' }
  description?: string
  fields: { label: string; value: string }[]
  lines?: string[]
  code?: string
  groups?: { label: string; items: ToolDetailItem[] }[]
}

/** DSH ToolDetailsModel: the card body and the collapsed-row summary. */
export interface ToolDetailsModel { items: ToolDetailItem[]; summary?: string }

export function isLoopTool(name: string): boolean {
  return name === 'ralph' || name === 'verified_ralph'
}

const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string')
const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
function json(text: string): unknown {
  try { return JSON.parse(text) } catch { return undefined }
}

/** DSH workflowDetails (ralph branch): the head line picks the badge; the final report JSON fills the card. */
function ralphDetails(objective: unknown, text: string): ToolDetailsModel | null {
  const split = text.indexOf('\nFinal report:\n')
  if (split < 0) return null
  const header = text.slice(0, split)
  const rounds = /\b(\d+) rounds?\b/u.exec(header)?.[1]
  const report = json(text.slice(split + 15))
  if (!record(report) || typeof report.summary !== 'string' || !strings(report.evidence) || !strings(report.nextSteps)
    || typeof report.blocker !== 'string') return null
  const badge: ToolDetailItem['badge'] = header.startsWith('Ralph worker reported completion ') ? { label: 'Worker reported completion', tone: 'success' }
    : header.startsWith('Ralph worker reported a blocker ') ? { label: 'Worker reported a blocker', tone: 'warning' }
    : header.startsWith('Ralph reached its ') ? { label: 'Round limit reached', tone: 'warning' }
    : undefined
  if (badge === undefined) return null
  const groups: NonNullable<ToolDetailItem['groups']> = []
  if (report.nextSteps.length > 0) groups.push({ label: 'Remaining work', items: [{ fields: [], lines: report.nextSteps }] })
  if (typeof objective === 'string') groups.push({ label: 'Task', items: [{ fields: [], description: objective }] })
  const fields = rounds === undefined ? [] : [{ label: 'Rounds', value: rounds }]
  if (report.blocker !== '') fields.push({ label: 'Blocker', value: report.blocker })
  return {
    items: [{ title: report.summary, badge, fields, ...(report.evidence.length === 0 ? {} : { lines: report.evidence }), groups }],
    summary: report.summary,
  }
}

const VERIFIED_BADGES: Record<string, NonNullable<ToolDetailItem['badge']>> = {
  verified: { label: 'Verified', tone: 'success' },
  blocked: { label: 'Worker reported a blocker', tone: 'warning' },
  'self-reported': { label: 'Self-reported completion', tone: 'warning' },
  'budget-limited': { label: 'Round limit reached', tone: 'warning' },
  'round-failed': { label: 'Round failed', tone: 'warning' },
}

/** verified_ralph `renderMessage` (dsh/bundles/verified-ralph, lab/middleware/ralph.py `verified_render`) read back. */
function verifiedRalphDetails(objective: unknown, text: string): ToolDetailsModel | null {
  const head = /^verified_ralph ended as (\S+) after (\d+) rounds?\./u.exec(text)
  if (head === null) return null
  const status = head[1]
  const line = (prefix: string) => text.split('\n').find(l => l.startsWith(prefix))?.slice(prefix.length)
  const TAIL = '\nLast verifier output tail:\n'
  const REPORT = '\nLast worker report:\n'
  const tailAt = text.indexOf(TAIL)
  const reportAt = text.indexOf(REPORT)
  const report = reportAt < 0 ? undefined : json(text.slice(reportAt + REPORT.length, tailAt > reportAt ? tailAt : undefined))
  const tail = tailAt < 0 ? '' : text.slice(tailAt + TAIL.length)
  const worker = record(report) && typeof report.summary === 'string' ? report : null
  const fields = [{ label: 'Rounds', value: head[2] }]
  const verifier = line('Verifier: ')
  if (verifier !== undefined) fields.push({ label: 'Verifier', value: verifier.replace(/\.$/u, '') })
  const failure = line('Failure: ')
  if (failure !== undefined) fields.push({ label: 'Failure', value: failure })
  if (worker && typeof worker.status === 'string') fields.push({ label: 'Worker', value: worker.status })
  if (worker && typeof worker.blocker === 'string' && worker.blocker !== '') fields.push({ label: 'Blocker', value: worker.blocker })
  const progress = line('Progress file: ')
  if (progress !== undefined) fields.push({ label: 'Progress', value: progress })
  const groups: NonNullable<ToolDetailItem['groups']> = []
  if (worker && strings(worker.nextSteps) && worker.nextSteps.length > 0) groups.push({ label: 'Remaining work', items: [{ fields: [], lines: worker.nextSteps }] })
  if (typeof objective === 'string') groups.push({ label: 'Task', items: [{ fields: [], description: objective }] })
  if (tail !== '') groups.push({ label: 'Verifier output', items: [{ fields: [], code: tail }] })
  const title = worker ? String(worker.summary) : `Ended as ${status}`
  return {
    items: [{ title, badge: VERIFIED_BADGES[status] ?? { label: status, tone: 'warning' }, fields, groups }],
    summary: title,
  }
}

/** The result card of a finished loop tool call, or null to fall back to the generic IN/OUT body. */
export function loopToolDetails(item: ToolItem): ToolDetailsModel | null {
  if (!item.done || item.error || !item.preview) return null
  const objective = asArgs(item.args).objective
  if (item.name === 'ralph') return ralphDetails(objective, item.preview)
  if (item.name === 'verified_ralph') return verifiedRalphDetails(objective, item.preview)
  return null
}
