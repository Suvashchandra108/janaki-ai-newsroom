import { PageHeader, Section, Stat } from '@/components/ui'
import { formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'

type Usage = {
  days: number
  ai_calls: number
  input_tokens: number
  output_tokens: number
  by_kind: Record<string, number>
}

export default async function UsagePage() {
  const { t, locale } = await getT()
  const u = await apiGet<Usage>('/usage/ai?days=30')
  const n = (x: number) => formatNumber(x, locale)
  return (
    <>
      <PageHeader title={t.usage.title} intro={`${t.usage.intro} ${t.usage.days}.`} />
      <div className="grid gap-3 sm:grid-cols-3" data-testid="usage">
        <Stat label={t.usage.calls} value={n(u.ai_calls)} />
        <Stat label={t.usage.input} value={n(u.input_tokens)} />
        <Stat label={t.usage.output} value={n(u.output_tokens)} />
      </div>
      <Section title={t.usage.byKind} className="mt-6">
        <ul className="divide-y divide-line text-sm">
          {Object.entries(u.by_kind).map(([k, v]) => (
            <li key={k} className="flex justify-between py-2">
              <span>{(t.usage.kinds as Record<string, string>)[k] ?? k}</span>
              <span className="tabular-nums">{n(v)}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-muted">{t.dashboard.costUnknown}</p>
        <p className="mt-1 text-xs text-muted">{t.usage.billingLater}</p>
      </Section>
    </>
  )
}
