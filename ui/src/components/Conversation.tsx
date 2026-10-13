/** Center column: DSH ConversationRoot — hero (new session) or session (header, Chat/Trajectory, composer). */
import { useMemo, useRef, useState } from 'react'
import {
  IconAgentPresetOutline16, IconChevronDownOutline14, IconEllipsisOutline16, IconFolderClose16, IconPanelLeftOutline16, IconPlusOutline16,
} from '../dsh/icons.tsx'
import root from '../dsh/css/ConversationRoot.module.css'
import hero from '../dsh/css/HeroShell.module.css'
import seat from '../dsh/css/AgentPresetSeat.module.css'
import presetLabel from '../dsh/css/AgentPresetLabel.module.css'
import expand from '../dsh/css/ExpandButton.module.css'
import { post, type SessionInfo } from '../lib/api.ts'
import { cx } from '../lib/format.ts'
import { useSessionEvents } from '../lib/session.ts'
import { modeLabel, useStore } from '../lib/store.tsx'
import { fold, type ApprovalItem, type QuestionItem } from '../lib/turns.ts'
import { ApprovalPanel, ChatView, CwdContext, TodoPanel, latestTodos } from './Chat.tsx'
import { PlanChip, QuestionComposer, type QuestionReply } from './Questions.tsx'
import { ContextMeter, InputBar, ModelSelect, PermissionSelect, StatsPills, modelDisplay, type SessionStats } from './Composer.tsx'
import { LabMark } from './Sidebar.tsx'
import { Menu, MenuItem, MenuLabel, MenuSeparator } from './primitives.tsx'
import { Trajectory, rowsFromEvents } from './Trajectory.tsx'

function PresetSeat() {
  const s = useStore()
  const anchor = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const dsh = s.harnesses.filter(h => h.engine === 'dsh')
  const lab = s.harnesses.filter(h => h.engine === 'lab')
  const pick = (engine: 'lab' | 'dsh', harness: string) => { s.setDraft({ engine, harness }); setOpen(false) }
  const item = (h: { engine: 'lab' | 'dsh'; name: string; description: string }) => (
    <MenuItem key={h.engine + h.name} selected={s.draft.engine === h.engine && s.draft.harness === h.name}
      disabled={h.engine === 'dsh' && !s.config?.dsh_installed} onSelect={() => pick(h.engine, h.name)}>
      <span className={seat.item}>
        <span className={seat.itemName}>{modeLabel(h.engine, h.name)}</span>
        <span className={seat.itemDesc}>{h.description}</span>
      </span>
    </MenuItem>
  )
  return (
    <span className={seat.menuAnchor}>
      <button ref={anchor} type="button" className={seat.seat} aria-haspopup="menu" aria-expanded={open}
        title="Agent preset (harness) for the session you are about to start" onClick={() => setOpen(!open)}>
        <IconAgentPresetOutline16 className={seat.seatIcon} />
        <span className={seat.seatLabel}>{modeLabel(s.draft.engine, s.draft.harness)}</span>
        <IconChevronDownOutline14 className={seat.chevron} />
      </button>
      <Menu open={open} onClose={() => setOpen(false)} anchor={anchor} minWidth={340}>
        <MenuLabel>DeepSeek Harness · headless</MenuLabel>
        {dsh.map(item)}
        <MenuSeparator />
        <MenuLabel>LangChain · deepagents</MenuLabel>
        {lab.map(item)}
      </Menu>
    </span>
  )
}

