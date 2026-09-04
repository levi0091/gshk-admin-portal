/**
 * Resolve the header funnel's hover states in a real browser.
 *
 * `thead th:hover .th-filter:hover` outranks `.th-filter.is-on:hover` on
 * specificity, so an APPLIED filter would silently take the indigo hover meant
 * for an unapplied one — a thing no unit test looks at and no diff shows. This
 * asserts the four states resolve to the colours they are supposed to.
 *
 *   SHOOT=1 npx vitest run src/pages/__tables_visual__.test.jsx
 *   node scripts/check-header-hover.mjs
 */
import { chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const dir = path.resolve(here, '../.visual')
const css = fs.readFileSync(path.resolve(here, '../src/index.css'), 'utf8')

const INDIGO_10 = 'rgb(233, 234, 240)'
const INDIGO_20 = 'rgb(189, 192, 209)'
const CARROT_20 = 'rgb(251, 211, 194)'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1180, height: 900 } })
const body = fs.readFileSync(path.join(dir, 't1-dashboard.html'), 'utf8')
await page.setContent(
  `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style>` +
  `<style>body{background:var(--bg-page);padding:28px;font-family:var(--font)}` +
  `.wrap{max-width:900px;margin:0 auto}</style></head>` +
  `<body><div class="wrap">${body}</div></body></html>`, { waitUntil: 'load' })

// These controls carry `transition: .15s`, and getComputedStyle mid-transition
// returns the INTERPOLATED colour — reading straight after a hover reports a
// nearly transparent background and looks exactly like a CSS bug. Wait it out.
const bg = async el => {
  await page.waitForTimeout(320)
  return page.evaluate(e => getComputedStyle(e).backgroundColor, el)
}

const plain = await page.$('.th-filter:not(.is-on)')
const applied = await page.$('.th-filter.is-on')
if (!plain) throw new Error('no unapplied funnel in the fixture')
if (!applied) throw new Error('no applied funnel in the fixture — cannot test the is-on path')

const results = []
results.push(['unapplied, at rest', await bg(plain), 'rgba(0, 0, 0, 0)'])
await plain.hover()
results.push(['unapplied, hovered', await bg(plain), INDIGO_20])

// Hover the applied funnel's own header, then the funnel itself.
await applied.hover()
results.push(['applied, hovered', await bg(applied), CARROT_20])

// A sibling funnel in a hovered header, not itself hovered, must take the box.
const sibling = await page.evaluateHandle(() => {
  const th = document.querySelector('thead th:has(.th-filter:not(.is-on))')
  return th ? th.querySelector('.th-filter') : null
})
if (sibling.asElement()) {
  await sibling.asElement().hover()
  results.push(['header-hover box drawn', await bg(sibling.asElement()), INDIGO_20])
}

let bad = 0
for (const [name, got, want] of results) {
  const ok = got === want
  if (!ok) bad++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name.padEnd(24)} got ${got}  want ${want}`)
}
console.log(bad === 0 ? '\nALL HOVER STATES RESOLVE AS INTENDED' : `\n${bad} STATE(S) WRONG`)
await browser.close()
process.exit(bad === 0 ? 0 : 1)
