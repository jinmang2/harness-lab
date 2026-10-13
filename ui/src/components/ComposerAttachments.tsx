/**
 * DSH draft attachments (ui-attachment ComposerAttachments, AttachmentRail, FileCard; ui-primitives
 * FileTypeIcon, fileSizeText; MIT): pending image thumbnails and file cards above the draft.
 * Same DOM, class names and copy. Files upload when the message is sent (POST play/<id>/upload).
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { IconChevronLeftOutline14, IconChevronRightOutline14, IconCloseFill14 } from '../dsh/icons.tsx'
import css from '../dsh/css/ComposerAttachments.module.css'
import railCss from '../dsh/css/AttachmentRail.module.css'
import cardCss from '../dsh/css/FileCard.module.css'
import typeCss from '../dsh/css/FileTypeIcon.module.css'
import { post, type Attachment } from '../lib/api.ts'
import { cx } from '../lib/format.ts'

/** Image types the lab (like DSH's image intake) sends to the model as images; anything else is a file. */
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024
export const MAX_IMAGES = 20

/** One picked file waiting in the draft. */
export interface PendingAttachment { id: string; file: File; kind: 'image' | 'file'; previewUrl?: string }

let seq = 0
export function pendingAttachment(file: File): PendingAttachment {
  const image = IMAGE_TYPES.includes(file.type)
  return { id: `a${++seq}`, file, kind: image ? 'image' : 'file', previewUrl: image ? URL.createObjectURL(file) : undefined }
}

/** DSH intake pre-check; returns the rejection copy, or null when the batch fits. */
export function intakeError(current: PendingAttachment[], files: File[]): string | null {
  const images = files.filter(f => IMAGE_TYPES.includes(f.type))
  if (current.filter(a => a.kind === 'image').length + images.length > MAX_IMAGES) return `A message can include up to ${MAX_IMAGES} images`
  if (images.some(f => f.size > MAX_IMAGE_BYTES)) return `Each image must be smaller than ${MAX_IMAGE_BYTES / (1024 * 1024)}MB`
  return null
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ''))
    reader.onerror = () => reject(reader.error ?? new Error('read failed'))
    reader.readAsDataURL(file)
  })
}

/** Product copy for a send/upload failure (DSH attachmentErrorText for the lab's reasons). */
export function attachmentErrorText(message: string): string {
  if (/does not support image input/.test(message)) return 'The current model does not support images; switch to a model that does'
  return message
}

/** Upload the draft's files to a session; returns their attachment ids in draft order. */
export async function uploadAttachments(sessionId: string, items: PendingAttachment[]): Promise<string[]> {
  const ids: string[] = []
  for (const a of items) {
    const data = await readBase64(a.file)
    const rec = await post<Attachment>(`play/${sessionId}/upload`, { name: a.file.name, mime: a.file.type, data })
    ids.push(rec.id)
  }
  return ids
}

