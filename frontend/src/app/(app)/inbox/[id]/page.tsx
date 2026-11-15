import Link from 'next/link'

import { ActionButton } from '@/components/ActionButton'
import { MediaGrid } from '@/components/MediaGrid'
import { Badge, Empty, ExternalLink, PageHeader, Section, StatusBadge } from '@/components/ui'
import { formatDateTime, formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { ArticleSummary, Claim, EventDetail, Me, Media } from '@/lib/types'

export default async function EventPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const { t, locale } = await getT()
  const [ev, claims, articles, media, me] = await Promise.all([
    apiGet<EventDetail>(`/events/${id}`),
    apiGet<Claim[]>(`/events/${id}/claims`),
    apiGet<ArticleSummary[]>(`/events/${id}/articles`),
    apiGet<Media[]>(`/events/${id}/media`),
    apiGet<Me>('/auth/me'),
  ])
  const can = (p: string) => me.permissions.includes(p)
  return (
    <>
      <PageHeader
        back={{ href: '/inbox', label: t.nav.inbox }}
        title={ev.title}
        intro={`${formatNumber(ev.publisher_count, locale)} ${t.common.publishers} · ${t.inbox.firstSeen} ${formatDateTime(ev.first_seen_at, locale)}`}
        actions={
          <>
            <StatusBadge status={ev.status} t={t} />
            {can('discovery.run') && (
              <ActionButton
                path={`/events/${id}/research`}
                label={t.event.researchNow}
                doneMessage={t.event.researchQueued}
              />
            )}
            {can('articles.create') && ev.status === 'evidence_assessment' && (
              <ActionButton
                path={`/events/${id}/write`}
                label={t.event.write}
                className="btn-primary"
                doneMessage={t.event.writeQueued}
              />
            )}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Section title={t.event.claims}>
            <p className="-mt-2 mb-4 text-sm text-muted">{t.event.claimsIntro}</p>
            {claims.length === 0 ? (
              <Empty>{t.event.noClaims}</Empty>
            ) : (
              <ul className="space-y-4" data-testid="claims">
                {claims.map((c) => (
                  <li key={c.id} className="rounded-lg border border-line p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="max-w-2xl text-sm text-ink">{c.text}</p>
                      <StatusBadge status={c.status} t={t} />
                    </div>
                    {c.status_reason && (
                      <p className="mt-1 text-xs text-muted">{c.status_reason}</p>
                    )}
                    {c.editor_note && <p className="mt-1 text-xs text-ok">✓ {c.editor_note}</p>}
                    {c.evidence.length > 0 && (
                      <details className="mt-3">
                        <summary className="cursor-pointer text-xs font-medium text-muted">
                          {t.event.evidence} ({formatNumber(c.evidence.length, locale)})
                        </summary>
                        <ul className="mt-2 space-y-2">
                          {c.evidence.map((e) => (
                            <li key={e.id} className="border-l-2 border-line pl-3 text-xs">
                              <div className="flex flex-wrap items-center gap-2">
                                <ExternalLink href={e.url}>{e.publisher_domain}</ExternalLink>
                                <Badge tone={e.relationship === 'contradicts' ? 'bad' : 'neutral'}>
                                  {e.relationship === 'contradicts'
                                    ? t.event.contradicts
                                    : t.event.supports}
                                </Badge>
                              </div>
                              <blockquote className="mt-1 text-muted italic">
                                “{e.excerpt}”
                              </blockquote>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {can('evidence.review') && (
                      <div className="mt-3">
                        {c.status === 'editor_verified' ? (
                          <ActionButton
                            path={`/claims/${c.id}/review`}
                            body={{ verified: false }}
                            label={t.event.unverify}
                          />
                        ) : (
                          <ActionButton
                            path={`/claims/${c.id}/review`}
                            body={{ verified: true }}
                            ask={t.event.note}
                            askField="note"
                            label={t.event.verify}
                            doneMessage={t.event.reviewDone}
                          />
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title={t.event.photos}>
            <MediaGrid
              media={media}
              articles={articles}
              eventId={id}
              t={t}
              canManage={can('media.manage')}
            />
          </Section>
        </div>

        <div className="min-w-0 space-y-6">
          <Section title={t.event.drafts}>
            {articles.length === 0 ? (
              <Empty>{t.drafts.empty}</Empty>
            ) : (
              <ul className="space-y-3">
                {articles.map((a) => (
                  <li key={a.id}>
                    <Link
                      href={`/drafts/${a.id}`}
                      className="block rounded-lg border border-line p-3 hover:bg-paper"
                    >
                      <div className="text-xs text-muted">
                        {(t.drafts.angle as Record<string, string>)[a.angle] ?? a.angle}
                      </div>
                      <div className="mt-0.5 text-sm font-medium">{a.headline}</div>
                      <div className="mt-2">
                        <StatusBadge status={a.status} t={t} />
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title={t.event.reports}>
            <ul className="space-y-3 text-sm">
              {ev.items.map((it) => (
                <li key={it.id}>
                  <ExternalLink href={it.url}>{it.title}</ExternalLink>
                  <div className="text-xs text-muted">
                    {it.publisher_domain} ·{' '}
                    {formatDateTime(it.published_at ?? it.retrieved_at, locale)}
                  </div>
                </li>
              ))}
            </ul>
            {ev.keywords.length > 0 && (
              <p className="mt-4 text-xs text-muted">
                {t.event.keywords}: {ev.keywords.join(', ')}
              </p>
            )}
          </Section>
        </div>
      </div>
    </>
  )
}
