/**
 * DSH GoalBar (ui-goal; MIT): the goal strip docked above the composer — glyph, phase label, objective,
 * and pause / resume / edit / clear. Same DOM, class names and copy. Goals are created with `/goal`;
 * no goal and complete goals render nothing.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  IconCheckOutline16, IconCloseOutline16, IconEditOutline16, IconGoalOutline16, IconPauseOutline16, IconPlayOutline16, IconTrashOutline16,
} from '../dsh/icons.tsx'
import css from '../dsh/css/GoalBar.module.css'
import type { Goal } from '../lib/api.ts'

export type GoalAction = 'edit' | 'pause' | 'resume' | 'clear'

const PHASE_LABEL = { active: 'Ongoing Goal', paused: 'Paused Goal', blocked: 'Blocked Goal' } as const

export function GoalBar({ goal, onAction }: { goal: Goal | null | undefined; onAction: (action: GoalAction, objective?: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [clearedGoalId, setClearedGoalId] = useState<string | null>(null)
  const pendingRef = useRef(false)

  // A new goal identity invalidates the local edit state.
  const goalId = goal?.id
  useEffect(() => {
    setEditing(false)
    setActionError(null)
    setClearedGoalId(null)
  }, [goalId])

  const run = useCallback(async (action: GoalAction, objective?: string): Promise<boolean> => {
    if (pendingRef.current) return false
    pendingRef.current = true
    setPending(true)
    setActionError(null)
    try {
      await onAction(action, objective)
      return true
    } catch (e) {
      setActionError((e as Error).message)
      return false
    } finally {
      pendingRef.current = false
      setPending(false)
    }
  }, [onAction])

  const handleEdit = async () => {
    const trimmed = draft.trim()
    if (trimmed === '') return
    if (await run('edit', trimmed)) setEditing(false)
  }

  if (!goal || goal.phase === 'complete' || goal.id === clearedGoalId) return null

  if (editing) {
    return (
      <div className={css.dock} data-goal-bar="">
        <div className={css.bar}>
          <input className={css.objectiveInput} type="text" aria-label="Goal objective" value={draft} autoFocus
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') void handleEdit()
              if (e.key === 'Escape') setEditing(false)
            }} />
          {actionError !== null && <span className={css.error} role="alert">{actionError}</span>}
          <div className={css.actions}>
            <button type="button" className={css.iconBtn} onClick={() => void handleEdit()} disabled={pending || draft.trim() === ''} aria-label="Save goal">
              <IconCheckOutline16 size={14} />
            </button>
            <button type="button" className={css.iconBtn} onClick={() => setEditing(false)} disabled={pending} aria-label="Cancel edit">
              <IconCloseOutline16 size={14} />
            </button>
          </div>
        </div>
      </div>
    )
  }

  const disarmed = goal.activation === 'disarmed'
  const label = goal.phase === 'active' && disarmed ? 'Inactive Goal' : PHASE_LABEL[goal.phase]
  const showResume = goal.phase === 'paused' || (goal.phase === 'active' && disarmed)
  return (
    <div className={css.dock} data-goal-bar="">
      <div className={css.bar} title={goal.phase === 'blocked' ? goal.blockedReason?.message : undefined}>
        <span className={css.goalGlyph}><IconGoalOutline16 size={14} /></span>
        <span className={css.label}>{label}</span>
        <span className={css.objective}>{goal.objective}</span>
        {actionError !== null && <span className={css.error} role="alert">{actionError}</span>}
        <div className={css.actions}>
          {goal.phase === 'active' && goal.activation === 'armed' && (
            <button type="button" className={css.iconBtn} disabled={pending} onClick={() => void run('pause')} aria-label="Pause goal">
              <IconPauseOutline16 size={14} />
            </button>
          )}
          {showResume && (
            <button type="button" className={css.iconBtn} disabled={pending} onClick={() => void run('resume')} aria-label="Resume goal">
              <IconPlayOutline16 size={14} />
            </button>
          )}
          <button type="button" className={css.iconBtn} disabled={pending} onClick={() => { setDraft(goal.objective); setEditing(true) }} aria-label="Edit goal">
            <IconEditOutline16 size={14} />
          </button>
          <button type="button" className={css.iconBtn} disabled={pending}
            onClick={() => { const id = goal.id; void run('clear').then(ok => { if (ok) setClearedGoalId(id) }) }} aria-label="Clear goal">
            <IconTrashOutline16 size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
