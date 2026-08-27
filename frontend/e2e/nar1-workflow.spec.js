// @ts-check
import { test, expect } from '@playwright/test'
import fs from 'node:fs'

/**
 * The NAR1 case workflow, driven through the real UI against the DEV backend
 * and the LIVE Companies Registry test environment.
 *
 * This is deliberately not a mocked test. Every mocked test of this screen
 * passed while `selectPersonId` carried an HKID and every address failed CR's
 * district vocabulary, because the fixtures were written from the same
 * misunderstanding as the code. What CR accepts is a fact only CR has.
 *
 * REQUIRES the CR TEST window: Mon-Fri 10:00-16:00 HKT. Outside it the form
 * endpoints refuse and the validation step will fail for a reason that has
 * nothing to do with the form.
 *
 * The company is CR's own seeded test company (BRN T0001137) with its three
 * associated e-Service accounts. Nothing here touches a real client.
 */

const CREDS = JSON.parse(fs.readFileSync(process.env.E2E_LOGIN_FILE, 'utf8'))
const ENTITY_ID = '4a20786b-7b50-4f35-8e4d-c3e342766db9' // CGAHCHBAABBG TEST COMPANY LIMITED

/** Console errors are failures here — a React crash still "renders a page". */
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

test.describe('NAR1 workflow — live CR', () => {
  test('opens a case, shows the return data, and validates with CR', async ({ page }) => {
    const crashes = []
    watchForCrashes(page, crashes)

    await login(page)

    // ── Open a case from the company profile ────────────────────────────
    await page.goto(`/companies/${ENTITY_ID}`)
    await expect(page.getByText('CGAHCHBAABBG TEST COMPANY LIMITED').first())
      .toBeVisible({ timeout: 20000 })

    await page.getByRole('button', { name: '+ New case' }).click()
    await page.getByRole('button', { name: 'Open case' }).click()

    // Landed on the workflow, at Data Verification.
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}/, { timeout: 20000 })
    await expect(page.locator('.pg-title')).toHaveText('Data Verification')

    // ── The header facts that were blank before ─────────────────────────
    await expect(page.locator('.crumb')).toContainText('CGAHCHBAABBG TEST COMPANY LIMITED')
    await expect(page.locator('.pg-sub')).toContainText('BRN T0001137')
    await expect(page.locator('.live-strip')).toContainText('Not sent to CR yet')

    // ── The return-data card the screen never had ───────────────────────
    const card = page.locator('.card', { hasText: 'NAR1 return data' })
    await expect(card).toBeVisible()
    await expect(card).toContainText('T0001137')
    await expect(card).toContainText('Test Tower')          // registered office
    await expect(card).toContainText('SECRETARY, CGAHCHBAABBG')  // signatory
    await expect(card).toContainText('Ordinary')            // share class
    // Nothing blocking: this company maps cleanly.
    await expect(card).not.toContainText('cannot be filed as a NAR1 yet')

    await page.screenshot({ path: 'e2e/shots/01-data-verification.png', fullPage: true })

    // ── Manual pre-checks ───────────────────────────────────────────────
    // Asserted one at a time. Firing both clicks and moving on hides the case
    // where the PATCH silently failed — and the CR button is gated on these,
    // so a missed tick would surface later as an unexplained disabled button.
    const aml = page.getByRole('button', { name: /AML screening cleared/ })
    await aml.click()
    await expect(aml).toHaveAttribute('aria-pressed', 'true')

    const ereg = page.getByRole('button', { name: /e-Reg accounts created/ })
    await ereg.click()
    await expect(ereg).toHaveAttribute('aria-pressed', 'true')

    // ── Validate with the live Companies Registry ───────────────────────
    const validate = page.getByRole('button', { name: 'Validate with CR' })
    await expect(validate).toBeEnabled()
    await validate.click()

    // Wait for the CALL to finish, not for a locator that was on screen before
    // the button was pressed: the return-data card is always visible, so an
    // `.or()` against it matches instantly and asserts nothing. CR is a live
    // third party over a slow link and validation is free, so the wait is
    // generous — a short one produces a flake that reads like a rejection.
    await expect(validate.or(page.getByRole('button', { name: /Checking with CR/ })))
      .not.toBeVisible({ timeout: 120000 })

    await page.screenshot({ path: 'e2e/shots/02-after-validate.png', fullPage: true })

    // The assertion that matters: CR accepted it.
    //
    // Asserted as "the gate opened", not as the stage-1 success banner. A
    // passing validation advances the workflow to Client Verification, so the
    // banner is on a stage the operator has already left — and Client
    // Verification is unreachable unless a filing is validated (workflow.js
    // `reachedStage`), which makes arriving here proof that CR signed it.
    await expect(page.locator('.pg-title')).toHaveText('Client Verification')
    await expect(page.locator('.live-strip')).toContainText(/Validated by CR|Validated/i)
    await expect(page.locator('.crumb')).toContainText('Client Verification')

    // Back one stage: the snapshot banner should be there, and the CR button
    // gone — validating twice would discard a snapshot the client may already
    // have been sent.
    await page.getByRole('tab', { name: /Data Verification/ }).click()
    await expect(page.getByText(/CR-signed snapshot frozen/i)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Validate with CR' })).toHaveCount(0)

    expect(crashes, `console errors:\n${crashes.join('\n')}`).toEqual([])
  })

  test('a company that cannot be filed says so before the CR button', async ({ page }) => {
    const crashes = []
    watchForCrashes(page, crashes)
    await login(page)

    // 'test' — no secretary, no incorporation date, no share classes. The
    // point of the card is that these are visible WITHOUT pressing Validate.
    await page.goto('/cases/9e7d34ac-32c3-408e-9cb7-e3f1acd3428d')
    const card = page.locator('.card', { hasText: 'NAR1 return data' })
    await expect(card).toBeVisible({ timeout: 20000 })
    await expect(card).toContainText('cannot be filed as a NAR1 yet')
    // Readable sentences, not "[object Object]" and not raw JSON.
    await expect(card).not.toContainText('[object Object]')
    await expect(card).not.toContainText('{"')

    await page.screenshot({ path: 'e2e/shots/03-unfileable.png', fullPage: true })
    expect(crashes, `console errors:\n${crashes.join('\n')}`).toEqual([])
  })
})
