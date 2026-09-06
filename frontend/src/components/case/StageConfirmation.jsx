import { useNavigate } from 'react-router-dom'
import { formatDateTime } from '../../lib/format.js'

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
 * IT ENDS AT THE RECEIPT, ON PURPOSE (Levi 2026-09-02: "the receipt should
 * have already been there and upon completion there should be no further
 * updates").
 *
 * There used to be a "What CR holds now" card here with a Check CR status
 * button. It was removed because it could not do the job its own copy claimed:
 *
 *   * NOTHING PERSISTED. The result lived in `useState` and was gone on the
 *     next reload, so it answered a question and then forgot the answer.
 *   * NOTHING EVER REACHES `registered`. No code path writes that stage — it
 *     is in the vocabulary and unreachable — so the reply could never change
 *     what this screen showed.
 *   * THE CASE IS ALREADY DONE. `nar1_case_status._FINISHED` counts
 *     `submitted` as finished, so the case reads Completed from the moment the
 *     receipt exists. There was no state left to advance.
 *
 * And it was not free of consequence: it spent a CR AUTHENTICATION on every
 * press, and repeated CR auth failures lock the account.
 */
// `canRead` and `onError` are gone with the CR status check — this screen
// makes no request now, so it has nothing to be permitted for and nothing to
// report. The parent still passes them; extra props are harmless and leaving
// the call sites alone keeps this change to one file.
export default function StageConfirmation({ caseRow, onGo }) {
  const navigate = useNavigate()

  const receipt = caseRow.receipt || null
  // `registered` is still read, and still never true today: no code path writes
  // that stage. Kept because it is CR's own vocabulary and a future docStatus
  // poller would set it — but nothing on this screen waits for it any more.
  const registered = caseRow.form_status?.code === 'registered'

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
                    {' '}has been delivered and the Companies Registry issued the
                    receipt below. The case is now marked <b>Completed</b>.</>}
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
