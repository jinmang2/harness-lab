/**
 * DSH QueueDock (ui-conversation queue/QueueDock; MIT): messages sent while a turn runs, docked above
 * the composer. One row renders directly; several collapse under a count header. Same DOM, class names
 * and copy. `next-turn` rows are queued; `next-step` rows were steered and wait for the running turn.
 */
import { useEffect, useId, useState } from 'react'
import {
  IconCheckOutline16, IconChevronDownOutline14, IconChevronUpOutline14, IconCloseOutline16, IconEditOutline16,
  IconQueueOutline14, IconSendOutline14, IconTrashOutline16,
} from '../dsh/icons.tsx'
import css from '../dsh/css/QueueDock.module.css'
import type { Attachment, QueueItem } from '../lib/api.ts'
import { FileTypeIcon, fileSizeText } from './ComposerAttachments.tsx'

export type QueueAction = 'edit' | 'remove' | 'steer'

function QueueAttachments({ sessionId, attachments }: { sessionId: string; attachments: Attachment[] }) {
  if (attachments.length === 0) return null
  return (
    <span className={css.attachments}>
      {attachments.map(a => a.kind === 'image'
        ? <img key={a.id} className={css.thumb} src={`/api/play/${sessionId}/attachment/${a.id}`} alt="Queued message image" />
        : (
          <span key={a.id} className={css.file} aria-label={`Queued file ${a.name}`} title={a.name}>
            <span className={css.fileIcon} aria-hidden><FileTypeIcon path={a.name} size={16} /></span>
            <span className={css.fileName}>{a.name}</span>
            <span className={css.fileSize}>{fileSizeText(a.bytes)}</span>
          </span>
        ))}
    </span>
  )
}

export function QueueDock({ sessionId, items, running, onAction, onError }: {
  sessionId: string
  items: QueueItem[]
  /** The agent is mid-turn, so a queued row can be steered into it. */
  running: boolean
  onAction: (id: string, action: QueueAction, text?: string) => Promise<void>
  onError: (text: string) => void
}) {
  const queue = items.filter(q => q.target === 'next-turn')
  const sending = items.filter(q => q.target === 'next-step')
  const rowCount = queue.length + sending.length
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(true)
  const listId = useId()

  useEffect(() => {
    if (rowCount === 0 && !collapsed) setCollapsed(true)
    if (editing !== null && !queue.some(q => q.id === editing.id)) setEditing(null)
  }, [collapsed, editing, queue, rowCount])

  if (rowCount === 0) return null

  const interactionActive = editing !== null || busy !== null
  const expanded = !collapsed || interactionActive
  const listVisible = rowCount === 1 || expanded

  const apply = async (id: string, action: QueueAction, failure: string, text?: string): Promise<boolean> => {
    setBusy(id)
    try {
      await onAction(id, action, text)
      return true
    } catch {
      onError(failure)
      return false
    } finally {
      setBusy(current => current === id ? null : current)
    }
  }
  const saveEdit = async () => {
    if (editing === null || editing.text.trim() === '') return
    if (await apply(editing.id, 'edit', 'Edit failed: this message may have already started sending.', editing.text)) setEditing(null)
  }
  const lead = rowCount === 1 && <span className={css.lead} aria-hidden><IconQueueOutline14 /></span>

  return (
    <div className={css.dock} data-queue-dock="">
      <div className={css.panel}>
        {rowCount > 1 && (
          <button type="button" className={css.header} aria-controls={listId} aria-expanded={expanded}
            disabled={interactionActive} onClick={() => setCollapsed(v => !v)}>
            <span className={css.lead} aria-hidden><IconQueueOutline14 /></span>
            <span className={css.count}>{`${rowCount} queued messages`}</span>
            {!listVisible && sending.length > 0 && <span className={css.status} role="status">Sending…</span>}
            <span className={css.chevron} aria-hidden>{expanded ? <IconChevronDownOutline14 /> : <IconChevronUpOutline14 />}</span>
          </button>
        )}
        <ul id={listId} className={css.list} hidden={!listVisible}>
          {listVisible && queue.map(row => {
            // DSH edits text-only rows; a row carrying attachments keeps them as they are.
            const editable = row.attachments.length === 0
            return (
              <li key={row.id} className={css.row}>
                {lead}
                {editing?.id === row.id
                  ? (
                    <input autoFocus className={css.editor} aria-label="Edit queued message" value={editing.text}
                      onChange={e => setEditing({ id: row.id, text: e.currentTarget.value })}
                      onKeyDown={e => {
                        if (e.key === 'Escape') { setEditing(null); return }
                        if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); void saveEdit() }
                      }} />
                  )
                  : (
                    <>
                      <QueueAttachments sessionId={sessionId} attachments={row.attachments} />
                      <span className={css.preview}>{row.text}</span>
                    </>
                  )}
                <div className={css.actions}>
                  {editing?.id === row.id
                    ? (
                      <>
                        <button type="button" className={css.action} aria-label="Save queued message"
                          disabled={busy !== null || editing.text.trim() === ''} onClick={() => void saveEdit()}>
                          <IconCheckOutline16 size={14} />
                        </button>
                        <button type="button" className={css.action} aria-label="Cancel editing" disabled={busy !== null} onClick={() => setEditing(null)}>
                          <IconCloseOutline16 size={14} />
                        </button>
                      </>
                    )
                    : (
                      <>
                        <button type="button" className={css.action} aria-label="Edit queued message"
                          title={editable ? undefined : 'Contains non-text content; editing is not supported yet'}
                          disabled={busy !== null || !editable} onClick={() => setEditing({ id: row.id, text: row.text })}>
                          <IconEditOutline16 size={14} />
                        </button>
                        <button type="button" className={css.action} aria-label="Remove queued message" disabled={busy !== null}
                          onClick={() => void apply(row.id, 'remove', 'Removal failed: this message may have already started sending.')}>
                          <IconTrashOutline16 size={14} />
                        </button>
                        <button type="button" className={css.action} aria-label="Steer queued message"
                          title={running ? undefined : 'Steering is available only while the agent is running'}
                          disabled={busy !== null || !running} onClick={() => void apply(row.id, 'steer', 'Steering failed. Try again.')}>
                          <IconSendOutline14 />
                        </button>
                      </>
                    )}
                </div>
              </li>
            )
          })}
          {listVisible && sending.map(row => (
            <li key={row.id} className={`${css.row} ${css.pendingRow}`} data-submission-echo="">
              {lead}
              <QueueAttachments sessionId={sessionId} attachments={row.attachments} />
              <span className={css.preview}>{row.text}</span>
              <span className={css.status} role="status">Sending…</span>
              <div className={css.actions}>
                <button type="button" className={css.action} aria-label="Edit queued message" title="Sending…" disabled><IconEditOutline16 size={14} /></button>
                <button type="button" className={css.action} aria-label="Remove queued message" title="Sending…" disabled><IconTrashOutline16 size={14} /></button>
                <button type="button" className={css.action} aria-label="Steer queued message" title="Sending…" disabled><IconSendOutline14 /></button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
