import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api.js'
import FaultPanel from './FaultPanel.jsx'
import { describeError, signedOff } from './workflow.js'

/**
 * Stage 3 — Signing. e-Sign (FE-2) and manual (FE-4) on one screen.
 *
 * THE TWO ROUTES ARE EXCLUSIVE AND THE CHOICE IS CONSEQUENTIAL. e-Sign applies
 * a real PIN signature at CR and leads to a chargeable submit. Manual means the
 * return is signed on paper and filed OFF this portal; the backend then refuses
 * the e-Sign chain for that case entirely. A wet signature is not evidence for
 * an e-filing and vice versa, so switching route discards what the other
 * produced rather than carrying it across.
 *
 * WHO SIGNS IS NOT A FIELD ON THIS SCREEN. A NAR1 is signed with the logged-in
 * user's own stored e-Service credential and no other (Levi, Q1 2026-08-30).
 * This screen used to offer two text boxes — a signatory id and a password — so
 * a client director could sign live; that made the signing account free text on
 * a statutory declaration and it is withdrawn. All this screen does now is show
 * whose signature is about to be applied, and refuse to proceed when the
 * logged-in user has no credential to apply.
 */
export default function StageSigning({ caseRow, canWrite, onChanged, onError }) {
  const method = caseRow.signing_method || 'esign'
  const [busy, setBusy] = useState(null)
  const [failure, setFailure] = useState(null)
  const [cred, setCred] = useState(null)
  const fileInput = useRef(null)

  // Read once, and never block the screen on it: a credential lookup that
  // fails must not hide the manual route, which needs no credential at all.
  useEffect(() => {
    let live = true
    api.get('/tpsi/credentials')
      .then(c => { if (live) setCred(c || {}) })
      .catch(() => { if (live) setCred({}) })
    return () => { live = false }
  }, [])

  // load_eservice() falls back to the legacy presentor_account_id when
  // eservice_user_id is unset, but get_metadata deliberately never returns
  // that column — so a user can be able to sign while this screen cannot name
  // the account. The stored PASSWORD is therefore what gates the button; the
  // id is only ever displayed.
  const canSign = cred?.has_eservice_password === true

  const done = signedOff(caseRow)
  const faults = caseRow.form_status?.code === 'signing_failed'
    ? caseRow.form_status.faults : null

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
      // No body. The backend takes the signatory from the session and forbids
      // extra fields, so anything sent here would be a 422 rather than a
      // signature in someone else's name.
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
      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">How will this return be signed?</div>
            <div className="card-sub">
              e-Sign files through this portal. Manual means it is signed on
              paper and filed outside it.
            </div>
          </div>
        </div>

        <div className="seg seg-inline" role="tablist" aria-label="Signing method">
          <button className={`seg-btn ${method === 'esign' ? 'active' : ''}`}
                  role="tab" aria-selected={method === 'esign'}
                  disabled={!canWrite || done || busy !== null}
                  onClick={() => setMethod('esign')}>
            e-Sign via CR
          </button>
          <button className={`seg-btn ${method === 'manual' ? 'active' : ''}`}
                  role="tab" aria-selected={method === 'manual'}
                  disabled={!canWrite || done || busy !== null}
                  onClick={() => setMethod('manual')}>
            Manual (wet signature)
          </button>
        </div>

        {method === 'manual' && (
          <div className="alert al-warn" role="status">
            <span className="al-icon">⚠</span>
            <div className="al-body">
              <b>This filing leaves G-FlowDesk.</b> Choosing manual means the
              return is signed on paper and submitted to the Companies Registry
              outside this portal. The portal will refuse to e-file this case
              afterwards — record the CR receipt here instead.
            </div>
          </div>
        )}
      </div>

      {done ? (
        <div className="card mb-16">
          <div className="alert al-success" role="status">
            <span className="al-icon">✓</span>
            <div className="al-body">
              {method === 'manual'
                ? 'The wet-signed return is attached. Record the CR receipt at the next step.'
                : 'The return is signed at CR. It has not been filed yet, and nothing has been charged.'}
            </div>
          </div>
        </div>
      ) : method === 'esign' ? (
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
          <FaultPanel faults={faults} title="The Companies Registry refused the signature" />

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
                <button className="btn btn-action" disabled={busy !== null || !canSign}
                        onClick={sign}>
                  {busy === 'sign' ? 'Signing at CR…' : 'Sign the return'}
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="card mb-16">
          <div className="card-hdr">
            <div>
              <div className="card-title">Upload the wet-signed return</div>
              <div className="card-sub">A scan of the signed NAR1. No CR call is made.</div>
            </div>
          </div>

          <input ref={fileInput} type="file" className="f-input" accept="application/pdf,image/*"
                 aria-label="Wet-signed NAR1"
                 disabled={!canWrite || busy !== null}
                 onChange={e => upload(e.target.files?.[0])} />
          <span className="f-hint" style={{ marginTop: 6, display: 'block' }}>
            {busy === 'upload' ? 'Uploading…' : 'PDF or an image of the signed form.'}
          </span>
        </div>
      )}
    </>
  )
}
