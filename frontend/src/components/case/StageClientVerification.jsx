import { useState, useEffect } from 'react'
import { api } from '../../lib/api.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { formatDateTime } from '../../lib/format.js'
import { hongKongTodayISO } from '../../lib/anniversary.js'
import { downloadCasePdf } from '../../lib/download.js'
import CheckRow from './CheckRow.jsx'
import PdfFrame, { usePdfBlob } from './PdfPreview.jsx'
import RecipientPicker from './RecipientPicker.jsx'
import ReturnYearCard from './ReturnYearCard.jsx'
import VerificationDeliveryModal from './VerificationDeliveryModal.jsx'
import { describeError, verificationBlock, isSubmitted, isValidated } from './workflow.js'
import { ActionWithheld } from '../RequirePermission.jsx'

/**
 * The address copied on every client verification email (Levi 2026-09-08).
 *
 * MUST MATCH `email_service.CLIENT_CC` — the backend decides who is actually
 * copied; this only tells the operator who that is. The screen states it as a
 * promise about a message that has not been sent yet, so it cannot read the
 * value back off a response, which is why the constant is repeated here at all.
 * `test_client_cc_matches_the_screen` in the backend suite reads THIS FILE and
 * fails if the two ever drift, so a change on either side has to be made on
 * both.
 */
export const CLIENT_CC = 'renewal@getstarted.hk'

// The frame's height and zoom live in PdfPreview.jsx now (2026-09-18), shared
// with Data Verification's validated-form viewer so the two copies of one
// return are looked at through the same window.

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
      // The "has to be validated by CR first" half of this was removed on
      // 2026-09-17: Client Verification is the FIRST stage now, so CR has not
      // seen the return when this is sent and that advice would send an
      // operator to do something the new order does not ask for. What is left
      // is the only 409 the gate can still produce here.
      return {
        message,
        hint: 'Nothing was sent. This case is already finished — CR is holding '
          + 'the return, or it was filed off-portal — so there is nothing left '
          + 'for the client to approve.',
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
 * What a partly-successful send actually did — who has the return, and who
 * does not, and why not.
 *
 * ONE MESSAGE PER DIRECTOR means a send can now half-work, and the report has
 * to answer the operator's real question, which is "do I need to do this
 * again, and for whom". Naming only the failures made re-sending to the whole
 * board the safe move, and that puts a second request for the same return in
 * front of a director who has already confirmed.
 *
 * The REASON is carried per address because the two failures need different
 * actions: a malformed address is fixed on the chip and re-sent, while a
 * provider rejection is fixed by pressing Send again with nothing changed.
 *
 * IT SAYS WHAT SENDING AGAIN COSTS, and that is not a detail. Every send
 * reissues the whole case's tokens (`nar1_approvals.issue` supersedes the
 * outstanding set), so a second send does not quietly top up the directors who
 * were missed: it kills the links the others are holding and asks them again.
 * An operator told only "send again" would find that out from a client.
 */
export function describePartialSend(result) {
  const failed = result?.failed?.length
    ? result.failed
    : (result?.failed_to || []).map(email => ({ email, reason: null }))
  const delivered = result?.to || []

  const missed = failed
    .map(f => (f.reason ? `${f.email} (${f.reason})` : f.email))
    .join(', ')
  const one = failed.length === 1

  const sent = delivered.length
    ? `Sent to ${delivered.join(', ')} — ${delivered.length === 1 ? 'that link is' : 'those links are'} live. `
    : ''

  const again = delivered.length
    ? ' Sending again reissues every link on this case, so anyone above who '
      + 'already has it will be asked a second time and their current link '
      + 'stops working.'
    : ''

  return `${sent}NOT sent to ${missed}. `
    + `Fix ${one ? 'that address' : 'those addresses'} and send again.${again}`
}

