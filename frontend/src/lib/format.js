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
