'use client'

import { useRouter } from 'next/navigation'

import type { Locale } from '@/i18n'

function rememberLocale(next: Locale) {
  document.cookie = `jn_locale=${next}; path=/; max-age=31536000; samesite=lax`
}

export function LanguageSwitch({ locale, compact = false }: { locale: Locale; compact?: boolean }) {
  const router = useRouter()
  function choose(next: Locale) {
    rememberLocale(next)
    router.refresh()
  }
  return (
    <div
      role="group"
      aria-label="Language / भाषा"
      className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm"
    >
      {(['en', 'ne'] as const).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => choose(l)}
          aria-pressed={locale === l}
          className={`rounded-md px-2.5 py-1 ${locale === l ? 'bg-brand text-brand-ink' : 'text-muted hover:text-ink'}`}
        >
          {l === 'en' ? (compact ? 'EN' : 'English') : compact ? 'ने' : 'नेपाली'}
        </button>
      ))}
    </div>
  )
}
