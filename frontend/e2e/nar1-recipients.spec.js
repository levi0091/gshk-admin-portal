// @ts-check
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

/**
 * The two things this change adds, driven through the real UI:
 *
 *   1. "Created By" on the post-incorporation dashboard.
 *   2. Client Verification sending to EVERY director, with the board seeded as
 *      removable chips and anyone else addable by hand.
 *
 * Against the DEV database and the LIVE Companies Registry test environment, so
 * it needs the CR window (Mon-Fri 10:00-16:00 HKT) for the validation step.
 * Nothing here signs or submits: validateFormNar1 is free, and the sign/submit
 * chain has its own spec.
 *
 * The backend must be started with EMAIL_TRANSPORT=console — Resend's key is
 * currently rejected, and without the stub the send cannot complete at all.
 */

const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_LOGIN_FILE, 'utf8'))
const ENTITY_ID = '4a20786b-7b50-4f35-8e4d-c3e342766db9' // CGAHCHBAABBG TEST COMPANY LIMITED

function watchForCrashes(page, sink) {
  page.on('console', m => { if (m.type() === 'error') sink.push(m.text()) })
  page.on('pageerror', e => sink.push(`pageerror: ${e.message}`))
}

async function login(page) {
  await page.goto('/')
  await page.getByLabel(/email/i).fill(CREDS.email)
  await page.getByLabel(/password/i).fill(CREDS.password)
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await expect(page.locator('.pg-title').first()).toBeVisible({ timeout: 30000 })
}

