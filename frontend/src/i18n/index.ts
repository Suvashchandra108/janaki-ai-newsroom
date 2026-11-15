import { en, type Dict } from './en'
import { ne } from './ne'

export type Locale = 'en' | 'ne'
export const LOCALES: Locale[] = ['en', 'ne']
const DICTS: Record<Locale, Dict> = { en, ne }

export function isLocale(v: unknown): v is Locale {
  return v === 'en' || v === 'ne'
}

export function dict(locale: Locale): Dict {
  return DICTS[locale]
}

/** Fills `{name}` placeholders. Unknown placeholders are left as they are. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in values ? String(values[k]) : m))
}

const NE_DIGITS = '०१२३४५६७८९'
export function formatNumber(n: number, locale: Locale): string {
  const s = new Intl.NumberFormat('en-IN').format(n)
  return locale === 'ne' ? s.replace(/\d/g, (d) => NE_DIGITS[Number(d)]) : s
}

/** Dates are shown in Nepal time, the newsroom's working day. */
export function formatDateTime(iso: string | null | undefined, locale: Locale): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const s = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kathmandu',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
  return locale === 'ne' ? s.replace(/\d/g, (x) => NE_DIGITS[Number(x)]) : s
}
