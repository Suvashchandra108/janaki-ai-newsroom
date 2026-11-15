'use client'

import QRCode from 'qrcode'
import { useState } from 'react'

import type { Dict } from '@/i18n/en'
import { ClientError, send } from '@/lib/client'
import { useHydrated } from '@/lib/useHydrated'

export function MfaSetup({ t }: { t: Dict }) {
  const ready = useHydrated()
  const [secret, setSecret] = useState<string | null>(null)
  const [qr, setQr] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function start() {
    setError(null)
    setBusy(true)
    try {
      const r = await send<{ secret: string; otpauth_uri: string }>('POST', '/auth/mfa/setup', {})
      setSecret(r.secret)
      setQr(await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 220 }))
    } catch (e) {
      setError(e instanceof ClientError ? e.message : t.common.error)
    } finally {
      setBusy(false)
    }
  }
  async function enable(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await send('POST', '/auth/mfa/enable', { code })
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- reload so the layout re-reads the session
      window.location.assign('/')
    } catch (err) {
      setError(err instanceof ClientError ? err.message : t.common.error)
      setBusy(false)
    }
  }

  return (
    <div className="card p-6">
      <h1 className="text-xl font-semibold">{t.mfa.title}</h1>
      <p className="mt-2 text-sm text-muted">{t.mfa.intro}</p>
      {!secret ? (
        <button className="btn-primary mt-5" onClick={start} disabled={!ready || busy}>
          {t.mfa.start}
        </button>
      ) : (
        <form onSubmit={enable} className="mt-5 space-y-4">
          {qr && (
            // eslint-disable-next-line @next/next/no-img-element -- generated data: URL, nothing to optimise
            <img src={qr} alt="" width={220} height={220} className="rounded border border-line" />
          )}
          <div>
            <div className="label">{t.mfa.secret}</div>
            <code className="block rounded bg-paper p-2 text-sm break-all">{secret}</code>
          </div>
          <div>
            <label className="label" htmlFor="code">
              {t.mfa.code}
            </label>
            <input
              id="code"
              className="input max-w-40 tracking-widest"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              required
            />
          </div>
          <button className="btn-primary" disabled={busy || code.length !== 6}>
            {t.mfa.enable}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-bad">
          {error}
        </p>
      )}
    </div>
  )
}
