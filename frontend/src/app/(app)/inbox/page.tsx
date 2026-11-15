import Link from 'next/link'

import { Empty, PageHeader, StatusBadge } from '@/components/ui'
import { formatDateTime, formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { NewsEvent } from '@/lib/types'

const FILTERS = ['', 'discovered', 'researching', 'evidence_assessment', 'draft', 'failed'] as const

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>
}) {
  const { t, locale } = await getT()
  const sp = await searchParams
  const status = FILTERS.includes((sp.status ?? '') as (typeof FILTERS)[number])
    ? (sp.status ?? '')
    : ''
  const minPub = Math.max(1, Math.min(9, Number(sp.min ?? 1) || 1))
  const q = new URLSearchParams({ limit: '100', min_publishers: String(minPub) })
  if (status) q.set('status', status)
  const events = await apiGet<NewsEvent[]>(`/events?${q}`)
  const link = (patch: Record<string, string>) => {
    const p = new URLSearchParams({ ...(status ? { status } : {}), min: String(minPub), ...patch })
    for (const [k, v] of [...p]) if (!v) p.delete(k)
    return `/inbox?${p}`
  }
  return (
    <>
      <PageHeader title={t.inbox.title} intro={t.inbox.intro} />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">{t.inbox.filter}:</span>
        {FILTERS.map((f) => (
          <Link
            key={f || 'all'}
            href={link({ status: f })}
            className={`rounded-full border px-3 py-1 ${status === f ? 'border-brand bg-brand text-brand-ink' : 'border-line bg-surface hover:bg-paper'}`}
          >
            {f ? (t.status as Record<string, string>)[f] : t.common.all}
          </Link>
        ))}
        <span className="ml-auto text-muted">{t.inbox.minPublishers}</span>
        {[1, 2, 3].map((m) => (
          <Link
            key={m}
            href={link({ min: String(m) })}
            className={`rounded-full border px-2.5 py-1 ${minPub === m ? 'border-brand bg-brand text-brand-ink' : 'border-line bg-surface'}`}
          >
            {formatNumber(m, locale)}
          </Link>
        ))}
      </div>
      {events.length === 0 ? (
        <Empty>{t.inbox.empty}</Empty>
      ) : (
        <ul className="card divide-y divide-line" data-testid="event-list">
          {events.map((e) => (
            <li key={e.id}>
              <Link
                href={`/inbox/${e.id}`}
                className="flex flex-col gap-1 px-4 py-3 hover:bg-paper sm:flex-row sm:items-center sm:gap-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-ink">{e.title}</div>
                  <div className="mt-0.5 text-xs text-muted">
                    {formatNumber(e.publisher_count, locale)} {t.common.publishers} ·{' '}
                    {formatNumber(e.item_count, locale)} {t.common.items}
                    {e.region ? ` · ${e.region}` : ''}
                    {e.category ? ` · ${e.category}` : ''}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={e.status} t={t} />
                  <time className="w-28 text-right text-xs text-muted tabular-nums">
                    {formatDateTime(e.last_seen_at, locale)}
                  </time>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
