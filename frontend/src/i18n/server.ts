import 'server-only'

import { cookies } from 'next/headers'

import { dict, isLocale, type Locale } from '.'
import { LOCALE_COOKIE } from '@/lib/session'

export async function getLocale(): Promise<Locale> {
  const v = (await cookies()).get(LOCALE_COOKIE)?.value
  return isLocale(v) ? v : 'en'
}

export async function getT() {
  const locale = await getLocale()
  return { locale, t: dict(locale) }
}
