/**
 * DSH's question takeover, plan review and plan chip (ui-user-questions, ui-plan;
 * MIT), ported to this lab's event stream. Same DOM, class names and copy.
 */
import { useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import css from '../dsh/css/QuestionComposer.module.css'
import planCss from '../dsh/css/PlanReviewPanel.module.css'
import chipCss from '../dsh/css/PlanModeControl.module.css'
import askCss from '../dsh/css/AskQuestionCard.module.css'
import cmdCss from '../dsh/css/GenericCommandCard.module.css'
import {
  IconApiOutline14, IconCheckOutline14, IconChevronDownOutline14, IconChevronLeftOutline14, IconChevronRightOutline14,
  IconChevronUpOutline14, IconCloseFill14, IconCloseOutline16, IconEditOutline16,
} from '../dsh/icons.tsx'
import { cx } from '../lib/format.ts'
import { Markdown } from '../lib/markdown.tsx'
import { asArgs, type CommandItem, type Question, type QuestionAnswer, type QuestionItem } from '../lib/turns.ts'
import { Button, DisclosureRow } from './primitives.tsx'

/** Reply sent to `POST play/<id>/answer`. */
export type QuestionReply = { answers: QuestionAnswer[] } | { cancelled: true }

const T = {
  incomplete: 'Please complete this question first.',
  unanswered: 'Please select an option or enter a custom answer.',
}

/** Split the conventional recommendation suffix without changing the answer value. */
function parseRecommendedLabel(label: string): { label: string; recommended: boolean } {
  const suffix = /\s*(?:\((?:recommended|推荐)\)|（(?:recommended|推荐)）)\s*$/i
  return suffix.test(label) ? { label: label.replace(suffix, ''), recommended: true } : { label, recommended: false }
}

function isComposing(event: KeyboardEvent<HTMLTextAreaElement>): boolean {
  return event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
}

function AnswerField(props: {
  variant: 'inline' | 'block'; value: string; placeholder: string; disabled: boolean; autoFocus?: boolean
  onFocus?: () => void; onChange: (e: ChangeEvent<HTMLTextAreaElement>) => void; onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void
}) {
  return (
    <div className={cx(css.field, props.variant === 'inline' ? css.customInline : css.customBlock)}>
      <div aria-hidden className={css.fieldMirror}>{`${props.value}\n`}</div>
      <textarea autoFocus={props.autoFocus} className={css.fieldInput} value={props.value} disabled={props.disabled} rows={1}
        aria-label={props.placeholder} placeholder={props.placeholder} onFocus={props.onFocus} onChange={props.onChange} onKeyDown={props.onKeyDown} />
    </div>
  )
}

/** One plan-review request narrowed like DSH `planReviewOf`, or undefined for a generic question set. */
function planReviewOf(questions: Question[]) {
  if (questions.length !== 1) return undefined
  const q = questions[0]!
  if (q.intent?.kind !== 'plan-review' || q.detail === undefined || q.multiSelect) return undefined
  const options = q.options ?? []
  if (options.length > 2) return undefined
  const approve = options.find(o => o.label === q.intent!.approve)
  if (!approve) return undefined
  const decline = options.find(o => o.label !== q.intent!.approve)
  return { id: q.id, question: q.question, plan: q.detail, approve, decline }
}

/** Composer takeover: the plan review for a plan-review request, the question flow otherwise. */
export function QuestionComposer({ item, onReply }: { item: QuestionItem; onReply: (r: QuestionReply) => Promise<void> }) {
  const review = useMemo(() => planReviewOf(item.questions), [item])
  return review
    ? <PlanReviewPanel key={item.key} itemKey={item.key} review={review} onReply={onReply} />
    : <QuestionFlow key={item.key} item={item} onReply={onReply} />
}

interface Draft { selected: string[]; custom: string; skipped: boolean }

function QuestionFlow({ item, onReply }: { item: QuestionItem; onReply: (r: QuestionReply) => Promise<void> }) {
  const questions = item.questions
  const [index, setIndex] = useState(0)
  const [drafts, setDrafts] = useState<Draft[]>(() => questions.map(() => ({ selected: [], custom: '', skipped: false })))
  const [busy, setBusy] = useState<'answer' | 'cancel' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [minimized, setMinimized] = useState(false)
  const focused = useRef(new Set<number>())
  const question = questions[index]!
  const draft = drafts[index]!
  const hasOptions = (question.options?.length ?? 0) > 0
  const multi = question.multiSelect === true

  const replace = (nextIndex: number, next: Draft[]) => { setIndex(nextIndex); setDrafts(next) }
  const update = (fn: (d: Draft) => Draft, nextIndex = index) => {
    replace(nextIndex, drafts.map((d, i) => i === index ? fn(d) : d))
    setError(null)
  }
  const answered = (d: Draft) => d.selected.length > 0 || d.custom.trim() !== ''
  const completed = (d: Draft) => answered(d) || d.skipped

  const settle = (kind: 'answer' | 'cancel', reply: QuestionReply) => {
    setBusy(kind)
    setError(null)
    onReply(reply).catch((cause: unknown) => { setBusy(null); setError(cause instanceof Error ? cause.message : String(cause)) })
  }
  const choose = (label: string) => {
    update(d => {
      if (multi) {
        const selected = d.selected.includes(label) ? d.selected.filter(x => x !== label) : [...d.selected, label]
        return { ...d, selected, skipped: false }
      }
      return { selected: [label], custom: '', skipped: false }
    }, !multi && index < questions.length - 1 ? index + 1 : index)
  }
  const submit = (values: Draft[]) => {
    const missing = values.findIndex(d => !completed(d))
    if (missing >= 0) { replace(missing, values); setError(T.incomplete); return }
    settle('answer', {
      answers: questions.map((q, i) => {
        const v = values[i]!
        if (v.skipped) return { id: q.id, selected: [] }
        const custom = v.custom.trim()
        return { id: q.id, selected: custom === '' || q.multiSelect === true ? v.selected : [], ...(custom === '' ? {} : { custom }) }
      }),
    })
  }
  const next = () => {
    if (!answered(draft)) { setError(T.unanswered); return }
    if (index < questions.length - 1) { replace(index + 1, drafts); setError(null); return }
    submit(drafts)
  }
  const draftCustom = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    update(d => ({ ...d, selected: multi ? d.selected : [], custom: value, skipped: false }))
  }
  const continueFromCustom = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey || isComposing(e)) return
    e.preventDefault()
    next()
  }
  const skip = () => {
    const values = drafts.map((d, i) => i === index ? { selected: [], custom: '', skipped: true } : d)
    replace(index < questions.length - 1 ? index + 1 : index, values)
    setError(null)
    if (index === questions.length - 1) submit(values)
  }
  const titleId = `question-${item.key}-${index}`

  return (
    <div className={css.frame} data-question-key={item.key}>
      <section className={cx(css.card, minimized && css.cardMinimized)} aria-labelledby={titleId}>
        <header className={css.header}>
          <div className={css.headingBlock}>
            {question.header !== undefined && <div className={css.eyebrow}>{question.header}</div>}
            <h2 className={css.title} id={titleId}>{question.question}</h2>
          </div>
          <div className={css.headerActions}>
            <button type="button" className={css.iconButton} aria-label={minimized ? 'Expand the question card' : 'Collapse the question card'}
              title={minimized ? 'Expand the question card' : 'Collapse the question card'} aria-expanded={!minimized}
              disabled={busy !== null} onClick={() => setMinimized(m => !m)}>
              {minimized ? <IconChevronUpOutline14 /> : <IconChevronDownOutline14 />}
            </button>
            <button type="button" className={css.iconButton} aria-label="Dismiss all questions" title="Dismiss all questions"
              disabled={busy !== null} onClick={() => settle('cancel', { cancelled: true })}>
              <IconCloseOutline16 />
            </button>
          </div>
        </header>
        {!minimized && (
          <>
            <div className={css.body} data-question-scroll="">
              {question.detail !== undefined && <div className={css.detail}><Markdown text={question.detail} /></div>}
              <div className={css.options} role={multi ? 'group' : 'radiogroup'}>
                {(question.options ?? []).map((option, i) => {
                  const selected = draft.selected.includes(option.label)
                  const display = parseRecommendedLabel(option.label)
                  return (
                    <button type="button" key={`${option.label}-${i}`} className={cx(css.option, selected && !multi && css.optionSelected)}
                      role={multi ? 'checkbox' : 'radio'} aria-checked={selected} aria-label={display.label} disabled={busy !== null}
                      onClick={() => choose(option.label)}
                      onKeyDown={e => { if (e.key !== 'Enter' || !drafts.every(completed)) return; e.preventDefault(); submit(drafts) }}>
                      {multi
                        ? <span className={cx(css.checkbox, selected && css.checkboxChecked)} aria-hidden="true">{selected && <IconCheckOutline14 size={12} />}</span>
                        : <span className={css.number}>{i + 1}</span>}
                      <span className={css.optionCopy}>
                        <span className={css.optionLine}>
                          <span className={css.optionLabel}>{display.label}</span>
                          {display.recommended && <span className={css.badge}>Recommended</span>}
                          {option.description !== undefined && <span className={css.description}>{option.description}</span>}
                        </span>
                      </span>
                    </button>
                  )
                })}
                {hasOptions
                  ? (
                    <div className={cx(css.customRow, draft.custom !== '' && css.customRowActive)}>
                      {multi
                        ? <span className={cx(css.checkbox, draft.custom !== '' && css.checkboxChecked)} aria-hidden="true">{draft.custom !== '' && <IconCheckOutline14 size={12} />}</span>
                        : <span className={css.number} aria-hidden="true"><IconEditOutline16 size={12} /></span>}
                      <AnswerField variant="inline" value={draft.custom} disabled={busy !== null} placeholder="Type your answer"
                        onChange={draftCustom} onKeyDown={continueFromCustom} />
                    </div>
                  )
                  : (
                    <AnswerField autoFocus={!focused.current.has(index)} variant="block" value={draft.custom} disabled={busy !== null}
                      placeholder="Type your answer" onFocus={() => focused.current.add(index)} onChange={draftCustom} onKeyDown={continueFromCustom} />
                  )}
              </div>
            </div>
            <footer className={css.footer}>
              <div className={css.pager}>
                <button type="button" className={css.iconButton} aria-label="Previous question" disabled={index === 0 || busy !== null}
                  onClick={() => { replace(index - 1, drafts); setError(null) }}><IconChevronLeftOutline14 /></button>
                <span className={css.progress}>{index + 1} / {questions.length}</span>
                <button type="button" className={css.iconButton} aria-label="Next question" disabled={index === questions.length - 1 || busy !== null}
                  onClick={() => { replace(index + 1, drafts); setError(null) }}><IconChevronRightOutline14 /></button>
              </div>
              <div className={css.feedback} role="status">{error}</div>
              <div className={css.footerActions}>
                <Button variant="outline" disabled={busy !== null} onClick={skip}>Skip this question</Button>
                <Button variant="primary" disabled={busy !== null || !answered(draft)} onClick={next}>
                  {busy === 'answer' ? 'Submitting…' : index === questions.length - 1 ? 'Submit' : 'Next'}
                </Button>
              </div>
            </footer>
          </>
        )}
      </section>
    </div>
  )
}

