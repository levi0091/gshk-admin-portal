import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import CheckRow from './CheckRow.jsx'
import FaultPanel from './FaultPanel.jsx'
import FilingSummaryCard from './FilingSummaryCard.jsx'
import { describeError } from './workflow.js'

/** CR's own receipt vocabulary — mirrors nar1_cases.RECEIPT_REQUIRED. */
const RECEIPT_FIELDS = [
  ['caseNo', 'Case number'],
  ['brNo', 'Business registration no.'],
  ['accNo', 'Account number'],
  ['engCoyName', 'Company name (English)'],
  ['pymtNo', 'Payment number'],
  ['pymtRefNo', 'Payment reference'],
  ['transactionDate', 'Transaction date'],
  ['transactionTime', 'Transaction time'],
  ['pymtMtd', 'Payment method'],
  ['totalAmount', 'Total amount'],
]
const LINE_FIELDS = [
  ['rcptNo', 'Receipt no.'],
  ['revCode', 'Revenue code'],
  ['docShtFrm', 'Document code'],
  ['amtChrg', 'Amount charged'],
]

const emptyLine = () => ({ rcptNo: '', revCode: '', docShtFrm: '', amtChrg: '' })

/**
 * Stage 4 — Submission. The chargeable, irreversible one.
 *
 * e-Sign: CR deducts the fee from GSHK's deposit account the moment
 * `submitFormNar1` succeeds, and nothing takes it back. So there are three
 * gates, and all of them are real:
 *
 *   1. A pre-flight (`preview`) that costs nothing and asks CR what the fee is
 *      and what the balance is. Submit is DISABLED when the balance will not
 *      cover it — discovering that at CR wastes a filing attempt.
 *   2. An explicit tick acknowledging the charge.
 *   3. `confirm: true` in the body, which the backend requires independently.
 *
 * Manual: no CR call and no charge here. The operator copies the receipt CR
 * already issued off-portal. Every problem with it comes back at once, because
 * they are transcribing from paper and should not discover the fields one round
 * trip at a time.
 */
export default function StageSubmission({ caseRow, canSubmit, onChanged, onError }) {
  const manual = caseRow.signing_method === 'manual'
  return manual
    ? <ManualSubmission caseRow={caseRow} canSubmit={canSubmit} onChanged={onChanged} onError={onError} />
    : <ESignSubmission caseRow={caseRow} canSubmit={canSubmit} onChanged={onChanged} onError={onError} />
}

function ESignSubmission({ caseRow, canSubmit, onChanged, onError }) {
  const [preflight, setPreflight] = useState(undefined)
  const [acknowledged, setAcknowledged] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState(null)

  const filingId = caseRow.filing_id
  const faults = caseRow.form_status?.code === 'submission_failed'
    ? caseRow.form_status.faults : null

  useEffect(() => {
    if (!filingId) return undefined
    let cancelled = false
    api.get(`/tpsi/filings/${filingId}/preview`)
      .then(p => { if (!cancelled) setPreflight(p) })
      .catch(e => { if (!cancelled) { setPreflight(null); setFailure(describeError(e)) } })
    return () => { cancelled = true }
  }, [filingId])

  const sufficient = preflight?.sufficient
  const blocked = preflight === undefined || preflight === null || !sufficient

  async function submit() {
    onError(null); setFailure(null); setBusy(true)
    try {
      await api.post(`/tpsi/filings/${filingId}/submit`, { confirm: true })
      onChanged()
    } catch (e) {
      const described = describeError(e)
      setFailure(described)
      onError(described)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* What is actually being filed, before the charge is confirmed. */}
      <FilingSummaryCard filingId={filingId} />

    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">File with the Companies Registry</div>
          <div className="card-sub">
            This charges GSHK's deposit account and cannot be undone.
          </div>
        </div>
      </div>

      {preflight === undefined ? (
        <div className="empty-state" style={{ padding: 16 }}>Checking the fee and balance…</div>
      ) : preflight === null ? (
        <div className="alert al-warn" role="alert" style={{ marginBottom: 14 }}>
          <span className="al-icon">⚠</span>
          <div className="al-body">
            Could not reach CR for the fee and balance, so filing is blocked.
            {failure?.hint && <div style={{ marginTop: 4 }}>{failure.hint}</div>}
          </div>
        </div>
      ) : (
        <div className={`alert ${sufficient ? 'al-info' : 'al-danger'}`} role="status"
             style={{ marginBottom: 14 }}>
          <span className="al-icon">{sufficient ? 'ℹ' : '⚠'}</span>
          <div className="al-body">
            <b>Fee HK${preflight.fee}</b> against a deposit balance of{' '}
            <b>HK${preflight.balance}</b>.{' '}
            {sufficient
              ? 'The balance covers this filing.'
              : 'The balance does not cover this filing — top up the deposit account before filing.'}
          </div>
        </div>
      )}

      {failure?.hint && (
        <div className="alert al-warn" role="alert" style={{ marginBottom: 14 }}>
          <span className="al-icon">⚠</span><div className="al-body">{failure.hint}</div>
        </div>
      )}
      <FaultPanel faults={faults} title="The Companies Registry refused the submission" />

      <div style={{ marginTop: faults?.length ? 16 : 0 }}>
        <CheckRow
          checked={acknowledged}
          disabled={!canSubmit || blocked || busy}
          onToggle={setAcknowledged}
          title="I understand this files the return and charges the fee"
          sub="The filing is made with the Companies Registry immediately and cannot be reversed."
        />
      </div>

      {canSubmit ? (
        <div className="action-bar">
          <div className="ab-note">
            {blocked
              ? 'Filing is blocked until CR confirms the balance covers the fee.'
              : acknowledged
                ? 'This is the irreversible step.'
                : 'Confirm you understand the charge to enable filing.'}
          </div>
          <div className="ab-actions">
            <button className="btn btn-danger" disabled={blocked || !acknowledged || busy}
                    onClick={submit}>
              {busy ? 'Filing with CR…' : 'File the return'}
            </button>
          </div>
        </div>
      ) : (
        <div className="f-hint" style={{ marginTop: 12 }}>
          Filing requires the <b>tpsi:submit</b> permission. Someone who holds it
          must complete this step.
        </div>
      )}
    </div>
    </>
  )
}

