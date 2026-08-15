import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it, expect } from 'vitest'

/**
 * Policy guard, not a unit test.
 *
 * Every date and time GSHK sees is a Hong Kong date (Levi, 2026-08-16). Storage
 * stays UTC; display is converted. `toLocaleDateString`/`toLocaleString` without
 * an explicit timeZone silently renders in whatever zone the viewer's machine is
 * in — which was right only because the team happens to sit at UTC+8. This test
 * fails the build if a new call site skips lib/format.js, because the bug it
 * causes is a one-day error that looks entirely plausible on screen.
 */
// Vitest runs from frontend/; import.meta.url is not a file: URL under jsdom.
const SRC = join(process.cwd(), 'src')
const ALLOWED = ['lib/format.js']   // the one place the zone is named
const rel = (f) => f.replace(/\\/g, '/').split('/src/')[1]

function walk(dir) {
  return readdirSync(dir).flatMap(name => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.(jsx?|tsx?)$/.test(name) ? [full] : []
  })
}

describe('timezone policy', () => {
  it('finds the source tree', () => {
    expect(walk(SRC).length).toBeGreaterThan(10)
  })

  it('routes every date/time render through lib/format.js', () => {
    const offenders = walk(SRC)
      .filter(f => !/\.test\.[jt]sx?$/.test(f))
      .filter(f => !ALLOWED.some(a => rel(f) === a))
      // toLocaleString on a number is fine — only Date rendering is in scope.
      .filter(f => /(?:Date\([^)]*\)|\biso\b|\bts\b)[^\n]*\.toLocale(Date|Time)?String\s*\(/
        .test(readFileSync(f, 'utf8')))
      .map(rel)

    expect(offenders, 'import formatDate/formatDateTime from lib/format.js instead')
      .toEqual([])
  })

  it('names Asia/Hong_Kong in exactly one module', () => {
    const named = walk(SRC)
      .filter(f => !/\.test\.[jt]sx?$/.test(f))
      .filter(f => readFileSync(f, 'utf8').includes('Asia/Hong_Kong'))
      .map(rel)

    expect(named).toEqual(['lib/format.js'])
  })
})
