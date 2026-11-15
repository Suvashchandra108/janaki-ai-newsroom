import { expect, test } from '@playwright/test'

import { login, seed, totp } from './helpers'

/**
 * Runs against the real FastAPI newsroom and a database seeded by backend/tests/e2e_seed.py.
 * Tests run in order and share that database (one worker).
 */

test('signed-out visitors are sent to sign in; wrong password is refused', async ({ page }) => {
  await page.goto('/drafts')
  await expect(page).toHaveURL(/\/login\?next=%2Fdrafts/)
  await page.getByLabel('Organisation').fill(seed.tenant)
  await page.getByLabel('Email').fill(seed.editor)
  await page.getByLabel('Password').fill('wrong password here')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('main').getByRole('alert')).toHaveText(
    'Email, password or organisation is not correct.',
  )
})

test('dashboard figures equal the backend records', async ({ page }) => {
  await login(page, seed.editor)
  await expect(page.getByRole('heading', { name: 'Today in the newsroom' })).toBeVisible()
  const api = await (await page.request.get('/bff/dashboard/summary')).json()
  const stats = page.getByTestId('stats-articles')
  await expect(stats.getByText('Awaiting review').locator('..')).toContainText(
    String(seed.counts.awaiting),
  )
  expect(api.articles.awaiting_review).toBe(seed.counts.awaiting)
  expect(api.articles.generated_today).toBeLessThanOrEqual(seed.counts.articles)
  expect(api.failures.jobs_24h).toBe(seed.counts.failed_jobs)
  await expect(page.getByText('Failed jobs (24 h)').locator('..')).toContainText(
    String(seed.counts.failed_jobs),
  )
  await expect(page.getByText('Not used (RSS only)')).toBeVisible()
  await expect(page.getByText('Cost is not calculated')).toBeVisible()
  // The failed job is in the activity feed and links to the jobs list.
  await page.getByRole('link', { name: /A Research job failed/ }).click()
  await expect(page).toHaveURL(/\/jobs\?status=failed/)
  await expect(page.getByTestId('jobs')).toContainText('AI provider quota exceeded (e2e fixture)')
})

test('editor reviews a draft: sources, flags, photo licence, history', async ({ page }) => {
  await login(page, seed.editor)
  await page.goto('/drafts')
  await expect(page.getByTestId('draft-list').getByRole('listitem')).toHaveCount(
    seed.counts.awaiting,
  )
  await page.getByRole('link', { name: new RegExp(seed.headline_a.slice(0, 30)) }).click()
  await expect(page.getByTestId('article').getByRole('heading', { level: 2 })).toHaveText(
    seed.headline_a,
  )
  await expect(page.getByText('Facts cited')).toBeVisible()
  await expect(page.getByText('kathmandupost.example.com').first()).toBeVisible()
  await expect(page.getByText('CC BY-SA 4.0').first()).toBeVisible()
  await expect(page.getByText('Approving and publishing happen in the website CMS')).toBeVisible()
  await expect(page.getByRole('img', { name: /Flooded fields/ })).toBeVisible()
  const img = await page.request.get(
    (await page.getByRole('img', { name: /Flooded fields/ }).getAttribute('src'))!,
  )
  expect(img.status()).toBe(200)
  expect(img.headers()['content-type']).toBe('image/webp')
  await expect(page.getByTestId('history').getByRole('listitem')).toHaveCount(1)
})

test('editor edits a draft: a new version is saved and shown', async ({ page }) => {
  await login(page, seed.editor)
  await page.goto(`/drafts/${seed.article_a}`)
  await page.getByRole('button', { name: /Edit/ }).click()
  const form = page.getByTestId('edit-form')
  await form.getByLabel(/^Headline/).fill('Saptari floods displace 2,000 families, province says')
  await form.getByLabel(/What did you change/).fill('Shorter headline')
  await form.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByTestId('article').getByRole('heading', { level: 2 })).toHaveText(
    'Saptari floods displace 2,000 families, province says',
  )
  await expect(page.getByTestId('history').getByRole('listitem')).toHaveCount(2)
  await page.getByTestId('history').getByRole('link', { name: 'Version 1' }).click()
  await expect(page.getByTestId('article').getByRole('heading', { level: 2 })).toHaveText(
    seed.headline_a,
  )
})

test('sending without a website connection explains why', async ({ page }) => {
  await login(page, seed.editor)
  await page.goto(`/drafts/${seed.article_a}`)
  await page.getByRole('button', { name: 'Send to website as draft' }).click()
  await expect(page.locator('main').getByRole('alert')).toContainText('not connected')
})

test('editor rejects the other draft with a reason', async ({ page }) => {
  await login(page, seed.editor)
  await page.goto(`/drafts/${seed.article_b}`)
  page.once('dialog', (d) => d.accept('Repeats the straight report'))
  await page.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('status')).toContainText('Repeats the straight report')
  await page.goto('/drafts?status=rejected')
  await expect(page.getByTestId('draft-list').getByRole('listitem')).toHaveCount(1)
})

