import { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { formatMoney } from '../../lib/format.js'
import { describeError } from './workflow.js'

/** "09/10/2026" — the way CR and the printed form write a date. */
export function crDate(iso) {
  if (!iso) return null
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

/**
 * What one year means, in a sentence: when its return is made up to, where
 * that sits against today, and — if it is due — what CR would charge today.
 */
export function describeOption(o) {
  if (!o) return null
  if (!o.return_date) {
    return 'There is no incorporation date on the company record, so the '
      + 'return date cannot be shown here. The Companies Registry works it out '
      + 'from its own register.'
  }
  const made = `Made up to ${crDate(o.return_date)}`
  const days = o.days_since_return_date
  if (o.due == null || days == null) return `${made}.`
  if (!o.due) {
    const until = -days
    return `${made} — ${until} day${until === 1 ? '' : 's'} from now. The `
      + 'client can be asked to approve it now; the Companies Registry will '
      + `only validate it from ${crDate(o.return_date)}.`
  }
  const when = days === 0 ? 'today' : `${days} day${days === 1 ? '' : 's'} ago`
  const fee = o.fee
    ? ` Filed today, CR would charge HK$${formatMoney(o.fee.amount)} (${o.fee.band}).`
    : ''
  return `${made} — ${when}.${fee}`
}

/**
 * Which annual return this case files — CR's `yearAnnualReturn` (Levi
 * 2026-09-18).
 *
 * "If the company has not been filing NAR1 for the last 4 years then we should
 * be able to file 4 times (once for 2023, 2024, 2025, 2026)." One case is one
 * year's return, and the year is chosen HERE, at Client Verification, because
 * what the client approves is the return for one year: the preview below, the
 * email, CR's validation and the submission are all built for it.
 *
 * CR takes the year and derives the made-up date itself (the incorporation
 * anniversary in that year), so each option shows that date and — for a year
 * already due — what filing it today would cost, which is the fact that
 * decides the order a backlog is worked in.
 *
 * LOCKED once the return has been sent to the client, and the card says so
 * and says how to unlock it (Restart verification). Years another open case
 * of this company already files are shown but cannot be chosen: one return
 * per year.
 */
export default function ReturnYearCard({ caseRow, canWrite, onChanged, onError }) {
  const [info, setInfo] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoadError(null)
    api.get(`/cases/${caseRow.id}/return-year`)
      .then(r => { if (!cancelled) setInfo(r) })
      .catch(e => { if (!cancelled) setLoadError(describeError(e)) })
    return () => { cancelled = true }
  }, [caseRow.id, caseRow.updated_at])

  async function choose(year) {
    onError?.(null)
    setSaving(true)
    try {
      await api.patch(`/cases/${caseRow.id}`, { ar_period_year: year })
      onChanged()
    } catch (e) {
      onError?.(describeError(e))
    } finally {
      setSaving(false)
    }
  }

  // Defensive about the SHAPE, not just the arrival: this card sits at the top
  // of the stage, and a render error here would blank the whole case screen
  // (see the React #31 note in project memory). A payload without a year or
  // options renders as "could not be loaded", never as a crash.
  const options = Array.isArray(info?.options) ? info.options : []
  // `year: null` is a VALID answer — nobody has chosen one yet (Levi
  // 2026-09-19: "make it empty by default but mandatory"). Only a payload with
  // no options at all, or a year that is neither null nor a whole number, is
  // one this card cannot read.
  const chosen = Number.isInteger(info?.year)
  const usable = info && options.length > 0 && (chosen || info.year == null)
  const selected = chosen && (options.find(o => o.year === info.year)
    // A year outside today's range (a legacy case built for a year that has
    // since slid out of it) is still THE year; describe it from the payload.
    || { year: info.year, return_date: info.return_date, due: null })

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">Annual return year</div>
          <div className="card-sub">
            Which year's return this case files. The client approves the return
            for this year, and it is the year validated and filed with the
            Companies Registry.
          </div>
        </div>
      </div>

      {loadError || (info && !usable) ? (
        <div className="card-note card-note-warn" role="status">
          <b>The return year could not be loaded.</b>
          {loadError?.message && <div style={{ marginTop: 4 }}>{loadError.message}</div>}
        </div>
      ) : !info ? (
        <div className="empty-state" style={{ padding: 16 }}>Loading…</div>
      ) : (
        <>
          <div className="f-group">
            <label className="f-label" htmlFor="return-year">
              Return year<span className="f-req"> *</span>
            </label>
            <select
              id="return-year"
              className="f-input"
              style={{ maxWidth: 420 }}
              value={chosen ? info.year : ''}
              required
              aria-invalid={!chosen}
              disabled={!canWrite || info.locked || saving}
              onChange={e => { if (e.target.value) choose(Number(e.target.value)) }}
            >
              {/* EMPTY UNTIL CHOSEN (2026-09-19). The placeholder is the only
                  thing selected on a new case; it cannot be chosen back. */}
              {!chosen && (
                <option value="" disabled>Choose the return year…</option>
              )}
              {/* The case's year first even when it is outside the offered
                  range, so the select never shows a value it does not hold. */}
              {chosen && !options.some(o => o.year === info.year) && (
                <option value={info.year}>{info.year}</option>
              )}
              {options.map(o => (
                <option key={o.year} value={o.year}
                        disabled={Boolean(o.held_by) && o.year !== info.year}>
                  {o.year}
                  {o.return_date ? ` — made up to ${crDate(o.return_date)}` : ''}
                  {o.held_by
                    ? ` · already on ${o.held_by.case_no || 'another case'}`
                    : o.due === false ? ' · not due yet' : ''}
                </option>
              ))}
            </select>
            <span className="f-hint" data-testid="return-year-detail">
              {chosen
                ? describeOption(selected)
                : 'Required. Nothing can be previewed or sent to the client '
                  + 'until the year is chosen.'}
            </span>
          </div>

          {info.locked ? (
            <div className="card-note" role="status">
              🔒 The year is fixed: {info.locked_reason}.
            </div>
          ) : (
            <div className="f-hint" style={{ marginTop: 6 }}>
              The last 10 years are offered. Each year is its own case — to
              file several missed years, open a case for each. The year is
              fixed once the return is sent to the client.
            </div>
          )}
        </>
      )}
    </div>
  )
}
