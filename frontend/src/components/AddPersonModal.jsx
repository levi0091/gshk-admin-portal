import { useState } from 'react'
import FormField from './FormField.jsx'
import DiscardConfirm from './DiscardConfirm.jsx'
import { useLookups } from '../lib/lookups.js'
import useDiscardGuard from '../lib/useDiscardGuard.js'
import { api } from '../lib/api.js'

// NAR1's labels, and NAR1's fields (PRD §10.5). Marital Status is gone for
// the same reason it is gone from the profile: neither form asks for it, and
// the column is retained so nothing is destroyed (D3).
//
// THE FOUR THAT WERE MISSING (Levi 2026-09-04). Previous Names in both
// languages, Nationality Origin and Place of Birth were all editable on the
// profile and absent here, so every one of them could only ever be filled in on
// a second visit to a record that had just been created from the same data.
// `prevNameEng` / `prevNameChi` are CR fields on both NAR1 and NNC1.
//
// NO IDENTITY DOCUMENT HERE (Levi 2026-09-04, reversing the block added
// earlier the same day). The Identity Documents section on the profile already
// records one, with its scan and its type-specific fields; asking for the type
// again during creation was a second, weaker way to do the same thing. Creating
// a person now does exactly one thing, and the profile owns their documents.
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
  const lookups = useLookups()
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [apiError, setApiError] = useState('')

  // Nothing here is pre-filled, so any value at all means the operator typed
  // something worth protecting (UAT F-1).
  const isDirty = Object.values(form).some(v => v !== '' && v != null)
  const guard = useDiscardGuard(isDirty, onClose)

  function validate() {
    const next = {}
    if (!(form.full_name || '').trim()) next.full_name = 'Full name is required'
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      next.email = 'Enter a valid email'
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
      <div className="modal modal-lg" role="dialog" aria-label="New Person">
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

          {/* Identity documents are added on the profile, in their own
              section, where the scan and the type-specific fields live. Saying
              so here is what stops the operator hunting for the ID Number box
              they expected to find on this form. */}
          <div className="f-legend">
            <span className="f-req">*</span> Fields marked with an asterisk are required.
            <br />
            Add this person’s HKID or passport from their profile, under Identity Documents.
          </div>
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
