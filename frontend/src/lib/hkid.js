/**
 * The Hong Kong identity card check digit (Brian's B14).
 *
 * A MIRROR of `backend/services/hkid.py`, not a substitute for it. The API is
 * what actually refuses a bad number — this exists so the operator is told
 * while they are looking at the field, rather than after a save that discards
 * the rest of the form.
 *
 * THE ALGORITHM, and the part everyone gets wrong: the letter prefix is
 * RIGHT-JUSTIFIED into two characters. A single-letter prefix takes a leading
 * space, and that space counts as 36 — not zero, and not nothing. Letters run
 * A=10 to Z=35. Weights are 9 down to 2 across the eight characters, and the
 * whole sum including the check digit must be divisible by 11. A check digit
 * of "A" means 10.
 *
 * Measured against DEV: 452 of the 483 stored HKIDs pass, one fails its check
 * digit (`Z351007(9)`), and 30 do not parse — 29 of those being 18-digit
 * Mainland China ID numbers filed under `id_type = 'hkid'`.
 */

/** CR's cap on `indvPptNo`. There is no check digit to go with it. */
export const PASSPORT_MAX = 25

const PATTERN = /^([A-Z]{1,2})(\d{6})\s*\(?([0-9A])\)?$/
const PREFIX_ONLY = /^([A-Z]{1,2})(\d{6})$/

const SPACE_VALUE = 36
const letterValue = ch => ch.charCodeAt(0) - 'A'.charCodeAt(0) + 10

/**
 * The check digit for a prefix-and-six-digits, or null if that is not what
 * this is. Returns a STRING because "A" is a legal check digit.
 */
export function checkDigit(prefixAndDigits) {
  const match = PREFIX_ONLY.exec(String(prefixAndDigits ?? '').trim().toUpperCase())
  if (!match) return null

  const [, prefix, digits] = match
  // Right-justified to two characters; the pad is worth 36.
  const head = prefix.length === 1
    ? [SPACE_VALUE, letterValue(prefix)]
    : [letterValue(prefix[0]), letterValue(prefix[1])]
  const values = [...head, ...digits.split('').map(Number)]

  let total = 0
  values.forEach((value, i) => { total += value * (9 - i) })

  const remainder = (11 - (total % 11)) % 11
  return remainder === 10 ? 'A' : String(remainder)
}

/** Whether a stored HKID is internally consistent. */
export function isValidHkid(number) {
  const match = PATTERN.exec(String(number ?? '').trim().toUpperCase())
  if (!match) return false
  const [, prefix, digits, check] = match
  return checkDigit(prefix + digits) === check
}

/**
 * What is wrong with this identity number, in words — or null.
 *
 * Only HKID and passport are checked. `china_id` and `other` are left alone
 * on purpose: this portal does not hold a validator for every country's
 * documents, and pretending otherwise would reject correct data.
 */
export function idNumberProblem(idType, number) {
  const value = String(number ?? '').trim()
  // Empty is not this function's business — a required field says so itself,
  // and complaining twice about one blank box helps nobody.
  if (!value) return null

  if (idType === 'hkid' && !isValidHkid(value)) {
    return 'This is not a valid Hong Kong identity card number — the check '
      + 'digit does not match. If it is a Mainland or other identity '
      + 'document, change the document type instead of retyping the number.'
  }
  if (idType === 'passport' && value.length > PASSPORT_MAX) {
    return `${value.length} characters — the Companies Registry accepts `
      + `${PASSPORT_MAX} for a passport number.`
  }
  return null
}
