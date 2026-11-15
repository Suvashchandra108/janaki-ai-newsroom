/**
 * Pure request checks used by the BFF and auth routes (unit-tested in tests/unit/guards.test.ts).
 */

/** A state-changing request must come from this dashboard's own origin. */
export function isSameOrigin(method: string, origin: string | null, host: string | null): boolean {
  if (['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) return true
  if (!origin || !host) return false
  try {
    return new URL(origin).host === host
  } catch {
    return false
  }
}

const SEGMENT = /^[A-Za-z0-9._~-]+$/

/**
 * Only API v1 paths may be forwarded, with plain segments (no `..`, no encoded slashes), so the
 * BFF cannot be turned into a proxy for other hosts or other parts of the API server.
 */
export function apiPath(segments: string[]): string | null {
  if (segments.length === 0 || segments.length > 8) return null
  for (const s of segments) {
    if (!SEGMENT.test(s) || s === '.' || s === '..') return null
  }
  if (segments[0] === 'auth' && !['me', 'mfa', 'password'].includes(segments[1] ?? '')) return null
  return `/api/v1/${segments.join('/')}`
}

/** Where to go after sign-in or refresh: same-site relative paths only. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return '/'
  if (next.startsWith('/auth/') || next.startsWith('/bff/')) return '/'
  return next.slice(0, 500)
}

/** Brand colours from tenant settings: 3- or 6-digit hex only, anything else is ignored. */
export function safeColor(value: unknown): string | null {
  return typeof value === 'string' && /^#(?:[0-9a-fA-F]{3}){1,2}$/.test(value) ? value : null
}
