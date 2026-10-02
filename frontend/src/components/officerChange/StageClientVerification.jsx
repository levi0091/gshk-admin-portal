import { useEffect, useState } from 'react'
import PdfFrame, { usePdfBlob } from '../case/PdfPreview.jsx'
import RecipientPicker from '../case/RecipientPicker.jsx'
import VerificationDeliveryModal from '../case/VerificationDeliveryModal.jsx'
import { formatDate, formatDateTime } from '../../lib/format.js'
import ChangesCard from './ChangesCard.jsx'
import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import RulesPanel from './RulesPanel.jsx'
import AttachmentsCard from './AttachmentsCard.jsx'
import CloseCaseModal from '../case/CloseCaseModal.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/** Jacqueline A7: the reason a case is closed when no director would remain. */
export const NO_DIRECTOR_REASON = 'Pending further instructions — no director would remain after ' +
  'these changes. The client has been told they may file Form ND4 themselves.'

/**
 * Stage 1 (spec §5): the change list, the company rules, and the client's copy
 * — CR's full form, PI sheets included since Jacqueline's A8 — sent with a
 * Confirm link to each recipient, and anything else ticked to go with it (A3).
 * The reply-by date defaults to five days before CR's deadline and is the
 * operator's to change. Nothing is approved on silence; an ND2B may proceed
 * without the client's confirmation when someone says why (BQ1).
 */
