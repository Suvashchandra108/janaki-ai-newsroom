import { defineConfig, devices } from '@playwright/test'

/**
 * Browser tests against a REAL newsroom API and a seeded e2e database (see tests/e2e/README).
 * BASE_URL: the running dashboard. CHROME_PATH: optional browser binary.
 */
const executablePath = process.env.CHROME_PATH || undefined

export default defineConfig({
  testDir: 'tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  reporter: [['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3100',
    trace: 'retain-on-failure',
    launchOptions: { executablePath },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], launchOptions: { executablePath } } },
  ],
})
