import { createHmac } from 'node:crypto'
import { readFileSync } from 'node:fs'

import { expect, type Page } from '@playwright/test'

export type Seed = {
  password: string
  tenant: string
  admin: { email: string; totp_secret: string }
  editor: string
  reporter: string
  new_admin: string
  event_id: string
  article_a: string
  article_b: string
  headline_a: string
  counts: { items: number; events: number; articles: number; awaiting: number; failed_jobs: number }
}

export const seed: Seed = JSON.parse(readFileSync(process.env.SEED_FILE || 'seed.json', 'utf8'))

/** RFC 6238 TOTP (SHA-1, 6 digits, 30 s), for the seeded administrator's authenticator. */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of secret.replace(/=+$/, '').toUpperCase())
    bits += alphabet.indexOf(c).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)))
  const h = createHmac('sha1', key).update(counter).digest()
  const o = h[h.length - 1] & 0xf
  const code = ((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).toString()
  return code.padStart(6, '0')
}

export async function login(page: Page, email: string, extra?: { totp?: string }) {
  await page.goto('/login')
  await page.getByLabel('Organisation').fill(seed.tenant)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(seed.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  if (extra?.totp) {
    await expect(page.locator('main').getByRole('alert')).toContainText('6-digit code')
    await page.getByLabel('Password').fill(seed.password)
    await page.getByLabel('Authenticator code').fill(extra.totp)
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
}
