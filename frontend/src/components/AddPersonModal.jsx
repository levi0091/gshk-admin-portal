import { useState } from 'react'
import FormField from './FormField.jsx'
import DiscardConfirm from './DiscardConfirm.jsx'
import { useLookups } from '../lib/lookups.js'
import useDiscardGuard from '../lib/useDiscardGuard.js'
import { api } from '../lib/api.js'
import { idNumberProblem } from '../lib/hkid.js'
import { useDocumentSections, identityRules, IDENTITY_FIELD } from '../lib/documentSections.js'

// NAR1's labels, and NAR1's fields (PRD §10.5). Marital Status is gone for
// the same reason it is gone from the profile: neither form asks for it, and
// the column is retained so nothing is destroyed (D3).
//
// THE FOUR THAT WERE MISSING (Levi 2026-09-04). Previous Names in both
// languages, Nationality Origin and Place of Birth were all editable on the
// profile and absent here, so every one of them could only ever be filled in on
// a second visit to a record that had just been created from the same data.
// `prevNameEng` / `prevNameChi` are CR fields on both NAR1 and NNC1.
const FIELDS = [
  { key: 'full_name', label: 'Full Name', required: true, full: true, placeholder: 'Legal name as per ID' },
  { key: 'surname', label: 'Name in English (Surname)' },
  { key: 'given_names', label: 'Name in English (Other Names)' },
  { key: 'full_name_zh', label: 'Name in Chinese' },
  { key: 'former_name', label: 'Previous Names (English)' },
  { key: 'former_name_zh', label: 'Previous Names (Chinese)' },
  { key: 'alias_en', label: 'Alias (English)' },
  { key: 'alias_zh', label: 'Alias (Chinese)' },
  { key: 'date_of_birth', label: 'Date of Birth', type: 'date' },
  { key: 'gender', label: 'Gender', lookup: 'gender' },
  { key: 'nationality', label: 'Nationality', lookup: 'nationality' },
  { key: 'nationality_origin', label: 'Nationality Origin', lookup: 'nationality' },
  { key: 'place_of_birth', label: 'Place of Birth', lookup: 'cr_country' },
  { key: 'occupation', label: 'Occupation' },
  { key: 'email', label: 'Email Address', type: 'email' },
  { key: 'phone', label: 'Phone' },
]

