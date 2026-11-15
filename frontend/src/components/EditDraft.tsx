'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import type { Dict } from '@/i18n/en'
import { ClientError, send } from '@/lib/client'
import { useHydrated } from '@/lib/useHydrated'
import type { Article } from '@/lib/types'

/**
 * Read view with an Edit switch. Saving creates a new version on the server, which re-runs the
 * fabrication checks; citations stay attached to their paragraphs.
 */
export function EditDraft({
  article,
  t,
  refs,
  children,
}: {
  article: Article
  t: Dict
  refs: Record<string, string>
  children: React.ReactNode
}) {
  const v = article.current
  const router = useRouter()
  const ready = useHydrated()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    headline: v.headline,
    alt_headline: v.alt_headline ?? '',
    summary: v.summary,
    seo_title: v.seo_title,
    seo_description: v.seo_description,
    keywords: v.keywords.join(', '),
    image_caption: v.image_caption ?? '',
    note: '',
  })
  const [paras, setParas] = useState(v.paragraphs.map((p) => ({ ...p })))
  const r = t.review

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await send('PATCH', `/articles/${article.id}`, {
        headline: form.headline,
        alt_headline: form.alt_headline || null,
        summary: form.summary,
        seo_title: form.seo_title,
        seo_description: form.seo_description,
        keywords: form.keywords
          .split(',')
          .map((k) => k.trim())
          .filter(Boolean)
          .slice(0, 15),
        image_caption: form.image_caption || null,
        paragraphs: paras
          .filter((p) => p.text.trim())
          .map((p) => ({ text: p.text.trim(), claim_ids: p.claim_ids })),
        note: form.note || null,
      })
      setEditing(false)
      router.refresh()
    } catch (err) {
      setError(err instanceof ClientError ? err.message : t.common.error)
    } finally {
      setBusy(false)
    }
  }

  if (!editing)
    return (
      <section className="card relative p-6">
        <button
          type="button"
          className="btn-secondary absolute top-4 right-4"
          onClick={() => setEditing(true)}
        >
          ✎ {r.edit}
        </button>
        {children}
      </section>
    )

  const field = (
    key: keyof typeof form,
    label: string,
    opts: { max?: number; area?: boolean; required?: boolean } = {},
  ) => (
    <div>
      <label className="label flex justify-between" htmlFor={`f-${key}`}>
        <span>{label}</span>
        {opts.max && (
          <span
            className={`text-xs font-normal ${form[key].length > opts.max ? 'text-bad' : 'text-muted'}`}
          >
            {form[key].length}/{opts.max}
          </span>
        )}
      </label>
      {opts.area ? (
        <textarea
          id={`f-${key}`}
          className="input min-h-20"
          value={form[key]}
          maxLength={opts.max}
          required={opts.required}
          onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        />
      ) : (
        <input
          id={`f-${key}`}
          className="input"
          value={form[key]}
          maxLength={opts.max}
          required={opts.required}
          onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        />
      )}
    </div>
  )

  return (
    <form onSubmit={save} className="card space-y-4 p-6" data-testid="edit-form">
      {field('headline', r.headline, { max: 120, required: true })}
      {field('alt_headline', r.altHeadline, { max: 120 })}
      {field('summary', r.summary, { max: 400, area: true, required: true })}
      <fieldset className="space-y-3">
        <legend className="label">{r.body}</legend>
        {paras.map((p, i) => (
          <div key={i}>
            <div className="mb-1 flex items-center justify-between text-xs text-muted">
              <span>
                {r.paragraph} {i + 1} · {p.claim_ids.map((c) => refs[c] ?? '?').join(', ') || '—'}
              </span>
              <button
                type="button"
                className="text-bad hover:underline"
                onClick={() => setParas(paras.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </div>
            <textarea
              aria-label={`${r.paragraph} ${i + 1}`}
              className="input min-h-24 font-serif text-[15px]"
              value={p.text}
              maxLength={3000}
              onChange={(e) =>
                setParas(paras.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))
              }
            />
          </div>
        ))}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        {field('seo_title', r.seoTitle, { max: 70, required: true })}
        {field('keywords', r.keywords)}
      </div>
      {field('seo_description', r.seoDescription, { max: 170, area: true, required: true })}
      {field('image_caption', t.media.caption, { max: 300 })}
      {field('note', r.editNote, { max: 1000 })}
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={!ready || busy}>
          {busy ? t.common.saving : t.common.save}
        </button>
        <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>
          {t.common.cancel}
        </button>
      </div>
    </form>
  )
}
