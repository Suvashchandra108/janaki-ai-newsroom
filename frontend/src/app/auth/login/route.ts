import { NextResponse, type NextRequest } from 'next/server'

import { API_URL, COOKIE_SECURE } from '@/lib/config'
import { isSameOrigin, safeNext } from '@/lib/guards'
import { seeOther, setSession, type Tokens } from '@/lib/session'

/** Sign-in form target. Credentials go server-to-server; only httpOnly cookies come back. */
export async function POST(request: NextRequest) {
  if (!isSameOrigin('POST', request.headers.get('origin'), request.headers.get('host')))
    return new NextResponse('Forbidden', { status: 403 })
  const form = await request.formData()
  const field = (k: string) => String(form.get(k) ?? '').trim()
  const next = safeNext(field('next'))
  const back = (error: string, extra: Record<string, string> = {}) => {
    const q = new URLSearchParams({
      error,
      next,
      email: field('email'),
      org: field('tenant_slug'),
      ...extra,
    })
    return seeOther(`/login?${q}`)
  }
  const totp = field('totp_code')
  let res: Response
  try {
    res = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: field('email'),
        password: String(form.get('password') ?? ''),
        tenant_slug: field('tenant_slug') || null,
        totp_code: totp || null,
      }),
      cache: 'no-store',
    })
  } catch {
    return back('unavailable')
  }
  if (!res.ok) {
    let code = 'invalid'
    try {
      code = ((await res.json()) as { error?: { code?: string } }).error?.code ?? code
    } catch {
      /* ignore */
    }
    if (code === 'mfa_required') return back('mfa_required', { mfa: '1' })
    if (res.status === 429 || code === 'account_locked') return back('locked')
    if (res.status === 422) return back('invalid')
    return back(code === 'invalid_totp' ? 'invalid_totp' : 'invalid')
  }
  const tokens = (await res.json()) as Tokens
  const out = seeOther(next)
  setSession(out.cookies, tokens, COOKIE_SECURE)
  return out
}
