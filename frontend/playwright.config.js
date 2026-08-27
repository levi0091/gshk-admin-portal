import { defineConfig } from '@playwright/test'

/**
 * E2E against a RUNNING stack, not a mocked one.
 *
 * These specs talk to the DEV database and the live Companies Registry test
 * environment, so they are NOT part of `npm test` and are not run in CI: CR's
 * form endpoints only answer Mon-Fri 10:00-16:00 HKT, and a CI job that fails
 * every night and at weekends teaches people to ignore it.
 *
 *   npm run dev -- --mode e2e            # frontend -> local backend
 *   uvicorn main:app --port 8010         # backend  -> DEV Supabase + CR test
 *   E2E_LOGIN_FILE=... npm run e2e
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  // Retries would re-drive real CR calls. Validation is free, but a retry that
  // silently turns a red run green is the opposite of what this suite is for.
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5183',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
})
