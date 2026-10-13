/** JSON API of `lab ui` (lab/viewer/server.py). Mutations carry the X-Lab header (CSRF guard). */

export async function get<T>(path: string): Promise<T> {
  const r = await fetch('/api/' + path)
  if (!r.ok) {
    let msg = String(r.status)
    try { msg = (await r.json()).error || msg } catch { /* not JSON */ }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

export async function getText(path: string): Promise<string | null> {
  const r = await fetch('/api/' + path)
  return r.ok ? r.text() : null
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch('/api/' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Lab': '1' },
    body: JSON.stringify(body ?? {}),
  })
  const j = await r.json()
  if (!r.ok) throw new Error(j.error || String(r.status))
  return j as T
}

export interface ModelInfo { id: string; name: string; context: number; input?: string[] }
export interface Config {
  play: boolean
  dsh_installed: boolean
  dsh_version: string
  models: ModelInfo[]
  efforts: string[]
  default_model: string
  default_effort: string
}
export interface HarnessInfo { engine: 'lab' | 'dsh'; name: string; description: string }
export interface SessionInfo {
  id: string
  engine: 'lab' | 'dsh'
  harness: string
  model: string
  effort: string | null
  approval: 'auto' | 'ask'
  title: string
  status: 'idle' | 'running' | 'waiting' | 'error' | 'archived'
  batch: string
  run_id: string
  workdir: string
  created: number
  updated: number
  turns: number
  events: number
  /** Lab harness with DSH plan mode + ask_user_question (lab/middleware/collaboration.py). */
  supports_plan?: boolean
  plan_mode?: boolean
  /** Lab harness with DSH goal tools + round driver (lab/middleware/goal.py). */
  supports_goal?: boolean
  goal?: Goal | null
  /** Messages sent while a turn runs: next-turn (queued) or next-step (steered, not yet claimed). */
  queue?: QueueItem[]
  /** Forked from this session id. */
  parent?: string | null
  /** A settled turn exists, so the session can be forked. */
  branchable?: boolean
}

/** DSH goal snapshot (packages/goal/goal) plus its activation. */
export interface Goal {
  id: string
  revision: number
  objective: string
  phase: 'active' | 'paused' | 'blocked' | 'complete'
  maxGoalRounds: number
  roundsStarted: number
  activation: 'armed' | 'disarmed'
  blockedReason?: { code: string; message: string }
}

/** An uploaded attachment as the browser sees it (no host path). Images are served at play/<id>/attachment/<aid>. */
export interface Attachment { id: string; name: string; mime: string; bytes: number; kind: 'image' | 'file'; width?: number; height?: number }

export interface QueueItem { id: string; text: string; target: 'next-turn' | 'next-step'; attachments: Attachment[] }
export interface Workspace { path: string; title: string; exists: boolean }
export interface PlayEvent { seq: number; type: string; t: number; [k: string]: unknown }
export interface EventsReply extends SessionInfo { items: PlayEvent[] }
export interface FileEntry { path: string; bytes: number; mtime?: number }

export interface Usage {
  input_tokens?: number
  output_tokens?: number
  input_token_details?: { cache_read?: number }
  output_token_details?: { reasoning?: number }
  steps?: number
  last_input?: number
}

export interface Settings {
  secrets: Record<string, { configured: boolean; source: string | null }>
  values: Record<string, { value: string; default: string; source: string | null }>
  choices: Record<string, string[]>
  models: string[]
  efforts: string[]
  env_file: string
  gateway: { running: boolean; mode?: string; url?: string; upstream?: string }
}

export interface RunSummary {
  run_id: string; batch: string; task: string; engine: string; harness: string; repeat: number; model: string
  status: string; check: boolean | null; quality?: number | null; quality_detail?: unknown
  tool_selection?: { accuracy: number; required_met: boolean; off_target: string[] } | null
  recovery?: { tool_errors: number; recovered: boolean | null }
  interrupts?: number; wall_ms: number; turn_ms?: number | null; llm_calls: number; tool_calls: number; tool_errors?: number
  tools_used?: string[]; tool_sequence?: string[]
  first_request?: { system_chars: number; tool_count: number; tools: string[]; input_billed: number }
  input_uncached: number; cache_read: number; cache_write?: number; output: number; reasoning: number
  input_billed: number; total_tokens: number; final?: string; error?: string
}
export interface BatchInfo { name: string; runs: number; tasks: string[]; harnesses: string[] }
export interface TraceEvent { kind: string; [k: string]: unknown }
export interface RunDetail { events: TraceEvent[]; wire: Record<string, unknown>[]; files: FileEntry[]; stderr: string }
