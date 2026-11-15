import type { NextRequest } from 'next/server'

import { API_URL, COOKIE_SECURE } from '@/lib/config'
import { safeNext } from '@/lib/guards'
import { clearSession, REFRESH_COOKIE, seeOther, setSession, type Tokens } from '@/lib/session'

/** Rotates the session (the API detects reuse of an old refresh token) and returns the user. */
export async function GET(request: NextRequest) {
  const next = safeNext(request.nextUrl.searchParams.get('next'))
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value
  const toLogin = () => {
    const out = seeOther(`/login?${new URLSearchParams({ next })}`)
    clearSession(out.cookies)
    return out
  }
  if (!refresh) return toLogin()
  try {
    const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: 'no-store',
    })
    if (!res.ok) return toLogin()
    const out = seeOther(next)
    setSession(out.cookies, (await res.json()) as Tokens, COOKIE_SECURE)
    return out
  } catch {
    return toLogin()
  }
}
