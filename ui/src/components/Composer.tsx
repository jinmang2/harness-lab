/** DSH InputBar: text box, access mode, model + effort, context meter, send / stop; StatsPills underneath. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  IconCheckOutline16, IconChevronDownOutline14, IconChevronRightOutline14, IconDataOutline16, IconDatabaseOutline16,
  IconGaugeOutline16, IconSendOutline16, IconStopFill16, IconUserOutline16,
} from '../dsh/icons.tsx'
import css from '../dsh/css/InputBar.module.css'
import modelCss from '../dsh/css/ModelSelect.module.css'
import permCss from '../dsh/css/PermissionSelect.module.css'
import meterCss from '../dsh/css/ContextMeter.module.css'
import pillCss from '../dsh/css/StatsPills.module.css'
import { cx, duration, tok } from '../lib/format.ts'
import { useStore } from '../lib/store.tsx'
import { Menu, MenuItem, StatDialog, useDismiss } from './primitives.tsx'

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
      <button type="button" className={modelCss.trigger} disabled={disabled} aria-expanded={open}
        aria-label={`Select model, current ${modelDisplay(model, config?.models)}`} title={`${modelDisplay(model, config?.models)} · ${EFFORT_LABEL[effort] ?? effort}`}
        onClick={() => { setOpen(!open); setPane('root') }}>
        <IconDataOutline16 className={modelCss.triggerIcon} size={16} />
        <span className={modelCss.triggerLabel}>{modelDisplay(model, config?.models)}</span>
        <span className={modelCss.triggerEffort}>{EFFORT_LABEL[effort] ?? effort}</span>
        <IconChevronDownOutline14 className={cx(modelCss.chevron, open && modelCss.chevronOpen)} />
      </button>
      {open && (
        <div className={modelCss.menu} role="menu">
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

/** DSH StatsPills: "N turns M steps · tok/s" and "X tok · Cache hit Y%", each opening a stat dialog. */
export function StatsPills({ stats }: { stats: SessionStats }) {
  const a = useRef<HTMLButtonElement>(null)
  const b = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState<'' | 'turns' | 'usage'>('')
  const tps = stats.llmMs > 0 ? Math.round(stats.output / (stats.llmMs / 1000)) : 0
  const hit = stats.input ? Math.round((100 * stats.cached) / stats.input) : 0
  const ttft = stats.ttftMs.length ? stats.ttftMs.reduce((x, y) => x + y, 0) / stats.ttftMs.length : 0
  return (
    <div className={pillCss.root} data-composer-stats="">
      <span className={pillCss.anchor}>
        <button ref={a} type="button" className={pillCss.pill} aria-expanded={open === 'turns'} onClick={() => setOpen(open === 'turns' ? '' : 'turns')}>
          <IconGaugeOutline16 />
          <span className={pillCss.label}>{`${stats.turns} turns ${stats.steps} steps`}{tps > 0 && <><span className={pillCss.sep}>·</span>{`${tps} tok/s`}</>}</span>
        </button>
      </span>
      <span className={pillCss.anchor}>
        <button ref={b} type="button" className={pillCss.pill} aria-expanded={open === 'usage'} onClick={() => setOpen(open === 'usage' ? '' : 'usage')}>
          <IconDatabaseOutline16 />
          <span className={pillCss.label}>{`${tok(stats.input + stats.output)} tok`}<span className={pillCss.sep}>·</span>{`Cache hit ${hit}%`}</span>
        </button>
      </span>
      <StatDialog open={open === 'turns'} onClose={() => setOpen('')} anchor={a} title="Session time" icon={<IconGaugeOutline16 />}>
        <dt>Model time</dt><dd>{duration(stats.llmMs)}</dd>
        <dt>Tool time</dt><dd>{duration(stats.toolMs)}</dd>
        {ttft > 0 && <><dt>Avg. time to first token</dt><dd>{`${(ttft / 1000).toFixed(2)}s`}</dd></>}
        {tps > 0 && <><dt>Output speed</dt><dd>{`${tps} tok/s`}</dd></>}
      </StatDialog>
      <StatDialog open={open === 'usage'} onClose={() => setOpen('')} anchor={b} title="Session usage" icon={<IconDatabaseOutline16 />}
        value={`${(stats.input + stats.output).toLocaleString()} tok`}>
        <dt>Cache hit</dt><dd>{`${hit}%`}</dd>
        <dt>Uncached input</dt><dd>{`${(stats.input - stats.cached).toLocaleString()} tok`}</dd>
        <dt>Cached input</dt><dd>{`${stats.cached.toLocaleString()} tok`}</dd>
        <dt>Output</dt><dd>{`${stats.output.toLocaleString()} tok`}</dd>
      </StatDialog>
    </div>
  )
}

/** The composer card. `hero` = empty-state variant. */
export function InputBar({ hero, placeholder, onSend, onStop, busy, disabled, modes, trailing, stats, notice }: {
  hero?: boolean; placeholder: string; onSend: (text: string) => void; onStop?: () => void; busy?: boolean; disabled?: boolean
  modes?: ReactNode; trailing?: ReactNode; stats?: ReactNode; notice?: ReactNode
}) {
  const { prefs } = useStore()
  const [text, setText] = useState('')
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [text])
  const send = () => {
    const t = text.trim()
    if (!t || disabled || busy) return
    onSend(t)
    setText('')
  }
  return (
    <div className={cx(css.root, hero && css.hero)}>
      {notice && <div className={css.notice}>{notice}</div>}
      <div className={css.card}>
        <div className={css.scroll}>
          <div className={css.grow}>
            <textarea ref={area} className={cx(css.input, disabled && css.inputDisabled)} rows={1} value={text} disabled={disabled}
              aria-label={placeholder} placeholder={placeholder}
              style={{ resize: 'none', border: 0, outline: 'none', background: 'transparent', width: '100%', font: 'inherit', color: 'inherit', overflow: 'hidden' }}
              onChange={e => setText(e.target.value)}
              onKeyDown={e => {
                if (e.key !== 'Enter' || e.nativeEvent.isComposing) return
                const mod = e.metaKey || e.ctrlKey
                const sendKey = prefs.enter === 'send' ? !e.shiftKey && !mod : mod
                if (sendKey) { e.preventDefault(); send() }
              }} />
          </div>
        </div>
        <div className={css.row}>
          <div className={css.tools}><div className={css.modes}>{modes}</div></div>
          <div className={css.trailing}>
            {trailing}
            {busy && onStop
              ? <button type="button" className={css.primary} aria-label="Stop" onClick={onStop}><IconStopFill16 /></button>
              : <button type="button" className={css.primary} aria-label="Send message" disabled={!text.trim() || disabled} onClick={send}><IconSendOutline16 /></button>}
          </div>
        </div>
      </div>
      {stats}
    </div>
  )
}