/** Byte count as compact size text (`312B`, `4.2KB`, `1.5MB`). */
export function fileSizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)}KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)}MB`
  const gb = mb / 1024
  return `${gb < 10 ? gb.toFixed(1) : Math.round(gb)}GB`
}

export function fileExtension(path: string): string {
  const name = path.slice(Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\')) + 1)
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1)
}

type FileKind = 'code' | 'excel' | 'html' | 'image' | 'markdown' | 'other' | 'pdf' | 'ppt' | 'video' | 'word'

// DSH draws its code/config categories with full-colour artwork; the lab uses the generic code glyph for them.
const CODE_EXT = 'ts tsx js jsx mjs cjs py rb go rs java kt c h cc cpp hpp cs swift php lua sh bash zsh ps1 sql json json5 jsonc yaml yml toml ini xml css scss sass less vue svelte astro dart scala r pl ex exs erl hs zig proto graphql bat cmd csv tsv env'.split(' ')
const EXT_KIND: Record<string, FileKind> = {
  html: 'html', htm: 'html',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', svg: 'image', webp: 'image', avif: 'image', bmp: 'image', ico: 'image', tif: 'image', tiff: 'image', heic: 'image', heif: 'image',
  md: 'markdown', mdx: 'markdown', markdown: 'markdown', pdf: 'pdf', ppt: 'ppt', pptx: 'ppt', key: 'ppt',
  mp4: 'video', mov: 'video', m4v: 'video', webm: 'video', mkv: 'video', avi: 'video', mpg: 'video', mpeg: 'video',
  doc: 'word', docx: 'word', rtf: 'word', odt: 'word', pages: 'word', xls: 'excel', xlsx: 'excel', xlsm: 'excel', numbers: 'excel',
}

function classify(path: string): FileKind {
  const ext = fileExtension(path).toLowerCase()
  const base = path.slice(path.lastIndexOf('/') + 1).toLowerCase()
  if (['readme', 'changelog', 'contributing'].includes(base)) return 'markdown'
  if (['dockerfile', 'makefile', '.gitignore'].includes(base) || CODE_EXT.includes(ext)) return 'code'
  return EXT_KIND[ext] ?? 'other'
}

const FILE_BODY = 'M8.48924 28H19.5108C21.6479 28 22.7165 28 23.5594 27.6509C24.6833 27.1853 25.5762 26.2924 26.0417 25.1685C26.3909 24.3256 26.3909 23.257 26.3909 21.1199V8.79443C26.3909 8.32877 26.3909 8.09593 26.3471 7.87507C26.2887 7.58058 26.173 7.30042 26.0067 7.05048C25.882 6.86303 25.7177 6.69799 25.3893 6.36792L20.0611 1.01354C19.7304 0.681235 19.5651 0.515081 19.3769 0.38885C19.126 0.220541 18.8443 0.103463 18.5481 0.0443412C18.3259 0 18.0915 0 17.6226 0H8.48924C6.35209 0 5.28351 0 4.4406 0.349145C3.31672 0.814671 2.4238 1.70759 1.95828 2.83147C1.60913 3.67438 1.60913 4.74296 1.60913 6.88011V21.1199C1.60913 23.257 1.60913 24.3256 1.95828 25.1685C2.4238 26.2924 3.31672 27.1853 4.4406 27.6509C5.28351 28 6.35209 28 8.48924 28Z'
const FILE_FOLD = 'M26.3909 7.37445L19.0525 0V3.77445C19.0525 4.89271 19.0525 5.45184 19.2352 5.89289C19.4788 6.48096 19.946 6.94818 20.5341 7.19176C20.9751 7.37445 21.5342 7.37445 22.6525 7.37445H26.3909Z'
const MARK = 'translate(14 16) scale(1.12) translate(-14 -16)'
const LARGE_MARK = 'translate(14 16) scale(1.22) translate(-14 -16)'

const MARKS: Record<Exclude<FileKind, 'other'>, { large?: boolean; d: string[] }> = {
  code: { d: ['M8.61 16.3601L11.76 18.3901V20.1401L7 17.0601V15.6601L11.76 12.5801V14.3301L8.61 16.3601Z', 'M16.1918 14.3301V12.5801L20.9518 15.6601V17.0601L16.1918 20.1401V18.3901L19.3418 16.3601L16.1918 14.3301Z'] },
  excel: { large: true, d: ['M10.2932 20.5L13.3532 16.25L13.3432 17.66L10.4032 13.5H12.6332L14.5132 16.21L13.5632 16.22L15.4132 13.5H17.5532L14.6132 17.58V16.18L17.7132 20.5H15.4332L13.5232 17.65H14.4332L12.5532 20.5H10.2932Z'] },
  html: { d: ['M13.9994 9.68298C17.212 9.68298 19.8167 12.2872 19.8168 15.4997C19.8168 18.7123 17.2121 21.3171 13.9994 21.3171C10.7869 21.3169 8.18274 18.7122 8.18274 15.4997C8.1829 12.2873 10.787 9.68315 13.9994 9.68298ZM9.26213 16.0247C9.47025 17.9241 10.7936 19.4876 12.5639 20.0463C12.42 19.7977 12.2952 19.5152 12.1879 19.2116C11.885 18.3541 11.693 17.2434 11.6424 16.0247H9.26213ZM16.3565 16.0247C16.3059 17.2434 16.1145 18.3542 15.8116 19.2116C15.7044 19.5151 15.5788 19.7971 15.435 20.0456C17.2054 19.487 18.5293 17.9242 18.7374 16.0247H16.3565ZM12.6938 16.0247C12.7439 17.1459 12.9212 18.1334 13.1784 18.8616C13.332 19.2962 13.503 19.61 13.6686 19.805C13.834 19.9996 13.9473 20.0256 13.9994 20.0258C14.0514 20.0258 14.1651 20.0002 14.331 19.805C14.4966 19.61 14.6676 19.2962 14.8211 18.8616C15.0784 18.1334 15.2557 17.1459 15.3058 16.0247H12.6938ZM13.9994 10.733C13.9473 10.7331 13.834 10.7598 13.6686 10.9545C13.503 11.1494 13.3319 11.4633 13.1784 11.8978C12.903 12.6777 12.7188 13.7545 12.6849 14.9747H15.3147C15.2808 13.7545 15.0966 12.6777 14.8211 11.8978C14.6676 11.4633 14.4965 11.1494 14.331 10.9545C14.1651 10.7593 14.0514 10.733 13.9994 10.733ZM15.5888 11.0051C15.6701 11.1756 15.7444 11.3576 15.8116 11.5478C16.1343 12.4613 16.3308 13.6619 16.3647 14.9747H18.7374C18.5352 13.1307 17.2817 11.6036 15.5888 11.0051ZM12.4101 11.0051C10.7174 11.6037 9.46428 13.1308 9.26213 14.9747H11.6349C11.6688 13.6619 11.8652 12.4613 12.1879 11.5478C12.2551 11.3577 12.3288 11.1756 12.4101 11.0051Z'] },
  image: { d: ['M10.4212 15.9204C10.5756 15.6558 10.9579 15.6558 11.1123 15.9204L13.6493 20.2696C13.8048 20.5362 13.6125 20.8711 13.3037 20.8711H8.22974C7.92102 20.8711 7.72868 20.5362 7.88423 20.2696L10.4212 15.9204Z', 'M15.4981 13.186C15.6505 12.9117 16.0451 12.9117 16.1975 13.186L20.1368 20.2769C20.2849 20.5435 20.0922 20.8711 19.7872 20.8711H11.9084C11.6034 20.8711 11.4107 20.5435 11.5588 20.2769L15.4981 13.186Z', 'M11.8603 11.3997C11.8603 12.286 11.1418 13.0045 10.2555 13.0045C9.36924 13.0045 8.65076 12.286 8.65076 11.3997C8.65076 10.5134 9.36924 9.79492 10.2555 9.79492C11.1418 9.79492 11.8603 10.5134 11.8603 11.3997Z'] },
  markdown: { large: true, d: ['M8.7588 19.5V14.6H9.8998L11.9298 17.932H11.3278L13.3018 14.6H14.4428L14.4568 19.5H13.1828L13.1688 16.539H13.3858L11.9088 19.017H11.2928L9.7738 16.539H10.0398V19.5H8.7588ZM15.4375 19.5V14.6H17.7545C18.2958 14.6 18.7718 14.7003 19.1825 14.901C19.5932 15.1017 19.9128 15.384 20.1415 15.748C20.3748 16.112 20.4915 16.546 20.4915 17.05C20.4915 17.5493 20.3748 17.9833 20.1415 18.352C19.9128 18.716 19.5932 18.9983 19.1825 19.199C18.7718 19.3997 18.2958 19.5 17.7545 19.5H15.4375ZM16.8235 18.394H17.6985C17.9785 18.394 18.2212 18.3427 18.4265 18.24C18.6365 18.1327 18.7998 17.9787 18.9165 17.778C19.0332 17.5727 19.0915 17.33 19.0915 17.05C19.0915 16.7653 19.0332 16.5227 18.9165 16.322C18.7998 16.1213 18.6365 15.9697 18.4265 15.867C18.2212 15.7597 17.9785 15.706 17.6985 15.706H16.8235V18.394Z'] },
  pdf: { large: true, d: ['M6.80616 19.5V14.6H9.04616C9.49416 14.6 9.87916 14.6723 10.2012 14.817C10.5278 14.9617 10.7798 15.1717 10.9572 15.447C11.1345 15.7177 11.2232 16.0397 11.2232 16.413C11.2232 16.7817 11.1345 17.1013 10.9572 17.372C10.7798 17.6427 10.5278 17.8527 10.2012 18.002C9.87916 18.1467 9.49416 18.219 9.04616 18.219H7.57616L8.19216 17.617V19.5H6.80616ZM8.19216 17.764L7.57616 17.127H8.96216C9.2515 17.127 9.46616 17.064 9.60616 16.938C9.75083 16.812 9.82316 16.637 9.82316 16.413C9.82316 16.1843 9.75083 16.007 9.60616 15.881C9.46616 15.755 9.2515 15.692 8.96216 15.692H7.57616L8.19216 15.055V17.764ZM11.8989 19.5V14.6H14.2159C14.7573 14.6 15.2333 14.7003 15.6439 14.901C16.0546 15.1017 16.3743 15.384 16.6029 15.748C16.8363 16.112 16.9529 16.546 16.9529 17.05C16.9529 17.5493 16.8363 17.9833 16.6029 18.352C16.3743 18.716 16.0546 18.9983 15.6439 19.199C15.2333 19.3997 14.7573 19.5 14.2159 19.5H11.8989ZM13.2849 18.394H14.1599C14.4399 18.394 14.6826 18.3427 14.8879 18.24C15.0979 18.1327 15.2613 17.9787 15.3779 17.778C15.4946 17.5727 15.5529 17.33 15.5529 17.05C15.5529 16.7653 15.4946 16.5227 15.3779 16.322C15.2613 16.1213 15.0979 15.9697 14.8879 15.867C14.6826 15.7597 14.4399 15.706 14.1599 15.706H13.2849V18.394ZM17.6821 19.5V14.6H21.5251V15.671H19.0681V19.5H17.6821ZM18.9701 17.82V16.749H21.2311V17.82H18.9701Z'] },
  ppt: { large: true, d: ['M11.0132 20.5V13.5H14.2132C14.8532 13.5 15.4032 13.6033 15.8632 13.81C16.3299 14.0167 16.6899 14.3167 16.9432 14.71C17.1966 15.0967 17.3232 15.5567 17.3232 16.09C17.3232 16.6167 17.1966 17.0733 16.9432 17.46C16.6899 17.8467 16.3299 18.1467 15.8632 18.36C15.4032 18.5667 14.8532 18.67 14.2132 18.67H12.1132L12.9932 17.81V20.5H11.0132ZM12.9932 18.02L12.1132 17.11H14.0932C14.5066 17.11 14.8132 17.02 15.0132 16.84C15.2199 16.66 15.3232 16.41 15.3232 16.09C15.3232 15.7633 15.2199 15.51 15.0132 15.33C14.8132 15.15 14.5066 15.06 14.0932 15.06H12.1132L12.9932 14.15V18.02Z'] },
  video: { d: ['M17.5 14.634C18.1667 15.0189 18.1667 15.9811 17.5 16.366L11.5 19.8301C10.8333 20.215 10 19.7339 10 18.9641L10 12.0359C10 11.2661 10.8333 10.785 11.5 11.1699L17.5 14.634Z'] },
  word: { large: true, d: ['M10.5118 20.5L8.24179 13.5H10.2818L12.1918 19.56H11.1618L13.1718 13.5H14.9918L16.8918 19.56H15.9018L17.8718 13.5H19.7618L17.4918 20.5H15.3718L13.7518 15.35H14.3218L12.6318 20.5H10.5118Z'] },
}

/** DSH FileTypeIcon: category-coloured file glyph for a path (decorative). */
export function FileTypeIcon({ path, size = 28 }: { path: string; size?: number }) {
  const kind = classify(path)
  const mark = kind === 'other' ? undefined : MARKS[kind]
  return (
    <svg width={size} height={size} className={cx(typeCss.icon, typeCss[kind])} viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden>
      <path d={FILE_BODY} fill="currentColor" />
      {mark
        ? <path d={FILE_FOLD} fill="var(--dsw-static-neutral-00)" fillOpacity=".7" />
        : <path d={FILE_FOLD} fill="var(--dsw-static-neutral-400)" />}
      {mark && (
        <g color="var(--dsw-static-neutral-00)" data-file-type-mark="" transform={mark.large ? LARGE_MARK : MARK}>
          {mark.d.map(d => <path key={d.slice(0, 16)} d={d} fill="currentColor" fillRule={kind === 'html' ? 'evenodd' : undefined} clipRule={kind === 'html' ? 'evenodd' : undefined} />)}
        </g>
      )}
    </svg>
  )
}

/** DSH AttachmentRail: scrollbar-less horizontal rail paged by edge arrows. */
function AttachmentRail<T extends { id: string }>({ items, renderItem }: { items: readonly T[]; renderItem: (item: T) => ReactNode }) {
  const railRef = useRef<HTMLDivElement | null>(null)
  const countRef = useRef<number | null>(null)
  const [edges, setEdges] = useState({ left: false, right: false })
  const updateEdges = useCallback(() => {
    const el = railRef.current
    if (el === null) return
    const left = el.scrollLeft > 1
    const right = el.scrollLeft < el.scrollWidth - el.clientWidth - 1
    setEdges(prev => prev.left === left && prev.right === right ? prev : { left, right })
  }, [])
  useLayoutEffect(() => {
    const grew = countRef.current !== null && items.length > countRef.current
    countRef.current = items.length
    const el = railRef.current
    if (el === null) return
    if (grew) el.scrollLeft = el.scrollWidth - el.clientWidth
    updateEdges()
  }, [items.length, updateEdges])
  useEffect(() => {
    const el = railRef.current
    if (el === null) return
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(updateEdges) : null
    observer?.observe(el)
    // A vertical wheel pans the rail horizontally instead of scrolling the conversation behind it.
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY === 0) return
      const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? el.clientWidth : 1
      event.preventDefault()
      el.scrollBy({ left: event.deltaX !== 0 ? event.deltaX * scale : Math.sign(event.deltaY) * Math.min(Math.abs(event.deltaY) * scale, 60), behavior: 'auto' })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => { observer?.disconnect(); el.removeEventListener('wheel', onWheel) }
  }, [updateEdges])
  const page = (direction: -1 | 1) => {
    const el = railRef.current
    if (el === null) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollBy({ left: direction * Math.max(el.clientWidth - 64, 200), behavior: reduce ? 'auto' : 'smooth' })
  }
  return (
    <div className={railCss.root}>
      {edges.left && (
        <button type="button" className={cx(railCss.arrow, railCss.arrowLeft)} aria-label="Scroll attachments left" onClick={() => page(-1)}>
          <IconChevronLeftOutline14 />
        </button>
      )}
      <div ref={railRef} className={railCss.rail} role="group" aria-label="Pending attachments" onScroll={updateEdges}>
        {items.map(item => <div key={item.id} className={railCss.item}>{renderItem(item)}</div>)}
      </div>
      {edges.right && (
        <button type="button" className={cx(railCss.arrow, railCss.arrowRight)} aria-label="Scroll attachments right" onClick={() => page(1)}>
          <IconChevronRightOutline14 />
        </button>
      )}
    </div>
  )
}

/** DSH FileCard in its ready state (the lab uploads on send, so there is no per-card progress). */
function FileCard({ name, bytes, onRemove }: { name: string; bytes: number; onRemove: () => void }) {
  const meta = [fileExtension(name).toUpperCase().slice(0, 8), fileSizeText(bytes)].filter(Boolean).join(' ')
  return (
    <div className={cardCss.card} title={name}>
      <span className={cardCss.icon} aria-hidden><FileTypeIcon path={name} /></span>
      <span className={cardCss.body} aria-label="Pending files">
        <span className={cardCss.name}>{name}</span>
        <span className={cardCss.meta}>{meta}</span>
      </span>
      <button type="button" className={cardCss.remove} aria-label={`Remove file ${name}`} onClick={onRemove}>
        <IconCloseFill14 size={12} />
      </button>
    </div>
  )
}

/** Draft image previews and pending-file cards. */
export function ComposerAttachments({ attachments, onRemove }: { attachments: PendingAttachment[]; onRemove: (id: string) => void }) {
  if (attachments.length === 0) return null
  return (
    <div className={css.rail}>
      <AttachmentRail items={attachments} renderItem={a => a.kind === 'file'
        ? <FileCard name={a.file.name || 'File'} bytes={a.file.size} onRemove={() => onRemove(a.id)} />
        : (
          <div className={css.imageItem}>
            <button type="button" className={css.thumbnail} title="View original" onClick={() => window.open(a.previewUrl, '_blank', 'noopener')}>
              <img src={a.previewUrl} alt={a.file.name || 'Pending images'} />
            </button>
            <button type="button" className={css.remove} aria-label={`Remove image ${a.file.name}`} onClick={() => onRemove(a.id)}>
              <IconCloseFill14 size={12} />
            </button>
          </div>
        )} />
    </div>
  )
}
