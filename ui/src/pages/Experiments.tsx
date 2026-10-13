/** Experiment pages: Runs (batch comparison, run detail), New run (`lab run`), Harnesses (anatomy). */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import css from './pages.module.css'
import { get, getText, post, type BatchInfo, type HarnessInfo, type RunDetail, type RunSummary } from '../lib/api.ts'
import { cx, num } from '../lib/format.ts'
import { modeLabel, useStore } from '../lib/store.tsx'
import { Button, Modal } from '../components/primitives.tsx'
import { Trajectory, rowsFromTrace } from '../components/Trajectory.tsx'

const pct = (v: number | undefined | null) => (v == null ? '—' : Math.round(v * 100) + '%')
const recov = (r: RunSummary) => {
  const e = r.recovery?.tool_errors ?? r.tool_errors ?? 0
  if (!e) return '0'
  const ok = r.recovery?.recovered
  return `${e} → ${ok == null ? '?' : ok ? 'ok' : 'fail'}`
}

function Page({ title, sub, actions, children }: { title: string; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className={css.page}>
      <div className={css.header}><h1 className={css.title}>{title}</h1>{sub && <span className={css.sub}>{sub}</span>}<span className={css.spacer} />{actions}</div>
      <div className={css.body}><div className={css.column}>{children}</div></div>
    </div>
  )
}

function Bars({ rows }: { rows: (RunSummary & { label: string })[] }) {
  const max = Math.max(1, ...rows.map(r => r.input_uncached + r.cache_read + r.output))
  const w = (v: number) => `${(100 * v) / max}%`
  return (
    <>
      <div className={css.legend}>
        <span><i style={{ background: 'var(--dsw-alias-state-business-primary)' }} />input uncached</span>
        <span><i style={{ background: 'var(--dsw-static-blue-300)' }} />input cached</span>
        <span><i style={{ background: 'var(--dsw-static-amber-500)' }} />output</span>
      </div>
      <div className={css.bars}>
        {rows.map(r => (
          <div key={r.run_id} className={css.barRow}>
            <span>{r.label}</span>
            <div className={css.bar} title={`uncached ${num(r.input_uncached)} · cached ${num(r.cache_read)} · output ${num(r.output)}`}>
              <span style={{ width: w(r.input_uncached), background: 'var(--dsw-alias-state-business-primary)' }} />
              <span style={{ width: w(r.cache_read), background: 'var(--dsw-static-blue-300)' }} />
              <span style={{ width: w(r.output), background: 'var(--dsw-static-amber-500)' }} />
            </div>
            <span style={{ textAlign: 'right' }}>{num(r.total_tokens)}</span>
          </div>
        ))}
      </div>
    </>
  )
}

