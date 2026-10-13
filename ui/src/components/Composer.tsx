/**
 * DSH InputBar (ui-conversation skeleton/InputBar, submission-policy; ui-chat StatsPills; ui-primitives
 * Toast; ui-model-selection ModelSelect; MIT): draft, Commands + attachments, access mode, model + effort,
 * context meter, send / queue / steer / stop; StatsPills underneath. Same DOM, class names and copy.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  IconCheckOutline16, IconChevronDownOutline14, IconChevronRightOutline14, IconDataOutline16, IconDatabaseOutline16,
  IconGaugeOutline16, IconPaperclipOutline16, IconPlusOutline16, IconUserOutline16, IconWarningOutline16,
} from '../dsh/icons.tsx'
import css from '../dsh/css/InputBar.module.css'
import modelCss from '../dsh/css/ModelSelect.module.css'
import permCss from '../dsh/css/PermissionSelect.module.css'
import meterCss from '../dsh/css/ContextMeter.module.css'
import pillCss from '../dsh/css/StatsPills.module.css'
import toastCss from '../dsh/css/Toast.module.css'
import { cx, tok } from '../lib/format.ts'
import { useStore } from '../lib/store.tsx'
import { Menu, MenuItem, StatDialog, useDismiss } from './primitives.tsx'
import { CommandMenu, GOAL_ACTIVE_HINT, rankByName, type CommandDef } from './CommandMenu.tsx'
import { ComposerAttachments, attachmentErrorText, intakeError, pendingAttachment, type PendingAttachment } from './ComposerAttachments.tsx'

export const ACCESS = {
  auto: { label: 'Auto approve', desc: 'Run shell commands and file writes without asking' },
  ask: { label: 'Ask first', desc: 'Pause for approval before shell commands and file writes' },
} as const

const EFFORT_LABEL: Record<string, string> = { off: 'Off', low: 'Low', high: 'High', max: 'Max' }

export function modelDisplay(id: string, models: { id: string; name: string }[] | undefined): string {
  return models?.find(m => m.id === id)?.name ?? id
}

export function PermissionSelect({ value, onChange, disabled, title }: {
  value: 'auto' | 'ask'; onChange: (v: 'auto' | 'ask') => void; disabled?: boolean; title?: string
}) {
  const anchor = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  return (
    <>
      <button ref={anchor} type="button" className={permCss.trigger} disabled={disabled} title={title}
        aria-label={`Access mode, current: ${ACCESS[value].label}`} onClick={() => setOpen(!open)}>
        <span className={permCss.triggerIcon}><IconUserOutline16 /></span>
        <span className={permCss.triggerLabel}>{ACCESS[value].label}</span>
        <span className={cx(permCss.chevron, open && permCss.chevronOpen)}><IconChevronDownOutline14 /></span>
      </button>
      <Menu open={open} onClose={() => setOpen(false)} anchor={anchor} side="top">
        {(Object.keys(ACCESS) as ('auto' | 'ask')[]).map(k => (
          <MenuItem key={k} selected={k === value} onSelect={() => { onChange(k); setOpen(false) }}>
            <span style={{ display: 'flex', flexDirection: 'column' }}>
              <span>{ACCESS[k].label}</span>
              <span style={{ fontSize: 12, lineHeight: '18px', color: 'var(--dsw-alias-label-tertiary)' }}>{ACCESS[k].desc}</span>
            </span>
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}

export function ModelSelect({ model, effort, onChange, disabled }: {
  model: string; effort: string; onChange: (model: string, effort: string) => void; disabled?: boolean
}) {
  const { config } = useStore()
  const root = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [pane, setPane] = useState<'root' | 'model' | 'effort'>('root')
  const refs = useRef([root]).current
  useDismiss(open, () => setOpen(false), refs)
  const efforts = config?.efforts ?? ['off', 'low', 'high', 'max']
  return (
    <div ref={root} className={modelCss.root}>
      <button type="button" className={modelCss.trigger} disabled={disabled} aria-haspopup="menu" aria-expanded={open}
        aria-label={`Select model, current ${modelDisplay(model, config?.models)}, reasoning effort ${EFFORT_LABEL[effort] ?? effort}`}
        title={`${modelDisplay(model, config?.models)} · ${EFFORT_LABEL[effort] ?? effort}`}
        onClick={() => { setOpen(!open); setPane('root') }}>
        <IconDataOutline16 className={modelCss.triggerIcon} size={16} />
        <span className={modelCss.triggerLabel}>{modelDisplay(model, config?.models)}</span>
        <span className={modelCss.triggerEffort}>{EFFORT_LABEL[effort] ?? effort}</span>
        <IconChevronDownOutline14 className={cx(modelCss.chevron, open && modelCss.chevronOpen)} />
      </button>
      {open && (
        <div className={modelCss.menu} role="menu" aria-label="Model and reasoning effort">
          {pane === 'root' && (
            <>
              <button type="button" role="menuitem" className={modelCss.cell} onClick={() => setPane('model')}>
                <span className={modelCss.cellLabel}>Model</span>
                <span className={modelCss.cellValue}>{modelDisplay(model, config?.models)}</span>
                <IconChevronRightOutline14 className={modelCss.cellChevron} />
              </button>
              <button type="button" role="menuitem" className={modelCss.cell} onClick={() => setPane('effort')}>
                <span className={modelCss.cellLabel}>Effort</span>
                <span className={modelCss.cellValue}>{EFFORT_LABEL[effort] ?? effort}</span>
                <IconChevronRightOutline14 className={modelCss.cellChevron} />
              </button>
            </>
          )}
          {pane === 'model' && (
            <div className={modelCss.groups}>
              <section role="group" className={modelCss.group}>
                <div className={modelCss.groupTitle}>DeepSeek</div>
                {(config?.models ?? []).map(m => (
                  <button key={m.id} type="button" role="menuitemradio" aria-checked={m.id === model}
                    className={cx(modelCss.option, m.id === model && modelCss.selected)}
                    onClick={() => { onChange(m.id, effort); setOpen(false) }}>
                    <span className={modelCss.optionCopy}><span className={modelCss.modelName}>{m.name}</span></span>
                    <span className={modelCss.check}>{m.id === model ? <IconCheckOutline16 /> : null}</span>
                  </button>
                ))}
              </section>
            </div>
          )}
          {pane === 'effort' && efforts.map(e => (
            <button key={e} type="button" role="menuitemradio" aria-checked={e === effort}
              className={cx(modelCss.option, e === effort && modelCss.selected)} onClick={() => { onChange(model, e); setOpen(false) }}>
              <span className={modelCss.optionCopy}><span className={modelCss.modelName}>{EFFORT_LABEL[e] ?? e}</span></span>
              <span className={modelCss.check}>{e === effort ? <IconCheckOutline16 /> : null}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const RADIUS = 5.5
const CIRC = 2 * Math.PI * RADIUS

/** DSH ContextMeter: ring with the share of the context window the last request used. */
export function ContextMeter({ used, window: win, breakdown }: { used: number; window: number; breakdown?: { system: number; tools: number; messages: number } }) {
  const root = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  const refs = useRef([root]).current
  useDismiss(open, () => setOpen(false), refs)
  const percent = Math.min(100, Math.round((100 * used) / Math.max(1, win)))
  const total = breakdown ? breakdown.system + breakdown.tools + breakdown.messages : 0
  const rowsDef = [
    { key: 'system' as const, label: 'System prompt', color: meterCss.colorSystem },
    { key: 'tools' as const, label: 'Tool definitions', color: meterCss.colorTools },
    { key: 'messages' as const, label: 'Messages', color: meterCss.colorMessages },
  ]
  return (
    <span ref={root} className={meterCss.root}>
      <button type="button" className={meterCss.trigger} aria-label={`${percent}% of context used`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden>
          <circle className={meterCss.track} cx="7" cy="7" r={RADIUS} />
          <circle className={meterCss.fill} cx="7" cy="7" r={RADIUS} strokeDasharray={`${(CIRC * percent) / 100} ${CIRC}`} transform="rotate(-90 7 7)" />
        </svg>
      </button>
      {open && (
        <div className={meterCss.panel} role="dialog" aria-label="Context used">
          <div className={meterCss.header}>
            <span className={meterCss.headline}>Context</span>
            <span className={meterCss.percent}>{percent}%</span>
            <span className={meterCss.headline}>used</span>
            <span className={meterCss.figures}>{`~${tok(used)} / ${tok(win)}`}</span>
          </div>
          <div className={meterCss.bar}>
            {(breakdown && total ? rowsDef.map(r => ({ key: r.key, color: r.color, width: (percent * breakdown[r.key]) / total }))
              : [{ key: 'total', color: '', width: percent }]).filter(p => p.width > 0).map(p => (
              <div key={p.key} className={cx(meterCss.segment, p.color)} style={{ width: `${p.width}%` }} />
            ))}
          </div>
          {breakdown && (
            <dl className={meterCss.rows}>
              {rowsDef.map(r => (
                <div key={r.key} className={meterCss.row}>
                  <dt><span className={cx(meterCss.swatch, r.color)} aria-hidden />{r.label}</dt>
                  <dd>{`~${tok(breakdown[r.key])}`}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
    </span>
  )
}

export interface SessionStats { turns: number; steps: number; input: number; cached: number; output: number; llmMs: number; toolMs: number; ttftMs: number[] }

/** DSH formatTokens: 999, 17.3K, 115K, 1.2M. */
function formatTokens(value: number): string {
  const scaled = (v: number) => v >= 100 ? String(Math.round(v)) : String(Math.round(v * 10) / 10)
  if (value < 1_000) return String(value)
  if (value < 1_000_000) return `${scaled(value / 1_000)}K`
  return `${scaled(value / 1_000_000)}M`
}

const exactTokens = (n: number) => `${n.toLocaleString('en-US')} tok`

/** DSH compact duration: 45.2s under a minute, 2m42s from there on. */
function compactDuration(ms: number): string {
  const s = ms / 1_000
  if (s < 60) return `${Math.round(s * 10) / 10}s`
  const whole = Math.round(s)
  return `${Math.floor(whole / 60)}m${whole % 60}s`
}

const formatTps = (tps: number) => tps >= 10 ? String(Math.round(tps)) : String(Math.round(Math.max(0, tps) * 10) / 10)

/** Cache-hit share that never rounds a partial hit up to 100 (DSH formatCacheHitPercent); null without input. */
export function cacheHitPercent(cached: number, input: number): string | null {
  if (input <= 0) return null
  if (cached >= input) return '100'
  const pct = (100 * cached) / input
  if (Math.round(pct) < 100) return String(Math.round(pct))
  // Floor at the first decimal place that still separates the share from 100.
  for (let places = 1; places < 8; places++) {
    const f = 10 ** places
    const v = Math.floor(pct * f) / f
    if (v < 100 - 1 / f || places === 7) return v.toFixed(places)
  }
  return '99.9'
}

/** DSH StatsPills: "N turns M steps · tok/s" and "X tok · Cache hit Y%", each opening a stat dialog. */
export function StatsPills({ stats }: { stats: SessionStats }) {
  const a = useRef<HTMLButtonElement>(null)
  const b = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState<'' | 'time' | 'usage'>('')
  const counts = `${stats.turns} turns ${stats.steps} steps`
  const tps = stats.llmMs > 0 && stats.output > 0 ? `${formatTps(stats.output / (stats.llmMs / 1000))} tok/s` : null
  const total = stats.input + stats.output
  const hit = cacheHitPercent(stats.cached, stats.input)
  const totalText = `${formatTokens(total)} tok`
  const hitText = hit !== null ? `Cache hit ${hit}%` : null
  const ttft = stats.ttftMs.length ? stats.ttftMs.reduce((x, y) => x + y, 0) / stats.ttftMs.length : 0
  const hasTokens = total > 0
  if (stats.steps === 0 && !hasTokens) return null
  const timeLabel = <span className={pillCss.label}>{counts}{tps !== null && <><span className={pillCss.sep} aria-hidden>·</span>{tps}</>}</span>
  const timed = stats.llmMs > 0 || stats.toolMs > 0 || ttft > 0
  return (
    <div className={pillCss.root} data-composer-stats="">
      {stats.steps > 0 && (timed
        ? (
          <span className={pillCss.anchor}>
            <button ref={a} type="button" className={pillCss.pill} aria-haspopup="dialog" aria-expanded={open === 'time'}
              aria-label={tps === null ? counts : `${counts} · ${tps}`} onClick={() => setOpen(open === 'time' ? '' : 'time')}>
              <IconGaugeOutline16 />{timeLabel}
            </button>
          </span>
        )
        : <span className={pillCss.anchor}><span className={pillCss.pill}><IconGaugeOutline16 />{timeLabel}</span></span>)}
      {hasTokens && (
        <span className={pillCss.anchor}>
          <button ref={b} type="button" className={pillCss.pill} aria-haspopup="dialog" aria-expanded={open === 'usage'}
            aria-label={hitText === null ? totalText : `${totalText} · ${hitText}`} onClick={() => setOpen(open === 'usage' ? '' : 'usage')}>
            <IconDatabaseOutline16 />
            <span className={pillCss.label}>{totalText}{hitText !== null && <><span className={pillCss.sep} aria-hidden>·</span>{hitText}</>}</span>
          </button>
        </span>
      )}
      <StatDialog open={open === 'time'} onClose={() => setOpen('')} anchor={a} title="Session statistics" icon={<IconGaugeOutline16 />}>
        {stats.llmMs > 0 && <><dt>LLM time</dt><dd>{compactDuration(stats.llmMs)}</dd></>}
        {stats.toolMs > 0 && <><dt>Tool time</dt><dd>{compactDuration(stats.toolMs)}</dd></>}
        {ttft > 0 && <><dt>Avg time to first token (TTFT)</dt><dd>{compactDuration(ttft)}</dd></>}
        {tps !== null && <><dt>Tokens per second (TPS)</dt><dd>{tps}</dd></>}
      </StatDialog>
      <StatDialog open={open === 'usage'} onClose={() => setOpen('')} anchor={b} title="Token usage" icon={<IconDatabaseOutline16 />}
        value={exactTokens(total)}>
        {hit !== null && <><dt>Cache hit</dt><dd>{`${hit}%`}</dd></>}
        <dt>Uncached input</dt><dd>{exactTokens(stats.input - stats.cached)}</dd>
        <dt>Cached input</dt><dd>{exactTokens(stats.cached)}</dd>
        <dt>Output</dt><dd>{exactTokens(stats.output)}</dd>
      </StatDialog>
    </div>
  )
}

/** DSH Toast: transient banner centred over the composer card; holds 3s, fades 1s, then reports done. */
function Toast({ text, anchor, onDone }: { text: string; anchor: HTMLElement | null; onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 4000)
    return () => clearTimeout(timer)
  }, [onDone])
  const [left, setLeft] = useState<number | null>(null)
  useLayoutEffect(() => {
    if (anchor == null) return
    const measure = () => { const r = anchor.getBoundingClientRect(); setLeft(r.left + r.width / 2) }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [anchor])
  return createPortal(
    <div className={toastCss.toast} role="alert" style={{ ...(left === null ? {} : { left }), '--dsh-toast-hold': '3000ms' } as CSSProperties}>
      <span className={toastCss.icon} aria-hidden><IconWarningOutline16 /></span>
      <span className={toastCss.text}>{text}</span>
    </div>,
    document.body,
  )
}

/** One submission: the draft text, its pending attachments, and (while a turn runs) queue or steer. */
export interface SendRequest { text: string; attachments: PendingAttachment[]; mode?: 'queue' | 'steer' }

const STOP_ICON = (
  <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden><rect x="3" y="3" width="10" height="10" rx="3" fill="currentColor" /></svg>
)
const SEND_ICON = (
  <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
    <path d="M8.3125 0.980183C8.66767 1.0531 8.97902 1.20418 9.2627 1.43233C9.48724 1.61297 9.73029 1.85793 9.97949 2.10714L14.707 6.83468L13.293 8.24874L9 3.95577V15.0417H7V3.95577L2.70703 8.24874L1.29297 6.83468L6.02051 2.10714C6.26971 1.85793 6.51277 1.61297 6.7373 1.43233C6.97662 1.23986 7.28445 1.04402 7.6875 0.980183C7.8973 0.947006 8.1031 0.95516 8.3125 0.980183Z" fill="currentColor" />
  </svg>
)

/**
 * The composer card. `hero` = empty-state variant; `placeholder` overrides the state-derived one.
 * While `running`, Enter (the Send button too) queues the message and Cmd/Ctrl+Enter steers it into the
 * running turn (DSH's default busy-Enter behaviour); with an empty draft Cmd/Ctrl+Enter steers every
 * queued message. Without `steering` (headless engine) a busy submission always queues.
 */
export function InputBar({
  hero, placeholder, onSend, onStop, running, steering = true, disabled, modes, trailing, stats, notice,
  commands = [], planActive, goalActive, queued = 0, onSteerQueue, error, onErrorShown,
}: {
  hero?: boolean; placeholder?: string; onSend: (req: SendRequest) => Promise<void> | void; onStop?: () => void
  running?: boolean; steering?: boolean; disabled?: boolean
  modes?: ReactNode; trailing?: ReactNode; stats?: ReactNode; notice?: ReactNode
  commands?: CommandDef[]; planActive?: boolean; goalActive?: boolean
  /** Messages waiting for the next turn (enables the empty-draft steer gesture). */
  queued?: number; onSteerQueue?: () => void
  /** An owner-raised failure shown as the composer toast. */
  error?: string | null; onErrorShown?: () => void
}) {
  const { prefs } = useStore()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<PendingAttachment[]>([])
  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState<{ seq: number; text: string } | null>(null)
  const [launcher, setLauncher] = useState(false)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [highlight, setHighlight] = useState(0)
  const area = useRef<HTMLTextAreaElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const toastSeq = useRef(0)
  const showToast = useCallback((t: string) => { toastSeq.current += 1; setToast({ seq: toastSeq.current, text: t }) }, [])
  const dismissToast = useCallback(() => setToast(null), [])

  useEffect(() => {
    if (!error) return
    showToast(error)
    onErrorShown?.()
  }, [error, onErrorShown, showToast])
  useEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [text])

  // The `/` trigger: a leading slash token, or the Commands button (launcher).
  const slash = /^\/(\S*)$/.exec(text)
  const query = launcher ? '' : slash?.[1]
  const menuItems = query !== undefined ? rankByName(commands, query) : []
  const menuOpen = !disabled && menuItems.length > 0 && (launcher || dismissed !== text)
  useEffect(() => setHighlight(0), [query])
  const closeMenu = useCallback(() => { setLauncher(false); setDismissed(text) }, [text])

  const focusAt = (caret: number) => requestAnimationFrame(() => {
    area.current?.focus({ preventScroll: true })
    area.current?.setSelectionRange(caret, caret)
  })
  const pick = (index: number) => {
    const c = menuItems[index]
    if (!c) return
    const token = `/${c.name} `
    const next = slash ? token : `${token}${text.trimStart()}`
    setText(next)
    setLauncher(false)
    focusAt(token.length)
  }

  // Claim ghost hint while a known command's arguments are still blank.
  const claimed = commands.find(c => text.startsWith(`/${c.name} `) && text.slice(c.name.length + 2).trim() === '')
  const hint = claimed ? (claimed.name === 'goal' && goalActive ? GOAL_ACTIVE_HINT : claimed.hint) : null

  const empty = text.trim() === '' && files.length === 0
  const canSteerQueue = !disabled && !sending && !menuOpen && empty && Boolean(running) && steering && queued > 0 && onSteerQueue !== undefined
  const placeholderText = placeholder ?? (disabled
    ? 'Session unavailable'
    : canSteerQueue
      ? 'Cmd/Ctrl+Enter steers all queued messages'
      : planActive ? 'describe your task to generate plan' : 'Message or run a task, / commands, @ files or sessions')

  const intake = (picked: File[]) => {
    if (picked.length === 0) return
    const rejected = intakeError(files, picked)
    if (rejected) { showToast(rejected); return }
    setFiles(prev => [...prev, ...picked.map(pendingAttachment)])
  }
  const remove = (id: string) => setFiles(prev => {
    const gone = prev.find(a => a.id === id)
    if (gone?.previewUrl) URL.revokeObjectURL(gone.previewUrl)
    return prev.filter(a => a.id !== id)
  })

  const submit = async (gesture: 'enter' | 'accelerated') => {
    if (disabled || sending) return
    if (gesture === 'accelerated' && canSteerQueue) { onSteerQueue?.(); return }
    const t = text.trim()
    if (!t && files.length === 0) return
    const mode = running ? (steering && gesture === 'accelerated' ? 'steer' : 'queue') : undefined
    setSending(true)
    try {
      await onSend({ text: t, attachments: files, mode })
      for (const a of files) if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
      setText('')
      setFiles([])
    } catch (e) {
      showToast(attachmentErrorText((e as Error).message))
    } finally {
      setSending(false)
    }
  }

  const keepFocus = (e: React.MouseEvent) => { e.preventDefault(); area.current?.focus({ preventScroll: true }) }
  const primaryStops = Boolean(running) && empty
  const primaryDisabled = primaryStops ? onStop === undefined : empty || disabled || sending
  const plainMessageDraft = !empty && !text.trimStart().startsWith('/')
  const primaryLabel = primaryStops
    ? 'Stop generating'
    : running && steering && !disabled && plainMessageDraft ? 'Queue message' : 'Send message'

  return (
    <div className={cx(css.root, hero && css.hero)}>
      {toast !== null && <Toast key={toast.seq} text={toast.text} anchor={cardRef.current} onDone={dismissToast} />}
      {notice && <div className={css.notice} role="status">{notice}</div>}
      <div ref={cardRef} className={css.card} data-composer-card="">
        <div className={css.overlayAnchor}>
          {menuOpen && <CommandMenu items={menuItems} highlight={highlight} onPick={pick} onHover={setHighlight} onDismiss={closeMenu} />}
        </div>
        <ComposerAttachments attachments={files} onRemove={remove} />
        <div className={css.scroll} data-input-scroll="">
          <div className={css.grow}>
            <textarea ref={area} className={cx(css.input, disabled && css.inputDisabled)} rows={1} value={text} disabled={disabled}
              readOnly={sending} aria-label={placeholderText}
              style={{ resize: 'none', border: 0, outline: 'none', background: 'transparent', width: '100%', font: 'inherit', color: 'inherit', overflow: 'hidden', display: 'block' }}
              onChange={e => { setText(e.target.value); setLauncher(false) }}
              onPaste={e => {
                const pasted = [...e.clipboardData.files]
                if (pasted.length === 0) return
                e.preventDefault()
                intake(pasted)
              }}
              onKeyDown={e => {
                const composing = e.nativeEvent.isComposing
                if (menuOpen) {
                  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault()
                    const n = menuItems.length
                    setHighlight(h => (h + (e.key === 'ArrowDown' ? 1 : n - 1)) % n)
                    return
                  }
                  if ((e.key === 'Enter' && !composing) || e.key === 'Tab') { e.preventDefault(); pick(highlight); return }
                  if (e.key === 'Escape') { e.preventDefault(); closeMenu(); return }
                }
                if (e.key !== 'Enter' || composing) return
                const mod = e.metaKey || e.ctrlKey
                if (prefs.enter === 'send') {
                  if (mod) { e.preventDefault(); void submit('accelerated') }
                  else if (!e.shiftKey) { e.preventDefault(); void submit('enter') }
                } else if (mod) { e.preventDefault(); void submit('enter') }
              }} />
            {text === '' && files.length === 0 && (
              <div aria-hidden className={css.placeholder} data-composer-placeholder="">{placeholderText}</div>
            )}
            {hint !== null && (
              <div aria-hidden className={css.placeholder} style={{ whiteSpace: 'pre' }}>
                <span style={{ visibility: 'hidden' }}>{text}</span>{hint}
              </div>
            )}
          </div>
        </div>
        <div className={css.row}>
          <div className={css.tools}>
            <button type="button" className={css.add} aria-label="Commands" aria-haspopup="listbox" aria-expanded={menuOpen}
              disabled={disabled || commands.length === 0} onMouseDown={keepFocus}
              onClick={() => { if (menuOpen) closeMenu(); else { setDismissed(null); setLauncher(true) } }}>
              <IconPlusOutline16 size={14} />
            </button>
            <button type="button" className={css.add} aria-label="Add attachment" disabled={disabled || sending}
              onMouseDown={keepFocus} onClick={() => fileInput.current?.click()}>
              <IconPaperclipOutline16 size={14} />
            </button>
            <input ref={fileInput} type="file" multiple hidden onChange={e => {
              const picked = e.target.files === null ? [] : [...e.target.files]
              e.target.value = ''
              intake(picked)
            }} />
            <div className={css.modes}>{modes}</div>
          </div>
          <div className={css.trailing}>
            {trailing}
            <button type="button" className={css.primary} aria-label={primaryLabel} title={primaryLabel} disabled={primaryDisabled}
              onMouseDown={keepFocus} onClick={() => { if (primaryStops) onStop?.(); else void submit('enter') }}>
              {primaryStops ? STOP_ICON : SEND_ICON}
            </button>
          </div>
        </div>
      </div>
      {stats}
    </div>
  )
}