/**
 * Stage 1 — Client Verification (FE-3).
 *
 * THE FIRST STAGE SINCE 2026-09-17, not the second. The client sees the return
 * before it is filed in their name, and now before CR has seen it either: the
 * PDF is rendered from `request_xml`, the return built from the company record,
 * so their corrections arrive before the filing is prepared rather than after
 * it. CR's own form, either way — a director knows what Form NAR1 looks like.
 *
 * The bytes mailed are stored on the case, so that when a CR rejection later
 * forces an edit the case can say which fields have moved since the director
 * said yes. That is a warning and never a refusal; see
 * `services/nar1_verification.py`.
 *
 * R1 has no inbound mail handling: the client replies to GSHK by email and a
 * human records the answer here. That is why "Client approved" is a button an
 * admin presses, and why it is audited as CLIENT_APPROVAL_RECEIVED.
 */
export default function StageClientVerification({ caseRow, canWrite, onChanged, onError, onWarn, onGo }) {
  // `profile` was read here only to name the signed-in user as the CC. The
  // copy is now the fixed renewals mailbox, so the screen no longer depends on
  // who is looking at it.
  const { isTestEnv } = useAuth()
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
  // The per-recipient list from the send that just happened, or null when no
  // send is being confirmed. Non-null puts the sending splash on screen and
  // holds the operator there until Resend has reported (or the wait times
  // out) — see VerificationDeliveryModal.
  const [confirming, setConfirming] = useState(null)
  // NO LOCAL ERROR STATE. What the send refused goes to `onError` and what it
  // REPORTED — a partial delivery, a message without a Confirm button — goes
  // to `onWarn`. Both render at the top of the page and both scroll there, so
  // this screen no longer keeps an error surface of its own (Levi 2026-09-03).
  const [recipients, setRecipients] = useState([])
  const [to, setTo] = useState(null)
  const [maxRecipients, setMaxRecipients] = useState(20)
  const [saving, setSaving] = useState(false)
  // THE CLIENT'S DEADLINE, and it starts EMPTY (Levi 2026-09-07). It used to be
  // `sent + 14 days`, computed in the token issuer, chosen by nobody — and a
  // fortnight is not a business rule: some clients are chased inside a week,
  // and a return prepared months before its filing window should not have its
  // link die long before anyone intends to file. Seeding it with a default
  // would put the old behaviour back behind a field the operator never reads.
  const [respondBy, setRespondBy] = useState('')

  const filingId = caseRow.filing_id
  const sent = Boolean(caseRow.verification_sent_at)
  const answered = Boolean(caseRow.client_response_at)

  // THE SEED ABOVE IS NOT ENOUGH ONCE RESTART IS ON OFFER HERE (2026-09-19).
  // `useState` reads `verification_sent_at` on mount only, and a restart
  // pressed while this stage is on screen re-reads the case WITHOUT remounting
  // it — so the tick stayed checked on a return nobody had looked at since, and
  // Send was one click away. Cleared on the transition to unsent; a tick the
  // operator gives before sending never changes `sent`, so it is left alone.
  useEffect(() => {
    if (!sent) setReviewed(false)
  }, [sent])
  const caseId = caseRow.id
  // Why the backend would refuse this send, worked out before the operator
  // presses anything. See workflow.verificationBlock.
  const blocked = verificationBlock(caseRow)
  // Filed by EITHER road: CR holds it, or it was filed off-portal on paper.
  const filed = isSubmitted(caseRow)
  // Whether CR has actually seen this return. Stage 1 is normally reached
  // BEFORE it has, so the copy on this screen must not claim otherwise — see
  // the banner below.
  const validated = isValidated(caseRow)
  // FROZEN ONCE SENT (Levi 2026-09-18): from the moment the return is mailed,
  // this stage shows the return the client was sent — and, once they answer,
  // the return they approved — however the record or CR's copy moves after.
  // The backend serves those bytes (`verification_xml`); this only says so.
  // Restart verification clears the send, and only then does it go live again.
  const approved = sent && answered && Boolean(caseRow.client_approved)
  const year = caseRow.return_year ?? caseRow.ar_period_year
  // MANDATORY and never defaulted (Levi 2026-09-19). Until a year is chosen
  // there is no return to preview, download or send — which year's would it
  // be? The backend refuses all three independently.
  const yearChosen = Boolean(year)
  const pdfName =
    `NAR1_${(caseRow.company_name || 'return').replace(/[^\w]+/g, '_').replace(/_+$/, '')}`
    + `${year ? `_${year}` : ''}.pdf`

  async function download() {
    setSaving(true)
    try {
      // The same document the preview shows, by the same route — a download
      // that needed a filing id would fail on exactly the cases the preview
      // now handles.
      await downloadCasePdf(caseId, pdfName)
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
  //
  // CASE-SCOPED, NOT FILING-SCOPED (2026-09-17). This used to be
  // `/tpsi/filings/${filingId}/pdf` behind `if (!filingId) return` — and at
  // stage 1 a case usually has NO FILING AT ALL, so the effect returned
  // immediately, neither `pdfUrl` nor `pdfError` was ever set, and the panel
  // sat on "Rendering the preview…" for ever. It was reported on two cases and
  // was true of 13 of DEV's 44 open ones.
  //
  // The case endpoint builds the return in memory when there is no filing, so
  // there is always either a document or a stated reason — never silence.
  // Keyed on `filingId` AND `updated_at` so that choosing a year, sending, or
  // restarting verification re-fetches rather than leaving yesterday's
  // document on screen.
  const { url: pdfUrl, error: pdfError } = usePdfBlob(
    sent || yearChosen ? `/cases/${caseId}/verification/preview` : null,
    `${filingId}|${caseRow.updated_at}`)

  async function send() {
    onError(null); onWarn?.(null, null); setBusy('send')
    // THE SPLASH OPENS ON THE CLICK, NOT ON THE RESPONSE (Levi 2026-09-08:
    // "there seems to be a lag between when i click on the send button and the
    // popup appearing"). The send is genuinely slow — it fills a 15-page
    // AcroForm, issues a token per director and makes one Resend call each —
    // and none of that used to show, so the button sat there looking dead.
    //
    // Seeded from the chips, which are exactly who is about to be written to,
    // so the board is on screen from the first frame with nothing invented.
    setConfirming({ phase: 'sending', recipients: (to || []).map(email => ({ email })) })
    try {
      // Always explicit, never `{}`. The chips on screen are what the operator
      // agreed to send to; letting the server re-derive the list would mail a
      // director they had just removed, and the two answers can differ the
      // moment someone edits the company in another tab.
      const result = await api.post(
        `/cases/${caseRow.id}/verification/send`, { to, respond_by: respondBy })
      // ONE MESSAGE PER DIRECTOR now, so a send can partly succeed. The
      // response names the addresses that failed; showing only a green tick
      // would leave a director unasked with nothing on screen saying so.
      //
      // Raised to the page, which puts it in the same place as every other
      // outcome and scrolls there — a partial send is the thing on this screen
      // an operator is most likely to miss, because the stage advances and the
      // status changes around it.
      if (result?.failed_to?.length) {
        // BOTH HALVES, NAMED (Levi 2026-09-07). This used to name only the
        // failures, which left the operator unable to tell whether the rest of
        // the board had been told — so the safe move was to send again to
        // everybody, and a director who had already confirmed got a second
        // request for the same return.
        onWarn?.('The return did not reach everyone.', describePartialSend(result))
      } else if (result?.approval_links === false) {
        onWarn?.('Sent without a Confirm button.',
          'This deployment could not build the approval link, so the client '
          + 'has to reply by email and you record the answer below. '
          + 'PUBLIC_API_BASE_URL needs setting on the backend.')
      }
      // HOLD THE OPERATOR HERE UNTIL RESEND HAS REPORTED (Levi 2026-09-08).
      // A 200 from the send means Resend accepted each message, not that
      // anybody received it — a dead mailbox at a live domain and a suppressed
      // address both look identical at this point. The splash asks, per
      // recipient, and only then lets the screen move on.
      //
      // `onChanged()` is deferred to the modal closing rather than fired here:
      // refreshing the case underneath a modal would advance the stage behind
      // it, so the operator would dismiss the splash onto a screen that had
      // already moved.
      if (result?.deliveries?.length) {
        setConfirming({ phase: 'confirming', recipients: result.deliveries })
      } else {
        // No per-recipient ids came back — an older backend, or a send that
        // returned none. There is nothing to confirm, so close the splash and
        // behave exactly as this screen did before it existed.
        setConfirming(null)
        onChanged()
      }
    } catch (e) {
      // The splash comes down before the refusal is raised: it is an overlay,
      // and a page banner drawn behind it would be invisible.
      setConfirming(null)
      // TO THE PAGE, like every other refusal. It used to be drawn here next
      // to the button because the banner sits above the PDF frame and was
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
      {/* The sending splash. Rendered first so it overlays the stage, and only
          while a send is being confirmed. Closing it is what refreshes the
          case — see send(). */}
      {confirming && (
        <VerificationDeliveryModal
          caseId={caseRow.id}
          phase={confirming.phase}
          deliveries={confirming.recipients}
          onClose={() => { setConfirming(null); onChanged() }}
        />
      )}
      {/* WHAT THIS DOCUMENT IS, and it is not the same claim before and after
          CR has seen it (2026-09-17). While Client Verification was the second
          stage this always read "Snapshot frozen at validation … generated from
          the CR-validated XML", which on stage 1 of the new order is simply
          untrue: CR has not seen the return yet. Saying so anyway would tell an
          operator the Registry had accepted something it had never been sent.

          FROZEN ONCE SENT (2026-09-18) comes first: from then on the document
          below is the one in the client's inbox, whatever else is true. */}
      {sent ? (
        <div className="alert al-success" role="note" style={{ marginBottom: 16 }}>
          <span className="al-icon">🔒</span>
          <div className="al-body">
            {approved ? (
              <>
                <b>This is the return the client approved</b> — sent{' '}
                {formatDateTime(caseRow.verification_sent_at)}, approved{' '}
                {formatDateTime(caseRow.client_response_at)}
                {caseRow.client_approval?.summary
                  ? ` (${caseRow.client_approval.summary})` : ''}.
              </>
            ) : (
              <>
                <b>This is the return sent to the client</b> on{' '}
                {formatDateTime(caseRow.verification_sent_at)}.
              </>
            )}{' '}
            It stays exactly as they saw it. What the Companies Registry
            validates is shown at Data Verification, with anything that differs
            from this copy marked. <b>Restart verification</b> discards it and
            builds the return afresh.
          </div>
        </div>
      ) : validated ? (
        <div className="alert al-success" role="note" style={{ marginBottom: 16 }}>
          <span className="al-icon">🔒</span>
          <div className="al-body">
            <b>Snapshot frozen at validation.</b> The PDF below is generated from
            the CR-validated XML. It, the client email, and the CR submission all
            read <b>this snapshot</b> — not the live profile.
          </div>
        </div>
      ) : (
        <div className="alert al-info" role="note" style={{ marginBottom: 16 }}>
          <span className="al-icon">ℹ</span>
          <div className="al-body">
            <b>Built from the company profile as it reads now.</b> This is CR's
            own Form NAR1 and it is what will be filed, but the Companies
            Registry has not checked it yet — that happens at Data Verification,
            after the client approves.
          </div>
        </div>
      )}

      {/* THE YEAR FIRST (Levi 2026-09-18): it decides which return everything
          below is — the preview, the email, and what is validated and filed. */}
      <ReturnYearCard caseRow={caseRow} canWrite={canWrite}
                      onChanged={onChanged} onError={onError} />

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">
              {approved ? 'The return the client approved'
                : sent ? 'The return sent to the client'
                  : 'The return the client will see'}
            </div>
            <div className="card-sub">
              {sent
                ? `Frozen as it was emailed on ${formatDateTime(caseRow.verification_sent_at)}`
                  + (approved ? ` and approved on ${formatDateTime(caseRow.client_response_at)}.` : '.')
                : validated
                  ? 'Rendered from the CR-validated snapshot — the same document '
                    + 'that will be filed.'
                  : 'Rendered from the return as prepared — the same document '
                    + 'that will be sent to the client and filed.'}
            </div>
          </div>
          <div className="row gap-8">
            <button type="button" className="btn btn-outline btn-sm"
                    disabled={saving || (!sent && !yearChosen)} onClick={download}>
              {saving ? 'Preparing…' : 'Download PDF'}
            </button>
            {/* A tab, not a modal: the operator is checking this against the
                company record in another window, and no embedded viewer that
                leaves room for the controls below it is a whole nine-page
                statutory return. */}
            <button type="button" className="btn btn-outline btn-sm"
                    disabled={!pdfUrl}
                    onClick={() => window.open(pdfUrl, '_blank', 'noopener')}>
              Open full screen
            </button>
          </div>
        </div>

        {/* The preview pane, or — in the same place — why there is nothing to
            show. Not an alert: nothing the operator did was refused, and the
            Download and Send controls still work. */}
        <PdfFrame
          url={pdfUrl}
          error={pdfError}
          fileName={pdfName}
          label="NAR1 preview"
          emptyText={sent || yearChosen
            ? 'Rendering the preview…'
            : 'Choose the return year above to see the return.'}
          pills={[
            { label: year ? `Annual return ${year}` : 'Form NAR1 + Schedule 1' },
            sent
              ? { label: approved ? 'Approved by the client' : 'As sent to the client',
                  tone: 'ok' }
              : validated
                ? { label: 'Rendered from the CR-validated XML', tone: 'ok' }
                : { label: 'Not yet checked by CR' },
          ]}
        />
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

        {/* THE DEADLINE, and it is the operator's to choose (Levi 2026-09-07).
            It sits between the recipients and the Send button because that is
            the order the decision is made: what, who, by when, go.

            It is one date doing three jobs — what the letter prints, when the
            Confirm links stop working, and when `jobs.auto_approve_nar1` reads
            the client's silence as consent. That last one is why there is no
            default: a date nobody chose still decides that a return goes to CR
            unanswered. */}
        <div className="f-group" style={{ marginTop: 14 }}>
          <label className="f-label" htmlFor="respond-by">
            Client must reply by<span className="f-req"> *</span>
          </label>
          <input
            id="respond-by"
            type="date"
            className="f-input"
            style={{ maxWidth: 220 }}
            value={respondBy}
            // Today is allowed and the past is not — the backend refuses a past
            // date independently. A deadline already gone would issue a link
            // that is dead on arrival and hand the auto-approval job a case it
            // would approve on "silence" the same night.
            min={hongKongTodayISO()}
            disabled={!canWrite || busy !== null || Boolean(blocked) || filed}
            onChange={e => setRespondBy(e.target.value)}
          />
          <span className="f-hint">
            The letter tells the client that if you do not hear from them by
            this date, GSHK will take the return as confirmed and file it. The
            Confirm link in their email expires at the end of this day.
          </span>
        </div>

        {/* Named, not implied. "A copy goes to the team" is unverifiable; the
            address is the whole assurance. Both facts are stated because they
            are different promises — one is a copy, the other is where the
            client's answer lands.

            THE COPY IS NO LONGER THE PERSON PRESSING SEND (Levi 2026-09-08).
            It is the shared renewals mailbox, so this no longer reads the
            signed-in user's address — see email_service.CLIENT_CC.

            AND THE LETTER NOW SENDS THE CLIENT THERE TOO (Levi 2026-09-08): it
            says in as many words that replies are not monitored, and names this
            mailbox for changes.

            REPLY-TO IS NO LONGER YOU EITHER (Levi 2026-09-25). It was, so that
            a stray reply reached a human who knew the case — but `reply-to` is
            a header every mail client DISPLAYS, so your personal work address
            was still printed on a letter about a client's statutory return,
            and reply-all fixed it into the thread. renewal@ answers the
            original objection instead of overriding it: it is staffed. This
            note therefore stops promising the operator that replies reach
            them, because they no longer do — an operator who kept believing
            that would sit watching an inbox nothing arrives in.

            IT IS WRITTEN IN THE FUTURE CONDITIONAL ON A TEST DEPLOYMENT, where
            NEITHER header goes out (Levi 2026-09-25): the copy was already
            dropped, and now the reply address is too. Stating the production
            behaviour flatly on DEV is the same class of untruth this note was
            just corrected for — it would have a tester believe renewal@ is on
            a message that does not name it. The hint below says what a test
            send really carries; this line stops asserting otherwise. */}
        <div className="cc-note">
          <span className="cc-icon" aria-hidden="true">↩</span>
          <div>
            {isTestEnv ? (<>
              In production a copy goes to <b>{CLIENT_CC}</b> and replies go
              there too — the same mailbox the letter gives the client for
              changes, since it tells them replies are not monitored. Your own
              address is never on the message: not as sender, not copied, not
              as the reply address.
            </>) : (<>
              A copy goes to <b>{CLIENT_CC}</b>, and replies go there too — the
              same mailbox the letter gives the client for changes, since it
              tells them replies are not monitored. Your own address is not on
              the message: not as sender, not copied, not as the reply address.
            </>)}
          </div>
        </div>

        {/* Levi 2026-08-30. The picker above deliberately still shows and still
            sends the REAL director addresses — selecting them is the thing
            being tested. The backend substitutes a fixed internal list before
            anything leaves the process (email_service.TEST_RECIPIENTS), which
            no environment variable can override. */}
        {/* The reason the copy is dropped CHANGED with the CC (2026-09-08).
            It used to be "you are already on that list", which was true of the
            case worker and is not true of renewal@getstarted.hk — that is a
            real GSHK mailbox and deliberately NOT one of the test recipients,
            so a test deployment must not reach it either.

            AND THE REPLY ADDRESS GOES WITH IT (Levi 2026-09-25). Same mailbox,
            and a reason that survives it not being a recipient: reply-to is
            PRINTED beside From, so a tester pressing Reply on a DEV message
            writes to the live renewals team about a case that exists only on
            DEV. Named here rather than left implied by "nothing reaches the
            client", because a header nobody is told about is a header nobody
            checks. */}
        {isTestEnv && (
          <div className="f-hint" style={{ marginTop: 10, lineHeight: 1.5 }}>
            This is a test environment, so nothing is delivered to the client —
            the message goes to the fixed internal test recipients instead, and
            both the copy to {CLIENT_CC} and the reply address are dropped,
            because that is a real GSHK mailbox and nothing sent from here may
            reach it or point anyone at it. A test message has no reply
            address at all.
          </div>
        )}

        {/* NEITHER THE REFUSAL NOR THE PARTIAL-SEND REPORT IS DRAWN HERE
            any more. They were, because the page banner sits above the PDF
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
                : !yearChosen
                  ? 'Choose the return year above before sending.'
                : !reviewed
                  ? 'Confirm you have reviewed the return to enable sending.'
                  : to === null
                    ? 'Loading the recipients…'
                    : to.length === 0
                      ? 'Add at least one recipient above.'
                      // Last, because it is the last field on the card and
                      // because the other three are about who is being asked
                      // at all. Named rather than left to the disabled button:
                      // a date box the operator scrolled past is exactly the
                      // thing they will not notice is empty.
                      : !respondBy
                        ? 'Choose the date the client must reply by.'
                        : `The return will be attached as a PDF, to ${to.length} `
                          + `recipient${to.length === 1 ? '' : 's'}.`}
            </div>
            <div className="ab-actions">
              <span className="perm-tag">Requires <b>nar1:write</b></span>
              <button className="btn btn-action"
                      disabled={!yearChosen || !reviewed || busy !== null || !to
                                || to.length === 0 || Boolean(blocked)
                                || !respondBy}
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

      {/* WHAT COMES NEXT, now that this stage is first (2026-09-17). Only on an
          approval: a decline leaves the case here, and the alert above already
          says to correct the return and send it again. */}
      {caseRow.client_approved && onGo && !filed && (
        <div className="action-bar">
          <div className="ab-note">
            The client has approved this return. The Companies Registry checks
            it next — validating is free and nothing is filed by it.
          </div>
          <div className="ab-actions">
            <button className="btn btn-primary" onClick={() => onGo(2)}>
              Continue to Data Verification →
            </button>
          </div>
        </div>
      )}
    </>
  )
}
