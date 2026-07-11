import { useState } from 'react'
import { api } from '../lib/api.js'

// Create-time status is restricted to Pre-Incorporation / Live (OQ-3);
// Ceased is reached later via a status action, never at create.
const STATUSES = [
  { value: 'pre_incorporation', label: 'Pre-Incorporation' },
  { value: 'live', label: 'Live' },
]

const COMPANY_TYPES = [
  'Private company limited by shares',
  'Private company limited by guarantee',
  'Public company limited by shares',
]

export default function AddCompanyModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    company_name: '', br_number: '', status: '', company_type: '',
    registered_address: '', company_phone: '',
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [apiError, setApiError] = useState('')

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  function validate() {
    const next = {}
    if (!form.company_name.trim()) next.company_name = 'Company name is required'
    if (!form.status) next.status = 'Status is required'
    if (!form.company_type) next.company_type = 'Company type is required'
    if (form.br_number && !/^\d{8}$/.test(form.br_number.trim())) {
      next.br_number = 'BRN must be 8 digits'
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
      const created = await api.post('/companies', body)
      onCreated(created)
    } catch (err) {
      setApiError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label="New Company">
        <div className="modal-hdr">
          <div className="modal-title">New Company</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          {apiError && (
            <div style={{ marginBottom: 14, padding: 10, background: '#FEE2E2', borderRadius: 6, color: '#B91C1C', fontSize: 12 }}>
              {apiError}
            </div>
          )}
          <div className="form-grid">
            <div className="f-group full">
              <label className="f-label" htmlFor="company_name">
                Company Name <span className="f-req">*</span>
              </label>
              <input id="company_name" className="f-input" type="text"
                     placeholder="e.g. Skyline Capital Management"
                     value={form.company_name} onChange={set('company_name')} />
              {errors.company_name && <span className="f-hint" style={{ color: '#C53030' }}>{errors.company_name}</span>}
            </div>

            <div className="f-group">
              <label className="f-label" htmlFor="br_number">BRN</label>
              <input id="br_number" className="f-input" type="text" placeholder="8-digit BR number"
                     value={form.br_number} onChange={set('br_number')} />
              {errors.br_number && <span className="f-hint" style={{ color: '#C53030' }}>{errors.br_number}</span>}
            </div>

            <div className="f-group">
              <label className="f-label" htmlFor="status">Status <span className="f-req">*</span></label>
              <select id="status" className="f-select" value={form.status} onChange={set('status')}>
                <option value="">Select…</option>
                {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              {errors.status && <span className="f-hint" style={{ color: '#C53030' }}>{errors.status}</span>}
            </div>

            <div className="f-group full">
              <label className="f-label" htmlFor="company_type">Company Type <span className="f-req">*</span></label>
              <select id="company_type" className="f-select" value={form.company_type} onChange={set('company_type')}>
                <option value="">Select…</option>
                {COMPANY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              {errors.company_type && <span className="f-hint" style={{ color: '#C53030' }}>{errors.company_type}</span>}
            </div>

            <div className="f-group full">
              <label className="f-label" htmlFor="registered_address">Registered Address</label>
              <input id="registered_address" className="f-input" type="text"
                     placeholder="Company registered address in HK"
                     value={form.registered_address} onChange={set('registered_address')} />
            </div>

            <div className="f-group">
              <label className="f-label" htmlFor="company_phone">Company Phone</label>
              <input id="company_phone" className="f-input" type="text" placeholder="+852 XXXX XXXX"
                     value={form.company_phone} onChange={set('company_phone')} />
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={saving}>
            {saving ? 'Creating…' : 'Create Company'}
          </button>
        </div>
      </div>
    </div>
  )
}
