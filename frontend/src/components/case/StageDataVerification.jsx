import { useState } from 'react'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import CheckRow from './CheckRow.jsx'
import FaultPanel from './FaultPanel.jsx'
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

  const validated = isValidated(caseRow)
  const faults = caseRow.form_status?.failed ? caseRow.form_status.faults : null

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
    onError(null); setBusy('restart')
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
          sub="Every signatory holds an individual e-Filing account with the Companies Registry."
        />
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
                          onClick={restart}>
                    {busy === 'restart' ? 'Restarting…' : 'Restart verification'}
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <>
            {failure?.hint && (
              <div className="alert al-warn" role="alert" style={{ marginBottom: 14 }}>
                <span className="al-icon">⚠</span>
                <div className="al-body">{failure.hint}</div>
              </div>
            )}
            <FaultPanel faults={faults} />
            <div className="action-bar" style={{ marginTop: faults?.length ? 16 : 0 }}>
              <div className="ab-note">
                {caseRow.filing_id
                  ? 'Re-checks the corrected details with CR.'
                  : 'Builds the return and asks CR to check it.'}
              </div>
              <div className="ab-actions">
                <button className="btn btn-action" disabled={!canValidate || busy !== null}
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
