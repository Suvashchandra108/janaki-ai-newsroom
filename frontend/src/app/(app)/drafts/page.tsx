import Link from 'next/link'

import { Badge, Empty, PageHeader, StatusBadge } from '@/components/ui'
import { formatDateTime, formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { ArticleSummary } from '@/lib/types'

const TABS = ['awaiting', 'needs_review', 'delivered', 'rejected', 'all'] as const
type Tab = (typeof TABS)[number]

export default async function DraftsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>
}) {
  const { t, locale } = await getT()
  const sp = await searchParams
  const tab: Tab = TABS.includes(sp.status as Tab) ? (sp.status as Tab) : 'awaiting'
  let rows: ArticleSummary[]
  if (tab === 'awaiting') {
    const [a, b] = await Promise.all([
      apiGet<ArticleSummary[]>('/articles?status=needs_review&limit=200'),
      apiGet<ArticleSummary[]>('/articles?status=draft&limit=200'),
    ])
    rows = [...a, ...b]
  } else {
    rows = await apiGet<ArticleSummary[]>(
      `/articles?limit=200${tab === 'all' ? '' : `&status=${tab}`}`,
    )
  }
  return (
    <>
      <PageHeader title={t.drafts.title} intro={t.drafts.intro} />
      <nav className="mb-4 flex flex-wrap gap-2 text-sm" aria-label={t.drafts.title}>
        {TABS.map((k) => (
          <Link
            key={k}
            href={`/drafts?status=${k}`}
            aria-current={tab === k ? 'page' : undefined}
            className={`rounded-full border px-3 py-1 ${tab === k ? 'border-brand bg-brand text-brand-ink' : 'border-line bg-surface hover:bg-paper'}`}
          >
            {t.drafts.tabs[k]}
          </Link>
        ))}
      </nav>
      {rows.length === 0 ? (
        <Empty>{t.drafts.empty}</Empty>
      ) : (
        <ul className="card divide-y divide-line" data-testid="draft-list">
          {rows.map((a) => (
            <li key={a.id}>
              <Link
                href={`/drafts/${a.id}`}
                className="flex flex-col gap-2 px-4 py-3 hover:bg-paper sm:flex-row sm:items-center sm:gap-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-serif text-[17px] leading-snug text-ink">{a.headline}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                    <span>{(t.drafts.angle as Record<string, string>)[a.angle] ?? a.angle}</span>
                    <span>·</span>
                    <span>{a.language === 'ne' ? t.review.nepali : t.review.english}</span>
                    {a.flag_count > 0 && (
                      <Badge tone="warn">
                        {formatNumber(a.flag_count, locale)} {t.drafts.warnings}
                      </Badge>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={a.status} t={t} />
                  <time className="w-28 text-right text-xs text-muted tabular-nums">
                    {formatDateTime(a.updated_at, locale)}
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