export default function AddPersonModal({ onClose, onCreated }) {
  const [form, setForm] = useState({})
  // The identity document, drafted separately because it lands in a different
  // table and carries CR's own rules.
  const [idDoc, setIdDoc] = useState({})
  const lookups = useLookups()
  const { sections, identity_fields: identityFields } = useDocumentSections('person')
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [apiError, setApiError] = useState('')

  const idTypes = (sections.find(s => s.is_identity)?.types || [])
    .filter(t => t.id_type)
  const selectedType = idTypes.find(t => t.code === idDoc.type_code)
  const idType = selectedType?.id_type || ''
  const idRules = identityRules(identityFields, idType)
  const idFields = (idRules.fields || []).map(k => IDENTITY_FIELD[k]).filter(Boolean)

  // Nothing here is pre-filled, so any value at all means the operator typed
  // something worth protecting (UAT F-1).
  const isDirty = [...Object.values(form), ...Object.values(idDoc)]
    .some(v => v !== '' && v != null)
  const guard = useDiscardGuard(isDirty, onClose)

  function validate() {
    const next = {}
    if (!(form.full_name || '').trim()) next.full_name = 'Full name is required'
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      next.email = 'Enter a valid email'
    }
    // An identity document is optional — a person can be recorded before their
    // documents arrive. Started, it has to be finished: a type with no number
    // is a record of nothing, and CR refuses a passport without its country.
    if (idDoc.type_code) {
      const problem = idNumberProblem(idType, idDoc.id_number)
      if (problem) next.id_number = problem
      for (const key of idRules.required || []) {
        if (!String(idDoc[key] ?? '').trim()) {
          next[key] = key === 'issuing_country' && idType === 'passport'
            ? 'CR refuses a passport number without its issuing country'
            : `${IDENTITY_FIELD[key]?.label || key} is required for a ${selectedType.label}`
        }
      }
    } else if ((idDoc.id_number || '').trim()) {
      next.type_code = 'Choose which identity document this number belongs to'
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function handleSubmit() {
    if (!validate()) return
    setSaving(true)
    setApiError('')
    const body = Object.fromEntries(
      Object.entries(form).filter(([, v]) => v !== '' && v != null)
    )
    if (idDoc.type_code) {
      body.identity_document = {
        id_type: idType,
        id_number: String(idDoc.id_number).trim(),
        // Only the fields this type carries. An HKID sent with an issuing
        // country would be storing an answer CR has no box for.
        ...Object.fromEntries((idRules.fields || [])
          .filter(k => k !== 'id_number' && idDoc[k])
          .map(k => [k, idDoc[k]])),
        is_primary: true,
      }
    }
    try {
      onCreated(await api.post('/persons', body))
    } catch (err) {
      setApiError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) guard.requestClose() }}>
      <div className="modal" role="dialog" aria-label="New Person">
        <div className="modal-hdr">
          <div className="modal-title">New Person</div>
          <button className="modal-close" onClick={guard.requestClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          {apiError && <div className="modal-error">{apiError}</div>}
          <div className="form-grid">
            {FIELDS.map(f => (
              <div key={f.key}>
                <FormField
                  field={f}
                  value={form[f.key]}
                  lookups={lookups}
                  onChange={(k, v) => setForm(s => ({ ...s, [k]: v }))}
                />
                {errors[f.key] && (
                  <span className="f-hint" style={{ color: '#C53030' }}>{errors[f.key]}</span>
                )}
              </div>
            ))}
          </div>

          {/* IDENTITY DOCUMENT. This block did not exist: a person could be
              created with names, a nationality and a date of birth, and no way
              to record the number CR files them by — the profile could only
              EDIT identity documents, so one created here had none.

              Which fields appear is the TYPE's answer, from /documents/sections.
              An HKID takes a number alone; a passport cannot be filed without
              its issuing country. */}
          <div className="tile-sec-lbl" style={{ marginTop: 18 }}>Identity Document</div>
          <div className="f-hint" style={{ marginBottom: 10 }}>
            Optional here, but NAR1 and NNC1 carry an HKID or passport number for
            every individual — a person holding neither blocks the return.
          </div>

          <div className="form-grid">
            <div>
              <div className="f-group">
                <label className="f-label" htmlFor="f_id_type">Document Type</label>
                <select id="f_id_type" className="f-select" value={idDoc.type_code || ''}
                        onChange={e => setIdDoc({ type_code: e.target.value })}>
                  <option value="">None</option>
                  {idTypes.map(t => <option key={t.code} value={t.code}>{t.label}</option>)}
                </select>
              </div>
              {errors.type_code && (
                <span className="f-hint" style={{ color: '#C53030' }}>{errors.type_code}</span>
              )}
            </div>

            {idFields.map(f => (
              <div key={f.key}>
                <FormField
                  field={{ ...f, required: (idRules.required || []).includes(f.key) }}
                  value={idDoc[f.key]}
                  lookups={lookups}
                  onChange={(k, v) => setIdDoc(s => ({ ...s, [k]: v }))}
                />
                {errors[f.key] && (
                  <span className="f-hint" style={{ color: '#C53030' }}>{errors[f.key]}</span>
                )}
              </div>
            ))}
          </div>

          <div className="f-legend"><span className="f-req">*</span> Fields marked with an asterisk are required.</div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={guard.requestClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={saving}>
            {saving ? 'Creating…' : 'Create Person'}
          </button>
        </div>

        {guard.confirming && (
          <DiscardConfirm onKeepEditing={guard.keepEditing} onDiscard={guard.discard} />
        )}
      </div>
    </div>
  )
}
