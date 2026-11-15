import type { ResponseCookies } from 'next/dist/compiled/@edge-runtime/cookies'
import { NextResponse } from 'next/server'

/**
 * Session cookies. The browser never sees a token it can read: both are httpOnly. The access
 * token is SameSite=Lax (links from email still open the dashboard); the refresh token is
 * SameSite=Strict and is only ever sent to /auth/refresh. Every state-changing request is also
 * checked for a same-origin `Origin` header (lib/guards.ts).
 */
export const ACCESS_COOKIE = 'jn_at'
export const REFRESH_COOKIE = 'jn_rt'
export const LOCALE_COOKIE = 'jn_locale'
const REFRESH_MAX_AGE = 14 * 24 * 3600

export type Tokens = { access_token: string; refresh_token: string; expires_in: number }

export function setSession(cookies: ResponseCookies, t: Tokens, secure: boolean): void {
  cookies.set(ACCESS_COOKIE, t.access_token, {
    httpOnly: true,
    sameSite: 'lax',
    secure,
    path: '/',
    maxAge: Math.max(60, t.expires_in - 30),
  })
  cookies.set(REFRESH_COOKIE, t.refresh_token, {
    httpOnly: true,
    sameSite: 'strict',
    secure,
    path: '/auth',
    maxAge: REFRESH_MAX_AGE,
  })
}

/**
 * A 303 to a same-site path, with a *relative* Location. Building an absolute URL from
 * `request.url` is wrong behind a proxy or when the server binds a different host name.
 */
export function seeOther(path: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { Location: path } })
}

export function clearSession(cookies: ResponseCookies): void {
  cookies.set(ACCESS_COOKIE, '', { path: '/', maxAge: 0 })
  cookies.set(REFRESH_COOKIE, '', { path: '/auth', maxAge: 0 })
}
