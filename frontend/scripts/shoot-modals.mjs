/**
 * Screenshot the dialogs against the REAL stylesheet.
 *
 * `__modals_visual__.test.jsx` (SHOOT=1) dumps each modal's markup; this loads
 * index.css, puts the dump on a page-coloured backdrop and shoots it. Not a
 * test and not in CI — a way to look at what an operator sees.
 *
 * It also MEASURES: a modal whose content is wider than its own box is the bug
 * this harness exists for, and a picture alone will not tell you it is 4px out.
 *
 *   SHOOT=1 npx vitest run src/components/__modals_visual__.test.jsx
 *   node scripts/shoot-modals.mjs
 */
import { chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const dir = path.resolve(here, '../.visual')
const css = fs.readFileSync(path.resolve(here, '../src/index.css'), 'utf8')

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1180, height: 1000 } })

let bad = 0
const dumps = fs.readdirSync(dir)
  .filter(f => /^[ms]\d/.test(f) && f.endsWith('.html'))
  .sort()

for (const file of dumps) {
  const name = file.replace(/\.html$/, '')
  const body = fs.readFileSync(path.join(dir, file), 'utf8')
  // `s*` dumps are page cards, which need the page's own gutter; `m*` dumps
  // are dialogs, which bring their own full-viewport overlay.
  const pad = name.startsWith('s') ? 'padding:28px;' : ''
  await page.setContent(
    `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style>` +
    `<style>body{background:var(--bg-page);font-family:var(--font);${pad}}` +
    `.detail-grid{max-width:900px;margin:0 auto}</style></head>` +
    `<body>${body}</body></html>`,
    { waitUntil: 'load' })
  await page.waitForTimeout(1200)   // the webfont is remote

  // Does anything stick out of the dialog? scrollWidth > clientWidth is the
  // overflow that was being reported by eye. Page cards have no fixed box to
  // measure against, so they are shot without the assertion.
  const report = await page.evaluate(() => {
    const modal = document.querySelector('.modal')
    if (!modal) return null
    const box = modal.getBoundingClientRect()
    const strays = [...modal.querySelectorAll('*')]
      .map(el => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.width && (r.right > box.right + 0.5 || r.left < box.left - 0.5))
      .map(({ el, r }) => `${el.className || el.tagName} +${(r.right - box.right).toFixed(1)}`)
    const body = modal.querySelector('.modal-body')
    return {
      width: Math.round(box.width),
      overflowX: modal.scrollWidth - modal.clientWidth,
      bodyOverflowX: body ? body.scrollWidth - body.clientWidth : 0,
      strays: strays.slice(0, 6),
    }
  })

  const ok = !report || (report.overflowX <= 0 && report.bodyOverflowX <= 0
                         && report.strays.length === 0)
  if (!ok) bad += 1
  console.log(`${ok ? 'OK  ' : 'BAD '} ${name.padEnd(22)} ` +
              `${report ? JSON.stringify(report) : '(page cards — shot only)'}`)

  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true })
}

await browser.close()
console.log(bad ? `${bad} dialog(s) overflow` : 'no dialog overflows its box')
process.exit(bad ? 1 : 0)
