import { LanguageSwitch } from '@/components/LanguageSwitch'
import { PageHeader, Section } from '@/components/ui'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { Me, Tenant } from '@/lib/types'

export default async function SettingsPage() {
  const { t, locale } = await getT()
  const me = await apiGet<Me>('/auth/me')
  const tenant = me.permissions.includes('tenant.read')
    ? await apiGet<Tenant>('/tenants/current')
    : null
  return (
    <>
      <PageHeader title={t.settings.title} />
      <div className="grid gap-6 md:grid-cols-2">
        <Section title={t.settings.language}>
          <LanguageSwitch locale={locale} />
          <p className="mt-3 text-sm text-muted">{t.settings.languageHint}</p>
        </Section>
        <Section title={t.settings.account}>
          <dl className="space-y-1 text-sm">
            <div>{me.email}</div>
            <div className="text-xs text-muted">{me.permissions.length} permissions</div>
          </dl>
        </Section>
        {tenant && (
          <Section title={t.settings.organisation}>
            <div className="text-sm font-medium">{tenant.name}</div>
            <div className="text-xs text-muted">{tenant.slug}</div>
            <h3 className="mt-4 text-sm font-medium">{t.settings.theme}</h3>
            <p className="mt-1 text-xs text-muted">{t.settings.themeHint}</p>
          </Section>
        )}
      </div>
    </>
  )
}
