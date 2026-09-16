import { useNavigate } from 'react-router-dom'
import { formatDateTime, formatMoney } from '../../lib/format.js'

/** The receipt fields worth showing, in the order CR prints them. */
const RECEIPT_ROWS = [
  // CR's case number on both paths — never the portal's NAR-2026-…, which is
  // already in the action bar below. Named so the two cannot be confused.
  ['caseNo', 'CR Case number'],
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
 * The receipt's MONEY fields, and only those.
 *
 * CR sends `totalAmount` as "2610.0", which is a figure and reads better
 * grouped — but everything else on this receipt is an IDENTIFIER. `pymtNo` is
 * "5010475972" and `brNo` is "00011651"; grouping either would put commas in a
 * number somebody has to quote back to CR, and dropping `brNo`'s leading zeros
 * would change it outright. So the list is explicit rather than "anything that
 * parses as a number".
 */
const MONEY_FIELDS = new Set(['totalAmount'])

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
 * button. It was removed because it could not do the job its own copy claimed —
 * nothing persisted, nothing ever reached `registered`, and the case already
 * read Completed. Since 2026-09-16 all three are false again, and the answer is
 * NOT to put the card back here: what CR did with the return is stage 6's
 * subject, and this stage is the receipt. Two stages, two questions.
 *
 * WHAT CHANGED HERE. This screen used to read `form_status.code ===
 * 'registered'` to decide its own headline, and that stage was written by
 * nothing — so the "filed & confirmed by CR" wording was unreachable and the
 * Confirmation step sat permanently at IN PROGRESS beneath a receipt. The
 * headline is now about DELIVERY, which is the thing the receipt actually
 * proves, and the register's verdict is one click away.
 */
export default function StageConfirmation({ caseRow, onGo }) {
  const navigate = useNavigate()

  const receipt = caseRow.receipt || null

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
              {caseRow.manual_submitted_at
                ? 'NAR1 filed off-portal & recorded'
                : 'NAR1 filed with the Companies Registry'}
            </div>
            {/* DELIVERED, not registered. The receipt proves CR received the
                return and took the fee; whether CR puts it on the register is
                a separate answer, and this screen must not make it on CR's
                behalf. That is what "Completed" used to do. */}
            <div className="confirm-p">
              The return
              {caseRow.company_name ? <> for <b>{caseRow.company_name}</b></> : null}
              {' '}has been delivered and the Companies Registry issued the
              receipt below. What CR has done with it since is on{' '}
              <b>CR Status</b>.
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
                    <span className="kv-val">
                      {MONEY_FIELDS.has(key)
                        ? formatMoney(receipt[key])
                        : String(receipt[key])}
                    </span>
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
                          <td>{formatMoney(l.amtChrg)}</td>
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

      {/* Every v11 panel offers the next stage. This one no longer dead-ends
          in "Back to Post-incorporation": CR's own answer is the next thing to
          read, and it is now a stage rather than a card bolted onto this one. */}
      <div className="action-bar">
        <div className="ab-note">
          Case {caseRow.case_no || '—'}
          {' · '}The Companies Registry still has to register it.
        </div>
        <div className="ab-actions">
          {caseRow.entity_id && (
            <button className="btn btn-outline"
                    onClick={() => navigate(`/companies/${caseRow.entity_id}`)}>
              View company profile
            </button>
          )}
          {onGo ? (
            <button className="btn btn-primary" onClick={() => onGo(6)}>
              Continue to CR Status →
            </button>
          ) : (
            <button className="btn btn-primary" onClick={() => navigate('/dashboard')}>
              Back to Post-incorporation
            </button>
          )}
        </div>
      </div>
    </>
  )
}
