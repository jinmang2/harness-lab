/** Small shared pieces (menu, anchored dialog, disclosure row) with DSH ui-primitives markup. */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { IconCheckOutline16, IconChevronDownOutline14, IconChevronRightOutline14, IconCloseOutline16 } from '../dsh/icons.tsx'
import menuCss from '../dsh/css/Menu.module.css'
import dialogCss from '../dsh/css/stat-dialog.module.css'
import discCss from '../dsh/css/DisclosureRow.module.css'
import modalCss from '../dsh/css/Modal.module.css'
import buttonCss from '../dsh/css/Button.module.css'
import stateDotCss from '../dsh/css/StateDot.module.css'
import { cx } from '../lib/format.ts'

const MARGIN = 12

/** Close on outside pointerdown or Escape. */
export function useDismiss(open: boolean, close: () => void, refs: RefObject<HTMLElement | null>[]) {
  useEffect(() => {
    if (!open) return
    const down = (e: PointerEvent) => {
      if (refs.some(r => r.current?.contains(e.target as Node))) return
      close()
    }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    document.addEventListener('pointerdown', down)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key) }
  }, [open, close, refs])
}

/** Fixed position for a portaled card next to its anchor; flips to fit the viewport. */
export function useAnchoredPosition(open: boolean, anchor: RefObject<HTMLElement | null>, card: RefObject<HTMLElement | null>,
  side: 'top' | 'bottom' = 'bottom', align: 'start' | 'end' = 'start') {
  const [pos, setPos] = useState<React.CSSProperties>({ visibility: 'hidden', top: 0, left: 0 })
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const a = anchor.current?.getBoundingClientRect()
      const c = card.current?.getBoundingClientRect()
      if (!a || !c) return
      const vh = window.innerHeight, vw = window.innerWidth
      let top = side === 'bottom' ? a.bottom + 4 : a.top - 4 - c.height
      if (side === 'bottom' && top + c.height > vh - MARGIN && a.top - 4 - c.height > MARGIN) top = a.top - 4 - c.height
      if (side === 'top' && top < MARGIN && a.bottom + 4 + c.height < vh - MARGIN) top = a.bottom + 4
      let left = align === 'start' ? a.left : a.right - c.width
      left = Math.max(MARGIN, Math.min(left, vw - MARGIN - c.width))
      setPos({ top: Math.max(MARGIN, top), left })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open, anchor, card, side, align])
  return pos
}

interface MenuProps {
  open: boolean
  onClose: () => void
  anchor: RefObject<HTMLElement | null>
  side?: 'top' | 'bottom'
  align?: 'start' | 'end'
  children: ReactNode
  footer?: ReactNode
  minWidth?: number
  /** DSH Menu `dense`: tighter rows, same typography. */
  dense?: boolean
}

/** DSH Menu: portaled card (`list scrollable portal`) with a scrolling viewport. */
export function Menu({ open, onClose, anchor, side = 'bottom', align = 'start', children, footer, minWidth, dense }: MenuProps) {
  const card = useRef<HTMLDivElement>(null)
  const pos = useAnchoredPosition(open, anchor, card, side, align)
  const refs = useRef([card, anchor]).current
  useDismiss(open, onClose, refs)
  if (!open) return null
  return createPortal(
    <div ref={card} className={cx(menuCss.list, dense && menuCss.denseList, menuCss.scrollable, menuCss.portal)} role="menu" style={{ ...pos, minWidth }}>
      <div className={menuCss.viewport} role="presentation">{children}</div>
      {footer && <div className={menuCss.footer}>{footer}</div>}
    </div>,
    document.body,
  )
}

export function MenuItem({ selected, onSelect, children, icon, danger, disabled, trailing }: {
  selected?: boolean; onSelect: () => void; children: ReactNode; icon?: ReactNode; danger?: boolean; disabled?: boolean; trailing?: ReactNode
}) {
  return (
    <div className={menuCss.itemWrap}>
      <button type="button" role="menuitem" disabled={disabled}
        className={cx(menuCss.item, selected && menuCss.selected, danger && menuCss.danger)} onClick={onSelect}>
        {icon && <span className={menuCss.itemIcon}>{icon}</span>}
        <span className={menuCss.itemLabel}>{children}</span>
        {trailing}
        {selected && <IconCheckOutline16 className={menuCss.check} />}
      </button>
    </div>
  )
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <div className={menuCss.label}>{children}</div>
}

export function MenuSeparator() {
  return <div className={menuCss.separator} role="separator" />
}

/** DSH stat dialog (Turn usage, Ran for, session stats): click-open card above the trigger. */
export function StatDialog({ open, onClose, anchor, title, icon, value, children }: {
  open: boolean; onClose: () => void; anchor: RefObject<HTMLElement | null>; title: string; icon: ReactNode; value?: ReactNode; children: ReactNode
}) {
  const card = useRef<HTMLDivElement>(null)
  const pos = useAnchoredPosition(open, anchor, card, 'top', 'start')
  const refs = useRef([card, anchor]).current
  useDismiss(open, onClose, refs)
  if (!open) return null
  return createPortal(
    <div ref={card} className={dialogCss.panel} role="dialog" aria-label={title} style={pos}>
      <div className={dialogCss.title}>
        <span className={dialogCss.titleLabel}>{icon}{title}</span>
        {value !== undefined && <span className={dialogCss.titleValue}>{value}</span>}
      </div>
      <div className={dialogCss.titleRule} aria-hidden />
      <dl className={dialogCss.details}>{children}</dl>
    </div>,
    document.body,
  )
}

