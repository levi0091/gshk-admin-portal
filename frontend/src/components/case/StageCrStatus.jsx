import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import { ActionWithheld } from '../RequirePermission.jsx'
import { CR_MEANING, CR_TONE, crStatus, describeError, isSubmitted } from './workflow.js'

/**
 * Stage 6 — CR Status.
 *
 * The first five stages are GSHK's process and they end at "we handed it over".
 * This one is the Companies Registry's, and it begins there: a NAR1 that
 * `submitFormNar1` accepted and charged for has been RECEIVED, not registered.
 * CR vets it and can still refuse it.
 *
 * Until 2026-09-16 the portal had nowhere to hold that answer, so it called a
 * received return "Completed" and drew a green tick on a claim nobody at CR had
 * made. `tpsi_filings.stage = 'registered'` had existed since migration 018 —
 * whose docstring already said "CR confirmed the filing via docStatusEnquiry" —
 * and nothing ever wrote it, because nothing ever enquired.
 *
 * THE VOCABULARY IS OPEN, AND THE SCREEN SHOWS CR'S OWN WORDS BECAUSE OF IT.
 * CR's specification declares `documentStatus` as `String(20)` and enumerates
 * no values (`services/tpsi/doc_status.py` has the measurement). So the badge
 * is this portal's reading and the quoted line beneath it is CR's — and on an
 * unrecognised status, that line is the only thing on screen that means
 * anything.
 */
export default function StageCrStatus({ caseRow, canRead, onChanged, onError, onGo }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)

  const status = crStatus(caseRow)
  const tone = CR_TONE[status.code] || 'wait'
  const filed = isSubmitted(caseRow)
  const checkedAt = caseRow.cr_status_checked_at

  async function check() {
    onError(null)
    setBusy(true)
    try {
      // `{}`, not nothing: `api.post` JSON-stringifies whatever it is given,
      // and `undefined` stringifies to `undefined` — a body FastAPI reads as
      // malformed rather than as absent.
      await api.post(`/tpsi/cases/${caseRow.id}/refresh-status`, {})
      // Re-read rather than patch local state: the answer changes the workflow
      // badge in the header and the medallion in the stepper, and both are
      // derived server-side. Guessing at them here is how a screen starts
      // disagreeing with the trail it shares.
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className={`card mb-16 cr-card cr-${tone}`}>
        <div className="cr-rail" aria-hidden="true" />
        <div className="cr-body">
          <div className="cr-head">
            <span className={`badge bc-${status.code.replace('cr_', '')}`}>
              {status.label}
            </span>
            <span className="cr-checked">
              {checkedAt
                ? <>Last checked with CR {formatDateTime(checkedAt)}</>
                : 'Not yet checked with CR'}
            </span>
          </div>

          {/* CR'S OWN WORDS, quoted and unedited. The badge above is this
              portal's reading of them; an operator ringing CR quotes what CR
              said, not what we decided it meant. */}
          {status.cr_text && (
            <div className="cr-quote">
              The Companies Registry reports this document as{' '}
              <b>&ldquo;{status.cr_text}&rdquo;</b>.
            </div>
          )}

          <div className="cr-meaning">{CR_MEANING[status.code]}</div>

          {caseRow.cr_document_ref_no && (
            <div className="kv-list" style={{ marginTop: 12 }}>
              <div className="kv-row">
                <span className="kv-key">CR document reference</span>
                <span className="kv-val">{caseRow.cr_document_ref_no}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="action-bar">
        <div className="ab-note">
          {/* The nightly job is the normal path and this button is the
              exception, so the note says so. A press costs a CR
              authentication, and repeated CR auth failures lock the account —
              which is the one objection to this button that did NOT go away. */}
          {status.terminal
            ? 'The Companies Registry has finished with this return, so it is no '
              + 'longer checked.'
            : 'Checked automatically each day, free of charge.'}
        </div>
        <div className="ab-actions">
          {!status.terminal && filed && (
            canRead ? (
              <>
                {/* Just the permission. The cadence and the cost are the note's
                    job, on the left — with all three in the tag the bar was
                    wide enough to wrap the button below it. */}
                <span className="perm-tag">
                  Requires <b>tpsi:read</b>
                </span>
                <button className="btn btn-outline" disabled={busy} onClick={check}>
                  {busy ? 'Asking CR…' : 'Check with CR now'}
                </button>
              </>
            ) : (
              <ActionWithheld module="tpsi" permission="read"
                              action="checking the status with CR" />
            )
          )}
          {/* NO "View company profile" HERE, though every other stage offers
              one. With the permission tag and the check button this bar was
              four items wide and wrapped at 1180px — and the page header three
              inches above already carries a "Company profile" button. This
              stage is about the register, not the company. */}
          {/* The last stage must not dead-end (v11). The operator goes back to
              the work rather than being left on a finished case with nowhere
              to go. */}
          <button className="btn btn-primary" onClick={() => navigate('/dashboard')}>
            Back to Post-incorporation
          </button>
        </div>
      </div>

      {/* One line back to the receipt, because the two stages answer two halves
          of one question and the receipt is the evidence behind this status. */}
      {onGo && (
        <div className="f-hint" style={{ marginTop: 12 }}>
          The filing receipt is on{' '}
          <button className="crumb-link" onClick={() => onGo(5)}>Confirmation</button>.
        </div>
      )}
    </>
  )
}
