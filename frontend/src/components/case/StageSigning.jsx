import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import { describeError, signedOff } from './workflow.js'

/**
 * Stage 3 — Signing (wireframe_v11 `cmwp3`). e-Sign (FE-2) and manual (FE-4).
 *
 * THE TWO ROUTES ARE EXCLUSIVE AND THE CHOICE IS CONSEQUENTIAL. e-Sign applies
 * a real PIN signature at CR and leads to a chargeable submit. Manual means the
 * return is signed on paper and filed OFF this portal; the backend then refuses
 * the e-Sign chain for that case entirely. A wet signature is not evidence for
 * an e-filing and vice versa, so switching route discards what the other
 * produced rather than carrying it across. That is why v11 draws them as two
 * cards that state their consequences, not as a toggle: the sentence under each
 * option is the part that matters, and a segmented control has nowhere to put
 * it.
 *
 * WHO SIGNS IS NOT A FIELD ON THIS SCREEN. A NAR1 is signed with the logged-in
 * user's own stored e-Service credential and no other (Levi, Q1 2026-08-30).
 * This screen used to offer two text boxes — a signatory id and a password — so
 * a client director could sign live; that made the signing account free text on
 * a statutory declaration and it is withdrawn. v11's "Choose the signatory"
 * radio list goes with it: there is nothing to choose. What survives is v11's
 * `pick-sig` row, which named the person who signed.
 */