/**
 * DSH DisclosureRow (ui-primitives DisclosureRow.tsx). Passing `expandable` selects the DSH contract:
 * `collapsedContent` sits in the row, `children` is the body shown while open, and a non-expandable row
 * is plain (no button role). Without `expandable` the row keeps the older shape where `children` sit
 * in the row and the caller renders the body.
 */
export function DisclosureRow({
  icon, title, open, onToggle, children, className, rowClassName, leadingClassName, titleClassName,
  expandable, expandOnRowClick = true, previewChevron, keepContentWhenOpen = false, collapsedContent, chevronClassName,
}: {
  icon: ReactNode; title: ReactNode; open: boolean; onToggle: () => void; children?: ReactNode
  className?: string; rowClassName?: string; leadingClassName?: string; titleClassName?: string
  expandable?: boolean; expandOnRowClick?: boolean; previewChevron?: boolean; keepContentWhenOpen?: boolean
  collapsedContent?: ReactNode; chevronClassName?: string
}) {
  if (expandable === undefined) {
    return (
      <div className={cx(discCss.root, className)}>
        <div className={cx(discCss.row, rowClassName)} role="button" tabIndex={0} aria-expanded={open} data-expandable=""
          onClick={onToggle} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}>
          <span className={cx(discCss.leading, leadingClassName)}>
            {open
              ? <IconChevronDownOutline14 />
              : <><span className={discCss.iconIdle}>{icon}</span><IconChevronRightOutline14 className={discCss.chevronHover} /></>}
          </span>
          <span className={cx(discCss.title, titleClassName)}>{title}</span>
          {children}
        </div>
      </div>
    )
  }
  const rowExpands = expandable && expandOnRowClick
  const preview = previewChevron ?? expandable
  const leading = open
    ? <IconChevronDownOutline14 className={chevronClassName} />
    : preview
      ? <><span className={discCss.iconIdle}>{icon}</span><IconChevronDownOutline14 className={cx(chevronClassName, discCss.chevronHover)} /></>
      : icon
  return (
    <div className={cx(discCss.root, className)} data-open={open || undefined}>
      <div className={cx(discCss.row, rowClassName)} data-disclosure-row="" data-expandable={rowExpands || undefined}
        role={rowExpands ? 'button' : undefined} tabIndex={rowExpands ? 0 : undefined} aria-expanded={rowExpands ? open : undefined}
        onClick={rowExpands ? onToggle : undefined}
        onKeyDown={rowExpands ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } } : undefined}>
        {expandable && !rowExpands
          ? <button type="button" className={cx(discCss.leading, leadingClassName)} aria-expanded={open}
              onClick={e => { e.stopPropagation(); onToggle() }}>{leading}</button>
          : <span className={cx(discCss.leading, leadingClassName)}>{leading}</span>}
        <span className={cx(discCss.title, titleClassName)}>{title}</span>
        {(keepContentWhenOpen || !open) && collapsedContent}
      </div>
      {open && children}
    </div>
  )
}

/** DSH Modal: mask + dialog with header (title, close), body, footer. */
export function Modal({ open, onClose, title, description, children, footer, className }: {
  open: boolean; onClose: () => void; title: string; description?: ReactNode; children?: ReactNode; footer?: ReactNode; className?: string
}) {
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className={modalCss.root} role="presentation">
      <div className={modalCss.mask} aria-hidden="true" onClick={onClose} />
      <div className={cx(modalCss.dialog, className)} role="dialog" aria-modal="true" aria-label={title}>
        <div className={modalCss.content}>
          <div className={modalCss.header}>
            <h2 className={modalCss.title}>{title}</h2>
            <button type="button" className={modalCss.close} aria-label="Close" onClick={onClose}><IconCloseOutline16 size={14} /></button>
          </div>
          {description && <p className={modalCss.description}>{description}</p>}
          {children !== undefined && <div className={modalCss.body}>{children}</div>}
        </div>
        {footer && <div className={modalCss.footer}>{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

/** DSH Button: variant primary | outline | ghost, size sm | md. */
export function Button({ variant = 'outline', size = 'md', className, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'outline' | 'ghost'; size?: 'sm' | 'md' }) {
  return <button type="button" className={cx(buttonCss.button, buttonCss[variant], buttonCss[size], className)} {...rest} />
}

/** Outer 3x3 matrix cells of the ongoing StateDot, clockwise from top-left. */
const MATRIX_CELLS: readonly (readonly [number, number])[] = [[0, 0], [4, 0], [8, 0], [8, 4], [8, 8], [4, 8], [0, 8], [0, 4]]

/** DSH StateDot: done / warning / error / idle dot, or the chasing matrix while ongoing (aria-hidden). */
export function StateDot({ state, size = 10, className }: { state: 'done' | 'warning' | 'ongoing' | 'error' | 'idle'; size?: number; className?: string }) {
  if (state === 'ongoing') {
    return (
      <svg className={cx(stateDotCss.matrix, className)} data-state="ongoing" width={size} height={size} viewBox="0 0 10 10"
        shapeRendering="crispEdges" aria-hidden="true">
        {MATRIX_CELLS.map(([x, y], i) => (
          <rect key={`${x}-${y}`} className={stateDotCss.cell} x={x} y={y} width="2" height="2"
            style={{ animationDelay: `${(i - MATRIX_CELLS.length) * 125}ms` }} />
        ))}
      </svg>
    )
  }
  return <span className={cx(stateDotCss.dot, className)} data-state={state} style={{ width: size, height: size }} aria-hidden="true" />
}