function PlanReviewPanel({ itemKey, review, onReply }: {
  itemKey: string
  review: NonNullable<ReturnType<typeof planReviewOf>>
  onReply: (r: QuestionReply) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const settle = (reply: QuestionReply) => {
    setBusy(true)
    setError(null)
    onReply(reply).catch((cause: unknown) => { setBusy(false); setError(cause instanceof Error ? cause.message : String(cause)) })
  }
  const decide = (label: string) => settle({ answers: [{ id: review.id, selected: [label] }] })
  return (
    <div className={planCss.frame} data-plan-review-key={itemKey}>
      <section className={planCss.card} aria-label={review.question}>
        <div className={planCss.strip}><span className={planCss.dot} />Plan review</div>
        <div className={planCss.body} data-plan-review-scroll=""><Markdown text={review.plan} /></div>
        <div className={planCss.footer}>
          <div className={planCss.feedback} role="status">{error}</div>
          <div className={planCss.actions}>
            <Button variant="ghost" className={planCss.discuss} disabled={busy} onClick={() => settle({ cancelled: true })}>
              <IconEditOutline16 size={14} />Chat about it
            </Button>
            {review.decline && (
              <Button variant="outline" title={review.decline.description} disabled={busy} onClick={() => decide(review.decline!.label)}>Refuse</Button>
            )}
            <Button variant="primary" title={review.approve.description} disabled={busy} onClick={() => decide(review.approve.label)}>Approve</Button>
          </div>
        </div>
      </section>
    </div>
  )
}

/** DSH PlanChip: shown while plan mode is on; pressing it runs `/plan off`. */
export function PlanChip({ active, locked, onOff }: { active: boolean; locked?: boolean; onOff: () => Promise<void> }) {
  const [leaving, setLeaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!active) return null
  const off = () => {
    setLeaving(true)
    setError(null)
    onOff().then(() => setLeaving(false), (reason: unknown) => { setLeaving(false); setError(reason instanceof Error ? reason.message : String(reason)) })
  }
  return (
    <span className={chipCss.wrap}>
      <button type="button" className={chipCss.chip} aria-label="Plan mode on, press to turn off" title="Plan mode on — click to turn off (/plan off)"
        disabled={locked || leaving} onClick={off}>
        Plan
        <span className={chipCss.close} aria-hidden><IconCloseFill14 size={12} /></span>
      </button>
      {error !== null && <span className={chipCss.error} role="status" title={error}>Failed to exit plan mode</span>}
    </span>
  )
}

/** DSH GenericCommandCard: `/plan` and friends, as one row with the command's result text. */
export function CommandRow({ item }: { item: CommandItem }) {
  return (
    <div className={cmdCss.root} data-variant="others" data-state="ok">
      <DisclosureRow rowClassName={cmdCss.row} leadingClassName={cmdCss.leading} titleClassName={cmdCss.title}
        icon={<IconApiOutline14 size={14} />} title={item.name} open={false} onToggle={() => {}}>
        <span className={cmdCss.separator} aria-hidden />
        <span className={cmdCss.summary}>{item.text}</span>
      </DisclosureRow>
    </div>
  )
}

/** Answered / cancelled transcript under an `Ask question` tool row (DSH AskQuestionCard). */
export function askQuestionView(args: unknown, preview: string | undefined, done: boolean, error: boolean | undefined) {
  const questions = (Array.isArray(asArgs(args).questions) ? asArgs(args).questions as { id?: unknown; question?: unknown }[] : [])
    .filter(q => typeof q?.id === 'string' && typeof q?.question === 'string') as { id: string; question: string }[]
  if (!done) return { summary: 'waiting', body: null }
  if (error) {
    const cancelled = (preview ?? '').includes('cancelled')
    return {
      summary: cancelled ? 'cancelled' : 'failed',
      body: cancelled && questions.length > 0
        ? (
          <div className={askCss.card}>
            <p className={askCss.verdict}>This question set was cancelled before answers were submitted.</p>
            <ul className={askCss.questionList}>{questions.map(q => <li className={askCss.unansweredQuestion} key={q.id}>{q.question}</li>)}</ul>
          </div>
        )
        : null,
    }
  }
  let answers: QuestionAnswer[] = []
  try { answers = (JSON.parse(preview ?? '') as { answers: QuestionAnswer[] }).answers ?? [] } catch { return { summary: '', body: null } }
  const answeredCount = answers.filter(a => a.selected.length > 0 || (a.custom ?? '') !== '').length
  const byId = new Map(answers.map(a => [a.id, a]))
  return {
    summary: `${answeredCount}/${answers.length} answered`,
    body: (
      <dl className={askCss.card}>
        {questions.map(q => {
          const a = byId.get(q.id)
          const lines = a ? [...a.selected, ...(a.custom ? [a.custom] : [])] : []
          return (
            <div className={askCss.item} key={q.id}>
              <dt className={askCss.question}>{q.question}</dt>
              <dd className={askCss.answer}>
                {lines.length === 0 ? <span className={askCss.skipped}>Not answered</span>
                  : lines.map((l, i) => <span className={askCss.answerLine} key={i}>{l}</span>)}
              </dd>
            </div>
          )
        })}
      </dl>
    ),
  }
}
