import { useState } from 'react'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

export const SUPPORT_TYPES = [
  ['resignation_letter', 'Resignation letter'],
  ['board_resolution', 'Board resolution'],
  ['consent_to_act', 'Consent to act'],
  ['officer_change_support', 'Other'],
]

/**
 * One joiner's or leaver's supporting documents (answer 7). Held on the case
 * until the form is filed, then saved to the officer's own profile — so the
 * list says where each file will go, and once filed, where it went.
 */
export default function SupportingDocuments({ data, entry, reload, can }) {
  const docs = entry.documents || []
  const [type, setType] = useState(entry.kind === 'cessation' ? 'resignation_letter' : 'consent_to_act')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const writable = can.write && !data.changes_applied_at && !data.manual_receipt

  async function upload() {
    setBusy(true); setError(null)
    try {
      await reload(await officerChangeApi.uploadDocument(data.id, entry.id, file, type))
      setFile(null)
    } catch (e) { setError(errorOf(e).message) } finally { setBusy(false) }
  }

  async function remove(doc) {
    setError(null)
    try { await reload(await officerChangeApi.removeDocument(data.id, doc.id)) }
    catch (e) { setError(errorOf(e).message) }
  }

  async function download(doc) {
    try {
      const { url } = await officerChangeApi.documentUrl(data.id, doc.id)
      if (url) window.open(url, '_blank', 'noopener')
    } catch (e) { setError(errorOf(e).message) }
  }

  return (
    <div className="f-group" aria-label={`Supporting documents for ${entry.party?.name}`}>
      <span className="f-label">Supporting documents</span>
      {docs.length === 0 && <div className="f-hint">None uploaded.</div>}
      {docs.map(doc => (
        <div className="doc-item" key={doc.id}>
          <span className="doc-name">{doc.file_name}</span>
          <span className="td-muted"> · {doc.type_label}</span>
          <span className="td-muted"> · {doc.filed ? 'saved to' : 'will be saved to'} {doc.destination?.name}</span>
          <span style={{ marginLeft: 'auto' }} className="row gap-8">
            <button className="btn btn-ghost btn-sm" onClick={() => download(doc)}>Download</button>
            {writable && !doc.filed && (
              <button className="btn btn-ghost btn-sm" onClick={() => remove(doc)}>Remove</button>
            )}
          </span>
        </div>
      ))}
      {writable && (
        <div className="row gap-8" style={{ marginTop: 6, flexWrap: 'wrap' }}>
          <select className="f-select" aria-label="Document type" value={type}
                  onChange={e => setType(e.target.value)} style={{ maxWidth: 200 }}>
            {SUPPORT_TYPES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
          <input type="file" aria-label="Choose file" onChange={e => setFile(e.target.files?.[0] || null)} />
          <button className="btn btn-outline btn-sm" disabled={!file || busy} onClick={upload}>
            {busy ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      )}
      {error && <div className="f-hint" role="alert" style={{ color: '#B91C1C' }}>{error}</div>}
    </div>
  )
}
