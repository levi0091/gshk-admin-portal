import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import { describeError } from './workflow.js'

/** The receipt fields worth showing, in the order CR prints them. */
const RECEIPT_ROWS = [
  ['caseNo', 'Case number'],
  ['brNo', 'Business registration no.'],
  ['engCoyName', 'Company name'],
  ['pymtNo', 'Payment number'],
  ['pymtRefNo', 'Payment reference'],
  ['transactionDate', 'Transaction date'],
  ['transactionTime', 'Transaction time'],
  ['pymtMtd', 'Payment method'],
  ['totalAmount', 'Total amount'],
]

/**
 * Stage 5 — Confirmation.
 *
 * The receipt is the evidence the return was delivered, whether it came back
 * from `submitFormNar1` or was transcribed off a paper receipt. Both render the
 * same way here on purpose: what the register holds does not depend on which
 * route got it there.
 *
 * "Check CR status" asks CR what it now holds. It is a read — free, no charge —
 * so it is safe to press whenever, which is why the Confirmation stage does not
 * dead-end at the receipt.
 */
export default function StageConfirmation({ caseRow, canRead, onError, onGo }) {
  const [rows, setRows] = useState(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  const receipt = caseRow.receipt || null
  const caseNo = receipt?.caseNo
  const registered = caseRow.form_status?.code === 'registered'

  async function checkStatus() {
    onError(null); setBusy(true)
    try {
      const result = await api.get(
        `/tpsi/doc-status?case_no=${encodeURIComponent(caseNo)}`)
      setRows(result?.rows || result || [])
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* v11's `confirm-hero`. The stage that says the statutory job is done
          should look done — the shipped screen opened straight into a receipt
          table, which reads like another form to fill in. */}
      {receipt && (
        <div className="card mb-16">
          <div className="confirm-hero">
            <div className="confirm-ring" aria-hidden="true">✓</div>
            <div className="confirm-h1">
              {registered
                ? 'NAR1 filed & confirmed by CR'
                : caseRow.manual_submitted_at
                  ? 'NAR1 filed off-portal & recorded'
                  : 'NAR1 filed with the Companies Registry'}
            </div>
            <div className="confirm-p">
              {registered
                ? <>The Companies Registry accepted the Annual Return
                    {caseRow.company_name ? <> for <b>{caseRow.company_name}</b></> : null}.
                    The case is now marked <b>Completed</b>.</>
                : <>The return
                    {caseRow.company_name ? <> for <b>{caseRow.company_name}</b></> : null}
                    {' '}has been delivered. Check the CR document status below to
                    confirm the Registry has registered it.</>}
            </div>
          </div>
        </div>
      )}

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Filing receipt</div>
            <div className="card-sub">
              {caseRow.manual_submitted_at
                ? 'Filed outside the portal and recorded here.'
                : 'Issued by the Companies Registry when the return was filed.'}
            </div>
          </div>
        </div>

        {receipt ? (
          <>
            <div className="kv-list">
              {RECEIPT_ROWS.map(([key, label]) => (
                receipt[key] ? (
                  <div className="kv-row" key={key}>
                    <span className="kv-key">{label}</span>
                    <span className="kv-val">{String(receipt[key])}</span>
                  </div>
                ) : null
              ))}
            </div>

            {(receipt.paymentRcptList || []).length > 0 && (
              <>
                <div className="tile-sec-lbl">Payment lines</div>
                <div className="tbl-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Receipt no.</th><th>Revenue code</th>
                        <th>Document</th><th>Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {receipt.paymentRcptList.map((l, i) => (
                        <tr key={i}>
                          <td><span className="td-id">{l.rcptNo}</span></td>
                          <td><span className="td-muted">{l.revCode}</span></td>
                          <td><span className="td-muted">{l.docShtFrm}</span></td>
                          <td>{l.amtChrg}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        ) : (
          <div className="empty-state" style={{ padding: 16 }}>
            No receipt recorded for this case yet.
          </div>
        )}

        {caseRow.manual_submitted_at && (
          <div className="f-hint" style={{ marginTop: 12 }}>
            Recorded {formatDateTime(caseRow.manual_submitted_at)}.
          </div>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">What CR holds now</div>
            <div className="card-sub">
              Asks the Companies Registry for the current status of this filing.
              A read — nothing is charged.
            </div>
          </div>
        </div>

        {rows === null ? (
          <div className="empty-state" style={{ padding: 16 }}>
            {caseNo ? 'Not checked yet.' : 'A case number is needed to check with CR.'}
          </div>
        ) : rows.length === 0 ? (
          <div className="empty-state" style={{ padding: 16 }}>
            CR returned no rows for this case number.
          </div>
        ) : (
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr><th>Document</th><th>Status</th><th>Submitted</th></tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.documentName || r.docShtFrm || '—'}</td>
                    <td><span className="td-primary">{r.documentStatus || '—'}</span></td>
                    <td><span className="td-muted">{r.submissionDate || '—'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {canRead && caseNo && (
          <div className="action-bar">
            <div className="ab-note">
              Queries CR by the receipt's case number. A read — free, and it
              works outside the Mon–Fri 10:00–16:00 filing window.
            </div>
            <div className="ab-actions">
              <span className="perm-tag">Requires <b>tpsi:read</b></span>
              <button className="btn btn-outline" disabled={busy} onClick={checkStatus}>
                {busy ? 'Asking CR…' : 'Check CR status'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* The last stage must not dead-end. v11 sends the operator back to the
          work rather than leaving them on a finished case with nowhere to go. */}
      <div className="action-bar">
        <div className="ab-note">
          Case {caseRow.case_no || '—'}
          {registered ? ' · Completed' : ''}
        </div>
        <div className="ab-actions">
          {caseRow.entity_id && (
            <button className="btn btn-outline"
                    onClick={() => navigate(`/companies/${caseRow.entity_id}`)}>
              View company profile
            </button>
          )}
          <button className="btn btn-primary" onClick={() => navigate('/dashboard')}>
            Back to Post-incorporation
          </button>
        </div>
      </div>
    </>
  )
}
