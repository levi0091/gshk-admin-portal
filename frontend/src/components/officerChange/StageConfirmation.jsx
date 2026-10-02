import { useState } from 'react'
import ProfileChangesList from './ProfileChangesList.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'
import { formatDateTime } from '../../lib/format.js'

/**
 * Stage 5 (answer 13): CR's receipt, and in the past tense what was written to
 * the profiles and which supporting documents were saved where.
 *
 * A filed form whose profile update did not finish says so here, with the way
 * to finish it: the update is per entry and idempotent, so pressing it again
 * completes only what is missing. Undone after a CR rejection, it is not
 * offered — that case is put back on purpose.
 */
export default function StageConfirmation({ data, reload, can, goTo }) {
  const receipt = data.receipt || data.manual_receipt || {}
  const unfinished = !data.applied_at && !data.undone_at
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [left, setLeft] = useState(null)

  async function finish() {
    setBusy(true); setError(null)
    try {
      const res = await officerChangeApi.retryApply(data.id)
      setLeft(res?.write_back?.errors?.length ? res.write_back.errors : null)
      await reload(res)
    } catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="card">
        <div className="card-title">Filed with the Companies Registry</div>
        <div className="kv-row"><span className="kv-key">CR case number</span>
          <span className="kv-val">{receipt.caseNo || '—'}</span></div>
        <div className="kv-row"><span className="kv-key">Transaction date</span>
          <span className="kv-val">{receipt.transactionDate || '—'}
            {receipt.transactionTime ? ` ${receipt.transactionTime}` : ''}</span></div>
        {receipt.refNo && <div className="kv-row"><span className="kv-key">Document reference</span>
          <span className="kv-val">{receipt.refNo}</span></div>}
        <div className="kv-row"><span className="kv-key">Route</span>
          <span className="kv-val">{data.signing_method === 'manual' ? 'Manual (CR portal)' : 'e-Sign via CR'}</span></div>
        {data.applied_at && <div className="kv-row"><span className="kv-key">Profiles updated</span>
          <span className="kv-val">{formatDateTime(data.applied_at)}</span></div>}
      </div>

      {unfinished && (
        <div className="alert al-warn" role="alert" style={{ marginTop: 16 }}>
          <div className="al-body">
            <b>The profile update did not finish.</b> CR has the form; some officers&apos; profiles
            have not been updated yet.
            {(left || []).length > 0 && (
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{left.map(l => <li key={l}>{l}</li>)}</ul>
            )}
            {can?.tpsiSubmit ? (
              <div style={{ marginTop: 8 }}>
                <button className="btn btn-outline btn-sm" disabled={busy} onClick={finish}>
                  {busy ? 'Updating…' : 'Finish the profile update'}
                </button>
              </div>
            ) : (
              <div style={{ marginTop: 6 }}>Finishing it needs Companies Registry filing (File with CR).</div>
            )}
            {error && <div style={{ marginTop: 6 }}>{error}</div>}
          </div>
        </div>
      )}

      <ProfileChangesList changes={data.profile_changes} documents={data.documents} done={!unfinished} />
      <div className="oc-send-row">
        <button className="btn btn-primary" onClick={() => goTo(6)}>Continue to CR Status →</button>
      </div>
    </>
  )
}
