import { useEffect, useState } from 'react'
import PdfFrame, { usePdfBlob } from '../case/PdfPreview.jsx'
import RecipientPicker from '../case/RecipientPicker.jsx'
import VerificationDeliveryModal from '../case/VerificationDeliveryModal.jsx'
import { formatDate, formatDateTime } from '../../lib/format.js'
import ChangesCard from './ChangesCard.jsx'
import ParticularsChangeCard from './ParticularsChangeCard.jsx'
import RulesPanel from './RulesPanel.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/**
 * Stage 1 (spec §5): the change list, the company rules, and the client's copy
 * — CR's own form, public pages only — sent with a Confirm link to each
 * recipient. The reply-by date defaults to five days before CR's deadline and
 * is the operator's to change. There is no auto-approval: nothing here says
 * that silence will be taken as consent, because it will not.
 */
export default function StageClientVerification({ data, reload, can, goTo }) {
  const sent = Boolean(data.verification_sent_at)
  const nd2b = data.form_code === 'Nd2b'
  const [recipients, setRecipients] = useState(null)
  const [to, setTo] = useState([])
  const [respondBy, setRespondBy] = useState(data.reply_by_default || '')
  const [sending, setSending] = useState(false)
  const [delivery, setDelivery] = useState(null)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const preview = usePdfBlob(
    (data.entries || []).length ? `/officer-changes/${data.id}/preview?audience=client` : null,
    data.updated_at)

  useEffect(() => {
    let live = true
    officerChangeApi.recipients(data.id).then(r => {
      if (!live) return
      setRecipients(r.recipients || [])
      setTo(r.default_to || [])
      if (!respondBy && r.reply_by_default) setRespondBy(r.reply_by_default)
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

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-hdr">
          <div>
            <div className="card-title">Send for verification</div>
            <div className="card-sub">
              The client receives CR's form — the public pages only — and confirms it with one
              press. Personal identity numbers and residential addresses are not included.
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
                    pills={[{ label: 'Client copy — public pages', tone: '' }]}
                    label="draft form" />
        )}

        {sent && (
          <div className={`alert ${data.client_approved === true ? 'al-success'
            : data.client_approved === false ? 'al-warn' : 'al-info'}`} style={{ marginTop: 12 }}>
            <div className="al-body">
              Sent {formatDateTime(data.verification_sent_at)}.{' '}
              {data.client_approved === true && <>Confirmed by the client
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
                       onChange={e => setRespondBy(e.target.value)} />
                {data.deadline?.date && (
                  <div className="f-hint">CR's deadline is {formatDate(data.deadline.date)}.</div>
                )}
              </div>
              <button className="btn btn-primary" disabled={Boolean(blocked) || sending} onClick={send}>
                {sending ? 'Sending…' : 'Send to client'}
              </button>
            </div>
            {blocked && <div className="oc-locked-note">{blocked}</div>}
          </>
        )}

        {can.write && sent && data.client_approved == null && (
          <div className="oc-send-row">
            <span className="f-hint">Client answered by email or phone?</span>
            <button className="btn btn-outline" onClick={() => answer(true)}>Client approved</button>
            <button className="btn btn-outline" onClick={() => answer(false)}>Client declined</button>
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

      {delivery && (
        <VerificationDeliveryModal caseId={data.id} deliveries={delivery.deliveries}
                                   phase={delivery.phase}
                                   deliveryPath={`/officer-changes/${data.id}/verification/delivery`}
                                   onClose={async () => { setDelivery(null); await reload() }} />
      )}
    </>
  )
}
