/**
 * How close a company is to the anniversary of its incorporation.
 *
 * A Hong Kong annual return (NAR1) must reach the Companies Registry within
 * **42 days** of that anniversary, so the anniversary is how the team finds the
 * companies that need work — hence the Days-to-anniversary column on the
 * Company listing (UAT F-6 / W-2).
 *
 * Derived from `entities.incorporation_date` and nothing else. `ar_next_date`
 * looks like the obvious source and carries the right month-day on 99.6% of
 * DEV rows, but its YEAR is a Viewpoint snapshot that was never rolled forward
 * — 850 live client companies still hold an ar_next_date in 2020-2024. A value
 * recomputed from the incorporation date cannot go stale.
 *
 * Deliberately says nothing about whether a NAR1 was actually filed (Levi
 * 2026-08-15). "Overdue" is a compliance judgement that needs the filing fact,
 * and DEV has it on 2 of 7,959 NAR1 rows. These helpers report the date
 * relationship only.
 */

import { HK_TZ } from './format.js'

/**
 * The statutory NAR1 filing window, in days after the anniversary.
 *
 * Kept although nothing reads it as a value any more: `labelForDays` stopped
 * drawing a line at 42 on 2026-09-07 (see the note there), and the dashboard
 * banner spells the number out in its own prose. It stays because it is the
 * statutory fact, and because it is the threshold to reinstate if the register
 * turns out to be too loud.
 */
export const FILING_WINDOW_DAYS = 42

const MS_PER_DAY = 86400000

/**
 * Today's date in Hong Kong, as a plain calendar day.
 *
 * The browser clock is not the authority here. A deadline is a Hong Kong date,
 * so between 00:00 and 08:00 HKT a UTC machine would still call it yesterday
 * and every count would be one day out. The backend view is pinned to the same
 * zone, so the number the column prints and the number the server sorts by are
 * derived from the same "today".
 */
export function hongKongToday(now = new Date()) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: HK_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(now).map(({ type, value }) => [type, value])
  )
  return new Date(Number(p.year), Number(p.month) - 1, Number(p.day))
}

/** Midnight, so a partial day never rounds a boundary the wrong way. */
function midnight(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function parse(incorporationDate) {
  if (!incorporationDate) return null
  const d = new Date(`${String(incorporationDate).slice(0, 10)}T00:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * The anniversary in `year`. 29 February lands on 28 February in a common year
 * — the same fallback the DEV data check uses, so UI and analysis agree.
 */
function anniversaryIn(year, incorporated) {
  const month = incorporated.getMonth()
  const day = incorporated.getDate()
  const d = new Date(year, month, day)
  // Overflowed into the next month (29 Feb in a common year) — take the last
  // day of the intended month instead, which day 0 of the following one is.
  return d.getMonth() === month ? d : new Date(year, month + 1, 0)
}

/** Whole days until the next anniversary — 0 on the day itself, never negative. */
export function daysToAnniversary(incorporationDate, today = hongKongToday()) {
  const incorporated = parse(incorporationDate)
  if (!incorporated) return null
  const from = midnight(today)
  let next = anniversaryIn(from.getFullYear(), incorporated)
  if (next < from) next = anniversaryIn(from.getFullYear() + 1, incorporated)
  return Math.round((next - from) / MS_PER_DAY)
}

/** Whole days since the most recent anniversary — 0 on the day itself. */
export function daysSinceAnniversary(incorporationDate, today = hongKongToday()) {
  const incorporated = parse(incorporationDate)
  if (!incorporated) return null
  const from = midnight(today)
  let last = anniversaryIn(from.getFullYear(), incorporated)
  if (last > from) last = anniversaryIn(from.getFullYear() - 1, incorporated)
  return Math.round((from - last) / MS_PER_DAY)
}

const plural = (n, unit) => `${n} ${unit}${n === 1 ? '' : 's'}`

/**
 * The single signed number the column shows and the server sorts by.
 *
 * Whichever anniversary is NEARER, signed: negative when the last one is closer
 * than the next, positive otherwise. Range about -182..182.
 *
 * The switch used to happen at day 42 rather than at the midpoint, which meant a
 * company 43 days past its anniversary read +322 and no value below -42 could
 * exist at all — so clearing the column filter's lower bound revealed nothing,
 * and every company whose filing window had shut was hidden among the ones with
 * most of a year in hand (Levi 2026-09-04). Migration 033 made the same change
 * in `company_registry.days_to_anniversary`; the two MUST agree, or the number a
 * row prints and the number the server sorted it by come from different rules.
 */
export function signedDaysToAnniversary(incorporationDate, today = hongKongToday()) {
  const since = daysSinceAnniversary(incorporationDate, today)
  if (since === null) return null
  const until = daysToAnniversary(incorporationDate, today)
  return since <= until ? -since : until
}

/**
 * Render a signed day count. Taking the number as input — rather than the date —
 * is what lets the row display the value the SERVER computed, so the text and
 * the sort order cannot disagree.
 *
 * `overdue` is TRUE FOR EVERY PASSED ANNIVERSARY, not only the ones inside the
 * 42-day window (Levi 2026-09-07). It used to be the window, on the reasoning
 * that 2,262 of DEV's client companies sit between -43 and -182 and painting
 * them all would colour 38% of the register for a fact that is not a deadline.
 * What retired that argument is the wording: the cell now says "overdue", and a
 * row reading "50d overdue" in muted grey beside one reading "37d overdue" in
 * red says the more overdue company needs less attention. If the register turns
 * out to be too loud, narrow it HERE — `days >= -FILING_WINDOW_DAYS` — and both
 * listings follow, because neither one decides this for itself.
 */
export function labelForDays(days) {
  if (days == null) return { text: '—', overdue: false }
  // Day 0 is the anniversary itself: nothing is late yet, so it is not called
  // overdue — but it is the day the filing window opens, so it is still marked.
  if (days === 0) return { text: 'today', overdue: true }
  if (days < 0) return { text: `${-days}d overdue`, overdue: true }
  return { text: `in ${plural(days, 'day')}`, overdue: false }
}

/**
 * What the cell reads, and whether it should be highlighted.
 *
 * `overdue` marks a company whose anniversary has passed. Inside the first 42
 * days the return is still legally deliverable and the late fee has not
 * started; the cell does not draw that line, and the dashboard banner is where
 * the window is explained. See the note on `labelForDays`.
 */
export function anniversaryLabel(incorporationDate, today = hongKongToday()) {
  return labelForDays(signedDaysToAnniversary(incorporationDate, today))
}
