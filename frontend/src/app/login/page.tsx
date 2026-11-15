import type { Metadata } from 'next'

import { LanguageSwitch } from '@/components/LanguageSwitch'
import { getT } from '@/i18n/server'
import { safeNext } from '@/lib/guards'

export const metadata: Metadata = { title: 'Sign in' }

type Search = Promise<Record<string, string | string[] | undefined>>

export default async function LoginPage({ searchParams }: { searchParams: Search }) {
  const { t, locale } = await getT()
  const sp = await searchParams
  const one = (k: string) => (typeof sp[k] === 'string' ? (sp[k] as string) : '')
  const error = one('error') as keyof typeof t.login.errors
  const message = t.login.errors[error] ?? null
  const showTotp = one('mfa') === '1' || error === 'invalid_totp'
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="eyebrow">{t.app.name}</div>
            <div className="text-sm text-muted">{t.app.tagline}</div>
          </div>
          <LanguageSwitch locale={locale} compact />
        </div>
        <form action="/auth/login" method="post" className="card space-y-4 p-6">
          <h1 className="text-xl font-semibold">{t.login.title}</h1>
          {message && (
            <p role="alert" className="rounded-lg bg-bad-bg px-3 py-2 text-sm text-bad">
              {message}
            </p>
          )}
          <input type="hidden" name="next" value={safeNext(one('next'))} />
          <div>
            <label className="label" htmlFor="tenant_slug">
              {t.login.org}
            </label>
            <input
              id="tenant_slug"
              name="tenant_slug"
              className="input"
              defaultValue={one('org')}
              autoComplete="organization"
              aria-describedby="org-hint"
              required
            />
            <p id="org-hint" className="mt-1 text-xs text-muted">
              {t.login.orgHint}
            </p>
          </div>
          <div>
            <label className="label" htmlFor="email">
              {t.login.email}
            </label>
            <input
              id="email"
              name="email"
              type="email"
              className="input"
              defaultValue={one('email')}
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="label" htmlFor="password">
              {t.login.password}
            </label>
            <input
              id="password"
              name="password"
              type="password"
              className="input"
              autoComplete="current-password"
              required
            />
          </div>
          {showTotp && (
            <div>
              <label className="label" htmlFor="totp_code">
                {t.login.totp}
              </label>
              <input
                id="totp_code"
                name="totp_code"
                className="input tracking-widest"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="\d{6}"
                maxLength={6}
                autoFocus
                required
              />
              <p className="mt-1 text-xs text-muted">{t.login.totpHint}</p>
            </div>
          )}
          <button className="btn-primary w-full">{t.login.submit}</button>
        </form>
        <p className="mt-6 text-center text-xs text-muted">{t.common.poweredBy}</p>
      </div>
    </main>
  )
}
