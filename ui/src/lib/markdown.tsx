import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useMemo } from 'react'
import css from '../dsh/css/MarkdownText.module.css'

marked.setOptions({ gfm: true, breaks: false })

// Model output is untrusted (prompt injection): no forms, and no remote images that would
// send a request the moment the answer renders. Links open in a new tab.
DOMPurify.addHook('afterSanitizeAttributes', node => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
  if (node.tagName === 'IMG') {
    const src = node.getAttribute('src') ?? ''
    if (!src.startsWith('data:')) {
      const alt = document.createElement('span')
      alt.textContent = `[image: ${node.getAttribute('alt') || src}]`
      node.replaceWith(alt)
    }
  }
})

const OPTIONS = { FORBID_TAGS: ['form', 'input', 'button', 'textarea', 'select', 'iframe', 'style'], FORBID_ATTR: ['style'] }

/** Assistant markdown, sanitized. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false }) as string, OPTIONS), [text])
  return <div className={[css.markdown, className].filter(Boolean).join(' ')} dangerouslySetInnerHTML={{ __html: html }} />
}
