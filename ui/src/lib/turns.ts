/** Fold a session's event stream (lab/viewer/play.py) into DSH-style turns. */
import type { PlayEvent, Usage } from './api.ts'

export interface ThinkItem { kind: 'think'; key: string; text: string; nested: boolean; done: boolean }
export interface TextItem { kind: 'text'; key: string; text: string; nested: boolean; done: boolean }
export interface ToolItem { kind: 'tool'; key: string; name: string; args: unknown; preview?: string; error?: boolean; done: boolean; nested: boolean }
export interface NoteItem { kind: 'note'; key: string; text: string; tone?: 'error' | 'muted' }
export interface ApprovalItem { kind: 'approval'; key: string; actions: { name: string; args: unknown; description?: string }[]; decision?: string }
export type ProcessItem = ThinkItem | TextItem | ToolItem | NoteItem | ApprovalItem

export interface Turn {
  index: number
  user: string
  userT: number
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
}

const emptyUsage = () => ({ input: 0, cached: 0, output: 0, reasoning: 0, steps: 0, lastInput: 0 })

export function fold(events: PlayEvent[]): Folded {
  const out: Folded = { turns: [] }
  let turn: Turn | null = null
  const llm = new Map<string, { think?: ThinkItem; text?: TextItem; nested: boolean; t0: number }>()
  const tools = new Map<string, ToolItem & { t0: number }>()
  for (const ev of events) {
    switch (ev.type) {
      case 'session': out.session = ev; break
      case 'request': out.request = { system: String(ev.system ?? ''), tools: (ev.tools as string[]) ?? [] }; break
      case 'user':
        turn = { index: out.turns.length, user: String(ev.text ?? ''), userT: ev.t, items: [], answer: '', answerKey: null, status: 'running', usage: emptyUsage(), llmMs: 0, toolMs: 0 }
        out.turns.push(turn)
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
        } else if (ev.type === 'interrupt') {
          t.items.push({ kind: 'approval', key: 'appr' + ev.seq, actions: (ev.actions as ApprovalItem['actions']) ?? [] })
          t.status = 'waiting'
        } else if (ev.type === 'decision') {
          const last = [...t.items].reverse().find(i => i.kind === 'approval') as ApprovalItem | undefined
          if (last) last.decision = String(ev.decision)
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

/** Short label of a tool for its card title, like DSH Web's tool views. */
export function toolTitle(name: string): string {
  const map: Record<string, string> = {
    bash: 'Bash', execute: 'Bash', shell: 'Bash', read_file: 'Read', read: 'Read', write_file: 'Write', write: 'Write',
    edit_file: 'Edit', edit: 'Edit', ls: 'List', glob: 'Glob', grep: 'Grep', fetch_url: 'Fetch', web_fetch: 'Fetch',
    web_search: 'Search', write_todos: 'Todo', todo_write: 'Todo', task: 'Subagent', skill: 'Skill',
  }
  return map[name] ?? name
}

export function asArgs(args: unknown): Record<string, unknown> {
  if (args && typeof args === 'object') return args as Record<string, unknown>
  if (typeof args === 'string') {
    try { const v = JSON.parse(args); if (v && typeof v === 'object') return v } catch { /* plain string */ }
    return { input: args }
  }
  return {}
}

export function toolSummary(name: string, args: unknown): string {
  const a = asArgs(args)
  const pick = (...ks: string[]) => { for (const k of ks) if (typeof a[k] === 'string' && a[k]) return String(a[k]); return '' }
  switch (toolTitle(name)) {
    case 'Bash': return pick('description', 'command')
    case 'Read': case 'Write': case 'Edit': case 'List': return pick('file_path', 'path')
    case 'Glob': case 'Grep': return pick('pattern', 'query')
    case 'Fetch': return pick('url')
    case 'Subagent': return pick('description', 'subagent_type')
    case 'Todo': return Array.isArray(a.todos) ? `${(a.todos as unknown[]).length} items` : ''
    default: return pick('description', 'query', 'path', 'input')
  }
}
