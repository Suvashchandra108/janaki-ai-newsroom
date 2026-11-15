'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'

import { ClientError, send } from '@/lib/client'
import { useHydrated } from '@/lib/useHydrated'

/**
 * A button that calls the API through the BFF, then refreshes the page's server data. Shows the
 * API's own error message if it fails. Optional `ask` prompts for a required reason first.
 */
export function ActionButton({
  method = 'POST',
  path,
  body,
  label,
  busyLabel,
  className = 'btn-secondary',
  confirm,
  ask,
  askField,
  doneMessage,
}: {
  method?: 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  path: string
  body?: Record<string, unknown>
  label: string
  busyLabel?: string
  className?: string
  confirm?: string
  ask?: string
  askField?: string
  doneMessage?: string
}) {
  const router = useRouter()
  const ready = useHydrated()
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function run() {
    setError(null)
    setDone(false)
    let payload = body
    if (ask) {
      const answer = window.prompt(ask)
      if (!answer || answer.trim().length < 3) return
      payload = { ...(body ?? {}), [askField ?? 'reason']: answer.trim() }
    } else if (confirm && !window.confirm(confirm)) return
    try {
      await send(method, path, payload ?? (method === 'POST' ? {} : undefined))
      setDone(true)
      start(() => router.refresh())
    } catch (e) {
      setError(e instanceof ClientError ? e.message : 'Error')
    }
  }

  return (
    <span className="inline-flex flex-col gap-1">
      <button type="button" className={className} onClick={run} disabled={!ready || pending}>
        {pending && busyLabel ? busyLabel : label}
      </button>
      {error && (
        <span role="alert" className="text-xs text-bad">
          {error}
        </span>
      )}
      {done && doneMessage && !error && <span className="text-xs text-ok">{doneMessage}</span>}
    </span>
  )
}
