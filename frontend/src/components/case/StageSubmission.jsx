import { useState, useEffect, useRef } from 'react'
import { api } from '../../lib/api.js'
import CheckRow from './CheckRow.jsx'
import FaultPanel from './FaultPanel.jsx'
import FilingSummaryCard from './FilingSummaryCard.jsx'
import { formatMoney as money } from '../../lib/format.js'
import { hongKongTodayISO } from '../../lib/anniversary.js'
import { describeError } from './workflow.js'

/**
 * The receipt fields the portal FILLS, shown rather than asked for (Levi
 * 2026-09-14). The backend replaces whatever is sent under these keys —
 * `nar1_cases.RECEIPT_DERIVED` — so this is a display, not input.
 *
 * NOT the case number. CR's case number is on CR's receipt and nowhere in the
 * portal, so it is typed, as "CR Case number" — named so it cannot be mistaken
 * for the portal's own NAR-2026-… number, which it briefly was.
 */
const DERIVED_ROWS = [
  ['brNo', 'Business registration no.'],
  ['engCoyName', 'Company name (English)'],
  ['accNo', 'Account number'],
]

/**
 * The two figures the audit trail and fee reconciliation actually read
 * (spec §4) — CR's case number and the total — and the date. The backend
 * validates every field and answers with every problem at once; this shorter
 * list is only what arms the button, so an operator halfway through
 * transcribing is not told the button is broken.
 */
const RECEIPT_REQUIRED = ['caseNo', 'transactionDate', 'totalAmount']

const OTHER = '__other__'

/** YYYY-MM-DD, as a date input holds it → DD/MM/YYYY, as CR prints it. */
export function toCrDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''))
  return m ? `${m[3]}/${m[2]}/${m[1]}` : ''
}

/**
 * HH:MM or HH:MM:SS → HH:MM:SS, as CR prints it. A time input drops the
 * seconds when they are zero, so "13:36" is a real answer, not a partial one.
 */
export function toCrTime(value) {
  const m = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(value || ''))
  return m ? `${m[1]}:${m[2]}:${m[3] || '00'}` : ''
}

/**
 * A typed amount → "2610.00". Sent as a STRING with two places — the backend
 * keeps money out of floats, and CR's own receipt carries strings.
 */
export function toAmount(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  const n = Number(text)
  return Number.isFinite(n) ? n.toFixed(2) : text
}

let lineSeq = 0
/** A payment line. `_key` is the React key only — stripped before sending. */
const emptyLine = () => ({
  _key: `line-${++lineSeq}`, rcptNo: '', revCode: '', docShtFrm: '', amtChrg: '',
})

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
export default function StageSubmission({ caseRow, canSubmit, onChanged, onError, onGo }) {
  const manual = caseRow.signing_method === 'manual'
  return manual
    ? <ManualSubmission caseRow={caseRow} canSubmit={canSubmit} onChanged={onChanged} onError={onError} onGo={onGo} />
    : <ESignSubmission caseRow={caseRow} canSubmit={canSubmit} onChanged={onChanged} onError={onError} onGo={onGo} />
}

