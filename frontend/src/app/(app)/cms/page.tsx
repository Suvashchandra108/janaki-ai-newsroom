import { ActionButton } from '@/components/ActionButton'
import { CmsForm } from '@/components/CmsForm'
import { PageHeader, Section } from '@/components/ui'
import { formatDateTime } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGetOptional } from '@/lib/api'
import type { CmsConnection } from '@/lib/types'

export default async function CmsPage() {
  const { t, locale } = await getT()
  const conn = await apiGetOptional<CmsConnection>('/cms/connection')
  return (
    <>
      <PageHeader
        title={t.cms.title}
        intro={t.cms.intro}
        actions={
          conn && (
            <>
              <ActionButton path="/cms/connection/check" label={t.cms.check} />
              <ActionButton path="/cms/sync" label={t.cms.sync} doneMessage={t.cms.synced} />
            </>
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <CmsForm conn={conn} t={t} />
        </div>
        <Section title={t.common.status}>
          {conn ? (
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-xs text-muted">{t.cms.lastOk}</dt>
                <dd>
                  {conn.last_ok_at ? formatDateTime(conn.last_ok_at, locale) : t.common.never}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t.cms.lastError}</dt>
                <dd className={conn.last_error ? 'text-bad' : ''}>
                  {conn.last_error ?? t.common.none}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted">{t.cms.notConnected}</p>
          )}
        </Section>
      </div>
    </>
  )
}
