/**
 * Measure the table header's hit targets against the REAL stylesheet.
 *
 * The point of the 2026-09-04 second pass was to grow the sort and filter
 * targets WITHOUT growing the header row — the negative block margin on
 * `.th-inner` is what buys that, and it is exactly the sort of thing that is
 * easy to get wrong and impossible to see in a diff. So measure it.
 *
 *   SHOOT=1 npx vitest run src/pages/__tables_visual__.test.jsx
 *   node scripts/measure-headers.mjs
 */
import { chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const dir = path.resolve(here, '../.visual')
const css = fs.readFileSync(path.resolve(here, '../src/index.css'), 'utf8')

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1180, height: 900 } })

const body = fs.readFileSync(path.join(dir, 't1-dashboard.html'), 'utf8')
await page.setContent(
  `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style>` +
  `<style>body{background:var(--bg-page);padding:28px;font-family:var(--font)}` +
  `.wrap{max-width:900px;margin:0 auto}</style></head>` +
  `<body><div class="wrap">${body}</div></body></html>`,
  { waitUntil: 'load' })

const out = await page.evaluate(() => {
  const box = el => { const r = el.getBoundingClientRect(); return { w: +r.width.toFixed(1), h: +r.height.toFixed(1) } }
  const th = document.querySelector('thead th')
  const sort = document.querySelector('.th-sort')
  const filter = document.querySelector('.th-filter')
  // Distance between the sort glyph's right edge and the funnel's left edge, in
  // the same header cell: the strip where a near miss re-sorts the table.
  const cell = document.querySelector('thead th .th-inner')
  const s = cell?.querySelector('.th-sort')?.getBoundingClientRect()
  const f = cell?.querySelector('.th-filter')?.getBoundingClientRect()
  return {
    headerRow: +document.querySelector('thead tr').getBoundingClientRect().height.toFixed(1),
    th: box(th),
    sortTarget: box(sort),
    filterTarget: box(filter),
    gapBetween: s && f ? +(f.left - s.right).toFixed(1) : null,
    sortArea: Math.round(box(sort).w * box(sort).h),
    filterArea: Math.round(box(filter).w * box(filter).h),
  }
})
console.log(JSON.stringify(out, null, 2))
await browser.close()
