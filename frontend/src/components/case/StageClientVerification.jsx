import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import CheckRow from './CheckRow.jsx'
import { describeError } from './workflow.js'

/**
 * Stage 2 — Client Verification (FE-3).
 *
 * The client sees the return before it is filed in their name. The PDF is
 * rendered from the CR-VALIDATED snapshot, not from the live company record —
 * showing the client one document and filing another is the failure this
 * guards against.
 *
 * R1 has no inbound mail handling: the client replies to GSHK by email and a
 * human records the answer here. That is why "Client approved" is a button an
 * admin presses, and why it is audited as CLIENT_APPROVAL_RECEIVED.
 */
export default function StageClientVerification({ caseRow, canWrite, onChanged, onError }) {
  const [reviewed, setReviewed] = useState(false)
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(null)
  const [pdfUrl, setPdfUrl] = useState(null)
  const [pdfError, setPdfError] = useState(null)

  const filingId = caseRow.filing_id
  const sent = Boolean(caseRow.verification_sent_at)
  const answered = Boolean(caseRow.client_response_at)

  // The PDF is fetched as a blob so the bearer token is not put in a URL. The
  // object URL is revoked on unmount; leaving it leaks the whole document.
  useEffect(() => {
    if (!filingId) return undefined
    let url = null
    let cancelled = false
    api.blob(`/tpsi/filings/${filingId}/pdf`)
      .then(b => {
        if (cancelled) return
        url = URL.createObjectURL(b)
        setPdfUrl(url)
      })
      .catch(e => { if (!cancelled) setPdfError(describeError(e)) })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [filingId])

  async function send() {
    onError(null); setBusy('send')
    try {
      await api.post(`/cases/${caseRow.id}/verification/send`,
                     to.trim() ? { to: to.trim() } : {})
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(null)
    }
  }

  async function record(approved) {
    onError(null); setBusy(approved ? 'approve' : 'reject')
    try {
      await api.post(`/cases/${caseRow.id}/verification/response`, { approved })
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
            <div className="card-title">The return the client will see</div>
            <div className="card-sub">
              Rendered from the CR-validated snapshot — the same document that
              will be filed.
            </div>
          </div>
        </div>

        {pdfError ? (
          <div className="alert al-warn" role="alert">
            <span className="al-icon">⚠</span>
            <div className="al-body">
              Could not render the preview: {pdfError.message}
              {pdfError.hint && <div style={{ marginTop: 4 }}>{pdfError.hint}</div>}
            </div>
          </div>
        ) : pdfUrl ? (
          <object data={pdfUrl} type="application/pdf" aria-label="NAR1 preview"
                  style={{ width: '100%', height: 460, border: '1px solid var(--border)', borderRadius: 8 }}>
            {/* Some browsers refuse to embed; a link is not a dead end. */}
            <a href={pdfUrl} target="_blank" rel="noreferrer">Open the NAR1 preview</a>
          </object>
        ) : (
          <div className="empty-state" style={{ padding: 24 }}>Rendering the preview…</div>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Send for verification</div>
            <div className="card-sub">Emails the client the return and asks them to confirm it.</div>
          </div>
        </div>

        {sent && (
          <div className="alert al-success" role="status" style={{ marginBottom: 14 }}>
            <span className="al-icon">✓</span>
            <div className="al-body">
              Sent {formatDateTime(caseRow.verification_sent_at)}.
              {!answered && ' Waiting on the client\'s reply.'}
            </div>
          </div>
        )}

        {/* The tick gates the send (R-5): an unread return going to a client
            over GSHK's name is the mistake this exists to slow down. */}
        <CheckRow
          checked={reviewed}
          disabled={!canWrite || busy !== null}
          onToggle={setReviewed}
          title="I have reviewed this return and it is correct"
          sub="Check the particulars above before it goes to the client."
        />

        <div className="f-group" style={{ marginTop: 12 }}>
          <label className="f-label" htmlFor="cv-to">Send to</label>
          <input id="cv-to" className="f-input" value={to} disabled={!canWrite}
                 placeholder="Leave blank to use the address on record"
                 onChange={e => setTo(e.target.value)} />
          <span className="f-hint">
            Overrides the client contact held against this company, for this send only.
          </span>
        </div>

        {canWrite && (
          <div className="action-bar">
            <div className="ab-note">
              {reviewed ? 'The return will be attached as a PDF.'
                        : 'Confirm you have reviewed the return to enable sending.'}
            </div>
            <div className="ab-actions">
              <button className="btn btn-action" disabled={!reviewed || busy !== null}
                      onClick={send}>
                {busy === 'send' ? 'Sending…' : sent ? 'Send again' : 'Send to client'}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Client's answer</div>
            <div className="card-sub">
              Recorded by you from the client's reply — the portal does not read
              inbound mail.
            </div>
          </div>
        </div>

        {answered ? (
          <div className={`alert ${caseRow.client_approved ? 'al-success' : 'al-danger'}`} role="status">
            <span className="al-icon">{caseRow.client_approved ? '✓' : '⚠'}</span>
            <div className="al-body">
              <b>{caseRow.client_approved ? 'Client approved' : 'Client declined'}</b>{' '}
              on {formatDateTime(caseRow.client_response_at)}.
              {!caseRow.client_approved
                && ' Correct the return, restart verification and send it again.'}
            </div>
          </div>
        ) : canWrite ? (
          <div className="action-bar">
            <div className="ab-note">
              {sent ? 'Record what the client replied.'
                    : 'Send the return first, then record the reply.'}
            </div>
            <div className="ab-actions">
              <button className="btn btn-outline" disabled={!sent || busy !== null}
                      onClick={() => record(false)}>
                {busy === 'reject' ? 'Recording…' : 'Client declined'}
              </button>
              <button className="btn btn-action" disabled={!sent || busy !== null}
                      onClick={() => record(true)}>
                {busy === 'approve' ? 'Recording…' : 'Client approved'}
              </button>
            </div>
          </div>
        ) : (
          <div className="empty-state" style={{ padding: 16 }}>No answer recorded yet.</div>
        )}
      </div>
    </>
  )
}
