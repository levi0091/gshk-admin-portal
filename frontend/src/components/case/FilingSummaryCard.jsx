import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { describeError } from './workflow.js'

/**
 * "Final summary · to be filed with the Companies Registry" (wireframe_v11 §4).
 *
 * The last thing anyone reads before an irreversible HK$105 charge, so it is
 * read out of the FROZEN XML — `/tpsi/filings/{id}/summary` — and not out of
 * the company profile. If the profile moved after validation, this still shows
 * what CR will actually receive; the mismatch is the cue to restart
 * verification, and hiding it behind a live re-read would turn that into a
 * surprise on the receipt.
 *
 * The presenter and deposit account number are deliberately absent: they are a
 * super-admin-only field (routers/tpsi.py `_deposit_account`). The fee and the
 * balance are shown by the card below this one, which is what a filer needs.
 */

function Row({ label, children }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">
        {children == null || children === ''
          ? <span className="td-muted">—</span>
          : children}
      </span>
    </div>
  )
}

export default function FilingSummaryCard({ filingId }) {
  const [data, setData] = useState(undefined)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!filingId) { setData(null); return }
    let live = true
    setError(null)
    api.get(`/tpsi/filings/${filingId}/summary`)
      .then(d => { if (live) setData(d) })
      .catch(e => { if (live) { setError(describeError(e)); setData(null) } })
    return () => { live = false }
  }, [filingId])

  if (!filingId) return null

  if (data === undefined) {
    return (
      <div className="card mb-16">
        <div className="empty-state" style={{ padding: 20 }}>
          Reading the return that will be filed…
        </div>
      </div>
    )
  }
  if (error) {
    return (
      <div className="card mb-16">
        <div className="alert al-warn" role="alert">
          <span className="al-icon">⚠</span>
          <div className="al-body">
            <b>Could not read the return that is about to be filed.</b>{' '}
            {error.message} Do not file until this shows the return.
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
          <div className="card-title">Final summary — to be filed with the Companies Registry</div>
          <div className="card-sub">
            Read from the CR-validated snapshot, not from the company profile.
            If this disagrees with the profile, restart verification rather than
            filing.
          </div>
        </div>
      </div>

      <div className="kv-list">
        <Row label="Form">
          {data.form_code === 'Nar1' ? 'NAR1 · Annual Return' : data.form_code}
          {data.has_schedule_1 ? ' + Schedule 1' : ''}
        </Row>
        <Row label="Company">
          {data.company_name}
          {data.br_number ? ` (BRN ${data.br_number})` : ''}
        </Row>
        <Row label="Return year">{data.year}</Row>
        <Row label="Registered office">{data.registered_office}</Row>
        <Row label="Directors">
          {data.directors?.length ? data.directors.join(' · ') : null}
        </Row>
        <Row label="Company secretary">
          {data.secretaries?.length ? data.secretaries.join(' · ') : null}
        </Row>
        <Row label="Members / shares">
          {data.member_count
            ? `${data.member_count} member${data.member_count === 1 ? '' : 's'}${shares ? ` · ${shares}` : ''}`
            : null}
        </Row>
        <Row label="Signature">
          {data.signatory?.name
            ? `${data.signed_at ? '✓ Signed — ' : ''}${data.signatory.name}` +
              `${data.signatory.capacity ? ` (${data.signatory.capacity})` : ''}` +
              `${data.signatory.date ? ` · ${data.signatory.date}` : ''}`
            : null}
        </Row>
        <Row label="Fee paid from">
          GSHK's presenter deposit account — <b>not</b> a company account
        </Row>
      </div>
    </div>
  )
}
