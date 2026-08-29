import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { formatDate } from '../../lib/format.js'
import { describeError } from './workflow.js'

/**
 * "NAR1 return data · sourced from company profile" (wireframe_v11 s20, step 1).
 *
 * The shipped Data Verification screen jumped straight from two tick-boxes to
 * a "Validate with CR" button, so the operator was asked to approve a return
 * they had never been shown. This is that return, read off the live company
 * profile — the same graph the mapper builds the XML from, so what is on
 * screen is what CR will be sent.
 *
 * IT NO LONGER PRE-JUDGES THE COMPANY. This card used to render the mapper's
 * `problems` as a red "This company cannot be filed as a NAR1 yet" panel before
 * anyone had pressed anything. Levi 2026-08-30: don't. Every real GSHK client
 * tripped it — the signing capacity of a body-corporate secretary cannot be
 * derived — so the portal was refusing work the operator knew how to do. The
 * capacity is now a picker below, and everything else surfaces as CR's own
 * faults when CR is actually asked, rendered by the validation card.
 */

function Row({ label, children, empty = 'Not on record' }) {
  const missing = children == null || children === '' ||
    (Array.isArray(children) && children.length === 0)
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">
        {missing ? <span className="td-muted">{empty}</span> : children}
      </span>
    </div>
  )
}

export default function ReturnDataCard({ caseId, reloadKey, onChanged }) {
  const [data, setData] = useState(undefined)
  const [error, setError] = useState(null)
  // Kept apart from `error`: a failed LOAD means there is no card to draw and
  // the whole thing becomes a message, but a failed SAVE must leave the card
  // standing — replacing the operator's data with an error box would hide the
  // return they were reading.
  const [saveError, setSaveError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let live = true
    setError(null)
    api.get(`/cases/${caseId}/return-data`)
      .then(d => { if (live) setData(d) })
      .catch(e => { if (live) { setError(describeError(e)); setData(null) } })
    return () => { live = false }
  }, [caseId, reloadKey])

  async function saveCapacity(value) {
    // Optimistic, so the select does not snap back to blank while the PATCH is
    // in flight. A failure re-reads rather than guessing what the server kept.
    setData(d => ({ ...d, signatory_capacity: value }))
    setSaving(true); setSaveError(null)
    try {
      await api.patch(`/cases/${caseId}`, { signatory_capacity: value })
      // Re-read rather than trust the optimistic value: the capacity is an
      // INPUT to the mapper, so every other field the mapper decides — the
      // resolved signatory included — may have changed with it.
      setData(await api.get(`/cases/${caseId}/return-data`))
      onChanged?.()
    } catch (e) {
      setSaveError(describeError(e))
      try {
        setData(await api.get(`/cases/${caseId}/return-data`))
      } catch { /* the save error is the more useful of the two */ }
    } finally {
      setSaving(false)
    }
  }

  if (data === undefined) {
    return (
      <div className="card mb-16">
        <div className="empty-state" style={{ padding: 20 }}>Reading the company profile…</div>
      </div>
    )
  }
  if (error) {
    return (
      <div className="card mb-16">
        <div className="alert al-warn" role="alert">
          <span className="al-icon">⚠</span>
          <div className="al-body">
            <b>Could not read this company's return data.</b> {error.message}
          </div>
        </div>
      </div>
    )
  }
  if (!data) return null

  const shares = (data.share_classes || [])
    .map(sc => `${sc.total_issued ?? '?'} ${sc.name || 'shares'}`)
    .join(' · ')

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">NAR1 return data</div>
          <div className="card-sub">
            Sourced from the company profile — this is what the Companies
            Registry will be sent. Correct it on the company profile, not here.
          </div>
        </div>
      </div>

      <div className="kv-list">
        <Row label="Company name">
          {data.company_name}
          {data.company_name_zh && (
            <span className="td-muted"> · {data.company_name_zh}</span>
          )}
        </Row>
        <Row label="BR number">{data.br_number}</Row>
        <Row label="Return year">{data.year}</Row>
        <Row label="Registered office">{data.registered_office}</Row>
        <Row label="Directors">
          {data.directors?.length ? data.directors.join(' · ') : null}
        </Row>
        <Row label="Company secretary">
          {data.secretaries?.length ? data.secretaries.join(' · ') : null}
        </Row>
        <Row label="Members (Sch. 1)">
          {data.member_count
            ? `${data.member_count} member${data.member_count === 1 ? '' : 's'}${shares ? ` · ${shares}` : ''}`
            : null}
        </Row>
        <Row label="Share classes">
          {data.share_classes?.length
            ? `${data.share_classes.length} (${data.share_classes.map(s => s.name).join(', ')})`
            : null}
        </Row>
        {/* Who signs is the single most common reason a NAR1 cannot be filed,
            so it belongs beside the data rather than three stages away. */}
        <Row label="Signatory" empty="No eligible signatory on record">
          {data.signatory ? data.signatory.name : null}
        </Row>
        {/* THE ONE THING THE PORTAL CANNOT DERIVE. GSHK is the company
            secretary of the companies it files for and GSHK is a body
            corporate; a body corporate signs through a natural person, and CR's
            selectCapacityDesc says which one. Nothing in the company profile
            answers that — it depends on who at GSHK actually signs — so it is
            the operator's choice, from CR's own vocabulary.

            This used to be a red "cannot be filed" panel instead, which since
            every real GSHK client is in this position meant no real company
            could be prepared at all. Levi 2026-08-30: offer the choice, do not
            block on it. */}
        {data.signatory && (
          <div className="kv-row">
            <span className="kv-key">Signing capacity</span>
            <span className="kv-val">
              <select
                className="f-input"
                aria-label="Signing capacity"
                value={data.signatory_capacity || ''}
                disabled={saving}
                onChange={e => saveCapacity(e.target.value)}
              >
                <option value="">Choose how the signatory signs…</option>
                {(data.signatory_capacity_options || []).map(opt => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              {saveError && (
                <div className="f-hint" style={{ color: 'var(--carrot)', marginTop: 6 }}>
                  {saveError.message}
                </div>
              )}
            </span>
          </div>
        )}
        {data.incorporation_date && (
          <Row label="Incorporated">{formatDate(data.incorporation_date)}</Row>
        )}
      </div>

    </div>
  )
}
