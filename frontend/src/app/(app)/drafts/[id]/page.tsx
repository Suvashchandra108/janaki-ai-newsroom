import Link from 'next/link'

import { ActionButton } from '@/components/ActionButton'
import { EditDraft } from '@/components/EditDraft'
import { LicenceLines, MediaPreview } from '@/components/MediaGrid'
import { Badge, PageHeader, Section, StatusBadge } from '@/components/ui'
import { formatDateTime, formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet, apiGetOptional } from '@/lib/api'
import type { Article, ArticleSummary, Claim, Delivery, Me, Media, Version } from '@/lib/types'

export default async function ReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<Record<string, string | undefined>>
}) {
  const { id } = await params
  const sp = await searchParams
  const { t, locale } = await getT()
  const r = t.review
  const art = await apiGet<Article>(`/articles/${id}`)
  const wanted = Number(sp.v)
  const viewing: Version =
    wanted && wanted !== art.current_version && art.versions.includes(wanted)
      ? await apiGet<Version>(`/articles/${id}/versions/${wanted}`)
      : art.current
  const isCurrent = viewing.version === art.current_version
  const [claims, siblings, media, delivery, me] = await Promise.all([
    apiGet<Claim[]>(`/events/${art.event_id}/claims`),
    apiGet<ArticleSummary[]>(`/events/${art.event_id}/articles`),
    apiGet<Media[]>(`/events/${art.event_id}/media`),
    apiGetOptional<Delivery>(`/articles/${id}/delivery`),
    apiGet<Me>('/auth/me'),
  ])
  const can = (p: string) => me.permissions.includes(p)
  const refOf = new Map(claims.map((c, i) => [c.id, `C${i + 1}`]))
  const cited = new Set(viewing.paragraphs.flatMap((p) => p.claim_ids))
  const usedClaims = claims.filter((c) => cited.has(c.id))
  const photo = media.find(
    (m) => m.article_id === id && m.status === 'selected' && m.role === 'hero',
  )
  const other = siblings.filter((s) => s.id !== id)
  const warnings = viewing.flags.filter((f) => f.severity === 'warning')
  const infos = viewing.flags.filter((f) => f.severity !== 'warning')
  const editable =
    isCurrent && can('articles.edit') && !['rejected', 'delivered'].includes(art.status)
  const angle = (t.drafts.angle as Record<string, string>)[art.angle] ?? art.angle

  return (
    <>
      <PageHeader
        back={{ href: '/drafts', label: t.nav.drafts }}
        title={angle}
        intro={`${r.viewVersion} ${formatNumber(viewing.version, locale)}${isCurrent ? ` (${r.current})` : ''} · ${formatDateTime(viewing.created_at, locale)}`}
        actions={<StatusBadge status={art.status} t={t} />}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <div role="tablist" aria-label={r.language} className="flex gap-1 border-b border-line">
            <span
              role="tab"
              aria-selected="true"
              className="border-b-2 border-brand px-4 py-2 text-sm font-semibold"
            >
              {r.english}
            </span>
            <span
              role="tab"
              aria-selected="false"
              aria-disabled="true"
              title={r.nepaliLater}
              className="cursor-not-allowed px-4 py-2 text-sm text-muted"
            >
              {r.nepali} · {r.nepaliLater}
            </span>
          </div>

          {art.status === 'rejected' && art.rejection_reason && (
            <div role="status" className="rounded-lg bg-bad-bg px-4 py-3 text-sm text-bad">
              <strong>{r.rejectedBecause}:</strong> {art.rejection_reason}
            </div>
          )}

          <Section title={r.flags}>
            {warnings.length === 0 && infos.length === 0 ? (
              <p className="text-sm text-ok">{r.noFlags}</p>
            ) : (
              <ul className="space-y-2 text-sm" data-testid="flags">
                {[...warnings, ...infos].map((f, i) => (
                  <li
                    key={i}
                    className={`rounded-lg px-3 py-2 ${f.severity === 'warning' ? 'bg-warn-bg text-warn' : 'bg-info-bg text-info'}`}
                  >
                    <span className="font-mono text-xs">{f.code}</span>
                    {f.paragraph !== undefined && f.paragraph !== null && (
                      <span className="text-xs">
                        {' '}
                        · {r.paragraph} {formatNumber(Number(f.paragraph) + 1, locale)}
                      </span>
                    )}
                    <div>{f.message}</div>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {editable ? (
            <EditDraft article={art} t={t} refs={Object.fromEntries(refOf)}>
              <ArticleView v={viewing} refOf={refOf} t={t} />
            </EditDraft>
          ) : (
            <section className="card p-6">
              <ArticleView v={viewing} refOf={refOf} t={t} />
            </section>
          )}

          <Section title={r.citations}>
            <ol className="space-y-3 text-sm">
              {usedClaims.map((c) => (
                <li key={c.id} id={`claim-${refOf.get(c.id)}`} className="flex gap-3">
                  <span className="font-mono text-xs text-muted">{refOf.get(c.id)}</span>
                  <div className="flex-1">
                    <div>{c.text}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <StatusBadge status={c.status} t={t} />
                      {c.evidence
                        .filter((e) => e.relationship === 'supports')
                        .slice(0, 4)
                        .map((e) => (
                          <a
                            key={e.id}
                            href={/^https?:\/\//.test(e.url) ? e.url : undefined}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            className="underline-offset-2 hover:underline"
                          >
                            {e.publisher_domain}
                          </a>
                        ))}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-xs text-muted">
              {r.attribution}: {viewing.attribution}
            </p>
          </Section>
        </div>

        <div className="min-w-0 space-y-6">
          <Section title={r.actions}>
            <div className="flex flex-col gap-3">
              <p className="rounded-lg bg-paper p-3 text-xs text-muted">{r.approveNote}</p>
              <div>
                <div className="eyebrow mb-1">{r.website}</div>
                {delivery ? (
                  <div className="space-y-1 text-sm" data-testid="delivery">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge
                        status={
                          delivery.status === 'delivered'
                            ? (delivery.remote_status ?? 'delivered')
                            : delivery.status
                        }
                        t={t}
                      />
                      {delivery.remote_id && (
                        <span className="text-xs text-muted">
                          {r.sentAs} #{delivery.remote_id}
                        </span>
                      )}
                    </div>
                    {delivery.last_error && (
                      <p className="text-xs text-bad">{delivery.last_error}</p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-muted">{r.notSent}</p>
                )}
              </div>
              {can('articles.edit') &&
                ['draft', 'needs_review'].includes(art.status) &&
                delivery?.status !== 'delivered' && (
                  <ActionButton
                    path={`/articles/${id}/deliver`}
                    label={delivery ? r.retry : r.send}
                    busyLabel={r.sending}
                    className="btn-primary w-full"
                  />
                )}
              {editable && (
                <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                  <ActionButton
                    path={`/articles/${id}/regenerate`}
                    label={r.regenerate}
                    busyLabel={t.common.loading}
                  />
                  {can('articles.reject') && (
                    <ActionButton
                      path={`/articles/${id}/reject`}
                      ask={r.rejectReason}
                      askField="reason"
                      label={r.reject}
                      className="btn-danger"
                    />
                  )}
                </div>
              )}
            </div>
          </Section>

          <Section title={r.image}>
            {photo ? (
              <div className="space-y-2">
                <div className="overflow-hidden rounded-lg border border-line">
                  <MediaPreview m={photo} />
                </div>
                {photo.ai_generated && <Badge tone="warn">{r.aiLabel}</Badge>}
                {photo.caption && <p className="text-sm">{photo.caption}</p>}
                <LicenceLines m={photo} t={t} />
              </div>
            ) : (
              <p className="text-sm text-muted">
                {r.noImage}{' '}
                <Link href={`/inbox/${art.event_id}`} className="text-info hover:underline">
                  {t.event.photos} →
                </Link>
              </p>
            )}
          </Section>

          <Section title={r.seo}>
            <dl className="space-y-3 text-sm">
              <Field label={r.seoTitle} value={viewing.seo_title} max={70} />
              <Field label={r.seoDescription} value={viewing.seo_description} max={170} />
              <div>
                <dt className="text-xs text-muted">{r.keywords}</dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {viewing.keywords.map((k) => (
                    <Badge key={k}>{k}</Badge>
                  ))}
                </dd>
              </div>
              {Object.entries(viewing.social ?? {}).map(([k, v]) => (
                <Field key={k} label={`${r.social} · ${k}`} value={v} />
              ))}
              {viewing.category && <Field label={r.category} value={viewing.category} />}
              {viewing.location && <Field label={r.location} value={viewing.location} />}
            </dl>
          </Section>

          {other.length > 0 && (
            <Section title={r.angleOther}>
              {other.map((o) => (
                <Link
                  key={o.id}
                  href={`/drafts/${o.id}`}
                  className="block rounded-lg border border-line p-3 hover:bg-paper"
                >
                  <div className="text-xs text-muted">
                    {(t.drafts.angle as Record<string, string>)[o.angle] ?? o.angle}
                  </div>
                  <div className="mt-0.5 text-sm font-medium">{o.headline}</div>
                </Link>
              ))}
            </Section>
          )}

          <Section title={r.history}>
            <ol className="space-y-1 text-sm" data-testid="history">
              {[...art.versions].reverse().map((v) => (
                <li key={v}>
                  <Link
                    href={v === art.current_version ? `/drafts/${id}` : `/drafts/${id}?v=${v}`}
                    aria-current={v === viewing.version ? 'true' : undefined}
                    className={`flex justify-between rounded px-2 py-1 ${v === viewing.version ? 'bg-paper font-medium' : 'hover:bg-paper'}`}
                  >
                    <span>
                      {r.viewVersion} {formatNumber(v, locale)}
                    </span>
                    {v === art.current_version && (
                      <span className="text-xs text-muted">{r.current}</span>
                    )}
                  </Link>
                </li>
              ))}
            </ol>
            <p className="mt-3 text-xs text-muted">
              {r.by[viewing.created_by_kind as 'ai' | 'user'] ?? viewing.created_by_kind}
              {viewing.model ? ` · ${viewing.model}` : ''}
              {viewing.note ? ` · ${viewing.note}` : ''}
            </p>
          </Section>
        </div>
      </div>
    </>
  )
}

function ArticleView({
  v,
  refOf,
  t,
}: {
  v: Version
  refOf: Map<string, string>
  t: Awaited<ReturnType<typeof getT>>['t']
}) {
  return (
    <article lang="en" data-testid="article">
      <h2 className="font-serif text-3xl leading-tight font-semibold text-ink">{v.headline}</h2>
      {v.alt_headline && (
        <p className="mt-2 text-sm text-muted">
          {t.review.altHeadline}: {v.alt_headline}
        </p>
      )}
      <p className="mt-4 font-serif text-lg leading-relaxed text-ink/85">{v.summary}</p>
      <div className="mt-6 space-y-4 font-serif text-[17px] leading-relaxed">
        {v.paragraphs.map((p, i) => (
          <p key={i}>
            {p.text}{' '}
            {p.claim_ids.map((c) => {
              const ref = refOf.get(c)
              return ref ? (
                <a
                  key={c}
                  href={`#claim-${ref}`}
                  className="ml-0.5 rounded bg-info-bg px-1 font-sans text-[11px] font-semibold text-info no-underline"
                >
                  {ref}
                </a>
              ) : null
            })}
          </p>
        ))}
      </div>
      {v.image_caption && <p className="mt-6 text-xs text-muted">📷 {v.image_caption}</p>}
    </article>
  )
}

function Field({ label, value, max }: { label: string; value: string; max?: number }) {
  return (
    <div>
      <dt className="flex justify-between text-xs text-muted">
        <span>{label}</span>
        {max && (
          <span className={value.length > max ? 'text-bad' : ''}>
            {value.length}/{max}
          </span>
        )}
      </dt>
      <dd className="mt-0.5">{value}</dd>
    </div>
  )
}
