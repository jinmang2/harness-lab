/**
 * DSH `/` trigger menu (ui-input-trigger MenuView, ui-primitives rankByName; MIT): the command
 * listbox floating above the composer card. Focus stays in the draft (combobox pattern), so rows
 * act on mousedown and the highlight rides aria-activedescendant. Same DOM, class names and copy.
 */
import { useEffect, useRef } from 'react'
import css from '../dsh/css/MenuView.module.css'
import { cx } from '../lib/format.ts'

export interface CommandDef { name: string; description: string; hint: string }

/** DSH's command roster entries for the commands the lab implements (roster order). */
export const LAB_COMMANDS: Record<'goal' | 'plan', CommandDef> = {
  goal: { name: 'goal', description: 'set or view the goal for a long-running task', hint: 'describe the objective for a long-running task' },
  plan: { name: 'plan', description: 'Enter or leave plan mode', hint: 'describe your task to generate plan' },
}
export const GOAL_ACTIVE_HINT = 'goal active — edit / pause / resume / clear'

function boundaryBonus(name: string, index: number): number {
  return index === 0 || name.charAt(index - 1) === '-' || name.charAt(index - 1) === '_' ? 8 : 0
}

/** Strongest ordered-subsequence alignment of `query` in `name`; undefined when it is not a subsequence. */
function alignmentScore(name: string, query: string): number | undefined {
  if (query.length > name.length) return undefined
  const none = Number.NEGATIVE_INFINITY
  let previous = Array<number>(name.length).fill(none)
  for (let i = 0; i < name.length; i++) if (name.charAt(i) === query.charAt(0)) previous[i] = 1 + boundaryBonus(name, i) - i
  for (let q = 1; q < query.length; q++) {
    const current = Array<number>(name.length).fill(none)
    let left = none, leftLeft = none, bestGapped = none
    for (const [i, prior] of previous.entries()) {
      if (leftLeft !== none) bestGapped = Math.max(bestGapped, leftLeft + i - 2)
      if (name.charAt(i) === query.charAt(q)) {
        const bonus = 1 + boundaryBonus(name, i)
        let score = none
        if (left !== none) score = left + bonus + 4
        if (bestGapped !== none) score = Math.max(score, bestGapped + bonus + 1 - i)
        current[i] = score
      }
      leftLeft = left
      left = prior
    }
    previous = current
  }
  const best = Math.max(...previous)
  return best === none ? undefined : best
}

/** DSH rankByName: prefix hits first, then alignment score, then source order. */
export function rankByName<T extends { name: string }>(items: readonly T[], rawQuery: string): T[] {
  const query = rawQuery.toLowerCase()
  if (query === '') return [...items]
  const ranked: { item: T; index: number; prefix: boolean; score: number }[] = []
  items.forEach((item, index) => {
    const name = item.name.toLowerCase()
    const score = alignmentScore(name, query)
    if (score !== undefined) ranked.push({ item, index, prefix: name.startsWith(query), score })
  })
  ranked.sort((a, b) => Number(b.prefix) - Number(a.prefix) || b.score - a.score || a.index - b.index)
  return ranked.map(r => r.item)
}

const optionId = (index: number) => `dsh-slash-option-command-${index}`

export function CommandMenu({ items, highlight, onPick, onHover, onDismiss }: {
  items: CommandDef[]; highlight: number; onPick: (index: number) => void; onHover: (index: number) => void; onDismiss: () => void
}) {
  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    document.getElementById(optionId(highlight))?.scrollIntoView({ block: 'nearest' })
  }, [highlight])
  // Dismiss on pointer outside the menu and outside the composer card.
  useEffect(() => {
    const down = (ev: PointerEvent) => {
      if (!(ev.target instanceof Node)) return
      if (listRef.current?.contains(ev.target)) return
      if (listRef.current?.closest('[data-composer-card]')?.contains(ev.target)) return
      onDismiss()
    }
    document.addEventListener('pointerdown', down, true)
    return () => document.removeEventListener('pointerdown', down, true)
  }, [onDismiss])
  return (
    <div ref={listRef} className={css.menu} data-trigger-menu="">
      <div className={css.viewport} role="listbox" aria-label="Trigger suggestions"
        aria-activedescendant={items.length ? optionId(highlight) : undefined}>
        {items.length > 0 && <div className={css.groupTitle} role="presentation" data-source="command">Commands</div>}
        {items.map((item, index) => (
          <button key={item.name} id={optionId(index)} type="button" role="option" aria-selected={index === highlight}
            className={cx(css.item, index === highlight && css.active)}
            onMouseDown={ev => { ev.preventDefault(); onPick(index) }}
            onMouseMove={index === highlight ? undefined : () => onHover(index)}>
            <span className={css.itemName}>{item.name}</span>
            <span className={css.itemDescription}>{item.description}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
