import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { formatDateTime } from '../../lib/format.js'
import CheckRow from './CheckRow.jsx'
import RecipientPicker from './RecipientPicker.jsx'
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
  const { isTestEnv } = useAuth()
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(null)
  const [pdfUrl, setPdfUrl] = useState(null)
  const [pdfError, setPdfError] = useState(null)
  const [recipients, setRecipients] = useState([])
  const [to, setTo] = useState(null)
  const [maxRecipients, setMaxRecipients] = useState(20)

  const filingId = caseRow.filing_id
  const sent = Boolean(caseRow.verification_sent_at)
  const answered = Boolean(caseRow.client_response_at)
  const caseId = caseRow.id

  // Who this goes to unless the operator says otherwise. `to` stays null until
  // this lands, so an empty chip row cannot be mistaken for "the operator
  // cleared every director" while the list is still loading — the send button
  // is gated on that distinction.
  useEffect(() => {
    let cancelled = false
    api.get(`/cases/${caseId}/verification/recipients`)
      .then(r => {
        if (cancelled) return
        setRecipients(r.recipients || [])
        setTo(r.default_to || [])
        if (r.max_recipients) setMaxRecipients(r.max_recipients)
      })
      .catch(e => { if (!cancelled) onError(describeError(e)) })
    return () => { cancelled = true }
    // onError is recreated per render by the parent; depending on it here would
    // refetch the recipient list on every keystroke elsewhere on the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

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
      // Always explicit, never `{}`. The chips on screen are what the operator
      // agreed to send to; letting the server re-derive the list would mail a
      // director they had just removed, and the two answers can differ the
      // moment someone edits the company in another tab.
      await api.post(`/cases/${caseRow.id}/verification/send`, { to })
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

        {/* The "nothing was actually delivered" warning that stood here is
            gone with EMAIL_TRANSPORT=console (2026-08-30). Mail now really
            sends; on a test deployment it reaches the four fixed recipients,
            which the test-environment note above already says. */}

        {/* The tick gates the send (R-5): an unread return going to a client
            over GSHK's name is the mistake this exists to slow down. */}
        <CheckRow
          checked={reviewed}
          disabled={!canWrite || busy !== null}
          onToggle={setReviewed}
          title="I have reviewed this return and it is correct"
          sub="Check the particulars above before it goes to the client."
        />

        {canWrite && (
          <div className="action-bar">
            <div className="ab-note">
              {!reviewed
                ? 'Confirm you have reviewed the return to enable sending.'
                : to === null
                  ? 'Loading the recipients…'
                  : to.length === 0
                    ? 'Add at least one recipient below.'
                    : `The return will be attached as a PDF, to ${to.length} `
                      + `recipient${to.length === 1 ? '' : 's'}.`}
            </div>
            <div className="ab-actions">
              <button className="btn btn-action"
                      disabled={!reviewed || busy !== null || !to || to.length === 0}
                      onClick={send}>
                {busy === 'send' ? 'Sending…' : sent ? 'Send again' : 'Send to client'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Below the send card on purpose: the tick above is about the RETURN,
          this is about the ADDRESSES, and merging them into one control would
          let a single click assert both. */}
      <RecipientPicker
        recipients={recipients}
        to={to || []}
        onChange={setTo}
        disabled={!canWrite || busy !== null || to === null}
        maxRecipients={maxRecipients}
      />

      {/* Levi 2026-08-30. The picker above deliberately still shows and still
          sends the REAL director addresses — selecting them is the thing being
          tested. The backend substitutes a fixed internal list before anything
          leaves the process (email_service.TEST_RECIPIENTS), which no
          environment variable can override. This note is the only place the
          operator is told that, so it sits directly under the addresses it is
          about rather than in a page-level banner they would scroll past. */}
      {isTestEnv && (
        <div className="f-hint" style={{ margin: '-6px 0 16px 2px', lineHeight: 1.5 }}>
          This is a test environment, so email will not actually be sent to the
          client.
        </div>
      )}

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
