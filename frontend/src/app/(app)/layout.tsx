import Link from 'next/link'

import { LanguageSwitch } from '@/components/LanguageSwitch'
import { MfaSetup } from '@/components/MfaSetup'
import { MobileMenu } from '@/components/MobileMenu'
import { NavLinks, type NavItem } from '@/components/Nav'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import { safeColor } from '@/lib/guards'
import type { Me, Notification, Tenant } from '@/lib/types'

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { t, locale } = await getT()
  const me = await apiGet<Me>('/auth/me')
  if (me.mfa_enrollment_required) {
    return (
      <main className="mx-auto max-w-lg px-4 py-12">
        <MfaSetup t={t} />
      </main>
    )
  }
  const can = (p: string) => me.permissions.includes(p)
  const [tenant, notes] = await Promise.all([
    can('tenant.read') ? apiGet<Tenant>('/tenants/current') : Promise.resolve(null),
    apiGet<Notification[]>('/dashboard/notifications?limit=50'),
  ])
  const theme = (tenant?.settings?.theme ?? {}) as Record<string, unknown>
  const style = {
    ...(safeColor(theme.primary) ? { '--brand': safeColor(theme.primary) } : {}),
    ...(safeColor(theme.accent) ? { '--accent': safeColor(theme.accent) } : {}),
  } as React.CSSProperties
  const errors = notes.filter((n) => n.severity === 'error').length

  const items: NavItem[] = [
    { href: '/', label: t.nav.dashboard, icon: '◧' },
    { href: '/inbox', label: t.nav.inbox, icon: '✉' },
    { href: '/drafts', label: t.nav.drafts, icon: '✎' },
    { href: '/jobs', label: t.nav.jobs, icon: '⟳' },
    { href: '/sources', label: t.nav.sources, icon: '☰' },
    ...(can('usage.read') ? [{ href: '/usage', label: t.nav.usage, icon: '▤' }] : []),
    ...(can('cms.manage') ? [{ href: '/cms', label: t.nav.cms, icon: '⇪' }] : []),
    ...(can('users.read') ? [{ href: '/users', label: t.nav.users, icon: '☺' }] : []),
    { href: '/settings', label: t.nav.settings, icon: '⚙' },
  ]

  const sidebar = (
    <>
      <div className="px-3 pt-5 pb-6">
        <div className="text-xs font-semibold tracking-widest text-white/60 uppercase">
          {t.app.name}
        </div>
        <div className="mt-1 truncate text-lg font-semibold text-white">{tenant?.name ?? '—'}</div>
      </div>
      <nav aria-label={t.nav.menu} className="px-2">
        <NavLinks items={items} />
      </nav>
      <div className="mt-auto px-3 pt-6 pb-5 text-xs text-white/60">
        <div className="truncate">{me.email}</div>
        <form action="/auth/logout" method="post" className="mt-2">
          <button className="text-white/80 underline-offset-2 hover:text-white hover:underline">
            {t.nav.signOut}
          </button>
        </form>
      </div>
    </>
  )

  return (
    <div style={style} className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="hidden bg-brand lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col">
        {sidebar}
      </aside>
      <div className="min-w-0">
        <div className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-line bg-surface/95 px-4 py-2.5 backdrop-blur lg:px-8">
          <MobileMenu label={t.nav.menu}>{sidebar}</MobileMenu>
          <div className="hidden text-sm text-muted lg:block">{t.app.tagline}</div>
          <div className="flex items-center gap-2">
            <Link
              href="/#activity"
              className="btn-secondary relative"
              aria-label={t.nav.notifications}
            >
              🔔
              {errors > 0 && (
                <span className="absolute -top-1 -right-1 rounded-full bg-bad px-1.5 text-[10px] font-semibold text-white">
                  {errors}
                </span>
              )}
            </Link>
            <LanguageSwitch locale={locale} compact />
          </div>
        </div>
        <main className="mx-auto max-w-7xl px-4 py-6 lg:px-8">{children}</main>
      </div>
    </div>
  )
}