test('editor verifies a fact on the research page', async ({ page }) => {
  await login(page, seed.editor)
  await page.goto(`/inbox/${seed.event_id}`)
  const claims = page.getByTestId('claims')
  const unverified = claims
    .getByRole('listitem')
    .filter({ has: page.getByRole('button', { name: 'Mark verified' }) })
  const first = unverified.first()
  const text = await first.locator('p').first().textContent()
  page.once('dialog', (d) => d.accept('Confirmed with the district office by phone'))
  await first.getByRole('button', { name: 'Mark verified' }).click()
  const row = claims.getByRole('listitem').filter({ hasText: text! })
  await expect(row.getByText('Verified by editor')).toBeVisible()
  await expect(row).toContainText('Confirmed with the district office by phone')
})

test('reporter sees no admin screens and cannot reject', async ({ page }) => {
  await login(page, seed.reporter)
  const nav = page.getByRole('navigation', { name: 'Menu' }).first()
  await expect(nav.getByRole('link', { name: 'Article drafts' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Users' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Website CMS' })).toHaveCount(0)
  await page.goto(`/drafts/${seed.article_a}`)
  await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0)
  // The server enforces it too: the reject call is refused.
  const r = await page.request.post(`/bff/articles/${seed.article_a}/reject`, {
    data: { reason: 'not allowed' },
    headers: { Origin: new URL(page.url()).origin },
  })
  expect(r.status()).toBe(403)
})

test('the BFF refuses cross-site writes, odd paths and missing sessions', async ({
  page,
  request,
}) => {
  await login(page, seed.editor)
  const cross = await page.request.post(`/bff/articles/${seed.article_a}/reject`, {
    data: { reason: 'csrf attempt' },
    headers: { Origin: 'https://evil.example' },
  })
  expect(cross.status()).toBe(403)
  const noOrigin = await page.request.post(`/bff/articles/${seed.article_a}/reject`, {
    data: { reason: 'x' },
  })
  expect(noOrigin.status()).toBe(403)
  expect((await page.request.get('/bff/auth/refresh')).status()).toBe(404)
  expect((await page.request.get('/bff/%2e%2e/health')).status()).toBe(404)
  expect((await request.get('/bff/dashboard/summary')).status()).toBe(401) // no cookies
})

test('administrator signs in with two-factor and sees Users and Website CMS', async ({ page }) => {
  await login(page, seed.admin.email, { totp: totp(seed.admin.totp_secret) })
  await expect(page.getByRole('heading', { name: 'Today in the newsroom' })).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Menu' })
    .first()
    .getByRole('link', { name: 'Users' })
    .click()
  await expect(page.getByRole('cell', { name: seed.editor })).toBeVisible()
  await page.goto('/cms')
  await expect(page.getByText('Not connected yet.')).toBeVisible()
  await page.getByLabel('Website address').fill('http://169.254.169.254')
  await page.getByLabel('Integration API key').fill('0123456789abcdef0123')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('status')).toContainText(/https|address/i)
})

test('a new administrator must set up two-factor before anything else', async ({ page }) => {
  await login(page, seed.new_admin)
  await expect(page.getByRole('heading', { name: 'Set up two-factor sign-in' })).toBeVisible()
  await page.getByRole('button', { name: 'Show my code' }).click()
  const secret = (await page.locator('code').textContent())!.trim()
  await page.getByLabel('6-digit code').fill(totp(secret))
  await page.getByRole('button', { name: 'Turn on' }).click()
  await expect(page.getByRole('heading', { name: 'Today in the newsroom' })).toBeVisible()
})

test('Nepali interface and sign-out', async ({ page }) => {
  await login(page, seed.editor)
  await page.getByRole('button', { name: 'ने' }).click()
  await expect(page.getByRole('heading', { name: 'आज न्यूजरुममा' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'ne')
  await page.getByRole('button', { name: 'EN' }).click()
  await expect(page.getByRole('heading', { name: 'Today in the newsroom' })).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Menu' })
    .first()
    .locator('..')
    .getByRole('button', { name: 'Sign out' })
    .click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
})

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  test('menu opens and every main screen loads', async ({ page }) => {
    await login(page, seed.editor)
    const screens: [string, string][] = [
      ['News inbox', '/inbox'],
      ['Article drafts', '/drafts'],
      ['Jobs', '/jobs'],
      ['Sources', '/sources'],
      ['Usage', '/usage'],
      ['Settings', '/settings'],
    ]
    for (const [name, path] of screens) {
      await page.getByText('☰ Menu').click()
      await page
        .getByRole('navigation', { name: 'Menu' })
        .last()
        .getByRole('link', { name })
        .click()
      await expect(page).toHaveURL(new RegExp(`${path}$`))
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await expect(page.locator('details[open]')).toHaveCount(0) // the menu closed itself
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      )
      expect(overflow, `${name} scrolls sideways`).toBeLessThanOrEqual(1)
    }
  })
})

test('long unbroken text never widens the page', async ({ page }) => {
  await login(page, seed.editor)
  for (const path of [`/drafts/${seed.article_a}`, `/inbox/${seed.event_id}`, '/', '/jobs']) {
    await page.goto(path)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow, path).toBeLessThanOrEqual(1)
  }
})
