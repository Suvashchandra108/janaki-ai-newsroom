import 'server-only'

import { cookies, headers } from 'next/headers'
import { redirect } from 'next/navigation'

import { API_URL } from './config'
import { ACCESS_COOKIE } from './session'

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

/** Reads the API's error envelope `{"error": {"code", "message"}}`. */
export async function readError(res: Response): Promise<ApiError> {
  let code = 'error'
  let message = `Request failed (${res.status})`
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string } }
    code = body.error?.code ?? code
    message = body.error?.message ?? message
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, code, message)
}

async function currentPath(): Promise<string> {
  const h = await headers()
  return h.get('x-jn-path') || '/'
}

/**
 * GET from the newsroom API as the signed-in user (server components only). An expired access
 * token sends the browser through /auth/refresh and back; no token means sign in.
 */
export async function apiGet<T>(path: string): Promise<T> {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value
  const next = encodeURIComponent(await currentPath())
  if (!token) redirect(`/auth/refresh?next=${next}`)
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    cache: 'no-store',
  })
  if (res.status === 401) redirect(`/auth/refresh?next=${next}`)
  if (!res.ok) throw await readError(res)
  return (await res.json()) as T
}

/** Like apiGet, but returns null for 404 (e.g. "no CMS connection yet"). */
export async function apiGetOptional<T>(path: string): Promise<T | null> {
  try {
    return await apiGet<T>(path)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}