function ESignSubmission({ caseRow, canSubmit, onChanged, onError, onGo }) {
  const [preflight, setPreflight] = useState(undefined)
  const [acknowledged, setAcknowledged] = useState(false)
  const [busy, setBusy] = useState(false)
  // The PRE-FLIGHT's own failure, and nothing else. It is not the outcome of
  // anything the operator pressed — it happens on arrival, and it explains why
  // this card has no numbers in it — so it stays inside the card as a note.
  // Every failure that IS an outcome goes to `onError`, which draws it once at
  // the top of the page and scrolls there.
  const [preflightError, setPreflightError] = useState(null)

  const filingId = caseRow.filing_id

  useEffect(() => {
    if (!filingId) return undefined
    let cancelled = false
    api.get(`/tpsi/filings/${filingId}/preview`)
      .then(p => { if (!cancelled) setPreflight(p) })
      .catch(e => {
        if (!cancelled) { setPreflight(null); setPreflightError(describeError(e)) }
      })
    return () => { cancelled = true }
  }, [filingId])

  const sufficient = preflight?.sufficient
  // Late = the computed fee is above the on-time one. Derived from the two
  // numbers rather than from the band text, so it cannot drift if CR renames
  // a band.
  const isLate = Boolean(
    preflight?.fee_is_certain &&
    preflight?.on_time_fee != null &&
    Number(preflight.fee) > Number(preflight.on_time_fee)
  )
  // THE RETURN IS NOT DUE YET (Levi 2026-09-07). An annual return reports on
  // the year ending at the company's return date, so it cannot be delivered
  // before that date arrives. `filings.submit` refuses this independently and
  // is the authority — the flag is read straight off the pre-flight rather
  // than recomputed here, so the screen and the gate cannot disagree about
  // which anniversary they mean.
  const tooEarly = preflight?.too_early === true
  const blocked = preflight === undefined || preflight === null
    || !sufficient || tooEarly

  async function submit() {
    onError(null); setBusy(true)
    try {
      await api.post(`/tpsi/filings/${filingId}/submit`, { confirm: true })
      onChanged()
    } catch (e) {
      // ONE SURFACE. The drift refusal used to be drawn here, at the button,
      // because the page banner could show a sentence but not a table and the
      // banner was off-screen anyway. Both halves of that are fixed: the
      // banner renders comparison cards, and every failure scrolls the page to
      // it. Drawing it twice is what produced the detailed refusal at the top
      // and the vague "not in a state that allows this" beside the button
      // (Levi 2026-09-03).
      onError(describeError(e))
      // The tick was an acknowledgement of a specific charge against a
      // specific document. Whatever was refused, that document is now in
      // question — so the acknowledgement is spent and must be given again.
      setAcknowledged(false)
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
        // A card note, not an alert. This is the fee panel saying it has no
        // figures to show; alerts on this screen mean "something you did was
        // refused" and live at the top of the page.
        <div className="card-note card-note-warn" role="status">
          <b>The fee and balance are unavailable, so filing is blocked.</b>
          {preflightError?.hint && <div style={{ marginTop: 4 }}>{preflightError.hint}</div>}
        </div>
      ) : tooEarly ? (
        // ITS OWN NOTE, ABOVE THE FEE, and the fee panel is not drawn at all.
        // Being early is not a money problem and quoting a fee beside it would
        // invite a top-up that changes nothing — CR will not take this return
        // today at any price. A card note rather than an alert, for the reason
        // every other note on this screen is one: nothing the operator pressed
        // was refused, this is the panel stating why it has no filing to offer.
        <div className="card-note card-note-warn" role="status"
             data-testid="submission-too-early">
          <b>This return is not due yet, so it cannot be filed.</b>
          <div style={{ marginTop: 4 }}>
            The company's return date is{' '}
            <b>{preflight.return_date}</b>
            {preflight.days_until_return_date != null && (
              <> — {preflight.days_until_return_date} day
                {preflight.days_until_return_date === 1 ? '' : 's'} from today</>
            )}
            . An annual return reports on the year ending on that date and
            cannot be delivered before it.
          </div>
          <div style={{ marginTop: 4 }}>
            If that date looks wrong, check the return year on this filing and
            the incorporation date on the company record.
          </div>
        </div>
      ) : (
        <div className={`card-note ${sufficient ? '' : 'card-note-warn'}`} role="status">
          <div>
            {/* The COMPUTED fee for this company's return date, not the flat
                on-time figure. A return 7 months past its anniversary is
                HK$2,610; quoting HK$105 for it told the operator something
                that was not true and let the balance check pass a filing the
                account could not cover. */}
            <b>Fee HK$ {money(preflight.fee)}</b>, against a deposit balance of{' '}
            <b>HK$ {money(preflight.balance)}</b>.{' '}
            {sufficient
              ? 'The balance covers this filing.'
              : 'The balance does not cover this filing — top up the deposit account before filing.'}

            {/* The band and the return date it was measured from. An operator
                can check those against the company record; they cannot check a
                bare number. */}
            {preflight.fee_is_certain && preflight.fee_detail?.return_date && (
              <div style={{ marginTop: 6 }}>
                {isLate
                  ? <>This return is <b>late</b>: delivered {preflight.fee_detail.band},
                      counted from its return date {preflight.fee_detail.return_date}
                      {' '}(the anniversary of incorporation).</>
                  : <>Delivered {preflight.fee_detail.band} — return date{' '}
                      {preflight.fee_detail.return_date}.</>}
              </div>
            )}

            {/* Not computable. Says why, and gates on the ceiling — being
                optimistic here means failing at CR with the money half spent. */}
            {preflight.fee_is_certain === false && (
              <div style={{ marginTop: 6 }}>
                The exact fee could not be worked out
                {preflight.fee_detail?.reason ? ` — ${preflight.fee_detail.reason}` : ''}.
                The balance is checked against the highest it could be
                (HK$ {money(preflight.max_fee)}); the real charge appears on the receipt.
              </div>
            )}
          </div>
        </div>
      )}

      {/* The arithmetic, not just the two numbers. "Balance HK$12,480, fee
          HK$2,610" leaves the operator to subtract; v11's deposit box does it,
          because what they actually need to know is what is left afterwards. */}
      {/* Not drawn when the return is early: the arithmetic would be real and
          irrelevant, and "Balance after ≈ HK$8,000" beside a return CR will
          not accept today reads as an invitation to top up and press on. */}
      {preflight && !tooEarly && (
        <div className="deposit-box">
          <div>
            <div className="deposit-l">
              Presenter deposit account · balance (<code>enquireDepositAccount</code>)
            </div>
            <div className="deposit-v">HK$ {money(preflight.balance)}</div>
          </div>
          <div className="deposit-r">
            <div className="fee-line">
              NAR1 registration fee
              {preflight.fee_is_certain === false ? ' (at most)' : ''}
            </div>
            <div className="fee-line fee-amt">
              − HK$ {money(preflight.fee_is_certain === false
                ? preflight.max_fee : preflight.fee)}
            </div>
            <div className="fee-after">
              Balance after ≈ HK$ {money(
                Number(preflight.balance)
                - Number(preflight.fee_is_certain === false
                  ? preflight.max_fee : preflight.fee))}
            </div>
          </div>
        </div>
      )}

      {/* NOTHING ABOUT THE LAST FAILURE IS DRAWN HERE. Not CR's faults, not
          the drift table, and not the hint — the hint is what put a yellow
          "The case is not in a state that allows this yet" between the deposit
          box and the Submit button, underneath a page banner that had already
          said, in detail, exactly what was wrong (Levi 2026-09-03).

          The page banner is the single surface and the page scrolls to it. The
          receipt panel in the manual half below is a DIFFERENT thing: those
          are our own field checks, and they belong beside the fields they are
          about. */}

      {/* v11's `danger-gate`. The tick and the button used to sit in an
          ordinary action bar, which made the irreversible step look like every
          other step on the screen. Boxing it is the point: it is the one
          control here that spends money and cannot be undone. */}
      {canSubmit ? (
        <div className="danger-gate">
          <div className="dg-hd">Irreversible action — two-step confirmation</div>
          <div className="dg-warn">
            Submitting files the Annual Return with the Companies Registry and{' '}
            <b>
              deducts {preflight?.fee_is_certain
                ? `HK$ ${money(preflight.fee)}`
                : 'the fee'} from the deposit account
            </b>. This cannot be reversed. Tick to confirm, then press Submit.
          </div>

          <CheckRow
            checked={acknowledged}
            disabled={blocked || busy}
            onToggle={setAcknowledged}
            // Names the ACTUAL amount. "charges the fee" let someone acknowledge
            // a HK$2,610 charge believing it was HK$105 — the tick is the record
            // that they knew what was being spent.
            title={preflight?.fee_is_certain
              ? `I understand this submits NAR1 to CR and deducts HK$ ${money(preflight.fee)} — this is irreversible`
              : 'I understand this submits NAR1 to CR and deducts the fee — this is irreversible'}
            sub="The filing is made with the Companies Registry immediately and cannot be reversed."
          />

          <div className="dg-actions">
            <button className="btn btn-danger btn-lg"
                    disabled={blocked || !acknowledged || busy} onClick={submit}>
              {busy ? 'Filing with CR…' : 'Submit NAR1 to Companies Registry'}
            </button>
            {onGo && (
              <button type="button" className="dg-cancel" disabled={busy}
                      onClick={() => onGo(3)}>
                Cancel — back to signing
              </button>
            )}
            <span className="perm-tag" style={{ marginLeft: 'auto' }}>
              Gated to <b>tpsi:submit</b> — a separate permission from tpsi:write
            </span>
          </div>

          {blocked && (
            <div className="ab-note" style={{ marginTop: 10 }}>
              {tooEarly
                // The balance is not the reason and saying it is would send
                // the operator to top up an account that is already fine.
                ? 'Filing is blocked until this company\'s return date.'
                : 'Filing is blocked until CR confirms the balance covers the fee.'}
            </div>
          )}
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

/* The drift table that used to live here is gone. Spec §6's refusal is now
   rendered by `RefusalDetail` in the page banner, as one comparison card per
   field that moved — see components/case/RefusalDetail.jsx. It was here
   because the banner could not show a table and was off-screen anyway; the
   banner now shows cards and the page scrolls to it. */

/** One labelled control. The label is always tied to the control by id. */
function Field({ id, label, children }) {
  return (
    <div className="f-group">
      <label className="f-label" htmlFor={id}>{label}</label>
      {children}
    </div>
  )
}

/**
 * A code from CR's receipt, picked rather than typed (Levi 2026-09-14) — with
 * an "Other" that opens a box, because CR has more codes than any receipt GSHK
 * has seen and a real receipt must never be untranscribable. The options come
 * from the backend (`nar1_cases.RECEIPT_VOCABULARY`); this holds no copy.
 */
function VocabSelect({ id, label, options = [], value, onChange, disabled }) {
  const known = options.some(o => o.code === value)
  const [custom, setCustom] = useState(Boolean(value) && !known)
  return (
    <>
      <select id={id} className="f-input" value={custom ? OTHER : (value || '')}
              disabled={disabled}
              onChange={e => {
                const next = e.target.value
                setCustom(next === OTHER)
                onChange(next === OTHER ? '' : next)
              }}>
        <option value="">Choose…</option>
        {options.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
        <option value={OTHER}>Other — type it as printed</option>
      </select>
      {custom && (
        <input className="f-input vocab-other" aria-label={`${label} (as printed)`}
               value={value} disabled={disabled} autoFocus
               onChange={e => onChange(e.target.value)} />
      )}
    </>
  )
}

/** HK$ amounts: a number field, never free text (Levi 2026-09-14). */
function MoneyInput({ id, value, onChange, disabled }) {
  return (
    <div className="f-money">
      <span className="f-money-cur" aria-hidden="true">HK$</span>
      <input id={id} className="f-input" type="number" inputMode="decimal"
             min="0" step="0.01" placeholder="0.00" value={value}
             disabled={disabled} onChange={e => onChange(e.target.value)} />
    </div>
  )
}

function ManualSubmission({ caseRow, canSubmit, onChanged, onError, onGo }) {
  const [fields, setFields] = useState({
    caseNo: '', pymtNo: '', pymtRefNo: '', transactionDate: '',
    transactionTime: '', pymtMtd: '', totalAmount: '',
  })
  const [lines, setLines] = useState(() => [emptyLine()])
  const [problems, setProblems] = useState([])
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  // undefined while loading, null when it could not be read, else the payload
  // of GET /cases/{id}/manual-receipt-prefill.
  const [prefill, setPrefill] = useState(undefined)
  const fileInput = useRef(null)

  const recorded = Boolean(caseRow.manual_submitted_at)
  const attached = Boolean(caseRow.manual_receipt_document_id)
  // The two halves of the receipt (spec §4). They are independent: nothing
  // parses figures out of the scan, and the scan is not derived from the
  // figures, so neither substitutes for the other.
  const typed = RECEIPT_REQUIRED.every(k => String(fields[k] || '').trim())

  useEffect(() => {
    if (recorded || !canSubmit) return undefined
    let live = true
    api.get(`/cases/${caseRow.id}/manual-receipt-prefill`)
      .then(p => { if (live) setPrefill(p) })
      // Not fatal: the backend fills these fields on submit whatever this
      // screen managed to show. Only the display and the dropdowns degrade.
      .catch(() => { if (live) setPrefill(null) })
    return () => { live = false }
  }, [caseRow.id, recorded, canSubmit])

  const vocab = prefill?.vocabulary || {}
  const depositMethod = prefill?.deposit_payment_method || 'Deduct from Account'

  function derivedValue(key) {
    const derived = prefill?.fields || {}
    if (key === 'accNo') {
      // A cheque was not drawn from GSHK's deposit account; saying which
      // account it came from would put a false fact on the receipt.
      if (fields.pymtMtd !== depositMethod) {
        return <span className="td-muted">Recorded only for a “{depositMethod}” payment</span>
      }
      return derived.accNo
        || <span className="td-muted">No deposit account is set up under CR Credentials</span>
    }
    // The case row already carries these, so nothing flashes empty while the
    // prefill is in flight.
    const fallback = { brNo: caseRow.br_number, engCoyName: caseRow.company_name }
    return derived[key] || fallback[key] || <span className="td-muted">Not on record</span>
  }

  function setField(key, value) {
    setFields(f => ({ ...f, [key]: value }))
  }
  function setLine(i, key, value) {
    setLines(ls => ls.map((l, j) => (j === i ? { ...l, [key]: value } : l)))
  }
  function removeLine(i) {
    // Never the first: a receipt has at least one payment line, and the backend
    // refuses one without.
    if (i === 0) return
    setLines(ls => ls.filter((_, j) => j !== i))
  }

  async function uploadReceipt(file) {
    if (!file) return
    onError(null); setProblems([]); setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      await api.upload(`/cases/${caseRow.id}/manual-receipt`, form)
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function record() {
    onError(null); setProblems([]); setBusy(true)
    try {
      // In CR's own shapes — DD/MM/YYYY, HH:MM:SS, "2610.00" — so a manual
      // receipt renders beside an e-Signed one without looking like a
      // different kind of record. The company's identifiers are NOT sent: the
      // backend fills them (RECEIPT_DERIVED) and would discard them anyway.
      await api.post(`/cases/${caseRow.id}/manual-submit`, {
        receipt: {
          caseNo: fields.caseNo.trim(),
          pymtNo: fields.pymtNo.trim(),
          pymtRefNo: fields.pymtRefNo.trim(),
          transactionDate: toCrDate(fields.transactionDate),
          transactionTime: toCrTime(fields.transactionTime),
          pymtMtd: fields.pymtMtd.trim(),
          totalAmount: toAmount(fields.totalAmount),
          paymentRcptList: lines.map(l => ({
            rcptNo: l.rcptNo.trim(),
            revCode: l.revCode.trim(),
            docShtFrm: l.docShtFrm.trim(),
            amtChrg: toAmount(l.amtChrg),
          })),
        },
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

  // NOTHING HAS BEEN RECORDED YET — the `recorded` branch above caught that
  // case — so for a role that cannot record one, every field below would be an
  // empty box it may not type in and an upload zone that refuses the file.
  // Draw the card, say what is outstanding, and stop.
  if (!canSubmit) {
    return (
      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Record the Companies Registry receipt</div>
            <div className="card-sub">
              This return was filed outside the portal, and CR's receipt has not
              been recorded against the case yet.
            </div>
          </div>
        </div>
        <div className="f-hint" style={{ marginTop: 12 }}>
          Recording a filing requires the <b>tpsi:submit</b> permission — it
          closes the case as filed, exactly as a real submission does.
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

      {/* WHAT THE PORTAL ALREADY KNOWS, shown rather than asked for (Levi
          2026-09-14). These were text boxes, so an operator retyped the BR
          number and the company name off a receipt about a company the case
          already names — and could get one of them wrong. */}
      <div className="tile-sec-lbl" style={{ marginTop: problems.length ? 16 : 0 }}>
        From the case record
      </div>
      <div className="kv-list" data-testid="receipt-derived">
        {DERIVED_ROWS.map(([key, label]) => (
          <div className="kv-row" key={key}>
            <span className="kv-key">{label}</span>
            <span className="kv-val">{derivedValue(key)}</span>
          </div>
        ))}
      </div>

      <div className="tile-sec-lbl">From CR's receipt</div>
      <div className="receipt-grid">
        {/* CR's number, typed off CR's receipt — the portal cannot know it.
            Labelled "CR" so nobody types the portal's NAR-2026-… here. */}
        <Field id="rc-caseNo" label="CR Case number">
          <input id="rc-caseNo" className="f-input" value={fields.caseNo}
                 disabled={busy} onChange={e => setField('caseNo', e.target.value)} />
        </Field>
        <Field id="rc-pymtNo" label="Payment number">
          <input id="rc-pymtNo" className="f-input" value={fields.pymtNo}
                 disabled={busy} onChange={e => setField('pymtNo', e.target.value)} />
        </Field>
        <Field id="rc-pymtRefNo" label="Payment reference">
          <input id="rc-pymtRefNo" className="f-input" value={fields.pymtRefNo}
                 disabled={busy} onChange={e => setField('pymtRefNo', e.target.value)} />
        </Field>
        {/* Pickers, not text (Levi 2026-09-14). A receipt is never dated in
            the future, so the calendar stops at today in Hong Kong. */}
        <Field id="rc-transactionDate" label="Transaction date">
          <input id="rc-transactionDate" className="f-input" type="date"
                 max={hongKongTodayISO()} value={fields.transactionDate}
                 disabled={busy}
                 onChange={e => setField('transactionDate', e.target.value)} />
        </Field>
        <Field id="rc-transactionTime" label="Transaction time">
          <input id="rc-transactionTime" className="f-input" type="time" step="1"
                 value={fields.transactionTime} disabled={busy}
                 onChange={e => setField('transactionTime', e.target.value)} />
        </Field>
        <Field id="rc-pymtMtd" label="Payment method">
          <VocabSelect id="rc-pymtMtd" label="Payment method" options={vocab.pymtMtd}
                       value={fields.pymtMtd} disabled={busy}
                       onChange={v => setField('pymtMtd', v)} />
        </Field>
        <Field id="rc-totalAmount" label="Total amount">
          <MoneyInput id="rc-totalAmount" value={fields.totalAmount} disabled={busy}
                      onChange={v => setField('totalAmount', v)} />
        </Field>
      </div>

      <div className="tile-sec-lbl">Payment lines</div>
      {lines.map((line, i) => (
        <div key={line._key} className="pay-line" data-testid="payment-line">
          <Field id={`rl-${i}-rcptNo`} label="Receipt no.">
            <input id={`rl-${i}-rcptNo`} className="f-input" value={line.rcptNo}
                   disabled={busy} onChange={e => setLine(i, 'rcptNo', e.target.value)} />
          </Field>
          <Field id={`rl-${i}-revCode`} label="Revenue code">
            <VocabSelect id={`rl-${i}-revCode`} label="Revenue code"
                         options={vocab.revCode} value={line.revCode} disabled={busy}
                         onChange={v => setLine(i, 'revCode', v)} />
          </Field>
          <Field id={`rl-${i}-docShtFrm`} label="Document code">
            <VocabSelect id={`rl-${i}-docShtFrm`} label="Document code"
                         options={vocab.docShtFrm} value={line.docShtFrm} disabled={busy}
                         onChange={v => setLine(i, 'docShtFrm', v)} />
          </Field>
          <Field id={`rl-${i}-amtChrg`} label="Amount charged">
            <MoneyInput id={`rl-${i}-amtChrg`} value={line.amtChrg} disabled={busy}
                        onChange={v => setLine(i, 'amtChrg', v)} />
          </Field>
          {/* Every line but the first can be taken back out (Levi
              2026-09-14). The first stays: a receipt has at least one. The
              cell is kept on the first line too, so the columns line up. */}
          <div className="pay-line-x">
            {i > 0 && (
              <button type="button" className="pay-line-remove"
                      aria-label={`Remove payment line ${i + 1}`}
                      title="Remove this payment line"
                      disabled={busy} onClick={() => removeLine(i)}>
                ×
              </button>
            )}
          </div>
        </div>
      ))}

      <div className="tile-sec-lbl">CR receipt document</div>
      <input ref={fileInput} type="file" className="visually-hidden"
             accept="application/pdf,image/*" aria-label="CR filing receipt"
             disabled={busy || uploading}
             onChange={e => uploadReceipt(e.target.files?.[0])} />

      {attached ? (
        <div className="up-done">
          <span className="up-tick" aria-hidden="true">✓</span>
          <span className="up-txt">
            {/* The case row carries no filename — the receipt is a versioned
                `documents` row and the case keeps only the pointer, so the
                version is what identifies WHICH scan is attached. */}
            <b>CR receipt attached</b>
            <span className="up-sub">
              {caseRow.manual_receipt_document_version
                ? `Version ${caseRow.manual_receipt_document_version} · `
                : ''}
              <code>NAR1_MANUAL_RECEIPT_ENTERED</code> written to the audit log
            </span>
          </span>
          {/* `canSubmit` is guaranteed here — the branch above returns for a
              role without it — so this is unconditional now. */}
          <button type="button" className="btn btn-outline btn-sm"
                  style={{ marginLeft: 'auto' }} disabled={busy || uploading}
                  onClick={() => fileInput.current?.click()}>
            Replace
          </button>
        </div>
      ) : (
        <button type="button" className="up-zone"
                disabled={busy || uploading}
                onClick={() => fileInput.current?.click()}>
          <span className="up-arrow" aria-hidden="true">⬆</span>
          <span className="up-txt">
            <b>{uploading ? 'Uploading…' : 'Choose the receipt CR issued'}</b>
            <span className="up-sub">
              The PDF or scan from CR's own portal. The typed figures above are
              what the audit trail reads; this is what proves CR issued them.
            </span>
          </span>
        </button>
      )}

      {(
        <div className="action-bar">
          <div className="ab-note" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {/* Back to the signed scan: the upload no longer throws the
                operator forward, and from here they may still find they
                attached the wrong one (Levi 2026-09-14). */}
            {onGo && (
              <button type="button" className="btn btn-outline btn-sm"
                      disabled={busy} onClick={() => onGo(3)}>
                ← Back to Signing
              </button>
            )}
            <button type="button" className="btn btn-outline btn-sm"
                    onClick={() => setLines(ls => [...ls, emptyLine()])} disabled={busy}>
              + Add payment line
            </button>
          </div>
          <div className="ab-actions">
            {/* AT THE BUTTON, not in a page banner. "I pressed Record and
                nothing happened" was a correct refusal rendered a screen and a
                half above the control that caused it (Levi 2026-08-31). */}
            {!(attached && typed) && (
              <span className="ab-note" data-testid="manual-submit-block">
                {!attached && !typed
                  ? 'Attach the CR receipt and complete the receipt fields first.'
                  : !attached
                    ? 'Attach the CR receipt before recording the filing.'
                    : 'Complete the receipt fields before recording the filing.'}
              </span>
            )}
            <button className="btn btn-action"
                    disabled={busy || uploading || !attached || !typed}
                    onClick={record}>
              {busy ? 'Recording…' : 'Record the filing'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