export default function StageClientVerification({ data, reload, can, goTo }) {
  const sent = Boolean(data.verification_sent_at)
  const nd2b = data.form_code === 'Nd2b'
  // How many verification emails have gone out (Levi 2026-10-02, migration
  // 051) — the same count NAR1's stage reads. From the second on the client's
  // email reads "[Rev. N]"; the first is unmarked, here as in their inbox. A
  // restart does not reset it: the client still has the earlier email.
  const sentRevision = Number(data.verification_revision) || 0
  const nextRevision = sentRevision + 1
  const revisionTag = sentRevision >= 2 ? `Rev. ${sentRevision}` : null
  const [recipients, setRecipients] = useState(null)
  const [to, setTo] = useState([])
  const [respondBy, setRespondBy] = useState(data.reply_by_default || '')
  // Until the operator picks a date, it FOLLOWS the default — which moves when
  // an earlier change brings CR's deadline forward. A date left behind would
  // ask the client to reply after the filing is already late.
  const [respondByTouched, setRespondByTouched] = useState(false)
  useEffect(() => {
    if (!respondByTouched && data.reply_by_default) setRespondBy(data.reply_by_default)
  }, [data.reply_by_default, respondByTouched])
  const [sending, setSending] = useState(false)
  const [delivery, setDelivery] = useState(null)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [closing, setClosing] = useState(false)
  const [waiving, setWaiving] = useState(false)
  const [waiveReason, setWaiveReason] = useState('')
  const noDirector = data.form_code === 'Nd2a' && Array.isArray(data.rules?.board?.directors)
    && data.rules.board.directors.length === 0 && (data.entries || []).length > 0
  const waived = data.client_approval?.source === 'staff_waiver'
  const preview = usePdfBlob(
    (data.entries || []).length ? `/officer-changes/${data.id}/preview?audience=client` : null,
    data.updated_at)

  useEffect(() => {
    let live = true
    officerChangeApi.recipients(data.id).then(r => {
      if (!live) return
      setRecipients(r.recipients || [])
      setTo(r.default_to || [])
      if (!respondByTouched && r.reply_by_default) setRespondBy(r.reply_by_default)
    }).catch(() => { if (live) setRecipients([]) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.id, (data.entries || []).length])

  const problems = data.problems || []
  const blocked = data.rules?.blocking
    ? 'A company rule is breached — see the rules below.'
    : !(data.entries || []).length ? 'Add at least one change first.'
      : problems.length ? 'The form cannot be prepared yet — see the list below.'
        : !respondBy ? 'Choose the date the client should reply by.'
          : !to.length ? 'Add at least one recipient.' : null

  async function send() {
    setError(null); setSending(true); setResult(null)
    setDelivery({ phase: 'sending', deliveries: to.map(email => ({ email })) })
    try {
      const res = await officerChangeApi.send(data.id, { emails: to, respond_by: respondBy })
      setResult(res)
      if (res.deliveries?.length) setDelivery({ phase: 'confirming', deliveries: res.deliveries })
      else { setDelivery(null); await reload() }
    } catch (e) {
      setDelivery(null)
      setError(errorOf(e))
    } finally {
      setSending(false)
    }
  }

  async function proceed() {
    setError(null)
    try {
      await reload(await officerChangeApi.proceed(data.id, waiveReason.trim()))
      setWaiving(false); setWaiveReason('')
    } catch (e) { setError(errorOf(e)) }
  }

  async function answer(approved) {
    setError(null)
    try { await reload(await officerChangeApi.recordResponse(data.id, { approved })) }
    catch (e) { setError(errorOf(e)) }
  }

  return (
    <>
      {nd2b ? <ParticularsChangeCard data={data} reload={reload} can={can} />
        : <ChangesCard data={data} reload={reload} can={can} />}
      <RulesPanel rules={data.rules} />
      {noDirector && (
        <div className="oc-nodir" role="status">
          <p>
            No director would remain after these changes. GSHK does not file the
            director's resignation (ND4) on the company's behalf; the client may file
            it themselves. If the client is deciding what to do, close this case
            pending their instructions.
          </p>
          {can.write && (
            <button className="btn btn-outline" onClick={() => setClosing(true)}>
              Close case — pending further instructions
            </button>
          )}
        </div>
      )}
      <AttachmentsCard data={data} reload={reload} can={can} />

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-hdr">
          <div>
            <div className="card-title">Send for verification</div>
            <div className="card-sub">
              The client receives CR's full form, including the protected-information sheets
              (identity numbers and residential addresses) for them to check, and confirms it
              with one press.
            </div>
          </div>
        </div>

        {problems.length > 0 && (
          <div className="card-note card-note-warn" role="status">
            <b>The form cannot be prepared yet.</b>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {problems.map(p => <li key={p}>{p}</li>)}
            </ul>
          </div>
        )}

        {(data.entries || []).length > 0 && (
          <PdfFrame url={preview.url} error={preview.error}
                    fileName={`${data.case_type}-${data.case_no}.pdf`}
                    pills={[{ label: 'Client copy — full form incl. PI', tone: '' }]}
                    label="draft form" />
        )}

        {sent && (
          <div className={`alert ${data.client_approved === true ? 'al-success'
            : data.client_approved === false ? 'al-warn' : 'al-info'}`} style={{ marginTop: 12 }}>
            <div className="al-body">
              {revisionTag ? `${revisionTag} sent` : 'Sent'}{' '}
              {formatDateTime(data.verification_sent_at)}.{' '}
              {data.client_approved === true && waived && <>Proceeding without the client's
                confirmation{data.client_approval?.reason ? ` — ${data.client_approval.reason}` : ''}.
                The client can still confirm from their email.</>}
              {data.client_approved === true && !waived && <>Confirmed by the client
                {data.client_approval?.name ? ` (${data.client_approval.name})` : ''}.</>}
              {data.client_approved === false && <>The client asked for changes. Correct the
                record, then restart verification from the header.</>}
              {data.client_approved == null && <>Waiting for the client to confirm.</>}
            </div>
          </div>
        )}

        {can.write && !sent && (
          <>
            <div style={{ marginTop: 12 }}>
              <RecipientPicker recipients={recipients || []} to={to} onChange={setTo}
                               disabled={sending || recipients === null} />
            </div>
            <div className="oc-send-row">
              <div className="f-group">
                <label className="f-label" htmlFor="oc-reply-by">Reply by <span className="f-req">*</span></label>
                <input id="oc-reply-by" type="date" className="f-input" value={respondBy}
                       onChange={e => { setRespondByTouched(true); setRespondBy(e.target.value) }} />
                {data.deadline?.date && (
                  <div className="f-hint">CR's deadline is {formatDate(data.deadline.date)}.</div>
                )}
              </div>
              <button className="btn btn-primary" disabled={Boolean(blocked) || sending} onClick={send}>
                {sending ? 'Sending…' : 'Send to client'}
              </button>
            </div>
            {blocked && <div className="oc-locked-note">{blocked}</div>}
            {/* Said BEFORE the press: the one consequence of a resend the
                client notices is that the button in the email they already
                have goes dead. */}
            {nextRevision >= 2 && (
              <div className="f-hint" style={{ marginTop: 8 }}>
                This goes out as Rev. {nextRevision}, and the Confirm link in the
                earlier email stops working.
              </div>
            )}
          </>
        )}

        {can.write && sent && data.client_approved == null && (
          <div className="oc-send-row">
            <span className="f-hint">Client answered by email or phone?</span>
            <button className="btn btn-outline" onClick={() => answer(true)}>Client approved</button>
            <button className="btn btn-outline" onClick={() => answer(false)}>Client declined</button>
            {nd2b && (
              // Jacqueline BQ1: "We usually submit the ND2B even if the client has
              // not confirmed the form." Never offered on an ND2A.
              <button className="btn btn-outline" onClick={() => setWaiving(true)}>
                Proceed without confirmation
              </button>
            )}
          </div>
        )}

        {data.client_approved === true && (
          <div className="oc-send-row">
            <button className="btn btn-primary" onClick={() => goTo(2)}>Continue to Data Verification →</button>
          </div>
        )}

        {result?.failed?.length > 0 && (
          <div className="alert al-warn" role="alert" style={{ marginTop: 12 }}>
            <div className="al-body">
              Not sent to: {result.failed.map(f => `${f.email} (${f.reason})`).join('; ')}.
            </div>
          </div>
        )}
        {error && (
          <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
            <div className="al-body"><b>{error.message}</b>
              {error.problems?.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                  {error.problems.map(p => <li key={p}>{p}</li>)}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>

      {closing && (
        <CloseCaseModal caseRow={data} closePath={`/officer-changes/${data.id}/close`}
                        initialReason={NO_DIRECTOR_REASON}
                        onClose={() => setClosing(false)}
                        onClosed={async () => { setClosing(false); await reload() }} />
      )}
      {waiving && (
        <div className="overlay" onClick={e => { if (e.target === e.currentTarget) setWaiving(false) }}>
          <div className="modal modal-sm" role="dialog" aria-label="Proceed without the client's confirmation">
            <div className="modal-hdr">
              <div className="modal-title">Proceed without the client's confirmation?</div>
              <button className="modal-close" onClick={() => setWaiving(false)} aria-label="Cancel">×</button>
            </div>
            <div className="modal-body">
              <p className="f-hint" style={{ marginTop: 0 }}>
                The ND2B moves on to Data Verification now. The client's Confirm link keeps
                working, and a confirmation that arrives later is recorded in place of this one.
              </p>
              <label className="f-label" htmlFor="oc-waive-reason">Why is this ND2B going ahead without the client?</label>
              <textarea id="oc-waive-reason" className="f-input f-textarea" rows={3} value={waiveReason}
                        onChange={e => setWaiveReason(e.target.value)} />
            </div>
            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setWaiving(false)}>Cancel</button>
              <button className="btn btn-primary" disabled={!waiveReason.trim()} onClick={proceed}>Proceed</button>
            </div>
          </div>
        </div>
      )}
      {delivery && (
        <VerificationDeliveryModal caseId={data.id} deliveries={delivery.deliveries}
                                   phase={delivery.phase}
                                   deliveryPath={`/officer-changes/${data.id}/verification/delivery`}
                                   onClose={async () => { setDelivery(null); await reload() }} />
      )}
    </>
  )
}
