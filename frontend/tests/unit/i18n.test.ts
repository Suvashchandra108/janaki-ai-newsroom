import { describe, expect, it } from 'vitest'

import { fill, formatDateTime, formatNumber } from '@/i18n'
import { en } from '@/i18n/en'
import { ne } from '@/i18n/ne'

/** Every leaf as a path (keys may contain dots, e.g. "ai.writing"). */
function paths(o: unknown, prefix: string[] = []): string[][] {
  if (typeof o !== 'object' || o === null) return [prefix]
  return Object.entries(o).flatMap(([k, v]) => paths(v, [...prefix, k]))
}
const at = (d: unknown, p: string[]) =>
  p.reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], d)
const id = (p: string[]) => JSON.stringify(p)

describe('interface text', () => {
  it('Nepali has exactly the English keys, none empty', () => {
    expect(paths(ne).map(id).sort()).toEqual(paths(en).map(id).sort())
    for (const p of paths(ne)) {
      const v = at(ne, p)
      expect(typeof v === 'string' && v.trim().length > 0, id(p)).toBe(true)
    }
  })
  it('placeholders match between languages', () => {
    const ph = (s: unknown) => (String(s).match(/\{\w+\}/g) ?? []).sort()
    for (const p of paths(en)) expect(ph(at(ne, p)), id(p)).toEqual(ph(at(en, p)))
  })
})

describe('formatting', () => {
  it('fills placeholders and leaves unknown ones', () => {
    expect(fill('A {job} job failed', { job: 'Research' })).toBe('A Research job failed')
    expect(fill('{x} and {y}', { x: 1 })).toBe('1 and {y}')
  })
  it('uses Devanagari digits in Nepali and Indian grouping', () => {
    expect(formatNumber(1234567, 'en')).toBe('12,34,567')
    expect(formatNumber(2000, 'ne')).toBe('२,०००')
  })
  it('shows times in Nepal time and handles missing dates', () => {
    expect(formatDateTime('2026-11-15T06:00:00Z', 'en')).toBe('15 Nov, 11:45')
    expect(formatDateTime(null, 'en')).toBe('—')
    expect(formatDateTime('not a date', 'ne')).toBe('—')
  })
})
