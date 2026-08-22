import { useState, useRef } from 'react'
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
 * The e-Service password is the SIGNING password, never the TPSI login one
 * (which authenticates and signs nothing). A client director's password is
 * never stored — they supply it at the moment of signing (D4).
 */
export default function StageSigning({ caseRow, canWrite, onChanged, onError }) {
  const method = caseRow.signing_method || 'esign'
  const [password, setPassword] = useState('')
  const [signatory, setSignatory] = useState('')
  const [busy, setBusy] = useState(null)
  const [failure, setFailure] = useState(null)
  const fileInput = useRef(null)

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
      const body = {}
      if (signatory.trim()) body.signatory_user_id = signatory.trim()
      if (password) body.eservice_password = password
      await api.post(`/tpsi/filings/${caseRow.filing_id}/sign`, body)
      // Never keep a signing password in memory a moment longer than the call.
      setPassword('')
      onChanged()
    } catch (e) {
      setPassword('')
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
            <label className="f-label" htmlFor="sg-signatory">Signatory e-Service user ID</label>
            <input id="sg-signatory" className="f-input" value={signatory} disabled={!canWrite}
                   placeholder="Leave blank to sign as yourself"
                   onChange={e => setSignatory(e.target.value)} />
            <span className="f-hint">
              CR's e-Service user ID for the person signing — not a G-FlowDesk
              user. Blank signs with your own stored credentials.
            </span>
          </div>

          <div className="f-group">
            <label className="f-label" htmlFor="sg-password">e-Service signing password</label>
            <input id="sg-password" className="f-input" type="password" value={password}
                   disabled={!canWrite} autoComplete="off"
                   placeholder="Leave blank to use your stored password"
                   onChange={e => setPassword(e.target.value)} />
            <span className="f-hint">
              The <b>signing</b> password, not the TPSI login password. A client
              director's password is never stored — enter it here at the moment
              of signing and it is discarded straight after.
            </span>
          </div>

          {canWrite && (
            <div className="action-bar">
              <div className="ab-note">Signing contacts CR. Nothing is charged and nothing is filed.</div>
              <div className="ab-actions">
                <button className="btn btn-action" disabled={busy !== null} onClick={sign}>
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
