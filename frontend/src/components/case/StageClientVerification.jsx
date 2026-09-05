import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { formatDateTime } from '../../lib/format.js'
import { downloadFilingPdf } from '../../lib/download.js'
import CheckRow from './CheckRow.jsx'
import RecipientPicker from './RecipientPicker.jsx'
import { describeError, verificationBlock, isSubmitted } from './workflow.js'
import { ActionWithheld } from '../RequirePermission.jsx'

// Zoom bounds for the embedded preview. 60% still shows a full A4 page on a
// laptop; past 200% the object viewport is taller than any screen and the
// operator is scrolling a scroller.
const ZOOM_MIN = 60
const ZOOM_MAX = 200
const ZOOM_STEP = 20

/**
 * What a failed SEND means — which is not what a failed CR call means.
 *
 * `describeError` answers for the TPSI chain: its 502 hint talks about the
 * Companies Registry refusing a filing, and its 503 hint sends the reader to
 * CR's Monday-to-Friday service window. Both are wrong here. Nothing on this
 * path touches CR — a 502 is Resend rejecting the message, and a 503 is the
 * deployment missing its mail configuration, which no amount of waiting for
 * Hong Kong office hours will fix.
 */
export function describeSendError(err) {
  const message = err?.message || 'The verification email was not sent.'
  switch (err?.status) {
    case 403:
      return { message, hint: 'Your role does not allow sending client verification for this case.' }
    case 409:
      // What state, and what to do about it — not the bare fact that the case
      // is in the wrong one. "Not in a state that allows this" is a sentence
      // an operator can do nothing with (Levi 2026-09-03).
      return {
        message,
        hint: 'Nothing was sent. The return has to be validated by CR and not '
          + 'yet filed before it can go to the client — check the CR form '
          + 'status in the header.',
      }
    case 422:
      return { message, hint: 'Fix the recipient list or re-validate the return, then try again.' }
    case 502:
      return {
        message,
        hint: 'The mail provider refused the message. Nothing was sent and the '
          + 'case is unchanged, so it is safe to try again.',
      }
    case 503:
      return {
        message,
        hint: 'This deployment is missing its email configuration — someone '
          + 'with access to the backend environment needs to set it. Nothing '
          + 'was sent.',
      }
    default:
      return { message, hint: 'Nothing was sent and the case is unchanged.' }
  }
}

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
export default function StageClientVerification({ caseRow, canWrite, onChanged, onError, onWarn }) {
  const { isTestEnv, profile } = useAuth()
  // Seeded from the case, not defaulted to false. The tick gates the send, and
  // the send is the evidence it was given: a mail cannot have gone out without
  // it. Leaving it unticked on a case whose banner says "Sent 31 Aug 2026,
  // 19:52" reads as a step that came undone — which is how Levi found it,
  // after stepping forward to Signing and back.
  //
  // `Restart verification` clears verification_sent_at, so it correctly resets
  // here too: a restarted case really does need reviewing again.
  const [reviewed, setReviewed] = useState(Boolean(caseRow.verification_sent_at))
  const [busy, setBusy] = useState(null)
  // NO LOCAL ERROR STATE. What the send refused goes to `onError` and what it
  // REPORTED — a partial delivery, a message without a Confirm button — goes
  // to `onWarn`. Both render at the top of the page and both scroll there, so
  // this screen no longer keeps an error surface of its own (Levi 2026-09-03).
  const [pdfUrl, setPdfUrl] = useState(null)
  const [pdfError, setPdfError] = useState(null)
  const [recipients, setRecipients] = useState([])
  const [to, setTo] = useState(null)
  const [maxRecipients, setMaxRecipients] = useState(20)
  const [zoom, setZoom] = useState(100)
  const [saving, setSaving] = useState(false)

  const filingId = caseRow.filing_id
  const sent = Boolean(caseRow.verification_sent_at)
  const answered = Boolean(caseRow.client_response_at)
  const caseId = caseRow.id
  // Why the backend would refuse this send, worked out before the operator
  // presses anything. See workflow.verificationBlock.
  const blocked = verificationBlock(caseRow)
  // Filed by EITHER road: CR holds it, or it was filed off-portal on paper.
  const filed = isSubmitted(caseRow)
  const pdfName =
    `NAR1_${(caseRow.company_name || 'return').replace(/[^\w]+/g, '_')}.pdf`

  async function download() {
    setSaving(true)
    try {
      await downloadFilingPdf(filingId, pdfName)
    } catch (e) {
      onError(describeError(e))
    } finally {
      setSaving(false)
    }
  }

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
    onError(null); onWarn?.(null, null); setBusy('send')
    try {
      // Always explicit, never `{}`. The chips on screen are what the operator
      // agreed to send to; letting the server re-derive the list would mail a
      // director they had just removed, and the two answers can differ the
      // moment someone edits the company in another tab.
      const result = await api.post(
        `/cases/${caseRow.id}/verification/send`, { to })
      // ONE MESSAGE PER DIRECTOR now, so a send can partly succeed. The
      // response names the addresses that failed; showing only a green tick
      // would leave a director unasked with nothing on screen saying so.
      //
      // Raised to the page, which puts it in the same place as every other
      // outcome and scrolls there — a partial send is the thing on this screen
      // an operator is most likely to miss, because the stage advances and the
      // status changes around it.
      if (result?.failed_to?.length) {
        const one = result.failed_to.length === 1
        onWarn?.('The return did not reach everyone.',
          `${result.failed_to.join(', ')} — send again to just `
          + `${one ? 'that address' : 'those addresses'}. The others have it `
          + 'and their links are live.')
      } else if (result?.approval_links === false) {
        onWarn?.('Sent without a Confirm button.',
          'This deployment could not build the approval link, so the client '
          + 'has to reply by email and you record the answer below. '
          + 'PUBLIC_API_BASE_URL needs setting on the backend.')
      }
      onChanged()
    } catch (e) {
      // TO THE PAGE, like every other refusal. It used to be drawn here next
      // to the button because the banner sits above a 690px PDF frame and was
      // therefore off-screen — but the page now scrolls to the banner on every
      // failure, so the reason for the exception is gone, and keeping it would
      // leave this screen with an error surface no other stage has (Levi
      // 2026-09-03).
      onError(describeSendError(e))
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
      {/* v11 leads this stage with the snapshot, because everything on it —
          the PDF, the email, and eventually the filing — reads the frozen copy
          rather than the company profile. Without this, a profile edited after
          validation looks like a bug in the preview. */}
      <div className="alert al-success" role="note" style={{ marginBottom: 16 }}>
        <span className="al-icon">🔒</span>
        <div className="al-body">
          <b>Snapshot frozen at validation.</b> The PDF below is generated from
          the CR-validated XML. It, the client email, and the CR submission all
          read <b>this snapshot</b> — not the live profile.
        </div>
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">The return the client will see</div>
            <div className="card-sub">
              Rendered from the CR-validated snapshot — the same document that
              will be filed.
            </div>
          </div>
          <div className="row gap-8">
            <button type="button" className="btn btn-outline btn-sm"
                    disabled={!pdfUrl || saving} onClick={download}>
              {saving ? 'Preparing…' : 'Download PDF'}
            </button>
            {/* A tab, not a modal: the operator is checking this against the
                company record in another window, and even 690px of embedded
                viewer is not a whole nine-page statutory return. */}
            <button type="button" className="btn btn-outline btn-sm"
                    disabled={!pdfUrl}
                    onClick={() => window.open(pdfUrl, '_blank', 'noopener')}>
              Open full screen
            </button>
          </div>
        </div>

        {pdfError ? (
          // The preview pane saying it has nothing to show, in the place the
          // preview would have been. Not an alert: nothing the operator did
          // was refused, and the Download and Send controls above it still
          // work.
          <div className="card-note card-note-warn" role="status">
            <b>The preview could not be rendered.</b>
            <div style={{ marginTop: 4 }}>{pdfError.message}</div>
            {pdfError.hint && <div style={{ marginTop: 4 }}>{pdfError.hint}</div>}
          </div>
        ) : pdfUrl ? (
          <>
            <div className="pdf-toolbar">
              <span className="pdf-fname">{pdfName}</span>
              <span className="pdf-pill">Form NAR1 + Schedule 1</span>
              <span className="pdf-pill ok">Rendered from the CR-validated XML</span>
              <span className="pdf-tb-spacer" />
              <span className="pdf-zoom">
                <button type="button" aria-label="Zoom out" disabled={zoom <= ZOOM_MIN}
                        onClick={() => setZoom(z => Math.max(ZOOM_MIN, z - ZOOM_STEP))}>−</button>
                <span className="zval">{zoom}%</span>
                <button type="button" aria-label="Zoom in" disabled={zoom >= ZOOM_MAX}
                        onClick={() => setZoom(z => Math.min(ZOOM_MAX, z + ZOOM_STEP))}>+</button>
              </span>
            </div>
            {/* Zoom grows the VIEWPORT, not a CSS transform. Scaling the
                element would scale its scrollbars and clip the page; a taller
                frame is what the embedded viewer actually reads as bigger. */}
            <object data={pdfUrl} type="application/pdf" aria-label="NAR1 preview"
                    className="pdf-frame"
                    style={{ height: Math.round(690 * zoom / 100) }}>
              {/* Some browsers refuse to embed; a link is not a dead end. */}
              <a href={pdfUrl} target="_blank" rel="noreferrer">Open the NAR1 preview</a>
            </object>
          </>
        ) : (
          <div className="empty-state" style={{ padding: 24 }}>Rendering the preview…</div>
        )}
      </div>

      {/* ONE section, in the order the decision is made (Levi 2026-08-30):
          confirm the return is right, then confirm who gets it, then send.
          Recipients used to be a separate card BELOW this one, which put the
          list of addresses after the button that mails them. */}
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
          readOnly={!canWrite}
          disabled={busy !== null || Boolean(blocked)
                    || Boolean(caseRow.verification_sent_at)}
          onToggle={setReviewed}
          title="I have reviewed this return and it is correct"
          sub="Check the particulars above before it goes to the client."
        />

        <RecipientPicker
          recipients={recipients}
          to={to || []}
          onChange={setTo}
          readOnly={!canWrite}
          disabled={busy !== null || to === null || Boolean(blocked)}
          maxRecipients={maxRecipients}
        />

        {/* Named, not implied. "A copy goes to you" is unverifiable; the
            address is the whole assurance. Both facts are stated because they
            are different promises — one is a copy, the other is where the
            client's answer lands. */}
        <div className="cc-note">
          <span className="cc-icon" aria-hidden="true">↩</span>
          <div>
            {profile?.email
              ? <>A copy goes to <b>{profile.email}</b>, and the client's reply
                  comes back to you rather than to the no-reply address.</>
              : <>A copy goes to you, and the client's reply comes back to you
                  rather than to the no-reply address.</>}
          </div>
        </div>

        {/* Levi 2026-08-30. The picker above deliberately still shows and still
            sends the REAL director addresses — selecting them is the thing
            being tested. The backend substitutes a fixed internal list before
            anything leaves the process (email_service.TEST_RECIPIENTS), which
            no environment variable can override. */}
        {isTestEnv && (
          <div className="f-hint" style={{ marginTop: 10, lineHeight: 1.5 }}>
            This is a test environment, so nothing is delivered to the client —
            the message goes to the fixed internal test recipients instead, and
            the copy to you is dropped because you are already on that list.
          </div>
        )}

        {/* NEITHER THE REFUSAL NOR THE PARTIAL-SEND REPORT IS DRAWN HERE
            any more. They were, because the page banner sits above a 690px PDF
            frame and a refused send therefore looked like a dead button. The
            page now scrolls to the banner on every failure, which removes the
            reason — and leaving them would give this one stage an error
            surface no other stage has. */}

        {/* PRE-EMPTIVE, and therefore not an alert: this says why the Send
            button is not on offer, before anyone presses anything. It reads as
            a note under the controls rather than as a refusal, which is what
            an alert box would have claimed. */}
        {blocked && !filed && (
          <div className="card-note card-note-warn" role="status"
               style={{ marginTop: 14 }}>{blocked}</div>
        )}

        {/* Nothing to send once the return is in the register, so nothing is
            offered. A disabled button beside a warning explaining why you may
            not press it is worse than no button: it invites the press. What
            stays above is the record — who it went to, when, what they said. */}
        {!filed && (canWrite ? (
          <div className="action-bar">
            <div className="ab-note">
              {blocked
                ? 'Sending is not available for this case.'
                : !reviewed
                  ? 'Confirm you have reviewed the return to enable sending.'
                  : to === null
                    ? 'Loading the recipients…'
                    : to.length === 0
                      ? 'Add at least one recipient above.'
                      : `The return will be attached as a PDF, to ${to.length} `
                        + `recipient${to.length === 1 ? '' : 's'}.`}
            </div>
            <div className="ab-actions">
              <span className="perm-tag">Requires <b>nar1:write</b></span>
              <button className="btn btn-action"
                      disabled={!reviewed || busy !== null || !to
                                || to.length === 0 || Boolean(blocked)}
                      onClick={send}>
                {busy === 'send' ? 'Sending…' : sent ? 'Send again' : 'Send to client'}
              </button>
            </div>
          </div>
        ) : (
          // The bar was simply absent before, which left a stage whose entire
          // purpose — get this to the client — had vanished without a word.
          <div className="action-bar">
            <div className="ab-note">
              This return has not been sent to the client yet.
            </div>
            <div className="ab-actions">
              <ActionWithheld module="nar1" action="sending it to the client" />
            </div>
          </div>
        ))}
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Client's answer</div>
            <div className="card-sub">
              The client can confirm from the link in their email, or reply and
              have you record it here — the portal does not read inbound mail.
            </div>
          </div>
        </div>

        {answered ? (
          <div className={`alert ${caseRow.client_approved ? 'al-success' : 'al-danger'}`} role="status">
            <span className="al-icon">{caseRow.client_approved ? '✓' : '⚠'}</span>
            <div className="al-body">
              {/* HOW it was approved, never a bare "Client approved" (spec §5).
                  A case the 14-day job approved on the client's silence must not
                  read the same as one a named director agreed to — the evidence
                  behind them is completely different, and the difference is
                  exactly what somebody reviewing a filing needs to see. */}
              <b>{caseRow.client_approved
                ? (caseRow.client_approval?.summary || 'Client approved')
                : 'Client declined'}</b>{' '}
              on {formatDateTime(caseRow.client_response_at)}.
              {caseRow.client_approval?.system
                && ' Nobody replied; the return is being filed as prepared.'}
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
          <div className="action-bar">
            <div className="ab-note">No answer recorded yet.</div>
            <div className="ab-actions">
              <ActionWithheld module="nar1"
                              action="recording the client's reply" />
            </div>
          </div>
        )}
      </div>
    </>
  )
}
