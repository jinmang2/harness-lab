/** Number and time labels in DSH Web's style ("18.1K tok", "Ran for 3s", "now"). */

export function tok(n: number | undefined | null): string {
  const v = n ?? 0
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M'
  if (v >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, '') + 'K'
  return String(v)
}

export const num = (n: unknown): string => (n == null ? '—' : Number(n).toLocaleString())

export function duration(ms: number | undefined | null): string {
  const s = Math.max(0, Math.round((ms ?? 0) / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${s % 60}s`
}

export function clock(t: number): string {
  const d = new Date(t * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function ago(t: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - t)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}min`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export const cx = (...xs: (string | false | null | undefined)[]): string => xs.filter(Boolean).join(' ')
