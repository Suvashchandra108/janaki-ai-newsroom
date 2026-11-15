import Link from 'next/link'

import { ActionButton } from '@/components/ActionButton'
import { Empty, PageHeader, StatusBadge } from '@/components/ui'
import { formatDateTime, formatNumber } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { Job, Me, Summary } from '@/lib/types'

const TYPES = ['', 'discovery', 'research', 'writing'] as const

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>
}) {
  const { t, locale } = await getT()
  const sp = await searchParams
  const failed = sp.status === 'failed'
  const type = TYPES.includes((sp.type ?? '') as (typeof TYPES)[number]) ? (sp.type ?? '') : ''
  const q = new URLSearchParams({ limit: '100' })
  if (failed) q.set('status', 'failed')
  if (type) q.set('job_type', type)
  const [jobs, me, s] = await Promise.all([
    apiGet<Job[]>(`/discovery/jobs?${q}`),
    apiGet<Me>('/auth/me'),
    apiGet<Summary>('/dashboard/summary'),
  ])
  const canRun = me.permissions.includes('discovery.run')
  const link = (patch: Record<string, string>) => {
    const p = new URLSearchParams({
      ...(failed ? { status: 'failed' } : {}),
      ...(type ? { type } : {}),
      ...patch,
    })
    for (const [k, v] of [...p]) if (!v) p.delete(k)
    return `/jobs?${p}`
  }
  return (
    <>
      <PageHeader
        title={t.jobs.title}
        intro={t.jobs.intro}
        actions={
          canRun && (
            <>
              {!s.discovery.paused && (
                <ActionButton
                  path="/discovery/run"
                  label={t.jobs.runNow}
                  className="btn-primary"
                  doneMessage={t.jobs.queued}
                />
              )}
              {s.discovery.paused ? (
                <ActionButton path="/discovery/resume" label={t.jobs.resume} />
              ) : (
                <ActionButton path="/discovery/pause" label={t.jobs.pause} />
              )}
            </>
          )
        }
      />
      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        {TYPES.map((k) => (
          <Link
            key={k || 'all'}
            href={link({ type: k })}
            className={`rounded-full border px-3 py-1 ${type === k ? 'border-brand bg-brand text-brand-ink' : 'border-line bg-surface'}`}
          >
            {k ? t.jobs.types[k] : t.common.all}
          </Link>
        ))}
        <Link
          href={link({ status: failed ? '' : 'failed' })}
          className={`ml-auto rounded-full border px-3 py-1 ${failed ? 'border-bad bg-bad text-white' : 'border-line bg-surface'}`}
        >
          {t.jobs.onlyFailed}
        </Link>
      </div>
      {jobs.length === 0 ? (
        <Empty>{t.jobs.empty}</Empty>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[42rem] text-sm" data-testid="jobs">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">{t.jobs.type}</th>
                <th className="px-4 py-2 font-medium">{t.common.status}</th>
                <th className="px-4 py-2 font-medium">{t.jobs.started}</th>
                <th className="px-4 py-2 font-medium">{t.jobs.trigger}</th>
                <th className="px-4 py-2 font-medium">{t.jobs.attempts}</th>
                <th className="px-4 py-2 font-medium">{t.jobs.error}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {jobs.map((j) => (
                <tr key={j.id} className={j.status === 'failed' ? 'bg-bad-bg/40' : ''}>
                  <td className="px-4 py-2">
                    {(t.jobs.types as Record<string, string>)[j.job_type] ?? j.job_type}
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={j.status} t={t} />
                  </td>
                  <td className="px-4 py-2 text-muted tabular-nums">
                    {formatDateTime(j.started_at ?? j.created_at, locale)}
                  </td>
                  <td className="px-4 py-2 text-muted">{j.trigger}</td>
                  <td className="px-4 py-2 tabular-nums">{formatNumber(j.attempts, locale)}</td>
                  <td className="max-w-md px-4 py-2 text-xs text-bad">{j.error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
