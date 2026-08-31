/**
 * The address shape the profile forms draft and send.
 *
 * An address is a row in its own table that a company or person POINTS AT, not
 * a set of columns on either — which is why it is drafted and saved separately
 * from the rest of the form, and why the server may answer a save by creating
 * a new row rather than editing the one you were looking at.
 */

/** The five fields CR takes. A missing address edits from blank, not undefined. */
export const EMPTY_ADDRESS = {
  line1: '', line2: '', line3: '',
  city: '', state_region: '', postal_code: '', country: '',
}

/** Only the columns the endpoint accepts — `id` and `shared_by` are read-only. */
export function addressPayload(a) {
  return Object.fromEntries(Object.keys(EMPTY_ADDRESS).map(k => [k, a?.[k] || null]))
}

/** Did anything actually change? An unchanged address must not be re-sent —
 *  the server writes one audit entry per changed line. */
export function addressChanged(draft, current) {
  const before = addressPayload(current)
  const after = addressPayload(draft)
  return Object.keys(EMPTY_ADDRESS).some(k => before[k] !== after[k])
}
