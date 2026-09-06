import { useState } from 'react'
import { api } from '../../lib/api.js'
import { describeError } from './workflow.js'

/**
 * Ending a case the client is not proceeding with. IRREVERSIBLE.
 *
 * TWO THINGS ARE ASKED FOR, and neither is ceremony.
 *
 * The REASON is the only record of why. Everything else about a closure can be
 * reconstructed later from the row — when, from `closed_at`; by whom, from
 * `closed_by`. Why cannot. Six months on, the case is a dead row with no filing
 * and no client answer, and without this the only honest reading is "somebody
 * closed it", which is the question being asked. The backend requires it too;
 * asking here means the operator writes it while they still know it, rather
 * than meeting a 400 and inventing one.
 *
 * The CASE NUMBER typed back is the deliberate-action check. `modal-confirm`'s
 * Cancel/Confirm pair is right for Restart — which is undoable by redoing the
 * work — and is not enough for a button with no undo at all. Typing the number
 * that is printed two lines above it is the smallest thing that cannot be done
 * by muscle memory, and it makes the operator look at WHICH case they are on:
 * a workflow screen is reached from a list, and closing the case above the one
 * you meant is the mistake that has no remedy. It is compared
 * case-insensitively and trimmed — the check is against absent-mindedness, not
 * against typing.
 *
 * The screen never claims the close succeeded until the server says so: the
 * page re-reads the case rather than assuming, exactly as every stage does.
 */
export default function CloseCaseModal({ caseRow: c, onClose, onClosed }) {
  const [reason, setReason] = useState('')
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const expected = (c.case_no || '').trim()
  const norm = v => v.trim().toLowerCase()
  // A case with no number cannot ask for one back. Rare (the number is
  // allocated at creation), but a confirmation nobody can satisfy is worse than
  // one that leans on the reason alone.
  const numberOk = !expected || norm(typed) === norm(expected)
  const ready = Boolean(reason.trim()) && numberOk && !busy

  async function submit() {
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      await api.post(`/cases/${c.id}/close`, { reason: reason.trim() })
      await onClosed()
    } catch (e) {
      // Rendered HERE, not bubbled to the page banner. The page is about to
      // stop showing this modal on success; on failure the operator is still
      // standing in it, and sending them to a banner behind the overlay is how
      // a refusal is experienced as "I pressed it and nothing happened".
      setError(describeError(e))
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onClick={busy ? undefined : onClose}>
      <div className="modal modal-sm" onClick={e => e.stopPropagation()}
           role="alertdialog" aria-label="Close case">
        <div className="modal-hdr">
          <div className="modal-title">Close this case?</div>
          {/* Not "Close" — the word means the opposite here, and this dialog
              already has a "Cancel". Two controls that both dismiss it must
              not both answer to the same name, for a screen reader or for
              anyone reading the markup. */}
          <div className="modal-close" onClick={busy ? undefined : onClose}
               role="button" aria-label="Cancel and keep this case open">×</div>
        </div>

        <div className="modal-body">
          {error && (
            <div className="alert al-danger" role="alert"
                 style={{ marginBottom: 14 }}>
              <span className="al-icon">⚠</span>
              <div className="al-body">
                <b>{error.message}</b>
                {error.hint && (
                  <div style={{ marginTop: 4 }}>{error.hint}</div>
                )}
              </div>
            </div>
          )}

          {/* The consequence first, in the operator's own terms, and stated as
              what will be true afterwards rather than as a warning label. */}
          <div className="alert al-warn" role="status"
               style={{ marginBottom: 16 }}>
            <span className="al-icon">⚠</span>
            <div className="al-body">
              <b>This cannot be undone.</b>
              <div style={{ marginTop: 4 }}>
                Case <b>{c.case_no || 'this case'}</b>
                {c.company_name ? ` · ${c.company_name}` : ''} will be closed
                permanently. It cannot be reopened, no annual return will be
                filed for it, and any confirmation link already sent to a
                director will stop working. If this return goes ahead later,
                it will need a new case.
              </div>
            </div>
          </div>

          <div className="f-group">
            <label className="f-label" htmlFor="cc-reason">
              Why is this case not proceeding?
            </label>
            <textarea
              id="cc-reason" className="f-input f-textarea" rows={3} autoFocus
              value={reason} disabled={busy}
              placeholder="e.g. client is dissolving the company"
              onChange={e => setReason(e.target.value)}
            />
            <span className="f-hint">
              Required. This is the only record of why, and it is written to the
              audit trail.
            </span>
          </div>

          {expected && (
            <div className="f-group" style={{ marginTop: 14 }}>
              <label className="f-label" htmlFor="cc-confirm">
                Type <b>{expected}</b> to confirm
              </label>
              <input
                id="cc-confirm" className="f-input" value={typed} disabled={busy}
                autoComplete="off" spellCheck="false"
                onChange={e => setTyped(e.target.value)}
              />
              <span className="f-hint">
                So the case being closed is the one you meant.
              </span>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-danger" onClick={submit} disabled={!ready}>
            {busy ? 'Closing…' : 'Close case permanently'}
          </button>
        </div>
      </div>
    </div>
  )
}
