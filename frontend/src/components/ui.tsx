import Link from 'next/link'

import type { Dict } from '@/i18n/en'

type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'neutral'
const TONE: Record<Tone, string> = {
  ok: 'bg-ok-bg text-ok',
  warn: 'bg-warn-bg text-warn',
  bad: 'bg-bad-bg text-bad',
  info: 'bg-info-bg text-info',
  neutral: 'bg-paper text-muted border border-line',
}

const STATUS_TONE: Record<string, Tone> = {
  succeeded: 'ok',
  corroborated: 'ok',
  editor_verified: 'ok',
  published: 'ok',
  delivered: 'info',
  draft: 'info',
  evidence_assessment: 'info',
  running: 'info',
  researching: 'info',
  generating: 'info',
  queued: 'neutral',
  discovered: 'neutral',
  unreviewed: 'neutral',
  pending: 'neutral',
  skipped: 'neutral',
  archived: 'neutral',
  needs_review: 'warn',
  insufficient: 'warn',
  partial: 'warn',
  inReview: 'warn',
  approved: 'info',
  scheduled: 'info',
  conflicting: 'bad',
  failed: 'bad',
  rejected: 'bad',
  removed: 'bad',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONE[tone]}`}
    >
      {children}
    </span>
  )
}

export function StatusBadge({ status, t }: { status: string; t: Dict }) {
  const label = (t.status as Record<string, string>)[status] ?? status
  return <Badge tone={STATUS_TONE[status] ?? 'neutral'}>{label}</Badge>
}

export function PageHeader({
  title,
  intro,
  actions,
  back,
}: {
  title: string
  intro?: string
  actions?: React.ReactNode
  back?: { href: string; label: string }
}) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back && (
          <Link href={back.href} className="mb-2 inline-block text-sm text-muted hover:text-ink">
            ← {back.label}
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {intro && <p className="mt-1 max-w-3xl text-sm text-muted">{intro}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

export function Section({
  title,
  children,
  aside,
  className = '',
}: {
  title?: string
  children: React.ReactNode
  aside?: React.ReactNode
  className?: string
}) {
  return (
    <section className={`card p-5 ${className}`}>
      {(title || aside) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  hint,
  tone,
  href,
}: {
  label: string
  value: string
  hint?: React.ReactNode
  tone?: 'bad' | 'warn' | 'ok'
  href?: string
}) {
  const color = tone === 'bad' ? 'text-bad' : tone === 'warn' ? 'text-warn' : 'text-ink'
  const inner = (
    <>
      <div className="text-sm text-muted">{label}</div>
      <div className={`mt-1 text-3xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </>
  )
  return href ? (
    <Link href={href} className="card block p-4 transition-colors hover:border-brand/40">
      {inner}
    </Link>
  ) : (
    <div className="card p-4">{inner}</div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
      {children}
    </div>
  )
}

export function Meter({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0
  return (
    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper" aria-hidden>
      <div className="h-full rounded-full bg-brand" style={{ width: `${pct}%` }} />
    </div>
  )
}

export function ExternalLink({ href, children }: { href: string; children: React.ReactNode }) {
  const safe = /^https?:\/\//i.test(href) ? href : undefined
  if (!safe) return <span>{children}</span>
  return (
    <a
      href={safe}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="text-info underline-offset-2 hover:underline"
    >
      {children}
    </a>
  )
}
