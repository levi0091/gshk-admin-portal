import { test, expect } from '@playwright/test'
import fs from 'node:fs'
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_LOGIN_FILE, 'utf8'))
test.use({ viewport: { width: 1920, height: 1000 }, baseURL: 'https://admin-dev.g-flowdesk.com' })

test('admin-dev shows Created By', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel(/email/i).fill(CREDS.email)
  await page.getByLabel(/password/i).fill(CREDS.password)
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await expect(page.locator('.pg-title').first()).toBeVisible({ timeout: 40000 })
  await page.goto('/dashboard')
  await expect(page.getByRole('columnheader', { name: /Created By/ })).toBeVisible({ timeout: 30000 })
  const cell = page.locator('td[data-label="Created By"]').first()
  await expect(cell).not.toHaveText('')
  await page.locator('.rail-toggle, .sidebar-toggle').first().click().catch(() => {})
  await page.waitForTimeout(600)
  await page.screenshot({ path: 'e2e/shots/30-live-created-by.png' })
})

test('admin-dev shows the recipients card', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel(/email/i).fill(CREDS.email)
  await page.getByLabel(/password/i).fill(CREDS.password)
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await expect(page.locator('.pg-title').first()).toBeVisible({ timeout: 40000 })
  // NAR-2026-0053 — validated by CR, sitting at Client Verification.
  await page.goto('/cases/bb947a0b-b9a1-4fa6-b45a-464f4f419ade')
  const card = page.locator('.card', { hasText: 'Recipients' })
  await expect(card).toBeVisible({ timeout: 30000 })
  await expect(card.locator('.chip').first()).toContainText('DIRECTOR, CGAHCHBAABBG')
  await expect(card).toContainText(/no address on record/)
  await card.scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'e2e/shots/31-live-recipients.png' })
})
