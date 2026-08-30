/**
 * Screenshot the workflow stages against the REAL stylesheet.
 *
 * `__visual__.test.jsx` (SHOOT=1) dumps each stage's markup; this wraps each
 * dump in the page shell, loads index.css, and shoots it. Not a test and not in
 * CI — a way to look at what was built rather than at the JSX that built it.
 *
 *   SHOOT=1 npx vitest run src/components/case/__visual__.test.jsx
 *   node scripts/shoot-stages.mjs
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

for (const file of fs.readdirSync(dir).filter(f => f.endsWith('.html'))) {
  const name = file.replace(/\.html$/, '')
  const body = fs.readFileSync(path.join(dir, file), 'utf8')
  await page.setContent(
    `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style>` +
    `<style>body{background:var(--bg-page);padding:28px;font-family:var(--font)}` +
    `.wrap{max-width:900px;margin:0 auto}</style></head>` +
    `<body><div class="wrap">${body}</div></body></html>`,
    { waitUntil: 'load' })
  // The webfont is remote; give it a beat or every shot is Times New Roman.
  await page.waitForTimeout(1200)
  const out = path.join(dir, `${name}.png`)
  await page.screenshot({ path: out, fullPage: true })
  console.log('shot', out)
}

await browser.close()
