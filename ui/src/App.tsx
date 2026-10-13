/** DSH AppFrame: sidebar | center | right sidebar, plus the Settings modal. */
import frame from './dsh/css/AppFrame.module.css'
import { NewSession, SessionView } from './components/Conversation.tsx'
import { RightPanel } from './components/RightPanel.tsx'
import { SettingsModal } from './components/Settings.tsx'
import { AddWorkspaceModal, Sidebar } from './components/Sidebar.tsx'
import { HarnessPage, NewRunPage, RunsPage } from './pages/Experiments.tsx'
import { StoreProvider, useStore } from './lib/store.tsx'

function Frame() {
  const s = useStore()
  const v = s.view
  const session = v.kind === 'session' ? s.sessions.find(x => x.id === v.id) ?? null : null
  const right = s.rightOpen && v.kind === 'session'
  const columns = `${s.sidebarCollapsed ? 56 : 280}px minmax(0, 1fr) ${right ? 'min(400px, 34vw)' : '0px'}`
  return (
    <div className={frame.frame} style={{ gridTemplateColumns: columns, height: '100vh' }}>
      <div className={frame.sidebarCol}><Sidebar /></div>
      <div className={frame.centerCol}>
        {v.kind === 'session' && <SessionView key={v.id} id={v.id} />}
        {v.kind === 'new' && <NewSession />}
        {v.kind === 'runs' && <RunsPage batch={v.batch} run={v.run} />}
        {v.kind === 'newrun' && <NewRunPage />}
        {v.kind === 'harness' && <HarnessPage engine={v.engine} name={v.name} />}
      </div>
      <div className={frame.rightbarCol}>{right && <RightPanel session={session} />}</div>
      <SettingsModal />
      <AddWorkspaceModal />
    </div>
  )
}

export function App() {
  return <StoreProvider><Frame /></StoreProvider>
}
