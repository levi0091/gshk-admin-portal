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
 *
 * THE LAST STAGE, AND WHERE UNDO LIVES (Levi 2026-10-17). A sixth stage, CR
 * Status, used to follow and offered Undo when CR's poll said "rejected". CR
 * will not report that, so a rejection reaches GSHK by CR's own notice and the
 * operator records it here: the button says what it records, and the backend
 * takes it only on a filed case.
 */
export default function StageConfirmation({ data, reload, can }) {
  const receipt = data.receipt || data.manual_receipt || {}
  const unfinished = !data.applied_at && !data.undone_at
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [left, setLeft] = useState(null)
  const [confirmUndo, setConfirmUndo] = useState(false)
  // Any entry applied, not only a complete write-back: the backend's Undo gate.
  const anyApplied = Boolean(data.applied_at) || (data.entries || []).some(e => e.applied)
  const canUndo = anyApplied && !data.undone_at && Boolean(can?.tpsiSubmit)

  async function undo() {
    setConfirmUndo(false); setBusy(true); setError(null)
    try { await reload(await officerChangeApi.undo(data.id)) }
    catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

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
        {/* A FREE form's receipt has no payment block (CR TEST, case 141946253):
            no transaction date, time or refNo. The date is then when this portal
            filed it, and the reference is the one CR printed in the barcode. */}
        <div className="kv-row"><span className="kv-key">{receipt.transactionDate ? 'Transaction date' : 'Filed'}</span>
          <span className="kv-val">
            {receipt.transactionDate
              ? `${receipt.transactionDate}${receipt.transactionTime ? ` ${receipt.transactionTime}` : ''}`
              : (data.filing?.submitted_at ? formatDateTime(data.filing.submitted_at) : '—')}
          </span></div>
        {(receipt.refNo || receipt.documentRefNo) && (
          <div className="kv-row"><span className="kv-key">Document reference</span>
            <span className="kv-val">{receipt.refNo || receipt.documentRefNo}</span></div>
        )}
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

      {(canUndo || data.undone_at) && (
        <div className="oc-send-row">
          {canUndo && (
            <button className="btn btn-danger-outline btn-outline" disabled={busy}
                    onClick={() => setConfirmUndo(true)}>
              CR rejected it — undo profile update
            </button>
          )}
          {data.undone_at && (
            <span className="f-hint">Profile update undone {formatDateTime(data.undone_at)}.</span>
          )}
        </div>
      )}
      {error && !unfinished && (
        <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
          <div className="al-body">{error}</div></div>
      )}
      {confirmUndo && (
        <div className="modal-confirm" role="alertdialog" aria-label="Undo profile update">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Undo the profile update?</div>
            <div className="modal-confirm-text">
              Only when the Companies Registry rejected this filing. Officers this form appointed
              are removed, officers it ceased are restored, and the particulars CR holds go back
              to what they were. The supporting documents stay on the profiles.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setConfirmUndo(false)}>Cancel</button>
              <button className="btn btn-danger" onClick={undo}>Undo profile update</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
