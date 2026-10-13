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
}

const emptyUsage = () => ({ input: 0, cached: 0, output: 0, reasoning: 0, steps: 0, lastInput: 0 })

const asAttachments = (v: unknown): Attachment[] => (Array.isArray(v) ? v as Attachment[] : [])

export function fold(events: PlayEvent[]): Folded {
  const out: Folded = { turns: [], after: [] }
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
      default: {
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
