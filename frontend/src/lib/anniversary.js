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

/** The statutory NAR1 filing window, in days after the anniversary. */
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
 */
export function labelForDays(days) {
  if (days == null) return { text: '—', due: false }
  if (days === 0) return { text: 'today', due: true }
  // `due` is the 42-day window, NOT merely "negative". Once the count could run
  // past -42 (migration 033) that distinction started carrying weight: 2,262 of
  // DEV's client companies sit between -43 and -182, and highlighting all of
  // them would paint 38% of the register carrot for a fact that is not a
  // deadline. Inside the window the return is deliverable today and the row
  // wants acting on; outside it, the cell states a date relationship and lets
  // the operator's filter do the asking.
  if (days < 0) {
    return { text: `${plural(-days, 'day')} ago`, due: days >= -FILING_WINDOW_DAYS }
  }
  return { text: `in ${plural(days, 'day')}`, due: false }
}

/**
 * What the cell reads, and whether it should be highlighted.
 *
 * `due` marks a company inside the 42-day filing window — the anniversary has
 * passed and the return is still legally deliverable. Past that the cell keeps
 * counting up, quietly, until the next anniversary is the nearer of the two and
 * it starts counting down again.
 */
export function anniversaryLabel(incorporationDate, today = hongKongToday()) {
  return labelForDays(signedDaysToAnniversary(incorporationDate, today))
}
