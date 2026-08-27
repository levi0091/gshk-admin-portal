import { useState } from 'react'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import CheckRow from './CheckRow.jsx'
import FaultPanel from './FaultPanel.jsx'
import ReturnDataCard from './ReturnDataCard.jsx'
import { describeError, isValidated } from './workflow.js'

/**
 * Stage 1 — Data Verification (FE-3).
 *
 * Two manual pre-checks the portal cannot do for itself, then the CR
 * validation that produces the immutable snapshot everything downstream is
 * built from.
 *
 * `prepare` and `validate` are two calls on purpose: prepare maps the company
 * to CR's schema and creates the filing (no CR contact), validate is what CR
 * actually answers. Splitting them means a mapping failure reads as a mapping
 * failure instead of arriving disguised as a CR rejection.
 */
export default function StageDataVerification({ caseRow, canWrite, canValidate, onChanged, onError }) {
  const [busy, setBusy] = useState(null)
  const [failure, setFailure] = useState(null)
  const [confirmRestart, setConfirmRestart] = useState(false)

  const validated = isValidated(caseRow)
  const faults = caseRow.form_status?.failed ? caseRow.form_status.faults : null

  // "CR validation stays locked until they are ticked" (wireframe_v11 s20).
  // The two checks are assertions about work done OUTSIDE the portal — AML
  // screening, and the e-Filing accounts CR will look for when the return is
  // signed. Validating first is not harmful (validateFormNar1 is free), but it
  // lets a case reach the client with neither done, and the frozen snapshot
  // makes that expensive to walk back.
  const prechecksDone = Boolean(caseRow.aml_cleared) && Boolean(caseRow.accounts_ready)

  async function patch(field, value) {
    onError(null)
    try {
      await api.patch(`/cases/${caseRow.id}`, { [field]: value })
      onChanged()
    } catch (e) {
      onError(describeError(e))
    }
  }

  async function runValidation() {
    onError(null); setFailure(null); setBusy('validate')
    try {
      // Reuse the filing if the case already has one — preparing a second
      // filing for the same case leaves an orphan draft behind.
      let filingId = caseRow.filing_id
      if (!filingId) {
        const filing = await api.post('/tpsi/filings/prepare', {
          entity_id: caseRow.entity_id,
          nar1_case_id: caseRow.id,
        })
        filingId = filing.id
      }
      await api.post(`/tpsi/filings/${filingId}/validate`, {})
      onChanged()
    } catch (e) {
      const described = describeError(e)
      setFailure(described)
      onError(described)
    } finally {
      setBusy(null)
    }
  }

  async function restart() {
    onError(null); setConfirmRestart(false); setBusy('restart')
    try {
      await api.patch(`/cases/${caseRow.id}`, { restart_verification: true })
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      {/* The return itself, first — the wireframe opens this stage with the
          data, and everything below it is a decision about that data. */}
      <ReturnDataCard caseId={caseRow.id} reloadKey={caseRow.updated_at} />

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Manual checks</div>
            <div className="card-sub">
              Two things the portal cannot confirm for you. Tick them once they
              are genuinely done — they are recorded against the case.
            </div>
          </div>
        </div>

        <CheckRow
          checked={Boolean(caseRow.aml_cleared)}
          disabled={!canWrite || busy !== null}
          onToggle={v => patch('aml_cleared', v)}
          title="AML screening cleared"
          sub="Anti-money-laundering checks completed for this client."
        />
        <CheckRow
          checked={Boolean(caseRow.accounts_ready)}
          disabled={!canWrite || busy !== null}
          onToggle={v => patch('accounts_ready', v)}
          title="e-Reg accounts created"
          sub="Every signatory holds an individual e-Filing account with the Companies Registry, and CR has associated it with this company."
        />
        {/* The wireframe's presentor note, without naming the account. Two
            different CR identities meet on this screen and confusing them
            wastes a filing window: GSHK's presenter account is what SUBMITS
            and pays, and it is already configured — the tick above is about
            the signatory's own e-Filing account, which is what CR checks
            against `selectPersonId` when the return is signed. The presenter's
            id and deposit account stay a super-admin-only field. */}
        <div className="f-hint" style={{ padding: '10px 4px 2px' }}>
          This is <b>not</b> GSHK's presenter account. That one submits the
          return and pays the fee, and is already set up; this tick is about the
          account the <b>signatory</b> signs with.
        </div>
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Companies Registry validation</div>
            <div className="card-sub">
              Builds the NAR1 from this company's live record and asks CR to
              check it. Nothing is filed and nothing is charged.
            </div>
          </div>
        </div>

        {validated ? (
          <>
            <div className="alert al-success" role="status" style={{ marginBottom: 14 }}>
              <span className="al-icon">✓</span>
              <div className="al-body">
                <b>CR-signed snapshot frozen{caseRow.validated_at ? ` ${formatDateTime(caseRow.validated_at)}` : ''}.</b>{' '}
                Everything from here — the PDF the client sees, the signature and
                the filing — is built from this exact snapshot, not from the live
                company record.
              </div>
            </div>
            {canValidate && (
              <div className="action-bar">
                <div className="ab-note">
                  Changed the company details since? Restart to discard the
                  snapshot and validate again.
                </div>
                <div className="ab-actions">
                  <button className="btn btn-outline" disabled={!canWrite || busy !== null}
                          onClick={() => setConfirmRestart(true)}>
                    {busy === 'restart' ? 'Restarting…' : 'Restart verification'}
                  </button>
                </div>
              </div>
            )}

            {/* Restart discards a CR-SIGNED snapshot and clears every step
                taken since — client verification and signatures included. On
                the wireframe it is behind a confirmation for that reason, and
                the shipped button did it on one click. */}
            {confirmRestart && (
              <div className="modal-confirm" role="alertdialog"
                   aria-label="Restart verification">
                <div className="modal-confirm-card">
                  <div className="modal-confirm-title">
                    Restart verification for {caseRow.case_no || 'this case'}?
                  </div>
                  <div className="modal-confirm-text">
                    The case goes back to Data Verification. The CR-signed
                    snapshot is discarded, and the client verification and any
                    signature recorded against it are cleared. The client will
                    have to approve the return again.
                  </div>
                  <div className="modal-confirm-actions">
                    <button className="btn btn-outline"
                            onClick={() => setConfirmRestart(false)}>
                      Cancel
                    </button>
                    <button className="btn btn-danger" onClick={restart}>
                      Restart — back to Data Verification
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          <>
            {/* Two different sources of "what is wrong", shown separately
                because they mean different things: `problems` is OUR mapper
                saying this company cannot be turned into a NAR1 (fix the
                company record), `faults` is CR rejecting a form we did build
                (fix the form). Collapsing them would send the operator to the
                wrong screen. */}
            {/* The live failure's `problems` are NOT repeated here. The page
                banner already lists every one of them, and rendering the same
                faults twice on one screen makes an operator wonder whether
                they are two different sets. What stays below is a DIFFERENT
                source: `faults` persisted on the case's form status, which is
                what a reload shows. */}
            {failure?.hint && !failure.problems && (
              <div className="alert al-warn" role="alert" style={{ marginBottom: 14 }}>
                <span className="al-icon">⚠</span>
                <div className="al-body">{failure.hint}</div>
              </div>
            )}
            <FaultPanel faults={faults} />
            <div className="action-bar" style={{ marginTop: faults?.length ? 16 : 0 }}>
              <div className="ab-note">
                {!prechecksDone
                  ? 'Tick both manual checks above before validating with CR.'
                  : caseRow.filing_id
                    ? 'Re-checks the corrected details with CR.'
                    : 'Builds the return and asks CR to check it.'}
              </div>
              <div className="ab-actions">
                <button className="btn btn-action"
                        disabled={!canValidate || !prechecksDone || busy !== null}
                        onClick={runValidation}>
                  {busy === 'validate' ? 'Checking with CR…' : 'Validate with CR'}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
