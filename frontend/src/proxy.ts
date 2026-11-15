import { NextResponse, type NextRequest } from 'next/server'

/**
 * Before any dashboard page renders: no access token means "try a refresh" (the refresh cookie
 * is scoped to /auth, so only /auth/refresh can see it; it sends the user to /login if there is
 * no valid session). Also passes the current path to server components.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  if (!request.cookies.has('jn_at')) {
    // Next.js turns this same-origin URL back into a relative Location on the way out.
    const url = new URL(
      `/auth/refresh?next=${encodeURIComponent(pathname + search)}`,
      request.nextUrl,
    )
    return NextResponse.redirect(url)
  }
  const h = new Headers(request.headers)
  h.set('x-jn-path', pathname + search)
  return NextResponse.next({ request: { headers: h } })
}

export const config = {
  matcher: ['/((?!auth/|bff/|_next/|favicon.ico|login).*)'],
}
