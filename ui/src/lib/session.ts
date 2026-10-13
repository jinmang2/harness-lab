/** Poll one chat session's events (single-flight, incremental by sequence number). */
import { useEffect, useRef, useState } from 'react'
import { get, type EventsReply, type PlayEvent, type SessionInfo } from './api.ts'

export function useSessionEvents(id: string | null) {
  const [info, setInfo] = useState<SessionInfo | null>(null)
  const [events, setEvents] = useState<PlayEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const state = useRef({ id, after: 0, timer: 0 as unknown as ReturnType<typeof setTimeout>, alive: true, kick: () => {} })

  useEffect(() => {
    const s = state.current
    s.id = id; s.after = 0; s.alive = true
    setEvents([]); setInfo(null); setError(null)
    if (!id) return
    let inflight = false
    const tick = async () => {
      clearTimeout(s.timer)
      if (!s.alive || inflight) return
      inflight = true
      let status = 'idle'
      try {
        const r = await get<EventsReply>(`play/${id}/events?after=${s.after}`)
        if (!s.alive || s.id !== id) return
        status = r.status
        const { items, ...meta } = r
        setInfo(meta)
        if (items.length) {
          s.after += items.length
          setEvents(prev => [...prev, ...items])
        }
        setError(null)
      } catch (e) {
        setError((e as Error).message)
      } finally {
        inflight = false
      }
      if (!s.alive || status === 'archived') return
      s.timer = setTimeout(tick, status === 'running' ? 300 : 1500)
    }
    s.kick = () => { setTimeout(tick, 50) }
    tick()
    return () => { s.alive = false; clearTimeout(s.timer) }
  }, [id])

  return { info, events, error, kick: () => state.current.kick() }
}
