import { useState } from 'react'
import RecipientPicker from '../case/RecipientPicker.jsx'
import VerificationDeliveryModal from '../case/VerificationDeliveryModal.jsx'
import { formatDateTime } from '../../lib/format.js'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/**
 * "Multiple directors must sign" (Levi 2026-10-29: "we should see 2 separate
 * sending features and the signatures should converge once all are collected").
 *
 * One panel per required signer, each with its own address, its own Send /
 * Re-send and its own status. The case moves on only when every one of them has
 * signed; until then the footer says it is waiting, and the stage's Continue
 * button does not appear.
 *
 * NOTHING IS PRE-FILLED. The director's address on record is a suggestion pill
 * (the 2026-10-29 rule that RecipientPicker documents), so a statutory form
 * never goes to an address nobody chose. A panel carries ONE address, because a
 * drawn signature is personal: the backend refuses an address that is already
 * another director's (409 `address_in_use`), and that refusal is drawn on the
 * panel it belongs to, not in a banner at the foot of the page.
 *
 * Reply-by is one shared field in the stage, passed down: the date is the
 * client's deadline for the form, not for a person.
 *
 * THE SPLASH IS THE SAME ONE THE SINGLE SEND USES, opened on the click and
 * polled only once the response carries `deliveries` (see
 * VerificationDeliveryModal). Nothing is refreshed underneath it, because
 * `reload()` advances the stage behind the overlay.
 *
 * The status words come from the server (`signer.status`); this component
 * decides only how each is drawn. `redirected` is never green and never says
 * "delivered": outside production the recipient lock mails the internal test
 * list, so nothing reached the director.
 */

function statusLine(s) {
  switch (s.status) {
    case 'signed': return { text: `Signed ${formatDateTime(s.signed_at)} ✓`, tone: 'is-signed' }
    case 'sent': return { text: `Sent ${formatDateTime(s.sent_at)}, awaiting signature`, tone: '' }
    case 'expired': return { text: 'Link expired, not signed', tone: '' }
    case 'not_delivered': {
      const detail = s.delivery?.detail
      return { text: detail ? `Not delivered ✗ — ${detail}` : 'Not delivered ✗', tone: 'is-bad' }
    }
    case 'redirected': return { text: 'Not sent (test)', tone: '' }
    default: return { text: 'Not sent', tone: '' }
  }
}

