import { describe, it, expect } from 'vitest'
import { checkDigit, isValidHkid, idNumberProblem, PASSPORT_MAX } from './hkid.js'

/**
 * Brian's B14. This mirrors `backend/services/hkid.py` exactly — the API is
 * what actually refuses a bad number (D4: block on save), and this exists so
 * the operator is told before they lose the rest of the form.
 *
 * Two numbers below are real: `Z351007(9)` is the one identity document in
 * DEV whose check digit is wrong, and the 18-digit value is a Mainland China
 * ID filed under `id_type = 'hkid'` — 29 rows are in that state.
 */
describe('checkDigit', () => {
  it('computes the digit for a single-letter prefix', () => {
    // The single letter is RIGHT-justified into two characters and the pad
    // counts as 36. Treating it as one character gets every one of these
    // wrong.
    expect(checkDigit('A123456')).toBe('3')
  })

  it('computes the digit for a two-letter prefix', () => {
    expect(checkDigit('AB987654')).toBe('3')
  })

  it('yields A where the remainder is 10', () => {
    expect(checkDigit('G123456')).toBe('A')
  })

  it('returns null for something that is not an HKID at all', () => {
    expect(checkDigit('440782198611028063')).toBeNull()
    expect(checkDigit('')).toBeNull()
    expect(checkDigit('123456')).toBeNull()
  })
})

describe('isValidHkid', () => {
  it('accepts a correct number with or without brackets and spaces', () => {
    expect(isValidHkid('A123456(3)')).toBe(true)
    expect(isValidHkid('A1234563')).toBe(true)
    expect(isValidHkid('A123456 (3)')).toBe(true)
    expect(isValidHkid('  a123456(3) ')).toBe(true)
  })

  it('rejects the one wrong check digit in the book', () => {
    expect(isValidHkid('Z351007(9)')).toBe(false)
    expect(isValidHkid('Z351007(8)')).toBe(true)
  })

  it('rejects an 18-digit Mainland China ID', () => {
    expect(isValidHkid('440782198611028063')).toBe(false)
  })

  it('rejects a placeholder somebody typed', () => {
    expect(isValidHkid('xxxxxxx')).toBe(false)
  })
})

describe('idNumberProblem', () => {
  it('explains a bad HKID and suggests the likelier fix', () => {
    // 29 of the 30 unparseable rows are Mainland IDs mistyped as HKID. The
    // message has to point at the document TYPE, or an operator will retype a
    // correct number until they give up.
    const problem = idNumberProblem('hkid', '440782198611028063')

    expect(problem).toMatch(/check digit|Hong Kong identity card/i)
    expect(problem).toMatch(/document type/i)
  })

  it('says nothing about a correct HKID', () => {
    expect(idNumberProblem('hkid', 'A123456(3)')).toBeNull()
  })

  it('says nothing about an empty value — that is the required check\'s job', () => {
    expect(idNumberProblem('hkid', '')).toBeNull()
    expect(idNumberProblem('hkid', null)).toBeNull()
  })

  it('checks a passport for length only, because there is nothing else to check', () => {
    // A passport's only checksums are in the machine-readable zone and are
    // computed over the whole MRZ line, not the number. A "checksum" on the
    // number alone would validate nothing.
    expect(idNumberProblem('passport', 'Z351007')).toBeNull()
    expect(idNumberProblem('passport', 'X'.repeat(PASSPORT_MAX + 1)))
      .toMatch(new RegExp(String(PASSPORT_MAX)))
  })

  it('leaves other document types alone', () => {
    expect(idNumberProblem('china_id', '440782198611028063')).toBeNull()
    expect(idNumberProblem('other', 'anything at all')).toBeNull()
  })
})
