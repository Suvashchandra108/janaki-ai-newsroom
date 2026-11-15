import type { Dict } from '@/i18n/en'
import type { ArticleSummary, Media } from '@/lib/types'

import { ActionButton } from './ActionButton'
import { Badge, Empty, ExternalLink } from './ui'

/** Photo candidates with their licence. Images load through the BFF (own organisation only). */
export function MediaGrid({
  media,
  articles,
  eventId,
  t,
  canManage,
}: {
  media: Media[]
  articles: ArticleSummary[]
  eventId: string
  t: Dict
  canManage: boolean
}) {
  const visible = media.filter((m) => m.status !== 'rejected')
  return (
    <div>
      {canManage && (
        <div className="mb-4">
          <ActionButton path={`/events/${eventId}/media/search`} label={t.event.findPhotos} />
        </div>
      )}
      {visible.length === 0 ? (
        <Empty>{t.media.none}</Empty>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2" data-testid="media">
          {visible.map((m) => (
            <li key={m.id} className="overflow-hidden rounded-lg border border-line">
              <MediaPreview m={m} />
              <div className="space-y-2 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  {m.status === 'selected' && <Badge tone="ok">{t.media.selected}</Badge>}
                  {m.publishable ? (
                    <Badge tone="info">{t.media.publishable}</Badge>
                  ) : (
                    <Badge tone="bad">{t.media.notPublishable}</Badge>
                  )}
                  {m.ai_generated && <Badge tone="warn">{t.review.aiLabel}</Badge>}
                </div>
                <div className="font-medium">{m.title}</div>
                <LicenceLines m={m} t={t} />
                {canManage && m.publishable && m.status !== 'selected' && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {articles
                      .filter((a) => a.status !== 'rejected')
                      .map((a) => (
                        <ActionButton
                          key={a.id}
                          path={`/media/${m.id}/select`}
                          body={{ article_id: a.id, role: 'hero' }}
                          label={`${t.media.select} — ${(t.drafts.angle as Record<string, string>)[a.angle] ?? a.angle}`}
                          className="btn-primary"
                        />
                      ))}
                    <ActionButton path={`/media/${m.id}/reject`} label={t.media.reject} />
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function MediaPreview({ m }: { m: Media }) {
  const small =
    [...m.derivatives].sort((a, b) => a.width - b.width).find((d) => d.width >= 400) ??
    m.derivatives[0]
  if (!small)
    return (
      <div
        className="flex aspect-video items-center justify-center bg-paper text-3xl text-muted"
        aria-hidden
      >
        🖼
      </div>
    )
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/bff/media/${m.id}/files/${small.name}`}
      alt={m.caption ?? m.title}
      className="aspect-video w-full bg-paper object-cover"
      loading="lazy"
    />
  )
}

export function LicenceLines({ m, t }: { m: Media; t: Dict }) {
  return (
    <dl className="space-y-1 text-xs text-muted">
      <div>
        <dt className="inline font-medium text-ink">{t.review.licence}: </dt>
        <dd className="inline">
          {m.licence_url ? (
            <ExternalLink href={m.licence_url}>{m.licence_name ?? m.licence_url}</ExternalLink>
          ) : (
            (m.licence_name ?? t.common.unknown)
          )}
        </dd>
      </div>
      {(m.attribution_text || m.creator) && (
        <div>
          <dt className="inline font-medium text-ink">{t.review.credit}: </dt>
          <dd className="inline">{m.attribution_text ?? m.creator}</dd>
        </div>
      )}
      {m.restrictions.length > 0 && (
        <div>
          <dt className="inline font-medium text-ink">{t.review.restrictions}: </dt>
          <dd className="inline">{m.restrictions.join(', ')}</dd>
        </div>
      )}
      {!m.publishable && m.licence_notes && <div className="text-bad">{m.licence_notes}</div>}
      {m.source_page_url && (
        <div>
          <ExternalLink href={m.source_page_url}>{t.common.source} ↗</ExternalLink>
        </div>
      )}
    </dl>
  )
}
