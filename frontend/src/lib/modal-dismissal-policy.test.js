import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it, expect } from 'vitest'

/**
 * Policy guard, not a unit test.
 *
 * A dialog closes from its own × or Cancel and from nothing else (Levi,
 * 2026-10-30: "it is irritating when it disappears so easily"). A drag that
 * starts in a box and ends outside it counts as a backdrop click, so an operator
 * selecting text could lose what they had keyed with no idea why. This fails the
 * build if a new dialog copies the old backdrop handler back in.
 */
// Vitest runs from frontend/; import.meta.url is not a file: URL under jsdom.
const SRC = join(process.cwd(), 'src')

function walk(dir) {
  return readdirSync(dir).flatMap(name => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.jsx$/.test(name) && !/\.test\./.test(name) ? [full] : []
  })
}

describe('modal dismissal policy', () => {
  const sources = walk(SRC).map(file => [file, readFileSync(file, 'utf8')])
  const dialogs = sources.filter(([, text]) => text.includes('className="overlay"'))

  it('finds the dialogs', () => {
    expect(dialogs.length).toBeGreaterThan(10)
  })

  it('no backdrop closes a dialog', () => {
    const offenders = sources
      .filter(([, text]) => /className="(overlay|oc-drawer-wrap)"[^>]*on(Click|MouseDown)=/.test(text))
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })

  it('every dialog has a way out of its own', () => {
    const stuck = dialogs
      .filter(([, text]) => !/modal-close|Cancel|Close|Done/.test(text))
      .map(([file]) => file)
    expect(stuck).toEqual([])
  })
})