test.describe('NAR1 — created by, and mailing the whole board', () => {
  test('the dashboard says who opened each case', async ({ page }) => {
    const crashes = []
    watchForCrashes(page, crashes)
    await login(page)

    await page.goto('/dashboard')
    const header = page.getByRole('columnheader', { name: /Created By/ })
    await expect(header).toBeVisible({ timeout: 20000 })

    // A real name in a real row, not just a header over an empty column.
    const cell = page.locator('td[data-label="Created By"]').first()
    await expect(cell).not.toHaveText('')
    await expect(cell).not.toHaveText('—')

    await page.screenshot({ path: 'e2e/shots/20-dashboard-created-by.png',
                            fullPage: false })

    // It sorts, and it sorts on the NAME — the server 422s on `created_by`.
    await header.click()
    await expect(page.locator('td[data-label="Created By"]').first())
      .toBeVisible({ timeout: 20000 })

    expect(crashes, `console errors:\n${crashes.join('\n')}`).toEqual([])
  })

  test('client verification seeds the board and mails all of them', async ({ page }) => {
    const crashes = []
    watchForCrashes(page, crashes)
    await login(page)

    // ── Open a fresh case and get it validated by CR ────────────────────
    await page.goto(`/companies/${ENTITY_ID}`)
    await page.getByRole('button', { name: '+ New case' }).click()
    await page.getByRole('button', { name: 'Open case' }).click()
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}/, { timeout: 20000 })
    const caseUrl = page.url()

    await page.getByRole('button', { name: /AML screening cleared/ }).click()
    await page.getByRole('button', { name: /e-Reg accounts created/ }).click()

    const validate = page.getByRole('button', { name: 'Validate with CR' })
    await validate.click()
    await expect(validate.or(page.getByRole('button', { name: /Checking with CR/ })))
      .not.toBeVisible({ timeout: 120000 })
    await expect(page.locator('.pg-title')).toHaveText('Client Verification')

    // ── The recipients card ─────────────────────────────────────────────
    const card = page.locator('.card', { hasText: 'Recipients' })
    await expect(card).toBeVisible()

    // The individual director, seeded from the company record.
    const chips = card.locator('.chip-row').first().locator('.chip')
    await expect(chips).toHaveCount(1)
    await expect(chips.first()).toContainText('DIRECTOR, CGAHCHBAABBG')

    // The corporate director is SHOWN, not dropped — a board of two rendering
    // one chip must not look like a board of one.
    await expect(card).toContainText('CGAHCHBAABBG DIRECTOR COMPANY LIMITED')
    await expect(card).toContainText(/no address on record/)

    await page.screenshot({ path: 'e2e/shots/21-recipients-seeded.png',
                            fullPage: true })

    // ── Add someone who is not on the board ─────────────────────────────
    await card.getByLabel('Add a recipient').fill('levi@zenexflow.com')
    await card.getByRole('button', { name: 'Add recipient' }).click()
    await expect(chips).toHaveCount(2)

    // A typo is refused before it can reach the server.
    await card.getByLabel('Add a recipient').fill('not-an-address')
    await card.getByRole('button', { name: 'Add recipient' }).click()
    await expect(card).toContainText(/is not an email address/)
    await expect(chips).toHaveCount(2)

    await page.screenshot({ path: 'e2e/shots/22-recipients-added.png',
                            fullPage: true })

    // ── Send, and watch the request carry BOTH addresses ────────────────
    await page.getByRole('button', { name: /I have reviewed this return/ }).click()

    const sendRequest = page.waitForRequest(r =>
      r.url().includes('/verification/send') && r.method() === 'POST')
    await page.getByRole('button', { name: 'Send to client' }).click()
    const body = JSON.parse((await sendRequest).postData() || '{}')
    expect(body.to).toHaveLength(2)
    expect(body.to).toContain('levi@zenexflow.com')

    await expect(page.getByText(/Waiting on the client's reply|Sent /))
      .toBeVisible({ timeout: 30000 })

    // Mail is stubbed on this deployment, and the screen has to say so —
    // otherwise the operator believes two people were emailed.
    await expect(page.getByText(/Nothing was actually delivered/)).toBeVisible()

    await page.screenshot({ path: 'e2e/shots/23-after-send.png', fullPage: true })

    // ── Record the client's answer and move on ──────────────────────────
    await page.getByRole('button', { name: 'Client approved' }).click()
    await expect(page.locator('.pg-title')).toHaveText('Signing', { timeout: 30000 })

    await page.screenshot({ path: 'e2e/shots/24-signing.png', fullPage: true })
    console.log(`\n  RECIPIENTS UI CASE: ${caseUrl}\n`)

    expect(crashes, `console errors:\n${crashes.join('\n')}`).toEqual([])
  })

  test('a removed director is not mailed', async ({ page }) => {
    // Driven on a case already at Client Verification, so this spends no CR
    // call: the point is only that the send carries the chips on screen.
    const crashes = []
    watchForCrashes(page, crashes)
    await login(page)

    await page.goto(`/companies/${ENTITY_ID}`)
    await page.getByRole('button', { name: '+ New case' }).click()
    await page.getByRole('button', { name: 'Open case' }).click()
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}/, { timeout: 20000 })
    await page.getByRole('button', { name: /AML screening cleared/ }).click()
    await page.getByRole('button', { name: /e-Reg accounts created/ }).click()
    const validate = page.getByRole('button', { name: 'Validate with CR' })
    await validate.click()
    await expect(validate.or(page.getByRole('button', { name: /Checking with CR/ })))
      .not.toBeVisible({ timeout: 120000 })

    const card = page.locator('.card', { hasText: 'Recipients' })
    const chips = card.locator('.chip-row').first().locator('.chip')
    await expect(chips).toHaveCount(1)

    // Take the only director off. Sending must now be impossible, not silently
    // fall back to mailing them anyway.
    await card.getByRole('button', { name: /^Remove / }).click()
    await page.getByRole('button', { name: /I have reviewed this return/ }).click()
    await expect(page.getByRole('button', { name: 'Send to client' })).toBeDisabled()
    await expect(card).toContainText(/No recipients/)

    await page.screenshot({ path: 'e2e/shots/25-no-recipients.png', fullPage: true })
    expect(crashes, `console errors:\n${crashes.join('\n')}`).toEqual([])
  })
})
