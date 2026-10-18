/**
 * Child agents of a session (ralph rounds): DSH ui-subagent SubagentHeaderLineage (the header's "N subagents"
 * catalog and the child crumb's sibling switcher) and SubagentReadOnlyComposer, ported from DeepSeek Harness (MIT).
 * DSH reads children from the session catalog; lab folds them from `child_start` / `child_end` events.
 */
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { IconChevronDownOutline14 } from '../dsh/icons.tsx'
import css from '../dsh/css/SubagentHeaderLineage.module.css'
import readOnly from '../dsh/css/SubagentReadOnlyComposer.module.css'
import { tok } from '../lib/format.ts'
import { childName, type ChildAgent } from '../lib/turns.ts'
import { StateDot } from './primitives.tsx'

/** DSH formatDuration below a day: "12s", "3m 04s", "1h 02m 03s"; days as "2d 3h". */
export function childDuration(ms: number): string {
  const total = Math.floor(Math.max(0, ms) / 1000)
  const s = total % 60
  const m = Math.floor(total / 60) % 60
  const h = Math.floor(total / 3600)
  const pad = (v: number) => String(v).padStart(2, '0')
  if (h >= 24) return h % 24 === 0 ? `${Math.floor(h / 24)}d` : `${Math.floor(h / 24)}d ${h % 24}h`
  if (h > 0) return `${h}h ${pad(m)}m ${pad(s)}s`
  if (total >= 60) return `${Math.floor(total / 60)}m ${pad(s)}s`
  return `${s}s`
}

function SubagentSwitcherIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M5.99951 12.7L8.95546 14.9478C9.40011 15.2859 9.62244 15.455 9.87526 15.488C9.95774 15.4988 10.0413 15.4988 10.1238 15.488C10.3766 15.455 10.5989 15.2859 11.0436 14.9478L13.9995 12.7" stroke="currentColor" strokeWidth="1.5" />
      <path d="M13.9995 7.7417L11.0436 5.49387C10.5989 5.15574 10.3766 4.98668 10.1238 4.95362C10.0413 4.94283 9.95775 4.94283 9.87527 4.95362C9.62245 4.98668 9.40012 5.15574 8.95547 5.49387L5.99952 7.7417" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

const MENU_VIEWPORT_MARGIN = 16

/** DSH catalogMenuPosition: below the trigger, inside the viewport. */
function menuPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(336, window.innerWidth - MENU_VIEWPORT_MARGIN * 2)
  return { top: rect.bottom + 5, left: Math.min(Math.max(MENU_VIEWPORT_MARGIN, rect.left), window.innerWidth - width - MENU_VIEWPORT_MARGIN) }
}

