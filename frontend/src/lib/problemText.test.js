import { describe, it, expect } from 'vitest'
import { splitProblem, splitLocator, splitFieldPath } from './problemText.js'

describe('splitProblem', () => {
  it('splits the real fault that started this — locator, fault, explanation', () => {
    // Verbatim from the screen Levi photographed on 2026-09-03.
    const { locator, headline, detail } = splitProblem(
      "corporate party CGAHCHBAABBG DIRECTOR COMPANY LIMITED: no CR region "
      + "code is known for country 'HK-CH' — CR's Country & Region sheet "
      + "(worksheet v1.0.14) carries no code, alpha-2 or English name matching "
      + "it; correct the address rather than guessing a code CR would take the "
      + "fee for and then reject")

    expect(locator).toBe('corporate party CGAHCHBAABBG DIRECTOR COMPANY LIMITED')
    expect(headline).toBe("No CR region code is known for country 'HK-CH'.")
    expect(detail).toMatch(/^CR's Country & Region sheet/)
    // Nothing is dropped on the floor.
    expect(detail).toMatch(/then reject\.$/)
  })

  it('keeps a fault with no explanation whole rather than inventing one', () => {
    const { locator, headline, detail } = splitProblem(
      'entity: no BR number')
    expect(locator).toBe('entity')
    expect(headline).toBe('No BR number.')
    expect(detail).toBeNull()
  })

  it('does not mistake a colon inside a sentence for a locator', () => {
    // The guard that matters: without it the first clause of an explanation
    // would be promoted to the card's eyebrow, where it reads as a party name.
    const text = 'The Companies Registry refused this. Reason: the form is stale'
    expect(splitProblem(text).locator).toBeNull()
    expect(splitProblem(text).headline).toBe(text + '.')
  })

  it('does not treat a long preamble as a locator', () => {
    const long = `${'x'.repeat(90)}: something`
    expect(splitProblem(long).locator).toBeNull()
  })

  it('leaves a fault that matches no shape entirely readable', () => {
    expect(splitProblem('something went wrong')).toEqual({
      locator: null, headline: 'Something went wrong.', detail: null,
    })
  })

  it('does not capitalise a value that is quoted or a code', () => {
    // Upper-casing 'HK-CH' would misreport what is on the record.
    expect(splitProblem("entity: 'hk-ch' is not a country").headline)
      .toBe("'hk-ch' is not a country.")
  })

  it('survives a null, an empty string and a non-string', () => {
    expect(splitProblem(null).headline).toBe('')
    expect(splitProblem('').headline).toBe('')
    expect(splitProblem(42).headline).toBe('42.')
  })
})

describe('splitLocator', () => {
  it('separates the register from the name the operator will search for', () => {
    expect(splitLocator('corporate party ACME LIMITED'))
      .toEqual({ kind: 'Corporate party', name: 'ACME LIMITED' })
  })

  it('prefers the longer locator — "corporate party" over "corporate"', () => {
    expect(splitLocator('corporate party X').kind).toBe('Corporate party')
  })

  it('names the company itself rather than showing the word "entity"', () => {
    expect(splitLocator('entity')).toEqual({ kind: 'This company', name: null })
  })

  it('keeps an unrecognised locator as its own words', () => {
    expect(splitLocator('registered office'))
      .toEqual({ kind: null, name: 'registered office' })
  })

  it('is null for nothing at all', () => {
    expect(splitLocator('')).toBeNull()
    expect(splitLocator(null)).toBeNull()
  })
})

describe('splitFieldPath', () => {
  it('separates the route through the form from the field at the end of it', () => {
    expect(splitFieldPath('Director (individual) 2 · Address · Building'))
      .toEqual({ path: ['Director (individual) 2', 'Address'], field: 'Building' })
  })

  it('handles a top-level field with no route', () => {
    expect(splitFieldPath('Business Registration number'))
      .toEqual({ path: [], field: 'Business Registration number' })
  })

  it('is empty for nothing at all', () => {
    expect(splitFieldPath('')).toEqual({ path: [], field: '' })
  })
})
