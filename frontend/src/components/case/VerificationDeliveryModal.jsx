import { useState, useEffect, useRef } from 'react'
import { api } from '../../lib/api.js'

/** How often to ask Resend, in ms. */
export const POLL_MS = 3000

/**
 * How long to keep asking before letting the operator go, in ms.
 *
 * NOT a guess at how long mail takes. A hard bounce is usually known in
 * seconds, because the receiving server rejects during the SMTP conversation
 * — so a minute catches the case this screen exists for. What it deliberately
 * does NOT do is wait for certainty: delivery confirmation has no upper bound
 * (greylisting, queue retries, a delayed bounce hours later), and a screen
 * that blocked until every recipient resolved could hold a case worker
 * indefinitely on something outside this portal's control.
 */
export const TIMEOUT_MS = 60000

/** One line per director: what we know, and what to do about it. */
function statusLabel(entry) {
  if (entry.status === 'delivered') return 'Delivered'
  if (entry.status === 'failed') return 'Not delivered'
  // NOT "Delivered", and deliberately not green. Outside production the
  // recipient lock sends the message to the internal test list instead, so
  // NOTHING reached the address on this row — see the modal docstring.
  if (entry.status === 'redirected') return 'Not sent (test)'
  return 'Sending…'
}

/**
 * The sending splash (Levi 2026-09-08).
 *
 * "after user click on send email we should actually wait for the resend to
 * confirm the status of each email that is sent before allowing user to
 * proceed with something else on screen."
 *
 * WHY A WAIT IS NEEDED AT ALL. `POST .../verification/send` returning 200 means
 * Resend ACCEPTED each message, not that anyone received it. A live domain with
 * a dead mailbox, and an address on Resend's suppression list after an earlier
 * hard bounce, both look exactly like success at that moment. The answer only
 * exists a few seconds later, so the screen has to ask for it.
 *
 * IT ASKS RATHER THAN WAITS FOR A PUSH. `GET .../verification/delivery` polls
 * Resend's own record of each message. That needs no webhook endpoint, no
 * signing secret and no Resend dashboard registration — it reuses the API key
 * already sending the mail, so it works the moment it deploys.
 *
 * IT NEVER REPORTS A REDIRECTED SEND AS DELIVERED. Outside production the
 * recipient lock substitutes the internal test list inside send(), so Resend's
 * record for that message describes a DIFFERENT mailbox. Printing its
 * "delivered" beside the intended address told Levi on 2026-09-08 that
 * levi214839824@zenexflow.com — an address that does not exist — had been
 * delivered to. Nothing had been sent there at all. Those rows now read
 * "Not sent (test)" and the modal says so once, in full.
 *
 * IT NEVER BLOCKS FOREVER. At TIMEOUT_MS it stops asking and says so, naming
 * the recipients still unresolved rather than implying they failed. The same
 * check is available on the case afterwards, so a bounce that lands later is
 * still visible — which is the point Levi actually cares about: knowing.
 */