function CatalogRows({ items, all, current, level, now, onOpen }: {
  items: ChildAgent[]; all: ChildAgent[]; current?: string; level: number; now: number; onOpen: (id: string) => void
}) {
  return (
    <>
      {items.map(c => {
        const label = childName(c)
        const activity = c.status === 'running' ? 'running' : c.status === 'done' ? 'completed' : 'not running'
        // DSH: the child's title, its mode (lab children are one-shot rounds), then its activity.
        const secondary = [c.label !== null ? c.title : undefined, 'one-shot', activity].filter(v => v !== undefined).join(' · ')
        const total = c.usage.input + c.usage.output
        const tokens = c.usage.steps > 0 ? `${tok(total)} tok` : undefined
        const ms = Math.max(0, ((c.t1 ?? now / 1000) - c.t0) * 1000)
        const nested = all.filter(x => x.parent === c.id)
        const isCurrent = c.id === current
        const open = () => onOpen(c.id)
        const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); open() }
        }
        return (
          <div key={c.id} className={css.node}>
            <div role="treeitem" tabIndex={0} aria-level={level} aria-current={isCurrent || undefined}
              aria-label={[label, secondary, tokens, childDuration(ms)].filter(Boolean).join(' ')}
              className={css.row} data-child-id={c.id} onClick={open} onKeyDown={onKey}>
              <div className={css.clickarea}>
                <span className={css.rowActivitySlot}>
                  <StateDot state={c.status === 'running' ? 'ongoing' : c.status === 'done' ? 'done' : 'idle'} />
                </span>
                <span className={css.content}>
                  <span className={`${css.label} ${isCurrent ? css.currentLabel : ''}`}>{label}</span>
                  <span className={css.summary}>{secondary}</span>
                </span>
                <span className={css.metrics}>
                  {tokens !== undefined && <span className={css.metricToken}>{tokens}</span>}
                  <span className={css.metricDuration} title={`Total active duration: ${childDuration(ms)}`}>{childDuration(ms)}</span>
                </span>
              </div>
            </div>
            {nested.length > 0 && (
              <div role="group" className={css.children}>
                <CatalogRows items={nested} all={all} current={current} level={level + 1} now={now} onOpen={onOpen} />
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}

/**
 * DSH CatalogDropdown. `count`: the root session's "N subagents" control in the header actions band.
 * `switcher`: the open child's crumb (its name and the switcher glyph) listing its siblings.
 */
export function SubagentCatalog({ items, variant, current, onOpen }: {
  items: ChildAgent[]; variant: 'count' | 'switcher'; current?: string; onOpen: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<CSSProperties>()
  const [now, setNow] = useState(() => Date.now())
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const top = items.filter(c => c.parent === null || !items.some(x => x.id === c.parent))
  const running = top.filter(c => c.status === 'running').length
  const anyRunning = items.some(c => c.status === 'running')

  useEffect(() => {
    if (!open || !anyRunning) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [open, anyRunning])
  useEffect(() => {
    if (!open) return
    const outside = (e: PointerEvent) => {
      if (e.target instanceof Node && !rootRef.current?.contains(e.target) && !menuRef.current?.contains(e.target)) setOpen(false)
    }
    const place = () => { if (triggerRef.current) setPos(menuPosition(triggerRef.current)) }
    document.addEventListener('pointerdown', outside)
    window.addEventListener('resize', place)
    document.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('resize', place)
      document.removeEventListener('scroll', place, true)
    }
  }, [open])

  if (items.length === 0) return null
  const toggle = () => {
    if (!open && triggerRef.current) { setPos(menuPosition(triggerRef.current)); setNow(Date.now()) }
    setOpen(!open)
  }
  const focusAt = (index: number) => {
    const rows = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])
    if (rows.length > 0) rows[(index + rows.length) % rows.length]?.focus()
  }
  const navigate = (e: KeyboardEvent<HTMLDivElement>) => {
    const rows = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])
    const index = rows.indexOf(document.activeElement as HTMLElement)
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); triggerRef.current?.focus() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(index + 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(index < 0 ? rows.length - 1 : index - 1) }
  }
  const count = `${top.length} subagent${top.length === 1 ? '' : 's'}`
  const currentChild = items.find(c => c.id === current)
  return (
    <div className={`${css.root} ${variant === 'switcher' ? css.switcherRoot : ''}`} ref={rootRef} onKeyDown={navigate}>
      <button ref={triggerRef} type="button" className={variant === 'switcher' ? css.switcherTrigger : css.trigger}
        aria-haspopup="tree" aria-expanded={open}
        aria-label={variant === 'switcher' ? `Switch subagent: ${currentChild ? childName(currentChild) : ''}`
          : running > 0 ? `${running} subagent${running === 1 ? '' : 's'} running` : count}
        onClick={toggle}
        onKeyDown={e => { if (e.key === 'ArrowDown') { e.preventDefault(); if (!open) toggle(); queueMicrotask(() => focusAt(0)) } }}>
        {variant === 'switcher'
          ? <span className={css.switcherTitle}>{currentChild ? childName(currentChild) : ''}</span>
          : (
            <>
              {running > 0 && <span className={css.activitySlot}><StateDot state="ongoing" /></span>}
              <span>{count}</span>
            </>
          )}
        {variant === 'switcher' ? <SubagentSwitcherIcon /> : <IconChevronDownOutline14 className={open ? css.triggerOpen : undefined} />}
      </button>
      {open && createPortal((
        <div ref={menuRef} className={css.menu} style={pos} onKeyDown={navigate}>
          <div className={css.menuBody} role="tree" aria-label="Subagent sessions">
            <CatalogRows items={top} all={items} current={current} level={1} now={now}
              onOpen={id => { setOpen(false); onOpen(id) }} />
          </div>
        </div>
      ), document.body)}
    </div>
  )
}

/** DSH SubagentReadOnlyComposer (one-shot): a child round takes no follow-up messages. */
export function SubagentReadOnlyComposer() {
  return (
    // Same width as the input card it replaces (DSH seats it in the composer chain).
    <div className={readOnly.frame} role="status"
      style={{ boxSizing: 'border-box', width: 'min(var(--dsh-composer-card-max-width), calc(100% - 48px))', margin: '0 auto 20px' }}>
      <strong>One-shot subagent record</strong>
      <span>One-shot tasks do not accept follow-ups; review the full execution record here.</span>
    </div>
  )
}
