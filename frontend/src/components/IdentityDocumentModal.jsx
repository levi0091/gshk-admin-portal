import { useState, useRef } from 'react'
import FormField from './FormField.jsx'
import { api } from '../lib/api.js'
import { idNumberProblem } from '../lib/hkid.js'
import { IDENTITY_FIELD, identityRules } from '../lib/documentSections.js'

/**
 * Add or replace one identity document, with the scan that evidences it.
 *
 * TWO THINGS ARE BEING SAVED AND THEY BEHAVE DIFFERENTLY. The NUMBER is
 * overwritten — a person holds one passport record, and re-recording it
 * replaces what was there. The SCAN is versioned — the previous file stays in
 * Document History, marked superseded. Before this existed, uploading a
 * passport did neither: it appended a file to history under a type called
 * "Identity Document Scan" and never touched the passport record at all.
 *
 * WHICH FIELDS APPEAR IS THE SERVER'S ANSWER, not this component's. An HKID
 * takes a number and nothing else (CR has no country box beside `<hkid>`, and
 * the card does not expire); a passport cannot be filed without its issuing
 * country. `identity_fields` comes from `/documents/sections`, which is the
 * same rule the API enforces on save.
 *
 * THE FILE IS OPTIONAL. GSHK holds passport numbers for clients whose scan
 * nobody can find, and CR never asks to see one — refusing the number until a
 * file turns up would block a return over evidence the Registry does not want.
 */
export default function IdentityDocumentModal({
  personId, personName, types = [], identityFields = {}, existing = [],
  lookups, initialType = '', onClose, onSaved,
}) {
  const [typeCode, setTypeCode] = useState(initialType)
  const [form, setForm] = useState({})
  const [title, setTitle] = useState('')
  const [file, setFile] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const fileRef = useRef(null)

  const selected = types.find(t => t.code === typeCode)
  const idType = selected?.id_type || ''
  const rules = identityRules(identityFields, idType)
  const fields = (rules.fields || []).map(k => IDENTITY_FIELD[k]).filter(Boolean)
  const required = rules.required || []

  // What this save would REPLACE — named, because the number is overwritten
  // and that is not something to discover afterwards.
  const replacing = existing.find(d => d.id_type === idType)

  // The check digit, while they are looking at the field. The API refuses it
  // too; this is so the rest of the form is not discarded to say so.
  const problem = idNumberProblem(idType, form.id_number)

  const missing = required.filter(k => !String(form[k] ?? '').trim())

  async function handleSave() {
    if (!typeCode) return setError('Select a document type')
    if (problem) return setError(problem)
    if (missing.length) {
      const labels = missing.map(k => IDENTITY_FIELD[k]?.label || k)
      return setError(`${labels.join(' and ')} ${missing.length > 1 ? 'are' : 'is'} required for a ${selected.label}`)
    }

    setSaving(true)
    setError('')
    const fd = new FormData()
    fd.append('id_type', idType)
    fd.append('id_number', String(form.id_number ?? '').trim())
    for (const key of ['issuing_country', 'issue_date', 'expiry_date']) {
      if ((rules.fields || []).includes(key) && form[key]) fd.append(key, form[key])
    }
    // The first document a person holds is made primary by the server whatever
    // this says, so an operator cannot create a person whose only identity
    // document is not the one their profile quotes.
    fd.append('is_primary', String(!existing.length))
    if (title) fd.append('title', title)
    if (file) fd.append('file', file)

    try {
      onSaved(await api.upload(`/persons/${personId}/identity-documents`, fd))
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label="Identity Document">
        <div className="modal-hdr">
          <div className="modal-title">
            {replacing ? 'Replace Identity Document' : 'Add Identity Document'}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          <div className="upload-owner-line">
            Recording against <b>{personName}</b>
          </div>

          {error && <div className="modal-error">{error}</div>}

          <div className="f-group" style={{ marginBottom: 14 }}>
            <label className="f-label" htmlFor="identity_type">
              Document Type <span className="f-req">*</span>
            </label>
            <select id="identity_type" className="f-select" value={typeCode}
                    onChange={e => { setTypeCode(e.target.value); setError('') }}>
              <option value="">Select…</option>
              {types.map(t => <option key={t.code} value={t.code}>{t.label}</option>)}
            </select>
            {replacing && (
              <span className="f-hint" style={{ color: 'var(--carrot)' }}>
                A {selected.label} is already on file ({replacing.id_number}). Saving
                REPLACES those details. Any scan you attach is kept as a new version —
                the previous file stays in Document History.
              </span>
            )}
          </div>

          {typeCode && (
            <>
              <div className="form-grid">
                {fields.map(f => (
                  <FormField
                    key={f.key}
                    field={{ ...f, required: required.includes(f.key) }}
                    value={form[f.key]}
                    lookups={lookups}
                    onChange={(k, v) => { setForm(s => ({ ...s, [k]: v })); setError('') }}
                  />
                ))}
              </div>
              {problem && (
                <div className="f-hint" style={{ color: '#C53030', marginBottom: 12 }}>
                  {problem}
                </div>
              )}

              <div className="f-group" style={{ marginBottom: 14 }}>
                <label className="f-label" htmlFor="identity_title">Title</label>
                <input id="identity_title" className="f-input" type="text"
                       placeholder="Optional label for the scan"
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
                    <div><span className="dz-link">Attach a scan</span> (optional)</div>
                    <div className="dz-sub">PDF or image · the number above is what CR is filed from</div>
                  </>
                )}
              </button>
            </>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving || !typeCode}>
            {saving ? 'Saving…' : replacing ? 'Replace' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
