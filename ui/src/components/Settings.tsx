/** DSH Settings modal: General, Models, Plugins, Agent presets — backed by .env (write-only keys) and local prefs. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  IconAgentPresetOutline16, IconBrowseOutline16, IconChevronDownOutline14, IconChevronUpOutline14, IconCloseOutline16, IconCordisPluginOutline14,
  IconDarkOutline16, IconDatabaseOutline16, IconFollowsystemOutline16, IconLightOutline16, IconPlusOutline16, IconSettingsOutline16,
} from '../dsh/icons.tsx'
import root from '../dsh/css/SettingsRoot.module.css'
import row from '../dsh/css/PermissionRow.module.css'
import look from '../dsh/css/AppearanceRow.module.css'
import font from '../dsh/css/FontSizeRow.module.css'
import models from '../dsh/css/ModelsSection.module.css'
import plugins from '../dsh/css/PluginsSettingsSection.module.css'
import pcard from '../dsh/css/PluginCard.module.css'
import presets from '../dsh/css/AgentPresetSection.module.css'
import tag from '../dsh/css/Tag.module.css'
import { get, post, type Settings as SettingsData } from '../lib/api.ts'
import { cx } from '../lib/format.ts'
import { modeLabel, useStore } from '../lib/store.tsx'
import { ACCESS } from './Composer.tsx'
import { Button, Menu, MenuItem } from './primitives.tsx'

const SECTIONS = [
  { id: 'general', label: 'General', icon: IconSettingsOutline16 },
  { id: 'models', label: 'Models', icon: IconDatabaseOutline16 },
  { id: 'plugins', label: 'Plugins', icon: IconCordisPluginOutline14 },
  { id: 'presets', label: 'Agent presets', icon: IconAgentPresetOutline16 },
] as const

export function SettingsModal() {
  const s = useStore()
  const [section, setSection] = useState(s.settings.section)
  useEffect(() => { setSection(s.settings.section) }, [s.settings.section, s.settings.open])
  useEffect(() => {
    if (!s.settings.open) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') s.closeSettings() }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [s.settings.open, s])
  if (!s.settings.open) return null
  return (
    <div className={root.overlay} role="presentation">
      <div className={root.mask} onClick={s.closeSettings} />
      <div className={root.panel} role="dialog" aria-label="Settings">
        <nav className={root.nav}>
          <div className={root.navTitle}><div>Settings</div></div>
          <div className={root.navList}>
            {SECTIONS.filter(x => s.config?.play || x.id === 'presets' || x.id === 'general').map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" className={cx(root.navCell, section === id && root.active)} onClick={() => setSection(id)}>
                <Icon className={root.navIcon} /><span className={root.navLabel}>{label}</span>
              </button>
            ))}
          </div>
        </nav>
        <div className={root.content}>
          <div className={root.header}>
            <div className={root.actions} />
            <button type="button" className={root.close} onClick={s.closeSettings}><IconCloseOutline16 /><span className={root.hiddenLabel}>Close</span></button>
          </div>
          <div className={root.options}>
            {section === 'general' && <General />}
            {section === 'models' && <Models />}
            {section === 'plugins' && <Plugins />}
            {section === 'presets' && <Presets />}
          </div>
        </div>
      </div>
    </div>
  )
}

function SelectRow<T extends string>({ title, desc, value, options, onChange }: {
  title: string; desc?: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  const anchor = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  return (
    <div className={row.row}>
      <div className={row.rowText}>
        <div className={row.title}>{title}</div>
        {desc && <div className={row.desc}>{desc}</div>}
      </div>
      <button ref={anchor} type="button" className={row.selector} aria-expanded={open} onClick={() => setOpen(!open)}>
        {options.find(o => o.value === value)?.label ?? value}<IconChevronDownOutline14 className={row.chevron} />
      </button>
      <Menu open={open} onClose={() => setOpen(false)} anchor={anchor} align="end">
        {options.map(o => <MenuItem key={o.value} selected={o.value === value} onSelect={() => { onChange(o.value); setOpen(false) }}>{o.label}</MenuItem>)}
      </Menu>
    </div>
  )
}

function General() {
  const { prefs, setPrefs } = useStore()
  return (
    <div>
      <SelectRow title="Permission" desc="Choose the default access mode for new sessions" value={prefs.approval}
        options={[{ value: 'auto', label: ACCESS.auto.label }, { value: 'ask', label: ACCESS.ask.label }]} onChange={v => setPrefs({ approval: v })} />
      <div className={look.group}>
        <div className={look.title}>Appearance</div>
        <div className={look.cubeRow}>
          {([['light', 'Light', IconLightOutline16], ['dark', 'Dark', IconDarkOutline16], ['system', 'System', IconFollowsystemOutline16]] as const).map(([v, label, Icon]) => (
            <button key={v} type="button" className={cx(look.themeCube, prefs.theme === v && look.selected)} onClick={() => setPrefs({ theme: v })}><Icon />{label}</button>
          ))}
        </div>
      </div>
      <div className={font.row}>
        <div className={font.rowText}><div className={font.title}>Font size</div><div className={font.desc}>Only affects conversation content</div></div>
        <div className={font.control}>
          <div className={font.stepper}>
            <span className={font.value}>{prefs.fontSize}</span>
            <span className={font.arrows}>
              <button type="button" className={font.arrow} aria-label="Increase font size" onClick={() => setPrefs({ fontSize: Math.min(17, prefs.fontSize + 1) })}><IconChevronUpOutline14 size={10} /></button>
              <button type="button" className={font.arrow} aria-label="Decrease font size" onClick={() => setPrefs({ fontSize: Math.max(12, prefs.fontSize - 1) })}><IconChevronDownOutline14 size={10} /></button>
            </span>
          </div>
          <span className={font.unit}>px</span>
        </div>
      </div>
      <SelectRow title="Conversation display" desc="Controls process content in completed turns" value={prefs.display}
        options={[{ value: 'compact', label: 'Compact' }, { value: 'full', label: 'Full' }]} onChange={v => setPrefs({ display: v })} />
      <SelectRow title="Enter key" desc="Enter sends and Shift+Enter adds a line, or Cmd/Ctrl+Enter sends" value={prefs.enter}
        options={[{ value: 'send', label: 'Enter sends' }, { value: 'newline', label: 'Cmd/Ctrl+Enter sends' }]} onChange={v => setPrefs({ enter: v })} />
    </div>
  )
}

function useSettings() {
  const [data, setData] = useState<SettingsData | null>(null)
  const reload = () => get<SettingsData>('settings').then(setData).catch(() => {})
  useEffect(() => { reload() }, [])
  return { data, reload, setData }
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className={models.field}>
      <span className={models.fieldLabel}>{label}</span>
      {children}
      {hint && <span style={{ fontSize: 12, color: 'var(--dsw-alias-label-tertiary)' }}>{hint}</span>}
    </label>
  )
}

function Models() {
  const { data, setData } = useSettings()
  const { refreshSessions } = useStore()
  const [editing, setEditing] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<ReactNode>(null)
  const [found, setFound] = useState<string[]>([])
  if (!data) return <div className={models.section}>Loading…</div>
  const v = data.values
  const save = async (changes: Record<string, string | null>) => {
    try { setData(await post<SettingsData>('settings', changes)); setMsg(null); setEditing(null); setForm({}); refreshSessions() }
    catch (e) { setMsg(<span className={models.error}>{(e as Error).message}</span>) }
  }
  const providers = [
    { id: 'deepseek', name: 'DeepSeek', key: 'DEEPSEEK_API_KEY', configured: data.secrets.DEEPSEEK_API_KEY.configured, source: data.secrets.DEEPSEEK_API_KEY.source },
    { id: 'langsmith', name: 'LangSmith (tracing)', key: 'LANGSMITH_API_KEY', configured: data.secrets.LANGSMITH_API_KEY.configured, source: data.secrets.LANGSMITH_API_KEY.source },
    { id: 'langfuse', name: 'Langfuse (tracing)', key: 'LANGFUSE_SECRET_KEY', configured: data.secrets.LANGFUSE_SECRET_KEY.configured && data.secrets.LANGFUSE_PUBLIC_KEY.configured, source: data.secrets.LANGFUSE_SECRET_KEY.source },
  ]
  return (
    <div className={models.section}>
      <h2 className={models.title}>Models</h2>
      <p className={models.intro}>Enter your API keys to use models from the following providers. Keys are written to <code>{data.env_file}</code> (gitignored, mode 600) and never shown again.</p>
      <ul className={models.rows}>
        {providers.map(p => (
          <li key={p.id} className={models.rowCard}>
            <div className={models.rowHead}>
              <span className={models.rowIdentity}>
                <span className={models.rowName}>{p.name}</span>
                <span className={cx(models.credentialDot, p.configured ? models.credentialDotConfigured : models.credentialDotMissing)} role="img"
                  aria-label={p.configured ? 'API key configured' : 'API key missing'} title={p.configured ? `API key configured (from ${p.source})` : 'API key missing'} />
              </span>
              <span className={models.rowActions}>
                <button type="button" className={models.secondaryButton} onClick={() => { setEditing(editing === p.id ? null : p.id); setForm({}); setMsg(null) }}>
                  {editing === p.id ? 'Close' : 'Edit'}
                </button>
              </span>
            </div>
            {editing === 'deepseek' && p.id === 'deepseek' && (
              <div className={models.editor}>
                <Field label="API key" hint={p.configured ? `Configured${p.source === 'env' ? ' from the launch environment (it wins over .env at the next start)' : ''}. Paste a new key to replace it.` : 'Paste your DeepSeek API key.'}>
                  <input className={models.input} type="password" autoComplete="off" placeholder={p.configured ? '••••••••' : 'sk-...'} value={form.DEEPSEEK_API_KEY ?? ''}
                    onChange={e => setForm({ ...form, DEEPSEEK_API_KEY: e.target.value })} />
                </Field>
                <Field label="Base URL" hint={data.gateway.running ? 'The gateway is on, so new sessions use it until it stops.' : 'Leave empty for https://api.deepseek.com'}>
                  <input className={models.input} placeholder={v.DEEPSEEK_BASE_URL.default} value={form.DEEPSEEK_BASE_URL ?? v.DEEPSEEK_BASE_URL.value}
                    onChange={e => setForm({ ...form, DEEPSEEK_BASE_URL: e.target.value })} disabled={data.gateway.running} />
                </Field>
                <Field label="Default model">
                  <select className={models.input} value={form.LAB_MODEL ?? v.LAB_MODEL.value} onChange={e => setForm({ ...form, LAB_MODEL: e.target.value })}>
                    <option value="">{`default (${v.LAB_MODEL.default})`}</option>
                    {[...new Set([...data.models, ...found, v.LAB_MODEL.value].filter(Boolean))].map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </Field>
                <Field label="Default reasoning effort">
                  <select className={models.input} value={form.LAB_THINKING === 'disabled' || (form.LAB_THINKING === undefined && v.LAB_THINKING.value === 'disabled') ? 'off' : (form.LAB_REASONING_EFFORT ?? v.LAB_REASONING_EFFORT.value)}
                    onChange={e => setForm({ ...form, LAB_THINKING: e.target.value === 'off' ? 'disabled' : 'enabled', LAB_REASONING_EFFORT: e.target.value === 'off' ? '' : e.target.value })}>
                    <option value="">{`default (${v.LAB_REASONING_EFFORT.default})`}</option>
                    {['off', 'low', 'high', 'max'].map(x => <option key={x} value={x}>{x}</option>)}
                  </select>
                </Field>
                <div className={models.editorActions}>
                  <Button size="sm" onClick={async () => {
                    setMsg('Checking…')
                    const r: { ok: boolean; models?: string[]; error?: string } = await post<{ ok: boolean; models?: string[]; error?: string }>('settings/models').catch(e => ({ ok: false, error: (e as Error).message }))
                    if (r.ok) { setFound(r.models ?? []); setMsg(<span>Connected · {r.models?.join(', ')}</span>) } else setMsg(<span className={models.error}>{r.error}</span>)
                  }}>Check connection · fetch models</Button>
                  {p.configured && p.source === '.env' && <Button size="sm" onClick={() => { if (confirm('Remove DEEPSEEK_API_KEY from .env?')) save({ DEEPSEEK_API_KEY: null }) }}>Remove key</Button>}
                  <Button size="sm" variant="primary" onClick={() => {
                    const ch: Record<string, string | null> = {}
                    for (const [k, val] of Object.entries(form)) if (k === 'DEEPSEEK_API_KEY' ? val.trim() : val !== (v[k]?.value ?? '')) ch[k] = val
                    if (Object.keys(ch).length) save(ch); else setEditing(null)
                  }}>Save</Button>
                </div>
                {msg && <div style={{ fontSize: 12, marginTop: 6 }}>{msg}</div>}
              </div>
            )}
            {editing === p.id && p.id !== 'deepseek' && (
              <div className={models.editor}>
                {p.id === 'langsmith' ? (
                  <>
                    <Field label="LANGSMITH_API_KEY"><input className={models.input} type="password" autoComplete="off" value={form.LANGSMITH_API_KEY ?? ''} onChange={e => setForm({ ...form, LANGSMITH_API_KEY: e.target.value })} /></Field>
                    <Field label="LANGSMITH_TRACING" hint="true sends lab-engine runs to LangSmith"><input className={models.input} value={form.LANGSMITH_TRACING ?? v.LANGSMITH_TRACING.value} onChange={e => setForm({ ...form, LANGSMITH_TRACING: e.target.value })} /></Field>
                  </>
                ) : (
                  <>
                    <Field label="LANGFUSE_PUBLIC_KEY"><input className={models.input} type="password" autoComplete="off" value={form.LANGFUSE_PUBLIC_KEY ?? ''} onChange={e => setForm({ ...form, LANGFUSE_PUBLIC_KEY: e.target.value })} /></Field>
                    <Field label="LANGFUSE_SECRET_KEY"><input className={models.input} type="password" autoComplete="off" value={form.LANGFUSE_SECRET_KEY ?? ''} onChange={e => setForm({ ...form, LANGFUSE_SECRET_KEY: e.target.value })} /></Field>
                    <Field label="LANGFUSE_HOST"><input className={models.input} placeholder="http://localhost:3000" value={form.LANGFUSE_HOST ?? v.LANGFUSE_HOST.value} onChange={e => setForm({ ...form, LANGFUSE_HOST: e.target.value })} /></Field>
                  </>
                )}
                <div className={models.editorActions}>
                  <Button size="sm" variant="primary" onClick={() => {
                    const ch: Record<string, string | null> = {}
                    for (const [k, val] of Object.entries(form)) if (val.trim() || k in v) ch[k] = val
                    save(ch)
                  }}>Save</Button>
                </div>
                {msg}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className={models.addBlock}>
        <div className={models.addActions}>
          <button type="button" className={models.addButton} onClick={() => { setEditing('advanced'); setForm({}) }}><IconPlusOutline16 />Other provider (lab engine)</button>
        </div>
      </div>
      {editing === 'advanced' && (
        <div className={models.editor}>
          <Field label="LAB_MODEL_SPEC" hint="Any init_chat_model spec, e.g. openai:gpt-5.4. Lab engine only; put that provider's key in the launch environment.">
            <input className={models.input} value={form.LAB_MODEL_SPEC ?? v.LAB_MODEL_SPEC.value} onChange={e => setForm({ ...form, LAB_MODEL_SPEC: e.target.value })} />
          </Field>
          <Field label="LAB_JUDGE_MODEL_SPEC" hint="Model for Output Quality judging; empty uses the experiment model.">
            <input className={models.input} value={form.LAB_JUDGE_MODEL_SPEC ?? v.LAB_JUDGE_MODEL_SPEC.value} onChange={e => setForm({ ...form, LAB_JUDGE_MODEL_SPEC: e.target.value })} />
          </Field>
          <div className={models.editorActions}><Button size="sm" variant="primary" onClick={() => save(form)}>Save</Button></div>
          {msg}
        </div>
      )}
    </div>
  )
}

function PluginCard({ name, description, children, open, onToggle }: { name: string; description: string; children: ReactNode; open: boolean; onToggle: () => void }) {
  return (
    <li className={cx(pcard.card, open && pcard.cardOpen)}>
      <button type="button" className={pcard.header} aria-expanded={open} onClick={onToggle}>
        <span className={pcard.headText}><span className={pcard.name}>{name}</span><span className={pcard.description}>{description}</span></span>
        <IconChevronDownOutline14 className={cx(pcard.chevron, open && pcard.chevronOpen)} />
      </button>
      {open && <div className={pcard.body}>{children}</div>}
    </li>
  )
}

function Plugins() {
  const { data, setData, reload } = useSettings()
  const { config } = useStore()
  const [open, setOpen] = useState('gateway')
  if (!data) return <div className={plugins.section}>Loading…</div>
  const g = data.gateway
  const gw = async (path: string, body?: unknown) => { try { await post(path, body); reload() } catch (e) { alert((e as Error).message) } }
  const t = (k: string) => setOpen(open === k ? '' : k)
  return (
    <div className={plugins.section}>
      <h2 className={plugins.heading}>Plugins</h2>
      <p className={plugins.intro}>Local services around the harnesses: the recording gateway, the DeepSeek Harness runtime, and batch policies.</p>
      <div className={plugins.panel} role="tabpanel">
        <ul className={plugins.cards}>
          <PluginCard name="Gateway" description={g.running ? `On · ${g.mode} · ${g.url}` : 'Records every model request of both engines; mock answers without an API key.'} open={open === 'gateway'} onToggle={() => t('gateway')}>
            <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>
              While on, sessions and runs started here go through 127.0.0.1:8790, so each run shows its exact request bodies (system prompt, tool schemas) and provider usage. Mock answers with canned replies. This lasts until <code>lab ui</code> stops; <code>.env</code> is unchanged.
            </p>
            {g.running && g.mode === 'proxy' && <p style={{ fontSize: 12 }}>Upstream: {g.upstream}</p>}
            <div className={pcard.footer}>
              {g.running
                ? <Button size="sm" onClick={() => gw('gateway/stop')}>Stop</Button>
                : <><Button size="sm" onClick={() => gw('gateway/start', { mode: 'mock' })}>Start mock</Button><Button size="sm" variant="primary" onClick={() => gw('gateway/start', { mode: 'proxy' })}>Start proxy (record)</Button></>}
            </div>
          </PluginCard>
          <PluginCard name="DeepSeek Harness" description={config?.dsh_installed ? `Installed · @deepseek-ai/dsh@${config.dsh_version} · headless` : 'Not installed'} open={open === 'dsh'} onToggle={() => t('dsh')}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>
              Runs as <code>dsh --profile headless</code> with patches from <code>dsh/patches/</code>, an isolated <code>DSH_HOME=.dsh-home</code>, and OTel upload off (<code>DSH_TELEMETRY_MODE=DISABLED</code>). The key and model settings are passed as environment variables.
              {!config?.dsh_installed && <> Install with <code>uv run lab dsh-install</code>.</>}
            </p>
          </PluginCard>
          <PluginCard name="Batch approvals" description="How hitl runs answer approvals when no one is watching (LAB_HITL)." open={open === 'hitl'} onToggle={() => t('hitl')}>
            <div className={pcard.footer}>
              {(['approve', 'reject'] as const).map(x => (
                <Button key={x} size="sm" variant={(data.values.LAB_HITL.value || 'approve') === x ? 'primary' : 'outline'}
                  onClick={async () => setData(await post<SettingsData>('settings', { LAB_HITL: x }))}>{x}</Button>
              ))}
            </div>
          </PluginCard>
        </ul>
      </div>
    </div>
  )
}

function Presets() {
  const s = useStore()
  const groups = [
    { head: 'DeepSeek Harness · headless', items: s.harnesses.filter(h => h.engine === 'dsh') },
    { head: 'LangChain · deepagents', items: s.harnesses.filter(h => h.engine === 'lab') },
  ]
  return (
    <div className={presets.section}>
      <h2 className={presets.title}>Agent presets</h2>
      <p className={presets.intro}>A preset (harness) is what one session's agent runs — its tools, prompt, and middleware. Click a card to use it for the next new session; the view button opens its full anatomy.</p>
      {groups.map(g => (
        <section key={g.head} className={presets.group}>
          <h3 className={presets.groupHead}>{g.head}</h3>
          <ul className={presets.cards}>
            {g.items.map(h => {
              const inUse = s.draft.engine === h.engine && s.draft.harness === h.name
              return (
                <li key={h.engine + h.name} className={cx(presets.card, inUse && presets.cardActive)}>
                  <button type="button" className={presets.cardMain} disabled={h.engine === 'dsh' && !s.config?.dsh_installed}
                    onClick={() => s.setDraft({ engine: h.engine, harness: h.name })}>
                    <span className={presets.cardHead}>
                      <span className={presets.cardName}>{modeLabel(h.engine, h.name)}</span>
                      <span className={tag.tag} data-tone="outline">Built-in</span>
                      {inUse && <span className={cx(tag.tag, presets.inUse)} data-tone="solid">Next session</span>}
                    </span>
                    <span className={presets.cardDesc}>{h.description}</span>
                    <code className={presets.cardId}>{h.name}</code>
                  </button>
                  <div className={presets.cardFoot}>
                    <button type="button" className={presets.iconButton} aria-label={`View: ${h.name}`} title="View anatomy"
                      onClick={() => { s.closeSettings(); s.go({ kind: 'harness', engine: h.engine, name: h.name }) }}><IconBrowseOutline16 /></button>
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