function ManualSubmission({ caseRow, canSubmit, onChanged, onError }) {
  const [fields, setFields] = useState(
    () => Object.fromEntries(RECEIPT_FIELDS.map(([k]) => [k, ''])))
  const [lines, setLines] = useState([emptyLine()])
  const [problems, setProblems] = useState([])
  const [busy, setBusy] = useState(false)

  const recorded = Boolean(caseRow.manual_submitted_at)

  function setField(key, value) {
    setFields(f => ({ ...f, [key]: value }))
  }
  function setLine(i, key, value) {
    setLines(ls => ls.map((l, j) => (j === i ? { ...l, [key]: value } : l)))
  }

  async function record() {
    onError(null); setProblems([]); setBusy(true)
    try {
      await api.post(`/cases/${caseRow.id}/manual-submit`, {
        receipt: { ...fields, paymentRcptList: lines },
      })
      onChanged()
    } catch (e) {
      // The backend answers 400 with every problem at once, as a list. Showing
      // them all is the whole point — they are transcribing off paper.
      const detail = e?.message
      if (e?.status === 400 && detail && typeof detail === 'object' && detail.problems) {
        setProblems(detail.problems)
      } else if (e?.status === 400) {
        setProblems([String(detail)])
      } else {
        onError(describeError(e))
      }
    } finally {
      setBusy(false)
    }
  }

  if (recorded) {
    return (
      <div className="card mb-16">
        <div className="alert al-success" role="status">
          <span className="al-icon">✓</span>
          <div className="al-body">
            This return was filed off-portal and the receipt is recorded. See the
            Confirmation step.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">Record the Companies Registry receipt</div>
          <div className="card-sub">
            This return was filed outside the portal. Copy CR's receipt here — it
            is the only evidence the return was delivered. No CR call is made and
            nothing is charged.
          </div>
        </div>
      </div>

      {problems.length > 0 && (
        <FaultPanel faults={problems} title="The receipt is incomplete" />
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))',
                    gap: 12, marginTop: problems.length ? 16 : 0 }}>
        {RECEIPT_FIELDS.map(([key, label]) => (
          <div className="f-group" key={key}>
            <label className="f-label" htmlFor={`rc-${key}`}>{label}</label>
            <input id={`rc-${key}`} className="f-input" value={fields[key]}
                   disabled={!canSubmit || busy}
                   onChange={e => setField(key, e.target.value)} />
          </div>
        ))}
      </div>

      <div className="tile-sec-lbl">Payment lines</div>
      {lines.map((line, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))',
                              gap: 10, marginBottom: 10 }}>
          {LINE_FIELDS.map(([key, label]) => (
            <div className="f-group" key={key}>
              <label className="f-label" htmlFor={`rl-${i}-${key}`}>{label}</label>
              <input id={`rl-${i}-${key}`} className="f-input" value={line[key]}
                     disabled={!canSubmit || busy}
                     onChange={e => setLine(i, key, e.target.value)} />
            </div>
          ))}
        </div>
      ))}

      {canSubmit && (
        <div className="action-bar">
          <div className="ab-note">
            <button type="button" className="btn btn-outline btn-sm"
                    onClick={() => setLines(ls => [...ls, emptyLine()])} disabled={busy}>
              + Add payment line
            </button>
          </div>
          <div className="ab-actions">
            <button className="btn btn-action" disabled={busy} onClick={record}>
              {busy ? 'Recording…' : 'Record the filing'}
            </button>
          </div>
        </div>
      )}
      {!canSubmit && (
        <div className="f-hint" style={{ marginTop: 12 }}>
          Recording a filing requires the <b>tpsi:submit</b> permission — it
          closes the case as filed, exactly as a real submission does.
        </div>
      )}
    </div>
  )
}
