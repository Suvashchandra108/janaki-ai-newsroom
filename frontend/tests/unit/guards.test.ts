import { describe, expect, it } from 'vitest'

import { apiPath, isSameOrigin, safeColor, safeNext } from '@/lib/guards'

describe('same-origin check for state-changing requests', () => {
  it('lets reads through and requires a matching Origin for writes', () => {
    expect(isSameOrigin('GET', null, 'news.example.com')).toBe(true)
    expect(isSameOrigin('POST', 'https://news.example.com', 'news.example.com')).toBe(true)
    expect(isSameOrigin('PATCH', 'https://evil.example', 'news.example.com')).toBe(false)
    expect(isSameOrigin('POST', null, 'news.example.com')).toBe(false)
    expect(isSameOrigin('DELETE', 'null', 'news.example.com')).toBe(false)
    expect(isSameOrigin('POST', 'https://news.example.com.evil.example', 'news.example.com')).toBe(
      false,
    )
    expect(isSameOrigin('PUT', 'https://news.example.com:444', 'news.example.com')).toBe(false)
  })
})

describe('API path allow-list', () => {
  it('maps plain segments to /api/v1', () => {
    expect(apiPath(['articles', 'abc-123', 'deliver'])).toBe('/api/v1/articles/abc-123/deliver')
    expect(apiPath(['auth', 'me'])).toBe('/api/v1/auth/me')
    expect(apiPath(['auth', 'mfa', 'setup'])).toBe('/api/v1/auth/mfa/setup')
  })
  it('refuses traversal, odd characters, token endpoints and empty paths', () => {
    for (const bad of [
      [],
      ['..', 'health'],
      ['.'],
      ['a%2fb'],
      ['a/b'],
      ['x y'],
      ['auth', 'refresh'],
      ['auth', 'login'],
      ['auth', 'logout'],
      Array(9).fill('a'),
    ]) {
      expect(apiPath(bad as string[])).toBeNull()
    }
  })
})

describe('post-login destination', () => {
  it('keeps same-site paths only', () => {
    expect(safeNext('/drafts?status=all')).toBe('/drafts?status=all')
    for (const bad of [
      'https://evil.example',
      '//evil.example',
      '/\\evil.example',
      'drafts',
      '',
      null,
      undefined,
      '/auth/logout',
      '/bff/x',
    ])
      expect(safeNext(bad)).toBe('/')
  })
})

describe('tenant brand colours', () => {
  it('accepts hex only', () => {
    expect(safeColor('#1f3a5f')).toBe('#1f3a5f')
    expect(safeColor('#abc')).toBe('#abc')
    for (const bad of [
      'red',
      'url(javascript:x)',
      '#12345',
      '#1f3a5f; background:url(x)',
      42,
      null,
    ])
      expect(safeColor(bad)).toBeNull()
  })
})
