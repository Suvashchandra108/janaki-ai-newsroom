import Link from 'next/link'

import { Activity } from '@/components/Activity'
import { Meter, PageHeader, Section, Stat } from '@/components/ui'
import { formatDateTime, formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { Notification, Summary } from '@/lib/types'

export default async function DashboardPage() {
  const { t, locale } = await getT()
  const [s, notes] = await Promise.all([
    apiGet<Summary>('/dashboard/summary'),
    apiGet<Notification[]>('/dashboard/notifications?limit=12'),
  ])
  const n = (x: number) => formatNumber(x, locale)
  const d = t.dashboard
  const failures = s.failures.jobs_24h + s.failures.deliveries

  return (
    <>
      <PageHeader
        title={d.title}
        intro={`${d.asOf} ${formatDateTime(s.as_of, locale)}`}
        actions={
          <Link href="/drafts" className="btn-primary">
            {d.reviewNow} ({n(s.articles.awaiting_review)})
          </Link>
        }
      />

      <div data-testid="stats-articles" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat
          label={d.awaiting}
          value={n(s.articles.awaiting_review)}
          hint={
            s.articles.needs_review ? `${n(s.articles.needs_review)} ${d.needsReview}` : undefined
          }
          tone={s.articles.needs_review ? 'warn' : undefined}
          href="/drafts"
        />
        <Stat
          label={d.draftsToday}
          value={n(s.articles.generated_today)}
          href="/drafts?status=all"
        />
        <Stat
          label={d.sent}
          value={n(s.articles.sent_to_website)}
          href="/drafts?status=delivered"
        />
        <Stat
          label={d.published}
          value={n(s.articles.published)}
          tone={s.articles.published ? 'ok' : undefined}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          <Section title={d.pipeline}>
            <div data-testid="stats-pipeline" className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label={d.discoveredToday} value={n(s.discovery.items_today)} href="/inbox" />
              <Stat label={d.eventsToday} value={n(s.discovery.events_today)} href="/inbox" />
              <Stat
                label={d.underResearch}
                value={n(s.pipeline.researching)}
                href="/inbox?status=researching"
              />
              <Stat
                label={d.verified}
                value={n(s.pipeline.verified_candidates)}
                href="/inbox?status=evidence_assessment"
              />
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted">{d.quota}</span>
                  <span className="font-medium tabular-nums">
                    {n(s.discovery.quota_remaining)} / {n(s.discovery.daily_item_quota)}
                  </span>
                </div>
                <Meter used={s.discovery.items_today} total={s.discovery.daily_item_quota} />
              </div>
              <div>
                <div className="flex justify-between text-sm">
                  <span className="text-muted">{d.researchQuota}</span>
                  <span className="font-medium tabular-nums">
                    {n(s.pipeline.research_remaining)} / {n(s.pipeline.research_cap)}
                  </span>
                </div>
                <Meter
                  used={s.pipeline.research_cap - s.pipeline.research_remaining}
                  total={s.pipeline.research_cap}
                />
              </div>
            </div>
            <p className="mt-4 text-sm text-muted">
              {s.discovery.paused ? (
                <span className="font-medium text-warn">{d.paused}</span>
              ) : (
                <>
                  {d.nextRun}:{' '}
                  <span className="font-medium text-ink">
                    {formatDateTime(s.discovery.next_scheduled_run, locale)}
                  </span>
                </>
              )}
            </p>
          </Section>

          <Section title={d.recent} className="scroll-mt-20" aside={<span id="activity" />}>
            <Activity notes={notes} t={t} locale={locale} />
          </Section>
        </div>

        <div className="min-w-0 space-y-6">
          <Section title={d.attention}>
            {failures === 0 ? (
              <p className="text-sm text-ok">{d.allClear}</p>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <Stat
                  label={d.failedJobs}
                  value={n(s.failures.jobs_24h)}
                  tone={s.failures.jobs_24h ? 'bad' : undefined}
                  href="/jobs?status=failed"
                />
                <Stat
                  label={d.failedDeliveries}
                  value={n(s.failures.deliveries)}
                  tone={s.failures.deliveries ? 'bad' : undefined}
                  href="/drafts?status=all"
                />
              </div>
            )}
          </Section>

          <Section title={d.cms}>
            <p className="text-sm">
              <span className={s.cms.connected ? 'font-medium text-ok' : 'font-medium text-muted'}>
                {s.cms.connected ? d.cmsConnected : d.cmsNotConnected}
              </span>
              {s.cms.connected && (
                <span className="text-muted"> · {s.cms.auto_deliver ? d.autoOn : d.autoOff}</span>
              )}
            </p>
            {s.cms.base_url && <p className="mt-1 truncate text-xs text-muted">{s.cms.base_url}</p>}
            {s.cms.last_error && <p className="mt-2 text-xs text-bad">{s.cms.last_error}</p>}
          </Section>

          <Section title={d.aiUsage}>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted">{d.aiUsage}</dt>
                <dd className="tabular-nums">
                  {n(s.usage.ai_calls_today)} {d.aiCalls} ·{' '}
                  {n(s.usage.ai_input_tokens_today + s.usage.ai_output_tokens_today)} {d.tokens}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">{d.month}</dt>
                <dd className="tabular-nums">
                  {n(s.usage.ai_calls_month)} {d.aiCalls} · {n(s.usage.ai_tokens_month)} {d.tokens}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">{d.search}</dt>
                <dd>{s.usage.search_provider ?? d.searchNone}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">{d.images}</dt>
                <dd className="tabular-nums">{n(s.usage.images_selected_month)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">{d.illustrations}</dt>
                <dd className="tabular-nums">
                  {n(s.usage.illustrations_today)} / {n(s.usage.illustrations_limit)}
                </dd>
              </div>
            </dl>
            {!s.usage.ai_cost_known && <p className="mt-3 text-xs text-muted">{d.costUnknown}</p>}
          </Section>
        </div>
      </div>
    </>
  )
}
