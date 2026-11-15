import { NextResponse, type NextRequest } from 'next/server'

import { API_URL } from '@/lib/config'
import { apiPath, isSameOrigin } from '@/lib/guards'
import { ACCESS_COOKIE } from '@/lib/session'

/**
 * Browser → dashboard server → newsroom API. Adds the user's token from the httpOnly cookie,
 * refuses cross-origin writes, forwards only /api/v1 paths, and never forwards the browser's
 * cookies or Authorization header. An expired token returns 401; the client then goes through
 * /auth/refresh (the only place the refresh cookie is sent) and comes back.
 */
async function handle(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const method = request.method.toUpperCase()
  if (!isSameOrigin(method, request.headers.get('origin'), request.headers.get('host')))
    return NextResponse.json(
      { error: { code: 'forbidden', message: 'Cross-site request refused.' } },
      { status: 403 },
    )
  const path = apiPath((await ctx.params).path)
  if (!path)
    return NextResponse.json(
      { error: { code: 'not_found', message: 'Not found.' } },
      { status: 404 },
    )
  const token = request.cookies.get(ACCESS_COOKIE)?.value
  if (!token)
    return NextResponse.json(
      { error: { code: 'unauthenticated', message: 'Please sign in again.' } },
      { status: 401 },
    )

  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: '*/*' }
  const ctype = request.headers.get('content-type')
  let body: ArrayBuffer | undefined
  if (!['GET', 'HEAD'].includes(method)) {
    body = await request.arrayBuffer()
    if (body.byteLength > 1_000_000)
      return NextResponse.json(
        { error: { code: 'too_large', message: 'Request too large.' } },
        { status: 413 },
      )
    if (ctype) headers['Content-Type'] = ctype
  }
  const upstream = await fetch(`${API_URL}${path}${request.nextUrl.search}`, {
    method,
    headers,
    body,
    cache: 'no-store',
    redirect: 'manual',
  }).catch(() => null)
  if (!upstream)
    return NextResponse.json(
      { error: { code: 'unavailable', message: 'The newsroom service is not reachable.' } },
      { status: 502 },
    )
  const out = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') ?? 'application/json',
      'Cache-Control': 'no-store',
      ...(upstream.headers.get('content-disposition')
        ? { 'Content-Disposition': upstream.headers.get('content-disposition')! }
        : {}),
    },
  })
  return out
}

export const GET = handle
export const POST = handle
export const PATCH = handle
export const PUT = handle
export const DELETE = handle
