import { useState, useEffect, useRef } from 'react'
import { api } from '../lib/api.js'

/**
 * Versioned upload. Re-uploading an existing document type for the same owner
 * creates a NEW VERSION server-side — history is preserved, never overwritten.
 *
 * ownerKind: 'entity' (company) | 'person'
 */
export default function UploadDocumentModal({ ownerKind, ownerId, ownerName, existingTypes = [], onClose, onUploaded }) {
  const [types, setTypes] = useState([])
  const [typeCode, setTypeCode] = useState('')
  const [title, setTitle] = useState('')
  const [file, setFile] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const fileRef = useRef(null)

  // Only the types this owner can actually hold — a Certificate of Incorporation
  // is not a person's document, and offering it here only invites a bad upload.
  const ownerType = ownerKind === 'person' ? 'person' : 'company'

  useEffect(() => {
    api.get(`/documents/types?owner_type=${ownerType}`)
      .then(setTypes)
      .catch(err => setError(err.message))
  }, [ownerType])

  const isNewVersion = typeCode && existingTypes.includes(typeCode)

  async function handleUpload() {
    if (!file) return setError('Choose a file to upload')
    if (!typeCode) return setError('Select a document type')

    setSaving(true)
    setError('')
    const fd = new FormData()
    fd.append('file', file)
    fd.append('document_type_code', typeCode)
    if (title) fd.append('title', title)

    const path = ownerKind === 'person'
      ? `/persons/${ownerId}/documents`
      : `/companies/${ownerId}/documents`
    try {
      onUploaded(await api.upload(path, fd))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label="Upload Document">
        <div className="modal-hdr">
          <div className="modal-title">Upload Document</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          <div className="upload-owner-line">
            Uploading to <b>{ownerName}</b>
          </div>

          {error && (
            <div style={{ marginBottom: 14, padding: 10, background: '#FEE2E2', borderRadius: 6, color: '#B91C1C', fontSize: 12 }}>
              {error}
            </div>
          )}

          <div className="f-group" style={{ marginBottom: 14 }}>
            <label className="f-label" htmlFor="document_type_code">
              Document Type <span className="f-req">*</span>
            </label>
            <select id="document_type_code" className="f-select" value={typeCode}
                    onChange={e => setTypeCode(e.target.value)}>
              <option value="">Select…</option>
              {types.map(t => <option key={t.code} value={t.code}>{t.label}</option>)}
            </select>
            {isNewVersion && (
              <span className="f-hint" style={{ color: 'var(--carrot)' }}>
                A document of this type already exists — this upload will be saved as a new version.
                The previous version is preserved.
              </span>
            )}
          </div>

          <div className="f-group" style={{ marginBottom: 14 }}>
            <label className="f-label" htmlFor="doc_title">Title</label>
            <input id="doc_title" className="f-input" type="text" placeholder="Optional label"
                   value={title} onChange={e => setTitle(e.target.value)} />
          </div>

          <input
            ref={fileRef}
            type="file"
            aria-label="Choose file"
            style={{ display: 'none' }}
            onChange={e => { setFile(e.target.files?.[0] || null); setError('') }}
          />
          <button type="button" className="drop-zone" onClick={() => fileRef.current?.click()}>
            {file ? (
              <>
                <div><b>{file.name}</b></div>
                <div className="dz-sub">{(file.size / 1024).toFixed(0)} KB · click to replace</div>
              </>
            ) : (
              <>
                <div><span className="dz-link">Choose a file</span> to upload</div>
                <div className="dz-sub">PDF or image</div>
              </>
            )}
          </button>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleUpload} disabled={saving}>
            {saving ? 'Uploading…' : isNewVersion ? 'Upload New Version' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  )
}
