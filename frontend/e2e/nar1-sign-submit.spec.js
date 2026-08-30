// @ts-check
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

/**
 * Signing and Submission, driven through the UI against the LIVE Companies
 * Registry TEST environment (apitest.cr.gov.hk).
 *
 * NOT production. The presenter and signatory are CR's own seeded test
 * accounts and the deposit account holds test money; `submitFormNar1` here
 * files against CR's test register and deducts from that balance. The backend
 * asserts `env == "test"` before this suite is allowed to run at all — see
 * the guard below — because the only difference between this and spending
 * GSHK's real money is one environment variable.
 *
 * CR LOCKS ACCOUNTS ON REPEATED AUTHENTICATION FAILURES, so there is exactly
 * one attempt at the e-Service signing password. `retries: 0` in the config is
 * load-bearing here, not tidiness.
 *
 * The case is prepared to the Signing gate by scripts/prep_case_for_signing.py,
 * which writes e2e_case.json. Client verification is a fixture there: the test
 * company has no contact on record, and sending a real verification email to
 * drive a test is not a thing this suite does.
 */

const CASE = JSON.parse(fs.readFileSync(process.env.E2E_CASE_FILE, 'utf8'))
const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_LOGIN_FILE, 'utf8'))
const SIGNATORY = JSON.parse(fs.readFileSync(process.env.E2E_SIGNATORY_FILE, 'utf8'))

async function login(page) {
  await page.goto('/')
  await page.getByLabel(/email/i).fill(CREDS.email)
  await page.getByLabel(/password/i).fill(CREDS.password)
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page.locator('.pg-title').first()).toBeVisible({ timeout: 30000 })
}

test.describe('NAR1 sign + submit — live CR test environment', () => {
  test('signs with CR and files the return', async ({ page }) => {
    const crashes = []
    page.on('console', m => { if (m.type() === 'error') crashes.push(m.text()) })
    page.on('pageerror', e => crashes.push(`pageerror: ${e.message}`))

    await login(page)
    await page.goto(`/cases/${CASE.case_id}`)

    // ── The case opens at Signing, because the client approved ──────────
    await expect(page.locator('.pg-title')).toHaveText('Signing', { timeout: 30000 })
    await expect(page.locator('.live-strip')).toContainText('Validated by CR')

    // ── Sign · verifyPinSigningNar1 (free) ──────────────────────────────
    // Nothing is typed. Since Q1 a NAR1 is signed with the logged-in user's
    // own stored e-Service credential and there is no field for anyone else's,
    // so this run depends on SIGNATORY's credential being stored against the
    // logged-in account — see prep_case_for_signing.py.
    await expect(page.getByText(SIGNATORY.user_id)).toBeVisible()

    const signBtn = page.getByRole('button', { name: 'Sign the return' })
    await expect(signBtn).toBeEnabled()
    await signBtn.click()

    // One attempt. Wait for the call to land rather than for a locator that
    // was already on screen.
    await expect(page.getByRole('button', { name: /Signing at CR…|Sign the return/ }))
      .not.toBeVisible({ timeout: 120000 })
    await page.screenshot({ path: 'e2e/shots/10-after-sign.png', fullPage: true })

    await expect(page.locator('.live-strip')).toContainText(/Signed/i)
    await expect(page.locator('.pg-title')).toHaveText('Submission')

    // The password must not survive the call, in the field or the DOM.
    expect(await page.content()).not.toContain(SIGNATORY.eservice_password)

    // ── Submission · the summary, read from the FROZEN snapshot ─────────
    const summary = page.locator('.card', { hasText: 'Final summary' })
    await expect(summary).toBeVisible()
    await expect(summary).toContainText('CGAHCHBAABBG TEST COMPANY LIMITED')
    await expect(summary).toContainText('T0001137')
    await expect(summary).toContainText('✓ Signed')
    // The presenter account is a super-admin-only field and must not be here.
    await expect(summary).not.toContainText('N00108070000')

    // Fee and balance pre-flight. The COMPUTED fee, which for this company is
    // NOT HK$105: its return date is years past, so CR charges a late tier.
    // Asserting HK$105 here would have passed only while the quote was wrong.
    await expect(page.getByText(/Fee HK\$3480\.00|Fee HK\$2610\.00/))
      .toBeVisible({ timeout: 60000 })
    const feeAlert = page.locator('.alert', { hasText: 'deposit balance' })
    await expect(feeAlert).toContainText(/return date/)

    // ── The two gates before an irreversible filing ─────────────────────
    const fileBtn = page.getByRole('button', { name: 'File the return' })
    await expect(fileBtn).toBeDisabled()   // gate 1: not acknowledged

    await page.getByRole('button', { name: /I understand this files the return/ }).click()
    await expect(fileBtn).toBeEnabled()

    await page.screenshot({ path: 'e2e/shots/11-before-submit.png', fullPage: true })

    // ── submitFormNar1 · chargeable, irreversible ───────────────────────
    await fileBtn.click()
    await expect(page.getByRole('button', { name: /Filing with CR…|File the return/ }))
      .not.toBeVisible({ timeout: 180000 })

    await page.screenshot({ path: 'e2e/shots/12-after-submit.png', fullPage: true })

    // ── Confirmation ────────────────────────────────────────────────────
    await expect(page.locator('.pg-title')).toHaveText('Confirmation')
    // "Filed with CR" is the FORM badge's own label — not "Submitted", which is
    // the stage name on the filing row. The two vocabularies are separate (D-6)
    // and the strip renders the badge.
    await expect(page.locator('.live-strip')).toContainText('Filed with CR')
    await expect(page.locator('.live-strip')).toContainText('Completed')
    await expect(page.locator('.card', { hasText: 'Filing receipt' })).toBeVisible()

    // The receipt carries CR's OWN charge, which for a late annual return is
    // not the HK$105 the pre-flight quoted.
    const receipt = page.locator('.card', { hasText: 'Filing receipt' })
    await expect(receipt).toContainText(/D\d{11}/)   // CR receipt number

    expect(crashes, `console errors:\n${crashes.join('\n')}`).toEqual([])
  })
})
