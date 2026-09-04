import { useState, useEffect, useRef } from 'react'
import { api } from '../lib/api.js'

/**
 * Versioned upload. Re-uploading an existing document type for the same owner
 * creates a NEW VERSION server-side — history is preserved, never overwritten.
 *
 * ownerKind: 'entity' (company) | 'person'
 * category:  optional — the SECTION this upload belongs to (migration 036).
 *            The button now lives inside a section rather than in the page
 *            header, so the picker it opens offers that section's types and no
 *            others. Omitted, it offers everything the owner can hold, which is
 *            what the company profile's single button still wants.
 *
 * Identity documents do NOT come through here: they carry a number, an issuing
 * country and dates that this modal has nowhere to put, and the number is
 * overwritten where the file is versioned. `IdentityDocumentModal` owns them.
 */
export default function UploadDocumentModal({
  ownerKind, ownerId, ownerName, existingTypes = [], category = null,
  sectionLabel = null, onClose, onUploaded,
}) {
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
    const scope = category ? `&category=${encodeURIComponent(category)}` : ''
    api.get(`/documents/types?owner_type=${ownerType}${scope}`)
      // A non-list here used to throw inside render and take the whole profile
      // down with it — a blank page, for a picker that could simply have been
      // empty.
      .then(data => setTypes(Array.isArray(data) ? data : []))
      .catch(err => setError(err.message))
  }, [ownerType, category])

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
          <div className="modal-title">
            {sectionLabel ? `Upload — ${sectionLabel}` : 'Upload Document'}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          <div className="upload-owner-line">
            Uploading to <b>{ownerName}</b>
          </div>

          {error && <div className="modal-error">{error}</div>}

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
