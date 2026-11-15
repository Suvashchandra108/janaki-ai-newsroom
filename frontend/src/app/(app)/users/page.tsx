import { Badge, PageHeader } from '@/components/ui'
import { formatDateTime } from '@/i18n'
import { getT } from '@/i18n/server'
import { apiGet } from '@/lib/api'
import type { User } from '@/lib/types'

export default async function UsersPage() {
  const { t, locale } = await getT()
  const users = await apiGet<User[]>('/users')
  return (
    <>
      <PageHeader title={t.users.title} />
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">{t.users.name}</th>
              <th className="px-4 py-2 font-medium">{t.users.email}</th>
              <th className="px-4 py-2 font-medium">{t.users.roles}</th>
              <th className="px-4 py-2 font-medium">{t.users.mfa}</th>
              <th className="px-4 py-2 font-medium">{t.users.lastLogin}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? '' : 'text-muted'}>
                <td className="px-4 py-2">{u.full_name}</td>
                <td className="px-4 py-2">{u.email}</td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {u.roles.map((r) => (
                      <Badge key={r}>{r}</Badge>
                    ))}
                    {u.kind === 'service' && <Badge tone="warn">service</Badge>}
                  </div>
                </td>
                <td className="px-4 py-2">{u.mfa_enabled ? '✓' : '—'}</td>
                <td className="px-4 py-2 text-muted tabular-nums">
                  {u.last_login_at ? formatDateTime(u.last_login_at, locale) : t.common.never}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