export function RunsPage({ batch, run }: { batch?: string; run?: string }) {
  const s = useStore()
  const [batches, setBatches] = useState<BatchInfo[]>([])
  const [summaries, setSummaries] = useState<RunSummary[]>([])
  useEffect(() => { get<BatchInfo[]>('batches').then(setBatches).catch(() => {}) }, [])
  const name = batch || batches[0]?.name
  useEffect(() => { if (name) get<RunSummary[]>(`batch/${name}`).then(setSummaries).catch(() => setSummaries([])) }, [name])
  if (run && name) return <RunDetailPage batch={name} run={run} summary={summaries.find(x => x.run_id === run)} />
  const byTask: Record<string, RunSummary[]> = {}
  for (const r of summaries) (byTask[r.task] ??= []).push(r)
  const judge = async () => { try { await post('jobs/judge', { batch: name }); s.go({ kind: 'newrun' }) } catch (e) { alert((e as Error).message) } }
  return (
    <Page title="Runs" sub={name ? `${summaries.length} runs · ${summaries[0]?.model ?? ''}` : undefined}
      actions={<>
        <select className={css.input} value={name ?? ''} onChange={e => s.go({ kind: 'runs', batch: e.target.value })}>
          {batches.map(b => <option key={b.name} value={b.name}>{`${b.name} (${b.runs})`}</option>)}
        </select>
        {s.config?.play && name && !name.startsWith('playground-') && <Button size="sm" onClick={judge}>Judge quality</Button>}
      </>}>
      {!name && <div className={css.card}>No runs yet. Start one from New run, or run <code>uv run lab run -H minimal,standard</code>.</div>}
      {Object.entries(byTask).map(([task, rs]) => (
        <section key={task} className={css.card}>
          <h2 className={css.cardTitle}>{task}</h2>
          <Bars rows={rs.map(r => ({ ...r, label: `${r.engine}/${r.harness} #${r.repeat}` }))} />
          <div className={css.scroll}>
            <table className={css.table}>
              <thead><tr><th>run</th><th>status</th><th>check</th><th>quality</th><th>tool sel.</th><th>err→recov</th><th>hitl</th><th title="Agent time (DSH: turn start→end, without process boot/exit)">time ms</th><th>llm</th><th>tools</th><th>1st req input</th><th>1st req tools</th><th>uncached</th><th>cached</th><th>output</th><th>total</th></tr></thead>
              <tbody>
                {rs.map(r => (
                  <tr key={r.run_id} className={css.rowClick} onClick={() => s.go({ kind: 'runs', batch: name, run: r.run_id })}>
                    <td>{`${r.engine}/${r.harness} #${r.repeat}`}</td>
                    <td className={r.status === 'ok' ? '' : css.bad}>{r.status}</td>
                    <td className={r.check === false ? css.bad : ''}>{r.check == null ? '—' : r.check ? 'pass' : 'fail'}</td>
                    <td>{r.quality ?? '—'}</td><td>{pct(r.tool_selection?.accuracy)}</td><td>{recov(r)}</td><td>{r.interrupts || '—'}</td>
                    <td title={`process ${num(r.wall_ms)} ms`}>{num(r.turn_ms ?? r.wall_ms)}</td><td>{num(r.llm_calls)}</td><td>{num(r.tool_calls)}</td>
                    <td>{num(r.first_request?.input_billed)}</td><td>{num(r.first_request?.tool_count)}</td>
                    <td>{num(r.input_uncached)}</td><td>{num(r.cache_read)}</td><td>{num(r.output)}</td><td>{num(r.total_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </Page>
  )
}

function RunDetailPage({ batch, run, summary: sm }: { batch: string; run: string; summary?: RunSummary }) {
  const s = useStore()
  const [d, setD] = useState<RunDetail | null>(null)
  const [dialog, setDialog] = useState<{ title: string; body: string } | null>(null)
  useEffect(() => { get<RunDetail>(`run/${batch}/${run}`).then(setD).catch(() => {}) }, [batch, run])
  const rows = useMemo(() => rowsFromTrace(d?.events ?? []), [d])
  const header = d?.events.find(e => e.kind === 'run') as Record<string, unknown> | undefined
  const chip = (k: string, v: unknown, bad?: boolean) => <span key={k} className={cx(css.chip, bad && css.bad)}>{k} <b>{String(v ?? '—')}</b></span>
  const openBody = async (id: string) => {
    const b = await get<{ messages?: { role: string; content: unknown }[]; tools?: unknown[] }>(`body/${id}`).catch(() => null)
    if (!b) { setDialog({ title: 'Request body', body: 'Not saved' }); return }
    const sys = (b.messages ?? []).filter(m => m.role === 'system').map(m => (typeof m.content === 'string' ? m.content : JSON.stringify(m.content))).join('\n---\n')
    setDialog({ title: 'Request body', body: `# system (${sys.length} chars)\n${sys}\n\n# tools (${(b.tools ?? []).length})\n${JSON.stringify(b.tools ?? [], null, 2)}\n\n# messages\n${JSON.stringify((b.messages ?? []).filter(m => m.role !== 'system'), null, 2)}` })
  }
  const openFile = async (path: string) => {
    const t = await getText(`file/${batch}/${run}/${path.split('/').map(encodeURIComponent).join('/')}`)
    setDialog({ title: path, body: t ?? 'Cannot read' })
  }
  return (
    <Page title={String(header?.title || sm?.task || run)} sub={sm ? `${modeLabel(sm.engine, sm.harness)} · #${sm.repeat}` : undefined}
      actions={<><Button size="sm" onClick={() => s.go({ kind: 'runs', batch })}>← Batch</Button><Button size="sm" onClick={() => { location.href = `/api/export/${batch}/${run}` }}>Export zip</Button></>}>
      {sm && (
        <section className={css.card}>
          <div className={css.chips}>
            {chip('status', sm.status, sm.status !== 'ok')}{chip('check', sm.check == null ? '—' : sm.check ? 'pass' : 'fail', sm.check === false)}
            {chip('time', `${num(sm.turn_ms ?? sm.wall_ms)} ms`)}{chip('process', `${num(sm.wall_ms)} ms`)}{chip('llm', sm.llm_calls)}{chip('tools', sm.tool_calls)}
            {chip('1st req input', num(sm.first_request?.input_billed))}{chip('1st req tools', sm.first_request?.tool_count)}
            {chip('total tokens', num(sm.total_tokens))}{chip('quality', sm.quality ?? '—')}
            {chip('tool sel.', pct(sm.tool_selection?.accuracy), sm.tool_selection ? !sm.tool_selection.required_met : false)}
            {chip('err→recov', recov(sm), sm.recovery?.recovered === false)}
            {sm.tool_selection?.off_target?.length ? chip('off-target', sm.tool_selection.off_target.join(', '), true) : null}
          </div>
        </section>
      )}
      <div className={css.trajectoryBox}><Trajectory rows={rows} /></div>
      <div className={css.grid2}>
        <section className={css.card}>
          <h2 className={css.cardTitle}>Final answer</h2>
          <pre className={css.pre}>{sm?.final || ''}</pre>
          {sm?.error && <><h2 className={css.cardTitle} style={{ marginTop: 12 }}>Error</h2><pre className={cx(css.pre, css.bad)}>{sm.error}</pre></>}
          {sm?.quality_detail ? <><h2 className={css.cardTitle} style={{ marginTop: 12 }}>Judge</h2><pre className={css.pre}>{JSON.stringify(sm.quality_detail, null, 2)}</pre></> : null}
          <h2 className={css.cardTitle} style={{ marginTop: 12 }}>Prompt</h2>
          <pre className={css.pre}>{String(header?.prompt ?? '')}</pre>
        </section>
        <section className={css.card}>
          <h2 className={css.cardTitle}>First request</h2>
          <p className={css.muted}>{`system ${num(sm?.first_request?.system_chars)} chars · tools: ${(sm?.first_request?.tools ?? []).join(', ') || 'none'}`}</p>
          {!!d?.wire.length && (
            <>
              <h2 className={css.cardTitle}>Wire (gateway)</h2>
              <table className={css.table}>
                <thead><tr><th>#</th><th>msgs</th><th>tools</th><th>in</th><th>cached</th><th>out</th><th>ms</th><th /></tr></thead>
                <tbody>{d.wire.map((w, i) => (
                  <tr key={i}><td>{i + 1}</td><td>{num(w.messages)}</td><td>{num((w.tools as unknown[] | undefined)?.length)}</td>
                    <td>{num(Number(w.input_uncached ?? 0) + Number(w.cache_read ?? 0))}</td><td>{num(w.cache_read)}</td><td>{num(w.output)}</td><td>{num(w.latency_ms)}</td>
                    <td><button className={css.link} onClick={() => openBody(String(w.id))}>body</button></td></tr>
                ))}</tbody>
              </table>
            </>
          )}
          <h2 className={css.cardTitle} style={{ marginTop: 12 }}>Workspace files</h2>
          {d?.files.length ? d.files.map(f => <div key={f.path}><button className={css.link} onClick={() => openFile(f.path)}>{f.path}</button> <span className={css.muted}>{num(f.bytes)} B</span></div>) : <p className={css.muted}>none</p>}
          {d?.stderr && <><h2 className={css.cardTitle} style={{ marginTop: 12 }}>stderr</h2><pre className={css.pre}>{d.stderr}</pre></>}
        </section>
      </div>
      <Modal open={!!dialog} onClose={() => setDialog(null)} title={dialog?.title ?? ''} className={css.wideModal}>
        <pre className={css.pre} style={{ maxHeight: '70vh' }}>{dialog?.body}</pre>
      </Modal>
    </Page>
  )
}

interface Job { id: string; kind: string; argv: string[]; status: string; batch: string | null; lines?: string[] }
interface TaskFile { file: string; tasks: { id: string; prompt: string }[] }

export function NewRunPage() {
  const s = useStore()
  const [tasks, setTasks] = useState<TaskFile[]>([])
  const [file, setFile] = useState('week1')
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [engines, setEngines] = useState<Record<string, boolean>>({ lab: true, dsh: false })
  const [hs, setHs] = useState<Record<string, boolean>>({ minimal: true, standard: true })
  const [repeat, setRepeat] = useState(1)
  const [label, setLabel] = useState('')
  const [judge, setJudge] = useState(false)
  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState('')
  useEffect(() => { get<TaskFile[]>('tasks').then(t => { setTasks(t); if (!t.some(x => x.file === 'week1') && t[0]) setFile(t[0].file) }).catch(() => {}) }, [])
  const tf = tasks.find(t => t.file === file)
  useEffect(() => { setPicked(Object.fromEntries((tf?.tasks ?? []).map(t => [t.id, true]))) }, [tf])
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      const list = await get<Job[]>('jobs').catch(() => [] as Job[])
      const full = await Promise.all(list.slice(0, 6).map(j => get<Job>(`jobs/${j.id}`).catch(() => j)))
      if (!alive) return
      setJobs(full)
      timer = setTimeout(tick, full.some(j => j.status === 'running') ? 1000 : 3000)
    }
    tick()
    return () => { alive = false; clearTimeout(timer) }
  }, [])
  const lab = s.harnesses.filter(h => h.engine === 'lab')
  const dshNames = new Set(s.harnesses.filter(h => h.engine === 'dsh').map(h => h.name))
  const chosen = Object.keys(hs).filter(k => hs[k])
  const nTasks = Object.values(picked).filter(Boolean).length
  const runs = nTasks * repeat * ((engines.lab ? chosen.length : 0) + (engines.dsh ? chosen.filter(h => dshNames.has(h)).length : 0))
  const start = async () => {
    setError('')
    const all = (tf?.tasks ?? []).map(t => t.id)
    const sel = all.filter(t => picked[t])
    try {
      await post('jobs/run', {
        tasks_file: file, tasks: sel.length === all.length ? [] : sel, engines: Object.keys(engines).filter(k => engines[k]),
        harnesses: chosen, repeat, label, judge,
      })
    } catch (e) { setError((e as Error).message) }
  }
  const box = (key: string, on: boolean, set: (v: boolean) => void, text: string, title?: string, disabled?: boolean) => (
    <label key={key} title={title}><input type="checkbox" checked={on} disabled={disabled} onChange={e => set(e.target.checked)} />{text}</label>
  )
  return (
    <Page title="New run" sub="= uv run lab run (tasks × harnesses × engines × N)">
      <section className={css.card}>
        <div className={css.grid2}>
          <div>
            <div className={css.field}><span className={css.fieldLabel}>Task file</span>
              <select className={css.input} value={file} onChange={e => setFile(e.target.value)}>{tasks.map(t => <option key={t.file} value={t.file}>{t.file}.yaml</option>)}</select></div>
            <div className={css.field}><span className={css.fieldLabel}>Tasks</span>
              <div className={css.checks}>{(tf?.tasks ?? []).map(t => box(t.id, !!picked[t.id], v => setPicked({ ...picked, [t.id]: v }), t.id, t.prompt))}</div></div>
            <div className={css.field}><span className={css.fieldLabel}>Engines</span>
              <div className={css.checks}>
                {box('lab', !!engines.lab, v => setEngines({ ...engines, lab: v }), 'lab (LangChain)')}
                {box('dsh', !!engines.dsh, v => setEngines({ ...engines, dsh: v }), `dsh (headless)${s.config?.dsh_installed ? '' : ' — not installed'}`, undefined, !s.config?.dsh_installed)}
              </div></div>
          </div>
          <div>
            <div className={css.field}><span className={css.fieldLabel}>{`Harnesses (dsh has ${[...dshNames].join(', ')} only)`}</span>
              <div className={css.checks}>{lab.map((h: HarnessInfo) => box(h.name, !!hs[h.name], v => setHs({ ...hs, [h.name]: v }), h.name, h.description))}</div></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto 80px auto 1fr', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <span className={css.fieldLabel}>Repeat</span>
              <input className={css.input} type="number" min={1} max={20} value={repeat} onChange={e => setRepeat(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
              <span className={css.fieldLabel}>Label</span>
              <input className={css.input} value={label} placeholder="optional" onChange={e => setLabel(e.target.value)} />
            </div>
            <div className={css.checks}>{box('judge', judge, setJudge, 'Judge Output Quality afterwards (extra model calls)')}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 14 }}>
          <Button variant="primary" onClick={start} disabled={!runs}>Run</Button>
          <span className={css.muted}>{`${runs} runs`}</span>
          {error && <span className={css.bad}>{error}</span>}
        </div>
      </section>
      <section className={css.card}>
        <h2 className={css.cardTitle}>Jobs</h2>
        {!jobs.length && <p className={css.muted}>None yet.</p>}
        {jobs.map((j, i) => (
          <details key={j.id} open={j.status === 'running' || i === 0} style={{ marginBottom: 10 }}>
            <summary style={{ cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <b>{j.kind}</b>
              <span className={j.status === 'failed' ? css.bad : j.status === 'done' ? css.good : ''}>{j.status}</span>
              {j.batch && <button className={css.link} onClick={() => s.go({ kind: 'runs', batch: j.batch! })}>{`${j.batch} →`}</button>}
              <span className={css.muted}>{`lab ${j.argv.join(' ')}`}</span>
              {j.status === 'running' && <Button size="sm" onClick={e => { e.preventDefault(); post(`jobs/${j.id}/stop`) }}>Stop</Button>}
            </summary>
            <pre className={css.pre} style={{ marginTop: 8 }}>{(j.lines ?? []).join('\n')}</pre>
          </details>
        ))}
      </section>
    </Page>
  )
}

interface Anatomy {
  harness: string
  middleware: { name: string; class: string; hooks: string[]; tools: string[]; doc: string }[]
  subagents: { name: string | null; middleware: { name: string }[]; system_prompt: string }[]
  system_prompt: string
  system_chars: number
  tools: { name: string; description: string; parameters: unknown; description_chars: number }[]
  tool_schema_chars: number
  graph_nodes: string[]
  patches?: { file: string; text: string }[]
}

export function HarnessPage({ engine, name }: { engine?: string; name?: string }) {
  const s = useStore()
  const eng = engine || 'lab'
  const nm = name || 'minimal'
  const [a, setA] = useState<Anatomy | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { setA(null); setError(''); get<Anatomy>(`anatomy/${eng}/${nm}`).then(setA).catch(e => setError((e as Error).message)) }, [eng, nm])
  const desc = s.harnesses.find(h => h.engine === eng && h.name === nm)?.description ?? ''
  const order = (hook: string) => {
    const ms = (a?.middleware ?? []).filter(m => m.hooks.includes(hook)).map(m => m.name)
    return hook.startsWith('after') ? ms.reverse() : ms
  }
  const onion = (hook: string, core: string) => { const ms = order(hook); return ms.length ? ms.join(' ( ') + ` ( ${core} ` + ')'.repeat(ms.length) : '—' }
  return (
    <Page title={modeLabel(eng, nm)} sub={desc}
      actions={<select className={css.input} value={`${eng}/${nm}`} onChange={e => { const [en, n] = e.target.value.split('/'); s.go({ kind: 'harness', engine: en, name: n }) }}>
        {s.harnesses.map(h => <option key={h.engine + h.name} value={`${h.engine}/${h.name}`}>{`${h.engine} · ${h.name}`}</option>)}
      </select>}>
      {error && <section className={css.card}><span className={css.bad}>{error}</span></section>}
      {!a && !error && <section className={css.card}>Building {eng}/{nm} with a probe model…</section>}
      {a && eng === 'dsh' && (
        <section className={css.card}>
          <p className={css.muted}>DSH runs <code>dsh --profile headless</code> with these overlays in order. The exact system prompt and tools it sends are in a gateway-recorded run (Runs → run → Wire → body).</p>
          {(a.patches ?? []).map(p => <div key={p.file}><h2 className={css.cardTitle}>{p.file}</h2><pre className={css.pre}>{p.text}</pre></div>)}
        </section>
      )}
      {a && eng === 'lab' && (
        <>
          <section className={css.card}>
            <div className={css.chips}>
              <span className={css.chip}>middleware <b>{a.middleware.length}</b></span><span className={css.chip}>tools <b>{a.tools.length}</b></span>
              <span className={css.chip}>system prompt <b>{num(a.system_chars)} chars</b></span><span className={css.chip}>tool schemas <b>{num(a.tool_schema_chars)} chars</b></span>
              {a.subagents.length > 0 && <span className={css.chip}>subagents <b>{a.subagents.map(x => x.name).join(', ')}</b></span>}
            </div>
            <p className={css.muted} style={{ marginBottom: 0 }}>Assembled without any API call: a probe model records the first request, so this is what actually goes out, including what middleware adds. The model name and folder in the prompt are the probe's.</p>
          </section>
          <section className={css.card}>
            <h2 className={css.cardTitle}>Middleware stack</h2>
            <div className={css.scroll}>
              <table className={cx(css.table, css.mwTable)}>
                <thead><tr><th>#</th><th className={css.left}>middleware</th><th className={css.left}>hooks</th><th className={css.left}>tools added</th><th className={css.left}>what it does</th></tr></thead>
                <tbody>{a.middleware.map((m, i) => (
                  <tr key={i}><td>{i + 1}</td><td className={css.left}><code title={m.class}>{m.name}</code></td><td className={css.left}>{m.hooks.join(', ') || '—'}</td>
                    <td className={css.left}>{m.tools.join(', ') || '—'}</td><td className={css.left} style={{ color: 'var(--dsw-alias-label-secondary)' }}>{m.doc}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <h2 className={css.cardTitle} style={{ marginTop: 14 }}>Order</h2>
            <pre className={css.pre}>{[
              `before_agent     ${order('before_agent').join(' → ') || '—'}`,
              `before_model     ${order('before_model').join(' → ') || '—'}`,
              `wrap_model_call  ${onion('wrap_model_call', 'model')}`,
              `after_model      ${order('after_model').join(' → ') || '—'}`,
              `wrap_tool_call   ${onion('wrap_tool_call', 'tool')}`,
              `after_agent      ${order('after_agent').join(' → ') || '—'}`,
            ].join('\n')}</pre>
            <p className={css.muted}>before_* run in list order, after_* in reverse, wrap_* nest like an onion with the first one outermost.</p>
          </section>
          <section className={css.card}>
            <h2 className={css.cardTitle}>{`Tools (${a.tools.length})`}</h2>
            {a.tools.map(t => (
              <details key={t.name} style={{ borderTop: '0.5px solid var(--dsw-alias-border-l1)', padding: '6px 0' }}>
                <summary style={{ cursor: 'pointer' }}><code>{t.name}</code> <span className={css.muted}>{`description ${num(t.description_chars)} chars`}</span></summary>
                <pre className={css.pre}>{t.description}</pre>
                <pre className={css.pre} style={{ marginTop: 6 }}>{JSON.stringify(t.parameters, null, 2)}</pre>
              </details>
            ))}
          </section>
          <section className={css.card}><h2 className={css.cardTitle}>System prompt (first request)</h2><pre className={css.pre} style={{ maxHeight: 600 }}>{a.system_prompt}</pre></section>
          {a.subagents.length > 0 && (
            <section className={css.card}>
              <h2 className={css.cardTitle}>Subagents</h2>
              {a.subagents.map(x => (
                <div key={String(x.name)} style={{ marginBottom: 12 }}>
                  <b>{x.name}</b> <span className={css.muted}>{x.middleware.map(m => m.name).join(' → ')}</span>
                  {x.system_prompt && <pre className={css.pre} style={{ marginTop: 6 }}>{x.system_prompt}</pre>}
                </div>
              ))}
            </section>
          )}
          <section className={css.card}><h2 className={css.cardTitle}>Graph nodes</h2><p className={css.muted}>{a.graph_nodes.join(' · ')}</p></section>
        </>
      )}
    </Page>
  )
}