export default function SignerPanels({
  data, state, loadError = false, can, respondBy, blocked, nextRevision,
  refresh, reload, goTo,
}) {
  // person_id -> the one address chosen for that director.
  const [chosen, setChosen] = useState({})
  // person_id -> { error, failed } from that director's last attempt.
  const [outcome, setOutcome] = useState({})
  const [busy, setBusy] = useState(null)
  const [delivery, setDelivery] = useState(null)

  if (!state || !Array.isArray(state.signers)) {
    return (
      <div className="oc-signers" style={{ marginTop: 12 }}>
        {loadError ? (
          <div className="alert al-warn" role="status">
            <div className="al-body">
              The directors who must sign could not be loaded.{' '}
              <button type="button" className="btn btn-outline" onClick={() => refresh()}>Try again</button>
            </div>
          </div>
        ) : <div className="f-hint">Loading the directors who must sign…</div>}
      </div>
    )
  }

  const signers = state.signers
  const required = state.required ?? signers.length
  const converged = Boolean(state.converged)

  async function settle() {
    await Promise.all([refresh(), reload()])
  }

  async function send(s) {
    const email = chosen[s.person_id]?.[0]
    if (!email) return
    setOutcome(o => ({ ...o, [s.person_id]: {} }))
    setBusy(s.person_id)
    setDelivery({ phase: 'sending', deliveries: [{ email, name: s.name, person_id: s.person_id }] })
    try {
      const res = await officerChangeApi.sendToSigner(data.id, s.person_id,
        { email, respond_by: respondBy })
      setChosen(c => ({ ...c, [s.person_id]: [] }))
      if (res?.failed?.length) setOutcome(o => ({ ...o, [s.person_id]: { failed: res.failed } }))
      if (res?.deliveries?.length) setDelivery({ phase: 'confirming', deliveries: res.deliveries })
      else { setDelivery(null); await settle() }
    } catch (e) {
      // A refused send takes the splash down, or the refusal would be drawn
      // behind the overlay. The address stays, so it can be swapped by name.
      setDelivery(null)
      setOutcome(o => ({ ...o, [s.person_id]: { error: errorOf(e) } }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="oc-signers">
      {state.set_changed && (
        <div className="card-note card-note-warn" role="status">
          The board has changed since this form was sent. Restart verification to ask the current directors.
        </div>
      )}
      {!state.frozen && (
        <div className="f-hint" style={{ marginTop: 12 }}>
          The first send fixes the form as Rev. {nextRevision}; every director receives the same copy.
        </div>
      )}
      {can.write && blocked && !converged && <div className="oc-locked-note">{blocked}</div>}

      <div className="oc-signer-list">
        {signers.map(s => {
          const line = statusLine(s)
          const signed = s.status === 'signed'
          const resend = s.status !== 'not_sent' && !signed
          const email = chosen[s.person_id] || []
          const out = outcome[s.person_id] || {}
          const title = `${s.name} (${s.role_label})`
          const headingId = `oc-signer-${s.person_id}`
          return (
            <section key={s.person_id} className="oc-signer" role="group" aria-labelledby={headingId}
                     data-status={s.status}>
              <div className="oc-signer-hd">
                <h4 id={headingId} className="oc-signer-name">{title}</h4>
                <span className={`oc-signer-status ${line.tone}`}>{line.text}</span>
              </div>
              {s.email && s.status !== 'not_sent' && (
                <div className="oc-signer-meta">
                  {signed ? 'Signed from' : 'Sent to'} {s.email}
                </div>
              )}
              {signed && s.signature_captured === false && (
                <div className="oc-signer-meta oc-signer-meta-warn">
                  Confirmed, but the signature image was not stored — this director's box will print blank.
                </div>
              )}

              {can.write && !signed && !converged && (
                <>
                  <RecipientPicker
                    recipients={[{ name: s.name, person_id: s.person_id, email: s.suggested_email || null,
                      reason: 'no email address on record' }]}
                    to={email} maxRecipients={1} disabled={busy !== null}
                    onChange={next => setChosen(c => ({ ...c, [s.person_id]: next }))} />
                  <div className="oc-signer-act">
                    <button type="button" className="btn btn-primary"
                            disabled={!email.length || !respondBy || Boolean(blocked) || busy !== null}
                            onClick={() => send(s)}>
                      {busy === s.person_id ? 'Sending…' : resend ? 'Re-send' : 'Send'}
                    </button>
                    {resend && (
                      <span className="f-hint">Re-sending retires only {s.name}'s earlier link.</span>
                    )}
                  </div>
                </>
              )}

              {out.failed?.length > 0 && (
                <div className="alert al-warn" role="alert" style={{ marginTop: 10 }}>
                  <div className="al-body">
                    Not sent to: {out.failed.map(f => `${f.email} (${f.reason})`).join('; ')}.
                  </div>
                </div>
              )}
              {out.error && (
                <div className="alert al-danger" role="alert" style={{ marginTop: 10 }}>
                  <div className="al-body"><b>{out.error.message}</b>
                    {out.error.problems?.length > 0 && (
                      <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                        {out.error.problems.map(p => <li key={p}>{p}</li>)}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </section>
          )
        })}
      </div>

      <div className={`oc-signers-foot ${converged ? 'is-done' : ''}`}>
        {converged ? (
          <>
            <span>All {required} directors have signed</span>
            <button type="button" className="btn btn-primary" onClick={() => goTo(2)}>
              Continue to Data Verification →
            </button>
          </>
        ) : (
          <span>Signatures: {state.signed ?? 0} of {required} — case waits for all</span>
        )}
      </div>

      {delivery && (
        <VerificationDeliveryModal caseId={data.id} deliveries={delivery.deliveries}
                                   phase={delivery.phase}
                                   deliveryPath={`/officer-changes/${data.id}/verification/delivery`}
                                   onClose={async () => { setDelivery(null); await settle() }} />
      )}
    </div>
  )
}
