/**
 * Dates and times are STORED in UTC and DISPLAYED in Hong Kong time (Levi,
 * 2026-08-16). GSHK works to HK dates: statutory deadlines, the NAR1 42-day
 * window and the CR filing hours are all Hong Kong wall-clock, so a timestamp
 * shown in the viewer's own zone would be the wrong fact, not a local courtesy.
 *
 * Every formatter here pins the zone explicitly. Nothing in the app should call
 * toLocaleDateString/toLocaleString directly — the default is whatever zone the
 * browser happens to be in, which is right only by luck.
 */
export const HK_TZ = 'Asia/Hong_Kong'

/** "20 May 2024" — the Hong Kong calendar date. */
export function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-HK', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: HK_TZ,
  })
}

/**
 * "12 Apr 2026, 14:39" — Hong Kong wall-clock, 24-hour.
 *
 * Was copy-pasted into AuditTrailTab and AuditLogPage; one definition means the
 * two audit surfaces cannot drift apart, and there is one place to change.
 */
export function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-HK', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: HK_TZ,
  })
}

/**
 * Every number this app SHOWS carries thousands separators — 1,234,567 (Levi
 * 2026-09-07).
 *
 * THIS IS A DISPLAY FUNCTION AND NOTHING ELSE. It must never be applied to an
 * `<input value>`, to anything sent in a request body, or to a value on its way
 * back to the API: "1,234,567" is a string with commas in it, Postgres would
 * refuse it as a numeric, and the failure would land on a share capital figure
 * rather than anywhere obvious. Read the raw value, format it on the way to the
 * screen, and keep the two apart.
 *
 * THE LOCALE IS PINNED, for the same reason the date formatters pin the zone.
 * A bare `toLocaleString()` renders in whatever locale the browser happens to
 * carry, so the same share count reads 1,234,567 on one desk and 1.234.567 on
 * the next — and a figure whose separators change per machine is a figure
 * nobody can quote to CR with confidence.
 *
 * Returns `null` for an absent value rather than "0" or "—": the callers draw
 * their own em dash, and printing a zero where a company simply has no figure
 * on record would be inventing data.
 */
export function formatNumber(value, options) {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(String(value).trim())
  // Not a number at all — a legacy free-text figure out of the Viewpoint ETL,
  // say. Shown as it is stored: mangling it would hide what needs fixing.
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString('en-HK', options)
}

/**
 * Hong Kong dollars, grouped, always two decimals — "12,480.00".
 *
 * Was defined twice, identically, in StageSigning and StageSubmission: the two
 * screens quote the SAME fee and balance one step apart, and a bare "12480"
 * beside "3480.00" is unreadable. One definition so they cannot drift.
 *
 * Takes the amount as a string wherever it comes from the API — fees and
 * balances are Decimals server-side and are serialised as strings on purpose,
 * so they are not put through a float on the way here.
 */
export function formatMoney(value) {
  // ABSENT IS NOT ZERO, and the old copies of this function said it was:
  // `Number(null)` is 0, so a missing balance rendered "HK$ 0.00" — a specific
  // and alarming claim about GSHK's deposit account, made from having no
  // figure at all. `0` itself still formats, because a genuinely empty account
  // is a fact worth printing.
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n)
    ? n.toLocaleString('en-HK', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(value)
}
