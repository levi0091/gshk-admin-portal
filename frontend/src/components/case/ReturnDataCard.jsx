import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { formatDate } from '../../lib/format.js'
import { describeError } from './workflow.js'
import FaultPanel from './FaultPanel.jsx'

/**
 * "NAR1 return data · sourced from company profile" (wireframe_v11 s20, step 1).
 *
 * The shipped Data Verification screen jumped straight from two tick-boxes to
 * a "Validate with CR" button, so the operator was asked to approve a return
 * they had never been shown. This is that return, read off the live company
 * profile — the same graph the mapper builds the XML from, so what is on
 * screen is what CR will be sent.
 *
 * It also carries the mapper's verdict. `problems` here are OUR refusal to
 * build the form (fix the company record); CR's `faults`, rendered by the
 * validation card below, are CR refusing a form we did build (fix the form).
 * They are never merged — they send the operator to different screens.
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

export default function ReturnDataCard({ caseId, reloadKey }) {
  const [data, setData] = useState(undefined)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    setError(null)
    api.get(`/cases/${caseId}/return-data`)
      .then(d => { if (live) setData(d) })
      .catch(e => { if (live) { setError(describeError(e)); setData(null) } })
    return () => { live = false }
  }, [caseId, reloadKey])

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
        <Row label="Signatory" empty="No eligible signatory — see below">
          {data.signatory
            ? `${data.signatory.name} (${data.signatory.capacity})`
            : null}
        </Row>
        {data.incorporation_date && (
          <Row label="Incorporated">{formatDate(data.incorporation_date)}</Row>
        )}
      </div>

      {data.problems?.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <FaultPanel
            faults={data.problems}
            title="This company cannot be filed as a NAR1 yet"
          />
        </div>
      )}
    </div>
  )
}