export default function StageSigning({ caseRow, canWrite, onChanged, onError, onGo }) {
  const method = caseRow.signing_method || 'esign'
  const [busy, setBusy] = useState(null)
  const [failure, setFailure] = useState(null)
  const [cred, setCred] = useState(null)
  const [preflight, setPreflight] = useState(undefined)
  const fileInput = useRef(null)

  const done = signedOff(caseRow)
  const filingId = caseRow.filing_id
  const faults = caseRow.form_status?.code === 'signing_failed'
    ? caseRow.form_status.faults : null

  // Read once, and never block the screen on it: a credential lookup that
  // fails must not hide the manual route, which needs no credential at all.
  useEffect(() => {
    let live = true
    api.get('/tpsi/credentials')
      .then(c => { if (live) setCred(c || {}) })
      .catch(() => { if (live) setCred({}) })
    return () => { live = false }
  }, [])

  // D-2 · the pre-flight. `preview` makes no CR-side change and is NOT gated on
  // the signed stage (filings.preview has no stage check — only `submit` does),
  // so the same read that prices the submission can price it here, one step
  // earlier, which is where an operator can still do something about a short
  // balance. Skipped on the manual path: nothing is drawn from the deposit
  // account there, so it would be a gate nobody can act on.
  useEffect(() => {
    if (!filingId || method === 'manual') return undefined
    let live = true
    api.get(`/tpsi/filings/${filingId}/preview`)
      .then(p => { if (live) setPreflight(p) })
      .catch(() => { if (live) setPreflight(null) })
    return () => { live = false }
  }, [filingId, method])

  // load_eservice() falls back to the legacy presentor_account_id when
  // eservice_user_id is unset, but get_metadata deliberately never returns
  // that column — so a user can be able to sign while this screen cannot name
  // the account. The stored PASSWORD is therefore what gates the button; the
  // id is only ever displayed.
  const canSign = cred?.has_eservice_password === true

  async function setMethod(next) {
    if (next === method) return
    onError(null); setBusy('method')
    try {
      await api.patch(`/cases/${caseRow.id}`, { signing_method: next })
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(null)
    }
  }

  async function sign() {
    onError(null); setFailure(null); setBusy('sign')
    try {
      // No body. The backend takes the signatory from the session and refuses
      // the withdrawn fields, so anything sent here would be a 400 rather than
      // a signature in someone else's name.
      await api.post(`/tpsi/filings/${caseRow.filing_id}/sign`, {})
      onChanged()
    } catch (e) {
      const described = describeError(e)
      setFailure(described)
      onError(described)
    } finally {
      setBusy(null)
    }
  }

  async function upload(file) {
    if (!file) return
    onError(null); setBusy('upload')
    try {
      const form = new FormData()
      form.append('file', file)
      await api.upload(`/cases/${caseRow.id}/manual-sign`, form)
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <>
      {/* WHAT AUTHORISES THIS SIGNATURE, at the top of the screen that applies
          it (Levi 2026-09-01). Signing commits the return; the operator about
          to do it should be able to see whether a named director agreed to it
          or whether nobody answered and a job approved it on their silence. */}
      <ClientApproval approval={caseRow.client_approval} />

      <MethodChoice method={method} disabled={!canWrite || done || busy !== null}
                    onPick={setMethod} />

      {method === 'esign' && <Preflight preflight={preflight} cred={cred} />}


      {/* The manual card is NOT replaced by a success alert once a scan is
          attached — it keeps its own done state (v11 `cm-upload-done`), which
          names the file and offers Replace. Swapping it for a generic alert
          left an operator who had attached the wrong scan with no way back. */}
      {method === 'manual' ? (
        <ManualUpload caseRow={caseRow} canWrite={canWrite} busy={busy}
                      fileInput={fileInput} onPick={upload} attached={done} />
      ) : done ? null : (
        <div className="card mb-16">
          <div className="card-hdr">
            <div>
              <div className="card-title">Apply the signature</div>
              <div className="card-sub">
                One signature by one individual — a director or the company
                secretary. CR rejects a signature from a corporate account.
              </div>
            </div>
          </div>

          {failure?.hint && (
            <div className="alert al-warn" role="alert" style={{ marginBottom: 14 }}>
              <span className="al-icon">⚠</span><div className="al-body">{failure.hint}</div>
            </div>
          )}
          {/* NO FaultPanel — the page banner is the single error surface
              (Levi 2026-08-31). `faults` still spaces the group below. */}

          <div className="f-group" style={{ marginTop: faults?.length ? 16 : 0 }}>
            <span className="f-label">Signing as</span>
            {cred === null ? (
              <div className="f-static" aria-busy="true">Checking your credentials…</div>
            ) : canSign ? (
              <>
                <div className="f-static">
                  <b>You</b>
                  {cred.eservice_user_id && (
                    <> — CR e-Service account <code>{cred.eservice_user_id}</code></>
                  )}
                </div>
                <span className="f-hint">
                  Your own stored e-Service signing password is used. A NAR1 can
                  only be signed with the e-Service account of the person signed
                  in — it cannot be signed on anyone else's behalf.
                </span>
              </>
            ) : (
              <div className="alert al-warn" role="status">
                <span className="al-icon">⚠</span>
                <div className="al-body">
                  <b>You have no e-Service signing password stored,</b> so you
                  cannot sign this return. Add one under{' '}
                  <Link to="/cr-credentials">CR Credentials</Link> — it is the{' '}
                  <b>signing</b> password, not the TPSI login one.
                </div>
              </div>
            )}
          </div>

          {canWrite && (
            <div className="action-bar">
              <div className="ab-note">Signing contacts CR. Nothing is charged and nothing is filed.</div>
              <div className="ab-actions">
                <span className="perm-tag">Requires <b>tpsi:write</b></span>
                <button className="btn btn-action" disabled={busy !== null || !canSign}
                        onClick={sign}>
                  {busy === 'sign' ? 'Signing at CR…' : 'Apply signature'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {done && onGo && (
        <div className="action-bar">
          <div className="ab-note">
            {method === 'manual'
              ? 'Record the receipt CR issued for the paper filing.'
              : 'Nothing has been charged yet. The fee is taken at Submission.'}
          </div>
          <div className="ab-actions">
            <button className="btn btn-primary" onClick={() => onGo(4)}>
              Continue to Submission →
            </button>
          </div>
        </div>
      )}
    </>
  )
}

/**
 * v11's `cm-method` radiogroup. Two cards, each carrying the consequence of
 * choosing it — which is the whole reason this is not a toggle.
 */
function MethodChoice({ method, disabled, onPick }) {
  const options = [
    ['esign', 'e-Sign',
     "CR e-Service PIN signing. The fee is drawn from the GSHK deposit account when you submit."],
    ['manual', 'Manual — pen & paper',
     'The signatory signs a printed NAR1. Filed off-portal: no CR API call and no fee deducted here.'],
  ]
  return (
    <div className="meth-group" role="radiogroup" aria-label="Signing method">
      <div className="meth-lbl">Signing method</div>
      {options.map(([value, title, sub]) => (
        <button key={value} type="button" role="radio"
                aria-checked={method === value}
                className={`meth-opt ${method === value ? 'sel' : ''}`}
                disabled={disabled}
                onClick={() => onPick(value)}>
          <span className="meth-radio" aria-hidden="true" />
          <span className="meth-body">
            <b>{title}</b>
            <span className="meth-sub">{sub}</span>
          </span>
        </button>
      ))}
    </div>
  )
}

/**
 * v11's D-2 pre-flight strip: quiet when everything is fine, loud only when it
 * is not. A green "you have enough money" banner on every filing is noise, so
 * the balance is always stated but only the framing changes.
 *
 * The password warning must never swallow the number the operator came for, so
 * it is appended to the balance sentence rather than replacing it.
 */
const PWD_WARN_DAYS = 30

function money(value) {
  const n = Number(value)
  return Number.isFinite(n)
    ? n.toLocaleString('en-HK', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : String(value)
}

export function daysUntil(iso) {
  if (!iso) return null
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return null
  return Math.ceil((then - Date.now()) / 86400000)
}

function Preflight({ preflight, cred }) {
  if (preflight === undefined) {
    return (
      <div className="preflight" role="status">
        <span>Checking deposit balance and account status…</span>
      </div>
    )
  }
  if (preflight === null) {
    return (
      <div className="preflight warn" role="status">
        <span>
          Could not read the deposit balance. Submission checks it again and
          will block if it does not cover the fee.
        </span>
      </div>
    )
  }

  const short = preflight.sufficient === false
  const left = daysUntil(cred?.tpsi_password_expires_at)
  const pwdSoon = left !== null && left <= PWD_WARN_DAYS

  return (
    <div className={`preflight ${short ? 'bad' : pwdSoon ? 'warn' : ''}`} role="status">
      <span>
        Deposit balance <b>HK$ {money(preflight.balance)}</b>
        {short ? (
          <> — <b>below the HK$ {money(preflight.fee)} fee.</b> Top up before
            signing; Submission is blocked until you do.</>
        ) : (
          <> · covers the HK$ {money(preflight.fee)} fee.</>
        )}
        {!short && pwdSoon && (
          <> <b>Your TPSI password expires in {left} day{left === 1 ? '' : 's'}</b>
            {' '}— change it in CR Credentials before it stops a filing
            mid-submission.</>
        )}
      </span>
      <span className="pf-spacer" />
      {!short && (
        <span className="pf-fee">Checked just now · <code>enquireDepositAccount</code></span>
      )}
    </div>
  )
}

/**
 * v11's drop zone. A bare <input type="file"> gives no indication of what
 * document is wanted, and — more importantly — no done state: once a scan was
 * attached there was nothing on screen saying so, or saying that attaching it
 * had been written to the audit trail.
 */
/**
 * Who approved this return, and how (spec §5).
 *
 * A BARE "Approved" IS NEVER RENDERED. The three sources carry different
 * evidence: a self-service confirmation has a director, a timestamp and an IP
 * behind it; a relayed reply has a staff member's word; a timeout approval has
 * nobody's. Collapsing them would let a return nobody ever answered look, on
 * the screen that signs it, exactly like one a director confirmed.
 *
 * Renders nothing when there is no approval — the stepper already refuses to
 * reach this stage without one, and an empty card would only take up room.
 */
function ClientApproval({ approval }) {
  if (!approval) return null
  return (
    <div className={`alert ${approval.system ? 'al-warn' : 'al-success'}`}
         role="status" style={{ marginBottom: 16 }}
         data-testid="client-approval-provenance">
      <span className="al-icon">{approval.system ? '⚠' : '✓'}</span>
      <div className="al-body">
        <b>{approval.summary}</b>
        {approval.responded_at && <> · {formatDateTime(approval.responded_at)}</>}
        {approval.system && (
          <div style={{ marginTop: 4 }}>
            Nobody confirmed this return. If that is not what you expect, stop
            and check with the client before signing.
          </div>
        )}
      </div>
    </div>
  )
}

function ManualUpload({ caseRow, canWrite, busy, fileInput, onPick, attached }) {
  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">Upload the wet-signed NAR1</div>
          <div className="card-sub">
            A scan of the printed form, signed by hand. There is no e-signature
            on this path — the upload is what unlocks Submission.
          </div>
        </div>
      </div>

      <input ref={fileInput} type="file" className="visually-hidden"
             accept="application/pdf,image/*" aria-label="Wet-signed NAR1"
             disabled={!canWrite || busy !== null}
             onChange={e => onPick(e.target.files?.[0])} />

      {attached ? (
        <div className="up-done">
          <span className="up-tick" aria-hidden="true">✓</span>
          <span className="up-txt">
            {/* The case row carries no filename — the signed form is a
                versioned `documents` row (upload_document re-versions the same
                row each year), and the case keeps only the pointer. So the
                version is what identifies WHICH scan is attached. */}
            <b>Signed NAR1 attached</b>
            <span className="up-sub">
              {caseRow.manual_signed_document_version
                ? `Version ${caseRow.manual_signed_document_version} · `
                : ''}
              <code>NAR1_MANUAL_SIGN_UPLOADED</code> written to the audit log
            </span>
          </span>
          {canWrite && (
            <button type="button" className="btn btn-outline btn-sm"
                    style={{ marginLeft: 'auto' }} disabled={busy !== null}
                    onClick={() => fileInput.current?.click()}>
              Replace
            </button>
          )}
        </div>
      ) : (
        <button type="button" className="up-zone" disabled={!canWrite || busy !== null}
                onClick={() => fileInput.current?.click()}>
          <span className="up-arrow" aria-hidden="true">⬆</span>
          <span className="up-txt">
            <b>{busy === 'upload' ? 'Uploading…' : 'Choose the signed PDF'}</b>
            <span className="up-sub">
              The signed original, as delivered to the Companies Registry
            </span>
          </span>
        </button>
      )}
    </div>
  )
}