export default function VerificationDeliveryModal({
  caseId, deliveries, phase = 'confirming', onClose,
}) {
  // Seeded from the send response so the board is listed the instant the modal
  // opens, rather than appearing a poll later. Every one starts pending: the
  // send told us Resend took it, which is not the question this asks.
  const [recipients, setRecipients] = useState(
    () => (deliveries || []).map(d => ({
      email: d.email, name: d.name, status: 'pending', detail: null,
    })),
  )
  const [settled, setSettled] = useState(false)
  const [timedOut, setTimedOut] = useState(false)
  // Only for the "we could not check" line — a failed poll must not read as a
  // failed delivery.
  const [unreachable, setUnreachable] = useState(false)
  const startedAt = useRef(Date.now())

  // The list is re-seeded when the send returns, because the modal opens BEFORE
  // it: the chips give us the addresses, and the response then adds the names
  // and the message ids. A useState initialiser runs once, so without this the
  // splash would keep showing the click-time list forever.
  useEffect(() => {
    setRecipients(current => {
      const next = (deliveries || []).map(d => ({
        email: d.email, name: d.name, status: 'pending', detail: null,
      }))
      // Keep whatever a poll has already resolved: re-seeding on every render
      // would flick a settled row back to "Sending…".
      const known = new Map(current.map(r => [r.email, r]))
      return next.map(r => (known.get(r.email)?.status !== 'pending'
        ? known.get(r.email) : { ...r, name: r.name ?? known.get(r.email)?.name }))
    })
  }, [deliveries])

  useEffect(() => {
    // NOTHING TO POLL YET. While the send is still in flight there is no audit
    // row to read, and asking would either 404 or — worse — return the PREVIOUS
    // send on this case and report a fresh send as already settled.
    if (phase !== 'confirming') return undefined

    let cancelled = false
    let timer = null

    async function check() {
      if (cancelled) return
      try {
        const result = await api.get(`/cases/${caseId}/verification/delivery`)
        if (cancelled) return
        setUnreachable(false)
        if (result?.recipients?.length) setRecipients(result.recipients)
        if (result?.settled) { setSettled(true); return }
      } catch {
        // The poll failed, NOT the send. Nothing here may turn into a red row
        // against a director — the message may well have arrived.
        if (cancelled) return
        setUnreachable(true)
      }
      if (Date.now() - startedAt.current >= TIMEOUT_MS) {
        if (!cancelled) setTimedOut(true)
        return
      }
      timer = setTimeout(check, POLL_MS)
    }

    // The clock starts when the CONFIRMING phase does, not when the modal
    // opened: the send itself can take several seconds, and counting those
    // against the timeout would shorten the window that catches a bounce.
    startedAt.current = Date.now()
    check()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [caseId, phase])

  const failed = recipients.filter(r => r.status === 'failed')
  const pending = recipients.filter(r => r.status === 'pending')
  const redirected = recipients.filter(r => r.status === 'redirected')
  // Never while the send is still going: the operator must not be released
  // before the thing they are waiting on has even been asked about.
  const done = phase === 'confirming' && (settled || timedOut)

  return (
    <div className="overlay" data-testid="delivery-modal">
      <div className="modal modal-sm" role="alertdialog"
           aria-label="Sending the verification email"
           aria-busy={done ? 'false' : 'true'}>
        <div className="modal-hdr">
          <div className="modal-title">
            {done ? 'Sending complete' : 'Sending…'}
          </div>
        </div>

        <div className="modal-body">
          <p className="f-hint" style={{ marginTop: 0 }}>
            {done
              ? 'Resend has reported on each message.'
              : phase === 'sending'
                // Says what is ACTUALLY happening. The send builds the
                // nine-page return and makes one call per director, which is
                // where the seconds go — "please wait" alone reads as a hang.
                ? 'Preparing the return and sending one message per recipient…'
                : 'Confirming each message with the mail provider. This takes a '
                  + 'few seconds — please wait.'}
          </p>

          <ul className="delivery-list">
            {recipients.map(r => (
              <li key={r.email} className={`delivery-row dr-${r.status}`}>
                <span className="dr-mark" aria-hidden="true">
                  {r.status === 'delivered' ? '✓'
                    : r.status === 'failed' ? '✗' : '…'}
                </span>
                <span className="dr-who">
                  {r.name ? <><b>{r.name}</b> — {r.email}</> : r.email}
                </span>
                <span className="dr-status">{statusLabel(r)}</span>
                {r.detail && <span className="dr-detail">{r.detail}</span>}
              </li>
            ))}
          </ul>

          {/* Named, never counted. An operator who reads "1 of 3 failed" and
              not WHICH one cannot re-send to the right person. */}
          {done && failed.length > 0 && (
            <div className="alert al-danger" role="status">
              <b>{failed.length === 1 ? 'One director did not get it.'
                : `${failed.length} directors did not get it.`}</b>{' '}
              {failed.map(f => f.email).join(', ')}. Fix the address on the
              company profile and send again — note that sending again reissues
              every approval link on this case, so anyone who already has one
              will be asked a second time.
            </div>
          )}

          {/* THE THING THAT MISREPORTED ITSELF (Levi 2026-09-08). On a test
              deployment the recipient lock sends every message to the internal
              list, so NOTHING reached the addresses on these rows — and this
              screen used to print Resend's "delivered" (true, of a different
              mailbox) beside them. Said once, in full, because an operator
              testing a bad address here would otherwise conclude it was
              good. */}
          {done && redirected.length > 0 && (
            <div className="alert al-warn" role="status">
              <b>Nothing was sent to {redirected.length === 1 ? 'this address'
                : 'these addresses'}.</b> This is a test environment, so the
              message went to the internal test recipients instead. Delivery to
              a real client address can only be confirmed on production.
            </div>
          )}

          {timedOut && pending.length > 0 && (
            <div className="alert al-warn" role="status">
              Still waiting on {pending.map(p => p.email).join(', ')}. Mail can
              take longer than this to confirm, so this is not a failure — the
              delivery status stays on this case, so you can reopen it later to
              see how it ended.
            </div>
          )}

          {unreachable && (
            <div className="f-hint" style={{ marginTop: 10 }}>
              The delivery status could not be checked just now. The emails were
              still sent — only the confirmation is unavailable.
            </div>
          )}
        </div>

        <div className="modal-footer">
          {/* Disabled until we have an answer or have stopped asking. This is
              the "do not let them proceed" half of the request — but it is
              time-bounded, never indefinite. */}
          <button className="btn btn-primary" onClick={onClose} disabled={!done}>
            {done ? 'Done' : 'Sending…'}
          </button>
        </div>
      </div>
    </div>
  )
}