function WorkspaceChip() {
  const s = useStore()
  const anchor = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const current = s.workspaces.find(w => w.path === s.draft.workspace)
  return (
    <>
      <button ref={anchor} type="button" className={hero.workspace} aria-label="Choose workspace" aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconFolderClose16 className={hero.folder} />
        <span className={hero.workspaceLabel}>{current?.title ?? 'Scratch'}</span>
        <IconChevronDownOutline14 className={hero.chevron} />
      </button>
      <Menu open={open} onClose={() => setOpen(false)} anchor={anchor} minWidth={260}>
        <MenuItem selected={!s.draft.workspace} onSelect={() => { s.setDraft({ workspace: '' }); setOpen(false) }}>
          <span className={seat.item}><span className={seat.itemName}>Scratch</span><span className={seat.itemDesc}>A fresh folder for this session</span></span>
        </MenuItem>
        {s.workspaces.map(w => (
          <MenuItem key={w.path} selected={s.draft.workspace === w.path} disabled={!w.exists} onSelect={() => { s.setDraft({ workspace: w.path }); setOpen(false) }}>
            <span className={seat.item}><span className={seat.itemName}>{w.title}</span><span className={seat.itemDesc}>{w.path}</span></span>
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem icon={<IconPlusOutline16 />} onSelect={() => { setOpen(false); s.setAddingWorkspace(true) }}>Add workspace…</MenuItem>
      </Menu>
    </>
  )
}

/** `/plan [message]` and `/plan off` (DSH's plan command); null for an ordinary message. */
function planCommand(text: string): { active: boolean; message: string } | null {
  const m = /^\/plan(?:\s+([\s\S]*))?$/.exec(text.trim())
  if (!m) return null
  const arg = (m[1] ?? '').trim()
  return arg === 'off' ? { active: false, message: '' } : { active: true, message: arg }
}

export function NewSession() {
  const s = useStore()
  const [error, setError] = useState('')
  const [approval, setApproval] = useState(s.prefs.approval)
  const model = s.draft.model || s.config?.default_model || ''
  const effort = s.draft.effort || s.config?.default_effort || 'high'
  const start = async (text: string) => {
    setError('')
    try {
      const plan = planCommand(text)
      const info = await post<SessionInfo>('play/start', {
        engine: s.draft.engine, harness: s.draft.harness, model: s.draft.model || undefined, effort: s.draft.effort || undefined,
        approval, workspace: s.draft.workspace || undefined, plan: plan?.active || undefined,
      })
      const message = plan ? plan.message : text
      if (message) await post(`play/${info.id}/send`, { text: message })
      await s.refreshSessions()
      s.go({ kind: 'session', id: info.id })
    } catch (e) { setError((e as Error).message) }
  }
  if (!s.config?.play) {
    return <ReadOnlyHero />
  }
  return (
    <div className={root.root} data-phase="hero">
      <div className={root.body}>
        <div className={root.scrollBody} data-conversation-scroll="">
          <div className={root.composerSeat} data-composer-seat="">
            <div className={cx(root.composerStack, root.composerHero)}>
              <div className={hero.root}>
                <div className={hero.stack}>
                  <div className={hero.headline}>
                    <span className={hero.fishHitbox}><LabMark size={34} /></span>
                    <span className={hero.titleGroup}><span>Same model, different harness</span><span className={hero.previewBadge}>Lab</span></span>
                  </div>
                  <div className={hero.body} />
                </div>
              </div>
              <div className={root.heroWorkspaceRow}>
                <WorkspaceChip />
                <PresetSeat />
              </div>
              <InputBar hero placeholder="Describe what you want to do" onSend={start}
                notice={error || undefined}
                modes={<PermissionSelect value={s.draft.engine === 'dsh' ? 'auto' : approval} onChange={setApproval}
                  disabled={s.draft.engine === 'dsh'} title={s.draft.engine === 'dsh' ? 'DSH headless cannot ask for approval' : undefined} />}
                trailing={<ModelSelect model={model} effort={effort} onChange={(m, e) => s.setDraft({ model: m, effort: e })} />} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ReadOnlyHero() {
  return (
    <div className={root.root} data-phase="hero">
      <div className={root.body}><div className={root.scrollBody}>
        <div className={hero.root}><div className={hero.stack}>
          <div className={hero.headline}>
            <span className={hero.fishHitbox}><LabMark size={34} /></span>
            <span className={hero.titleGroup}><span>Read-only viewer</span><span className={hero.previewBadge}>lab view</span></span>
          </div>
          <div className={hero.body} style={{ textAlign: 'center', color: 'var(--dsw-alias-label-secondary)' }}>
            Runs and Harnesses are on the left. To chat, run batches and change settings, start <code>uv run lab ui</code>.
          </div>
        </div></div>
      </div></div>
    </div>
  )
}

export function SessionView({ id }: { id: string }) {
  const s = useStore()
  const { info, events, error, kick } = useSessionEvents(id)
  const [tab, setTab] = useState<'chat' | 'trajectory'>('chat')
  const [menu, setMenu] = useState(false)
  const more = useRef<HTMLButtonElement>(null)
  const folded = useMemo(() => fold(events), [events])
  const rows = useMemo(() => rowsFromEvents(events), [events])
  const todos = latestTodos(folded)
  const live = info?.status !== 'archived'
  const busy = info?.status === 'running' || info?.status === 'waiting'
  const pendingApproval = info?.status === 'waiting'
    ? [...(folded.turns.at(-1)?.items ?? [])].reverse().find(i => i.kind === 'approval' && !i.decision) as ApprovalItem | undefined
    : undefined
  const ctxWindow = s.config?.models?.find(m => m.id === info?.model)?.context ?? 1_000_000
  const lastTurn = [...folded.turns].reverse().find(t => t.usage.lastInput > 0)
  const stats: SessionStats = folded.turns.reduce((acc, t) => ({
    turns: acc.turns + 1, steps: acc.steps + t.usage.steps, input: acc.input + t.usage.input, cached: acc.cached + t.usage.cached,
    output: acc.output + t.usage.output, llmMs: acc.llmMs + t.llmMs, toolMs: acc.toolMs + t.toolMs,
    ttftMs: t.stats?.ttft_ms != null ? [...acc.ttftMs, t.stats.ttft_ms] : acc.ttftMs,
  }), { turns: 0, steps: 0, input: 0, cached: 0, output: 0, llmMs: 0, toolMs: 0, ttftMs: [] as number[] })
  const sysTokens = folded.request ? Math.round(folded.request.system.length / 4) : 0
  const send = async (text: string) => {
    const plan = planCommand(text)
    try { await (plan ? post(`play/${id}/plan`, plan) : post(`play/${id}/send`, { text })); kick() } catch (e) { alert((e as Error).message) }
  }
  const setPlan = async (active: boolean) => { await post(`play/${id}/plan`, { active }); kick() }
  const reply = async (r: QuestionReply) => { await post(`play/${id}/answer`, r); kick() }
  const pendingQuestion = info?.status === 'waiting'
    ? [...(folded.turns.at(-1)?.items ?? [])].reverse().find(i => i.kind === 'question' && !i.answered) as QuestionItem | undefined
    : undefined
  const stop = async () => { try { await post(`play/${id}/cancel`) } catch (e) { alert((e as Error).message) } }
  const decide = async (d: 'approve' | 'reject') => {
    try { await post(`play/${id}/resume`, { decision: d }); kick(); return true } catch (e) { alert((e as Error).message); return false }
  }
  const effortLabel = info?.effort ?? s.config?.default_effort ?? 'high'

  if (!info) {
    return <div className={root.root} data-phase="active"><div className={root.body} style={{ padding: 24, color: 'var(--dsw-alias-label-tertiary)' }}>{error ?? 'Loading…'}</div></div>
  }
  return (
    <div className={root.root} data-phase="active">
      <header className={root.header}>
        <div className={root.titleRow}>
          <div className={root.titleCluster}>
            <nav className={root.crumbs} aria-label="Session hierarchy">
              <span className={root.crumbSeg}><span className={cx(root.crumb, root.crumbCurrent)}>{info.title || 'New Session'}</span></span>
            </nav>
            <div className={root.headerActions}>
              <span className={presetLabel.label} title={s.harnesses.find(h => h.engine === info.engine && h.name === info.harness)?.description}>
                <IconAgentPresetOutline16 className={presetLabel.icon} />{modeLabel(info.engine, info.harness)}
              </span>
              {info.status === 'archived' && <span className={presetLabel.label}>· read-only (earlier run)</span>}
            </div>
          </div>
          <div className={root.headerUtilities}>
            <button ref={more} type="button" className={expand.button} aria-label="More actions" onClick={() => setMenu(!menu)}><IconEllipsisOutline16 /></button>
            <Menu open={menu} onClose={() => setMenu(false)} anchor={more} align="end">
              <MenuItem onSelect={() => { setMenu(false); s.go({ kind: 'runs', batch: info.batch, run: info.run_id }) }}>Open in Runs</MenuItem>
              <MenuItem onSelect={() => { setMenu(false); location.href = `/api/export/${info.batch}/${info.run_id}` }}>Download session log</MenuItem>
              <MenuItem onSelect={() => { setMenu(false); navigator.clipboard?.writeText(info.workdir) }}>Copy workspace path</MenuItem>
            </Menu>
          </div>
          <div className={root.headerCorner}>
            <button type="button" className={expand.button} aria-label={s.rightOpen ? 'Close right sidebar' : 'Open right sidebar'} onClick={() => s.setRightOpen(!s.rightOpen)}>
              <IconPanelLeftOutline16 className={expand.icon} />
            </button>
          </div>
        </div>
        <div className={root.tabs} role="tablist">
          {(['chat', 'trajectory'] as const).map(t => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} className={cx(root.tab, tab === t && root.tabActive)} onClick={() => setTab(t)}>
              {t === 'chat' ? 'Chat' : 'Trajectory'}
            </button>
          ))}
        </div>
      </header>
      <div className={root.body}>
        <div className={root.scrollBody} data-conversation-scroll="">
          <div className={root.viewArea}>
            {tab === 'chat'
              ? <CwdContext.Provider value={info.workdir.split('/').filter(Boolean).pop() ?? ''}><ChatView folded={folded} modelLabel={`${info.engine} · ${modelDisplay(info.model, s.config?.models)}`} live={live} /></CwdContext.Provider>
              : <Trajectory rows={rows} />}
          </div>
          {tab === 'chat' && live && (
            <div className={root.composerSeat} data-composer-seat="">
              <div className={root.composerStack}>
                {todos && todos.length > 0 && <TodoPanel todos={todos} />}
                {pendingQuestion
                  ? <QuestionComposer key={pendingQuestion.key} item={pendingQuestion} onReply={reply} />
                  : pendingApproval
                  ? <ApprovalPanel key={pendingApproval.key} item={pendingApproval} onAnswer={decide} />
                  : (
                    <InputBar placeholder={info.engine === 'dsh' ? 'Message (each message is a new headless task in this workspace)' : 'Message or run a task'}
                      onSend={send} onStop={stop} busy={busy}
                      modes={<>
                        <PermissionSelect value={info.approval} onChange={() => {}} disabled title="Set when the session starts" />
                        <PlanChip active={Boolean(info.plan_mode)} locked={busy} onOff={() => setPlan(false)} />
                      </>}
                      trailing={<>
                        <ModelSelect model={info.model} effort={effortLabel} onChange={() => {}} disabled />
                        {lastTurn && <ContextMeter used={lastTurn.usage.lastInput} window={ctxWindow}
                          breakdown={{ system: sysTokens, tools: 0, messages: Math.max(0, lastTurn.usage.lastInput - sysTokens) }} />}
                      </>}
                      stats={<StatsPills stats={stats} />} />
                  )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
