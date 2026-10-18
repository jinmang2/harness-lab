/** Compact, read-only fields and lists for recorded tool results: DSH ui-tool ToolDetails (MIT), the parts lab uses. */
import { IconChevronRightOutline14 } from '../dsh/icons.tsx'
import css from '../dsh/css/ToolDetails.module.css'
import type { ToolDetailItem, ToolDetailsModel } from '../lib/turns.ts'

function DetailItem({ item }: { item: ToolDetailItem }) {
  return (
    <li className={css.item}>
      {item.title !== undefined && (
        <div className={css.heading}>
          <span className={css.text}>{item.title}</span>
          {item.badge !== undefined && <span className={css.badge} data-tone={item.badge.tone}>{item.badge.label}</span>}
        </div>
      )}
      {item.description !== undefined && <p className={css.description}>{item.description}</p>}
      {item.fields.length > 0 && (
        <dl className={css.fields}>
          {item.fields.map(field => (
            <div key={field.label} className={css.field}>
              <dt>{field.label}</dt>
              <dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {item.lines !== undefined && <ul className={css.lines}>{item.lines.map((line, index) => <li key={index}>{line}</li>)}</ul>}
      {item.code !== undefined && <pre className={css.code} style={{ font: 'var(--dsw-font-markdown-code-block)', whiteSpace: 'pre-wrap' }}>{item.code}</pre>}
      {item.groups?.map((group, index) => (
        <details key={index} className={css.group}>
          <summary><IconChevronRightOutline14 /><span>{group.label}</span></summary>
          <ul className={css.list}>
            {group.items.map((child, childIndex) => <DetailItem key={childIndex} item={child} />)}
          </ul>
        </details>
      ))}
    </li>
  )
}

export function ToolDetails({ model }: { model: ToolDetailsModel }) {
  return (
    <div className={css.root}>
      <ul className={css.list}>
        {model.items.map((item, index) => <DetailItem key={index} item={item} />)}
      </ul>
    </div>
  )
}
