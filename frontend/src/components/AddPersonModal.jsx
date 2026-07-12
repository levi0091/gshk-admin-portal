import { useState } from 'react'
import FormField from './FormField.jsx'
import { useLookups } from '../lib/lookups.js'
import { api } from '../lib/api.js'

const FIELDS = [
  { key: 'full_name', label: 'Full Name', required: true, full: true, placeholder: 'Legal name as per ID' },
  { key: 'given_names', label: 'Given Names' },
  { key: 'surname', label: 'Surname' },
  { key: 'full_name_zh', label: 'Chinese Name' },
  { key: 'date_of_birth', label: 'Date of Birth', type: 'date' },
  { key: 'gender', label: 'Gender', lookup: 'gender' },
  { key: 'nationality', label: 'Nationality', lookup: 'nationality' },
  { key: 'marital_status', label: 'Marital Status', lookup: 'marital_status' },
  { key: 'occupation', label: 'Occupation' },
  { key: 'email', label: 'Email', type: 'email' },
  { key: 'phone', label: 'Phone' },
]

export default function AddPersonModal({ onClose, onCreated }) {
  const [form, setForm] = useState({})
  const lookups = useLookups()
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [apiError, setApiError] = useState('')

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
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label="New Person">
        <div className="modal-hdr">
          <div className="modal-title">New Person</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          {apiError && (
            <div style={{ marginBottom: 14, padding: 10, background: '#FEE2E2', borderRadius: 6, color: '#B91C1C', fontSize: 12 }}>
              {apiError}
            </div>
          )}
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
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={saving}>
            {saving ? 'Creating…' : 'Create Person'}
          </button>
        </div>
      </div>
    </div>
  )
}
