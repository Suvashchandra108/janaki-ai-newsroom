import Link from 'next/link'

import { fill, formatDateTime, type Locale } from '@/i18n'
import type { Dict } from '@/i18n/en'
import type { Notification } from '@/lib/types'

import { Empty } from './ui'

const DOT = { info: 'bg-info', warning: 'bg-warn', error: 'bg-bad' } as const

export function Activity({ notes, t, locale }: { notes: Notification[]; t: Dict; locale: Locale }) {
  if (notes.length === 0) return <Empty>{t.notify.empty}</Empty>
  return (
    <ol className="divide-y divide-line">
      {notes.map((n, i) => {
        const job = String(n.data.job_type ?? '')
        const jobLabel = (t.jobs.types as Record<string, string>)[job] ?? job
        const to = String(n.data.to ?? '')
        const title =
          n.kind === 'job_failed'
            ? fill(t.notify.job_failed, { job: jobLabel })
            : n.kind === 'draft_ready'
              ? n.severity === 'warning'
                ? t.notify.draft_ready_warn
                : t.notify.draft_ready
              : n.kind === 'website_status'
                ? fill(t.notify.website_status, {
                    to: (t.status as Record<string, string>)[to] ?? to,
                  })
                : t.notify[n.kind]
        const detail =
          n.kind === 'job_failed' || n.kind === 'delivery_failed'
            ? String(n.data.error ?? '')
            : n.kind === 'draft_ready'
              ? String(n.data.slug ?? '')
              : ''
        const href =
          n.target_type === 'article' && n.target_id
            ? `/drafts/${n.target_id}`
            : n.target_type === 'job'
              ? '/jobs?status=failed'
              : null
        const body = (
          <div className="flex items-start gap-3 py-2.5">
            <span
              aria-hidden
              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[n.severity]}`}
            />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-ink">{title}</div>
              {detail && <div className="truncate text-xs text-muted">{detail}</div>}
            </div>
            <time className="shrink-0 text-xs text-muted tabular-nums">
              {formatDateTime(n.at, locale)}
            </time>
          </div>
        )
        return (
          <li key={`${n.kind}-${n.target_id}-${i}`}>
            {href ? (
              <Link href={href} className="block rounded hover:bg-paper">
                {body}
              </Link>
            ) : (
              body
            )}
          </li>
        )
      })}
    </ol>
  )
}
