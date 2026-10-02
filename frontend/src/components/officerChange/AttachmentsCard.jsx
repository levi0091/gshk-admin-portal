import { useState } from 'react'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

const CASE_TYPES = [
  ['board_resolution', 'Written resolution'],
  ['officer_change_support', 'Other'],
]

/**
 * What goes with the client email besides the draft form (Jacqueline A3:
 * "the client doesn't need to receive two separate emails — one automated
 * from the G Flow system and another manual email from us").
 *
 * Two sources. Any document uploaded here for the whole form — GSHK's own
 * written resolution, say — and ticked "Send with the email". And, for an
 * ND2A, the written resolution G-FlowDesk prepares from the change list: off
 * until someone has previewed it, because its wording is a standard one and
 * not GSHK's own template. Everything uploaded here is filed to the company's
 * documents once the form is filed. Without Officer changes (edit), the card
 * lists what will be attached and draws no control.
 */
export default function AttachmentsCard({ data, reload, can }) {
  const docs = (data.documents || []).filter(d => d.entry_id == null)
  const writable = can.write && !data.verification_sent_at && !data.manual_receipt
    && !data.changes_applied_at
  const nd2a = data.form_code === 'Nd2a'
  const [type, setType] = useState('board_resolution')
  const [send, setSend] = useState(true)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(promise) {
    setError(null); setBusy(true)
    try { await reload(await promise) } catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  async function upload() {
    await run(officerChangeApi.uploadCaseDocument(data.id, file, type, send))
    setFile(null)
  }

  async function preview() {
    try {
      const blob = await officerChangeApi.resolutionPdf(data.id)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e) { setError(errorOf(e).message) }
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-hdr">
        <div>
          <div className="card-title">Sent with the email</div>
          <div className="card-sub">
            The draft form is always attached. Add anything else the client should
            receive in the same email.
          </div>
        </div>
      </div>

      {docs.length === 0 && !nd2a && <div className="f-hint">Nothing else is attached.</div>}
      {docs.map(doc => (
        <div className="oc-attach-row" key={doc.id}>
          {writable ? (
            <input type="checkbox" checked={Boolean(doc.send_with_email)} disabled={busy}
                   aria-label={`Send ${doc.file_name} with the email`}
                   onChange={e => run(officerChangeApi.setSendWithEmail(data.id, doc.id, e.target.checked))} />
          ) : null}
          <span className="oc-attach-name">{doc.file_name}</span>
          <span className="td-muted">{doc.type_label}</span>
          <span className="td-muted" style={{ marginLeft: 'auto' }}>
            {doc.send_with_email ? 'Goes with the email' : 'Kept on the case only'}
          </span>
          {writable && (
            <button className="btn btn-ghost btn-sm" disabled={busy}
                    onClick={() => run(officerChangeApi.removeDocument(data.id, doc.id))}>Remove</button>
          )}
        </div>
      ))}

      {nd2a && (
        <div className="oc-attach-gen">
          {writable ? (
            <label className="oc-inline-check">
              <input type="checkbox" checked={Boolean(data.attach_resolution)} disabled={busy}
                     onChange={e => run(officerChangeApi.patch(data.id, { attach_resolution: e.target.checked }))} />
              Attach the written resolution prepared by G-FlowDesk
            </label>
          ) : (
            <span>Written resolution prepared by G-FlowDesk:{' '}
              {data.attach_resolution ? 'attached' : 'not attached'}</span>
          )}
          <button type="button" className="btn btn-outline btn-sm" onClick={preview}>
            Preview resolution
          </button>
          <span className="f-hint" style={{ flexBasis: '100%' }}>
            Built from the changes above for the directors to sign. Check the wording before
            attaching it.
          </span>
        </div>
      )}

      {writable && (
        <div className="row gap-8" style={{ marginTop: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <select className="f-select" aria-label="Document type" value={type}
                  onChange={e => setType(e.target.value)} style={{ maxWidth: 200 }}>
            {CASE_TYPES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
          <input type="file" aria-label="Choose file" onChange={e => setFile(e.target.files?.[0] || null)} />
          <label className="oc-inline-check">
            <input type="checkbox" checked={send} onChange={e => setSend(e.target.checked)} />
            Send with the email
          </label>
          <button className="btn btn-outline btn-sm" disabled={!file || busy} onClick={upload}>
            {busy ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      )}
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 10 }}>
        <div className="al-body">{error}</div></div>}
    </div>
  )
}
