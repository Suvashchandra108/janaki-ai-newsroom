'use client'

/** Browser-side calls go to the dashboard's own BFF, never to the API directly. */
export class ClientError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

export async function send<T = unknown>(
  method: 'POST' | 'PATCH' | 'PUT' | 'DELETE' | 'GET',
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`/bff${path}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  if (res.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search)
    // /auth/refresh is a route handler (sets cookies), so it needs a full navigation.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/auth/refresh?next=${next}`)
    throw new ClientError(401, 'unauthenticated', 'Session expired')
  }
  const text = await res.text()
  const data = text ? (JSON.parse(text) as unknown) : null
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error
    throw new ClientError(
      res.status,
      err?.code ?? 'error',
      err?.message ?? `Request failed (${res.status})`,
    )
  }
  return data as T
}
