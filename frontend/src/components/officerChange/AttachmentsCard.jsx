import { useState } from 'react'
import FileDropZone from '../FileDropZone.jsx'
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
 * email: drop it here and it goes with the email, unless its tick is cleared.
 * Everything uploaded here is filed to the company's documents once the form is
 * filed. Without Officer changes (edit), the card lists what will be attached
 * and draws no control.
 */
export default function AttachmentsCard({ data, reload, can }) {
  const docs = (data.documents || []).filter(d => d.entry_id == null)
  const writable = can.write && !data.verification_sent_at && !data.manual_receipt
    && !data.changes_applied_at
  const nd2a = data.form_code === 'Nd2a'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(promise) {
    setError(null); setBusy(true)
    try { await reload(await promise) } catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  // One at a time, and one refused file does not lose the others: each is named.
  async function upload(files) {
    setError(null); setBusy(true)
    const failed = []
    let latest = null
    for (const file of files) {
      try { latest = await officerChangeApi.uploadCaseDocument(data.id, file, 'officer_change_support', true) }
      catch (e) { failed.push(`${file.name}: ${errorOf(e).message}`) }
    }
    try { if (latest) await reload(latest) } catch (e) { failed.push(errorOf(e).message) }
    if (failed.length) setError(failed.join(' '))
    setBusy(false)
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
        <div style={{ marginTop: 12 }}>
          <FileDropZone onFiles={upload} busy={busy}
                        sub="Each file goes with the email. Clear its tick to keep it on the case only." />
        </div>
      )}
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 10 }}>
        <div className="al-body">{error}</div></div>}
    </div>
  )
}
