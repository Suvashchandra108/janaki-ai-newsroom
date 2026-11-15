import { NextResponse, type NextRequest } from 'next/server'

import { API_URL } from '@/lib/config'
import { isSameOrigin } from '@/lib/guards'
import { ACCESS_COOKIE, clearSession, seeOther } from '@/lib/session'

export async function POST(request: NextRequest) {
  if (!isSameOrigin('POST', request.headers.get('origin'), request.headers.get('host')))
    return new NextResponse('Forbidden', { status: 403 })
  const token = request.cookies.get(ACCESS_COOKIE)?.value
  if (token) {
    await fetch(`${API_URL}/api/v1/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ everywhere: false }),
      cache: 'no-store',
    }).catch(() => null)
  }
  const out = seeOther('/login')
  clearSession(out.cookies)
  return out
}
