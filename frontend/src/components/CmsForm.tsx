'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import type { Dict } from '@/i18n/en'
import { ClientError, send } from '@/lib/client'
import { useHydrated } from '@/lib/useHydrated'
import type { CmsConnection } from '@/lib/types'

export function CmsForm({ conn, t }: { conn: CmsConnection | null; t: Dict }) {
  const router = useRouter()
  const ready = useHydrated()
  const [baseUrl, setBaseUrl] = useState(conn?.base_url ?? '')
  const [key, setKey] = useState('')
  const [enabled, setEnabled] = useState(conn?.enabled ?? true)
  const [auto, setAuto] = useState(conn?.auto_deliver ?? false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    try {
      const r = await send<{ ok: boolean; detail: string }>('PUT', '/cms/connection', {
        base_url: baseUrl,
        api_key: key || null,
        enabled,
        auto_deliver: auto,
      })
      setKey('')
      setResult({ ok: r.ok, text: `${r.ok ? t.cms.ok : t.cms.failed}: ${r.detail}` })
      router.refresh()
    } catch (err) {
      setResult({ ok: false, text: err instanceof ClientError ? err.message : t.common.error })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} className="card space-y-4 p-5" data-testid="cms-form">
      <div>
        <label className="label" htmlFor="base_url">
          {t.cms.address}
        </label>
        <input
          id="base_url"
          className="input"
          type="url"
          placeholder="https://"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          required
        />
      </div>
      <div>
        <label className="label" htmlFor="api_key">
          {t.cms.key}
        </label>
        <input
          id="api_key"
          className="input"
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={conn ? `${t.cms.keyStored} …${conn.api_key_last4}` : ''}
          required={!conn}
        />
        <p className="mt-1 text-xs text-muted">{t.cms.keyHint}</p>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />{' '}
        {t.cms.enabled}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />{' '}
        {t.cms.auto}
      </label>
      {result && (
        <p role="status" className={`text-sm ${result.ok ? 'text-ok' : 'text-bad'}`}>
          {result.text}
        </p>
      )}
      <button className="btn-primary" disabled={!ready || busy}>
        {busy ? t.common.saving : t.common.save}
      </button>
    </form>
  )
}
