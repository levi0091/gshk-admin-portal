import { useState } from 'react'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/**
 * What else goes with the client email (Jacqueline A3: "the client doesn't
 * need to receive two separate emails").
 *
 * The draft form always goes, and an ND2A's written resolution — built to
 * GSHK's own sample — always goes with it (Levi 2026-10-05: "When they click
 * send to client button then both are sent"); both are previewed on the tabs
 * above. This card is for anything ELSE the client should have in the same
 * email: upload it and tick "Send with the email". Everything uploaded here is
 * filed to the company's documents once the form is filed. Without Officer
 * changes (edit), the card lists what will be attached and draws no control.
 */
export default function AttachmentsCard({ data, reload, can }) {
  const docs = (data.documents || []).filter(d => d.entry_id == null)
  const writable = can.write && !data.verification_sent_at && !data.manual_receipt
    && !data.changes_applied_at
  const nd2a = data.form_code === 'Nd2a'
  const [send, setSend] = useState(true)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(promise) {
    setError(null); setBusy(true)
    try { await reload(await promise) } catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  async function upload() {
    await run(officerChangeApi.uploadCaseDocument(data.id, file, 'officer_change_support', send))
    setFile(null)
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-hdr">
        <div>
          <div className="card-title">Sent with the email</div>
          <div className="card-sub">
            {nd2a ? 'The draft form and its written resolution are always attached.'
              : 'The draft form is always attached.'} Add anything else the client should
            receive in the same email.
          </div>
        </div>
      </div>

      {docs.length === 0 && <div className="f-hint">Nothing else is attached.</div>}
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

      {writable && (
        <div className="row gap-8" style={{ marginTop: 12, flexWrap: 'wrap', alignItems: 'center' }}>
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
