/** Number and time labels in DSH Web's style ("18.1K tok", "Ran for 1m 05s", "14:02"). */

/** DSH formatTokens (ui-chat token-format.ts): 517 / 12.2K / 517K / 1.2M. */
export function tok(n: number | undefined | null): string {
  const v = Math.max(0, n ?? 0)
  const scaled = (x: number) => (x >= 100 ? String(Math.round(x)) : String(Math.round(x * 10) / 10))
  if (v < 1000) return String(v)
  if (v < 1_000_000) return `${scaled(v / 1000)}K`
  return `${scaled(v / 1_000_000)}M`
}

export const num = (n: unknown): string => (n == null ? '—' : Number(n).toLocaleString())

export function duration(ms: number | undefined | null): string {
  const s = Math.max(0, Math.round((ms ?? 0) / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

/** DSH formatRunDuration (ui-chat message-chrome.ts): whole seconds, "42s" or "1m 05s". */
export function runDuration(ms: number | undefined | null): string {
  const total = Math.max(0, Math.floor((ms ?? 0) / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`
}

/** DSH formatLatencySeconds: one decimal under ten seconds, whole seconds beyond. */
export function latencySeconds(ms: number): string {
  const s = Math.max(0, ms) / 1000
  return s < 10 ? String(Math.round(s * 10) / 10) : String(Math.round(s))
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** Wall-clock HH:mm of a unix-seconds timestamp. */
export function clock(t: number): string {
  const d = new Date(t * 1000)
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** DSH formatMessageClock: same day "HH:mm"; this year "M/D HH:mm"; older "Y-M-D HH:mm". */
export function messageClock(t: number, now = Date.now()): string {
  const d = new Date(t * 1000)
  const n = new Date(now)
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  if (d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate()) return hm
  const md = d.getFullYear() === n.getFullYear()
    ? `${d.getMonth() + 1}/${d.getDate()}`
    : `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
  return `${md} ${hm}`
}

export function ago(t: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - t)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}min`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

/** DSH fileSizeText (ui-primitives file-size.ts): 312B, 4.2KB, 15MB. */
export function fileSizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)}KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)}MB`
  const gb = mb / 1024
  return `${gb < 10 ? gb.toFixed(1) : Math.round(gb)}GB`
}

export const cx = (...xs: (string | false | null | undefined)[]): string => xs.filter(Boolean).join(' ')
