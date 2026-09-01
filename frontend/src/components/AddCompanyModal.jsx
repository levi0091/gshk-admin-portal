import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import AddressBlock from './AddressBlock.jsx'
import { EMPTY_ADDRESS, addressPayload } from '../lib/address.js'
import { useLookups } from '../lib/lookups.js'
import useDiscardGuard from '../lib/useDiscardGuard.js'
import DiscardConfirm from './DiscardConfirm.jsx'

// Create-time status is restricted to Pre-Incorporation / Live (OQ-3);
// Ceased is reached later via a status action, never at create.
const STATUSES = [
  { value: 'pre_incorporation', label: 'Pre-Incorporation' },
  { value: 'live', label: 'Live' },
]

// Company type comes from CR's own vocabulary (`cr_company_type`: P Private,
// N Public, G Limited by Guarantee), served from /lookups.
//
// It used to be three hardcoded free-text descriptions lifted from Viewpoint.
// CR refuses anything but its three codes on `coyType`, so a company created
// here was born carrying a value its own annual return could not state — and
// nothing said so until the filing.

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
  incorporation_place: '',
  phone_code: DEFAULT_DIAL_CODE, phone_number: '',
}

// Hong Kong by default: this form creates HK companies, and the district
// dropdown only appears once a country says so.
const EMPTY_NEW_ADDRESS = { ...EMPTY_ADDRESS, country: 'HK' }

/** Hong Kong as the seeded vocabulary spells it — by code, then by label. */
function findHongKong(countries) {
  const list = Array.isArray(countries) ? countries : []
  return list.find(c => c.code === 'HK')
    || list.find(c => String(c.label).trim().toLowerCase() === 'hong kong')
}

export default function AddCompanyModal({ onClose, onCreated }) {
  const [form, setForm] = useState(EMPTY_FORM)
  // The address is its own row on the server, so it is its own state here.
  const [address, setAddress] = useState(EMPTY_NEW_ADDRESS)
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
    // line1 + country, not the whole address: CR needs a country to file at
    // all, and an address with no first line is not an address. The rest can
    // be filled in on the profile.
    if (!(address.line1 || '').trim()) next.address = 'A registered address is required'
    else if (!(address.country || '').trim()) next.address = 'The address needs a country'
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
      // The address goes through its own endpoint so it meets the same
      // validation as every later edit — a company created here must not be
      // able to hold an address the NAR1 mapper would refuse.
      await api.put(`/companies/${created.id}/registered-address`, addressPayload(address))
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
                {(lookups.cr_company_type || []).map(t => (
                  <option key={t.code} value={t.code}>{t.label}</option>
                ))}
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
              <div className="tile-sec-lbl">
                Registered Address <span className="f-req">*</span>
              </div>
              {/* Separate lines, not one box. The single free-text field this
                  replaced wrote everything into line1, which is the same shape
                  of mistake the ETL made in the other direction. */}
              <AddressBlock
                value={address}
                lookups={lookups}
                onChange={(k, v) => setAddress(a => ({ ...a, [k]: v }))}
              />
              {errors.address && <span className="f-hint" style={{ color: '#C53030' }}>{errors.address}</span>}
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
