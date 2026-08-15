import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { useLookups } from '../lib/lookups.js'
import useDiscardGuard from '../lib/useDiscardGuard.js'
import DiscardConfirm from './DiscardConfirm.jsx'

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

// UAT F-3: operators were keying bare local numbers with no country prefix.
// A short curated list beats a 200-row lookup here — `company_phone` stays a
// single string on the wire, so no migration (OQ-6).
const DEFAULT_DIAL_CODE = '+852'
const DIAL_CODES = [
  { code: '+852', label: '+852  Hong Kong' },
  { code: '+86', label: '+86  Mainland China' },
  { code: '+853', label: '+853  Macau' },
  { code: '+886', label: '+886  Taiwan' },
  { code: '+65', label: '+65  Singapore' },
  { code: '+44', label: '+44  United Kingdom' },
  { code: '+1', label: '+1  US / Canada' },
  { code: '+61', label: '+61  Australia' },
]

const EMPTY_FORM = {
  company_name: '', br_number: '', status: '', company_type: '',
  incorporation_place: '', registered_address: '',
  phone_code: DEFAULT_DIAL_CODE, phone_number: '',
}

/** Hong Kong as the seeded vocabulary spells it — by code, then by label. */
function findHongKong(countries) {
  const list = Array.isArray(countries) ? countries : []
  return list.find(c => c.code === 'HK')
    || list.find(c => String(c.label).trim().toLowerCase() === 'hong kong')
}

export default function AddCompanyModal({ onClose, onCreated }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const lookups = useLookups()
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [apiError, setApiError] = useState('')

  // What the form looked like before the operator touched it. Moves in step
  // with the Hong Kong default below so that auto-fill never reads as an edit.
  const baseline = useRef(EMPTY_FORM)

  // UAT F-2: virtually every company here is incorporated in Hong Kong, so
  // preselect it. The lookup arrives async, hence the effect rather than an
  // initial value; if the vocabulary has no Hong Kong row, leave it blank
  // rather than posting a code the backend has never heard of.
  useEffect(() => {
    const hk = findHongKong(lookups.country)
    if (!hk) return
    setForm(f => (f.incorporation_place ? f : { ...f, incorporation_place: hk.code }))
    if (!baseline.current.incorporation_place) {
      baseline.current = { ...baseline.current, incorporation_place: hk.code }
    }
  }, [lookups.country])

  const isDirty = Object.keys(form).some(k => form[k] !== baseline.current[k])
  const guard = useDiscardGuard(isDirty, onClose)

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  function validate() {
    const next = {}
    if (!form.company_name.trim()) next.company_name = 'Company name is required'
    if (!form.status) next.status = 'Status is required'
    if (!form.company_type) next.company_type = 'Company type is required'
    if (form.br_number && !/^\d{8}$/.test(form.br_number.trim())) {
      next.br_number = 'BRN must be 8 digits'
    }
    if (!form.incorporation_place) next.incorporation_place = 'Country of incorporation is required'
    if (!form.registered_address.trim()) next.registered_address = 'Registered address is required'
    // A dialling code on its own is not a phone number.
    if (!form.phone_number.trim()) next.company_phone = 'Company phone is required'
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function handleSubmit() {
    if (!validate()) return
    setSaving(true)
    setApiError('')
    const { phone_code, phone_number, ...rest } = form
    const body = Object.fromEntries(
      Object.entries({ ...rest, company_phone: `${phone_code} ${phone_number.trim()}`.trim() })
        .filter(([, v]) => v !== '' && v != null)
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
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) guard.requestClose() }}>
      <div className="modal" role="dialog" aria-label="New Company">
        <div className="modal-hdr">
          <div className="modal-title">New Company</div>
          <button className="modal-close" onClick={guard.requestClose} aria-label="Close">×</button>
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

            <div className="f-group">
              <label className="f-label" htmlFor="incorporation_place">
                Country of Incorporation <span className="f-req">*</span>
              </label>
              <select id="incorporation_place" className="f-select"
                      value={form.incorporation_place} onChange={set('incorporation_place')}>
                <option value="">Select…</option>
                {(lookups.country || []).map(c => (
                  <option key={c.code} value={c.code}>{c.label}</option>
                ))}
              </select>
              {errors.incorporation_place && <span className="f-hint" style={{ color: '#C53030' }}>{errors.incorporation_place}</span>}
            </div>

            <div className="f-group full">
              <label className="f-label" htmlFor="registered_address">
                Registered Address <span className="f-req">*</span>
              </label>
              <input id="registered_address" className="f-input" type="text"
                     placeholder="Company registered address in HK"
                     value={form.registered_address} onChange={set('registered_address')} />
              {errors.registered_address && <span className="f-hint" style={{ color: '#C53030' }}>{errors.registered_address}</span>}
            </div>

            <div className="f-group full">
              <label className="f-label" htmlFor="company_phone">
                Company Phone <span className="f-req">*</span>
              </label>
              <div className="f-phone">
                <select className="f-select" aria-label="Dialling code"
                        value={form.phone_code} onChange={set('phone_code')}>
                  {DIAL_CODES.map(d => <option key={d.code} value={d.code}>{d.label}</option>)}
                </select>
                <input id="company_phone" className="f-input" type="tel" placeholder="9123 4567"
                       value={form.phone_number} onChange={set('phone_number')} />
              </div>
              {errors.company_phone && <span className="f-hint" style={{ color: '#C53030' }}>{errors.company_phone}</span>}
            </div>
          </div>

          <div className="f-legend"><span className="f-req">*</span> Fields marked with an asterisk are required.</div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={guard.requestClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={saving}>
            {saving ? 'Creating…' : 'Create Company'}
          </button>
        </div>

        {guard.confirming && (
          <DiscardConfirm onKeepEditing={guard.keepEditing} onDiscard={guard.discard} />
        )}
      </div>
    </div>
  )
}
