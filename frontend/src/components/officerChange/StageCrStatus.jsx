import { useState } from 'react'
import { crStatus } from '../case/workflow.js'
import { formatDateTime } from '../../lib/format.js'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/**
 * Stage 6: what CR's register says, asked through the same poller NAR1 uses.
 * On a REJECTION the profile update can be undone — the profiles were updated
 * when the form was filed (spec B-5), so a refusal leaves them claiming a change
 * CR did not accept.
 */
export default function StageCrStatus({ data, reload, can }) {
  const [busy, setBusy] = useState(false)
  const [confirmUndo, setConfirmUndo] = useState(false)
  const [error, setError] = useState(null)
  const status = crStatus(data)
  // `cr_text` is what the backend sends (doc_status.describe): CR's exact words.
  const crText = data.cr_status?.cr_text || null
  const rejected = data.cr_status?.code === 'cr_rejected'
  // Any entry applied, not only a complete write-back: the backend's Undo gate.
  const anyApplied = Boolean(data.applied_at) || (data.entries || []).some(e => e.applied)
  const canUndo = rejected && anyApplied && !data.undone_at && can.tpsiSubmit

  async function check() {
    setBusy(true); setError(null)
    try { await officerChangeApi.refreshCrStatus(data.id); await reload() }
    catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  async function undo() {
    setConfirmUndo(false); setBusy(true); setError(null)
    try { await reload(await officerChangeApi.undo(data.id)) }
    catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  return (
    <div className="card">
      <div className="card-hdr">
        <div>
          <div className="card-title">CR Status</div>
          <div className="card-sub">
            {data.cr_status_checked_at ? `Last asked ${formatDateTime(data.cr_status_checked_at)}.`
              : 'Not yet checked with CR.'}
          </div>
        </div>
        {/* On an answer this portal does not recognise, CR's own words are
            the only thing that says anything — they go on the badge. */}
        <span className="badge">
          {data.cr_status?.code === 'cr_unknown' && crText ? crText : status.label}
        </span>
      </div>
      {crText && <div className="cr-quote">CR says: “{crText}”</div>}
      <div className="oc-send-row">
        {can.tpsiRead && (
          <button className="btn btn-outline" disabled={busy} onClick={check}>
            {busy ? 'Checking…' : 'Check now'}
          </button>
        )}
        {canUndo && (
          <button className="btn btn-danger-outline btn-outline" onClick={() => setConfirmUndo(true)}>
            Undo profile update
          </button>
        )}
        {data.undone_at && <span className="f-hint">Profile update undone {formatDateTime(data.undone_at)}.</span>}
      </div>
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
        <div className="al-body">{error}</div></div>}
      {confirmUndo && (
        <div className="modal-confirm" role="alertdialog" aria-label="Undo profile update">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Undo the profile update?</div>
            <div className="modal-confirm-text">
              Officers this form appointed are removed, officers it ceased are restored, and the
              particulars CR holds go back to what they were. The supporting documents stay on the
              profiles.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setConfirmUndo(false)}>Cancel</button>
              <button className="btn btn-danger" onClick={undo}>Undo profile update</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
