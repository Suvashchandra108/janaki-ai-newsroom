import { ActionButton } from '@/components/ActionButton'
import { Badge, ExternalLink, PageHeader } from '@/components/ui'
import { formatDateTime } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { Me, Source } from '@/lib/types'

export default async function SourcesPage() {
  const { t, locale } = await getT()
  const [sources, me] = await Promise.all([
    apiGet<Source[]>('/sources?limit=200'),
    apiGet<Me>('/auth/me'),
  ])
  const canManage = me.permissions.includes('sources.manage')
  return (
    <>
      <PageHeader title={t.sources.title} intro={t.sources.intro} />
      <ul className="grid gap-3 md:grid-cols-2" data-testid="sources">
        {sources.map((s) => (
          <li key={s.id} className="card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium">{s.name}</div>
                <div className="truncate text-xs text-muted">{s.allowed_domains.join(', ')}</div>
              </div>
              <Badge tone={s.is_enabled ? 'ok' : 'neutral'}>
                {s.is_enabled ? t.sources.enabled : t.sources.disabled}
              </Badge>
            </div>
            <dl className="mt-3 space-y-1 text-xs text-muted">
              {s.feed_url && (
                <div className="truncate">
                  {t.sources.feed}: <ExternalLink href={s.feed_url}>{s.feed_url}</ExternalLink>
                </div>
              )}
              {s.credibility && (
                <div>
                  {t.sources.credibility}: {s.credibility}
                </div>
              )}
              <div>
                {t.sources.lastFetched}:{' '}
                {s.last_fetched_at ? formatDateTime(s.last_fetched_at, locale) : t.common.never}
              </div>
              {s.last_error && (
                <div className="text-bad">
                  {t.sources.lastError}: {s.last_error}
                </div>
              )}
            </dl>
            {canManage && (
              <div className="mt-3">
                <ActionButton
                  method="PATCH"
                  path={`/sources/${s.id}`}
                  body={{ is_enabled: !s.is_enabled }}
                  label={s.is_enabled ? t.sources.turnOff : t.sources.turnOn}
                />
              </div>
            )}
          </li>
        ))}
      </ul>
    </>
  )
}
