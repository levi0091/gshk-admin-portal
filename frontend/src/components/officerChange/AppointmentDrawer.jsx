import { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import Drawer from './Drawer.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

const CONSENT_CAPACITIES = ['Director', 'Company Secretary', 'Authorized Person']
const BLANK_ADDRESS = { line1: '', line2: '', line3: '', city: '', country: '' }

function usePartySearch(kind, term) {
  const [results, setResults] = useState([])
  useEffect(() => {
    if (!term || term.trim().length < 2) { setResults([]); return undefined }
    const t = setTimeout(() => {
      const path = kind === 'person'
        ? `/persons?search=${encodeURIComponent(term)}&page_size=10`
        : `/companies?search=${encodeURIComponent(term)}&flag=corporate_party&page_size=10`
      api.get(path)
        .then(d => setResults(kind === 'person' ? (d.persons || []) : (d.companies || [])))
        .catch(() => setResults([]))
    }, 300)
    return () => clearTimeout(t)
  }, [kind, term])
  return results
}

function PartyPicker({ kind, selected, onSelect, label }) {
  const [term, setTerm] = useState('')
  const results = usePartySearch(kind, term)
  const nameOf = r => r.full_name || r.company_name || r.name
  if (selected) {
    return (
      <div className="f-group">
        <span className="f-label">{label}</span>
        <div className="row gap-8">
          <span className="f-static" style={{ flex: 1 }}>{nameOf(selected)}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onSelect(null)}>Change</button>
        </div>
      </div>
    )
  }
  return (
    <div className="f-group">
      <label className="f-label" htmlFor={`oc-search-${label}`}>{label} <span className="f-req">*</span></label>
      <input id={`oc-search-${label}`} className="f-input" value={term}
             placeholder={kind === 'person' ? 'Search people by name or ID number' : 'Search companies by name or BRN'}
             onChange={e => setTerm(e.target.value)} />
      {results.length > 0 && (
        <div className="oc-results" role="listbox">
          {results.map(r => (
            <button type="button" key={r.id} className="oc-result" role="option" aria-selected="false"
                    onClick={() => onSelect(r)}>
              {nameOf(r)}{r.primary_id_number ? ` · ${r.primary_id_number}` : ''}
              {r.br_number ? ` · BRN ${r.br_number}` : ''}
            </button>
          ))}
        </div>
      )}
      <div className="f-hint">Particulars come from the profile and are not retyped here.</div>
    </div>
  )
}

/**
 * Add or edit an appointment (spec §2, answers 3, 4, 6). The drawer asks only
 * what nothing else holds: who, as what, from when — plus, where it applies,
 * whether the correspondence address is the residential one, the Section 5
 * confirmation for a natural-person secretary, and who signs a body corporate
 * director's consent.
 */
export default function AppointmentDrawer({ data, entry, onClose, onSaved }) {
  const editing = Boolean(entry)
  const [kind, setKind] = useState(entry ? (entry.party_type === 'corporate' ? 'corporate' : 'person') : 'person')
  const [party, setParty] = useState(entry ? { id: entry.person_id || entry.corporate_entity_id,
    full_name: entry.party?.name } : null)
  const [capacity, setCapacity] = useState(entry?.capacity || 'director')
  const [date, setDate] = useState(entry?.effective_date || '')
  const [sameAddress, setSameAddress] = useState(entry ? entry.correspondence_same_as_residential !== false : true)
  const [address, setAddress] = useState({ ...BLANK_ADDRESS, ...(entry?.correspondence_address || {}) })
  const [section5, setSection5] = useState(Boolean(entry?.section5_confirmed))
  const [signer, setSigner] = useState(entry?.consent_person_id
    ? { id: entry.consent_person_id, full_name: entry.consent_person_name } : null)
  const [signerCapacity, setSignerCapacity] = useState(entry?.consent_capacity || 'Director')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  const natural = kind === 'person'
  const corporateDirector = !natural && capacity === 'director'
  const naturalSecretary = natural && capacity === 'company_secretary'

  function payload() {
    const body = { capacity, effective_date: date }
    if (natural) {
      body.correspondence_same_as_residential = sameAddress
      body.correspondence_address = sameAddress ? null : address
      body.section5_confirmed = naturalSecretary ? section5 : false
    }
    if (corporateDirector) {
      body.consent_person_id = signer?.id || null
      body.consent_capacity = signerCapacity
    }
    return body
  }

  async function save() {
    setError(null); setSaving(true)
    try {
      const next = editing
        ? await officerChangeApi.updateEntry(data.id, entry.id, payload())
        : await officerChangeApi.addEntry(data.id, {
          kind: 'appointment', party_type: natural ? 'individual' : 'corporate',
          [natural ? 'person_id' : 'corporate_entity_id']: party?.id, ...payload() })
      onSaved(next)
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setSaving(false)
    }
  }

  const ready = party && date && (sameAddress || !natural || (address.line1 && address.country))
    && (!corporateDirector || signer) && (!naturalSecretary || section5)

  return (
    <Drawer title={editing ? 'Edit appointment' : 'Add appointment'}
            sub="An officer joining the company."
            onClose={onClose}
            footer={<>
              <button className="btn btn-outline" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" disabled={!ready || saving} onClick={save}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Add appointment'}
              </button>
            </>}>
      {!editing && (
        <div className="oc-seg" role="group" aria-label="Who is appointed">
          <button type="button" aria-pressed={natural}
                  onClick={() => { setKind('person'); setParty(null) }}>Natural person</button>
          <button type="button" aria-pressed={!natural}
                  onClick={() => { setKind('corporate'); setParty(null) }}>Body corporate</button>
        </div>
      )}

      {editing ? (
        <div className="f-group"><span className="f-label">Appointee</span>
          <div className="f-static">{entry.party?.name}</div></div>
      ) : (
        <PartyPicker kind={kind} selected={party} onSelect={setParty}
                     label={natural ? 'Person' : 'Body corporate'} />
      )}

      <fieldset className="f-group" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="f-label">Capacity <span className="f-req">*</span></legend>
        <label className="check-row"><input type="radio" name="oc-cap" checked={capacity === 'director'}
          onChange={() => setCapacity('director')} /> Director</label>
        <label className="check-row"><input type="radio" name="oc-cap" checked={capacity === 'company_secretary'}
          onChange={() => setCapacity('company_secretary')} /> Company Secretary</label>
      </fieldset>

      <div className="f-group">
        <label className="f-label" htmlFor="oc-app-date">Date of appointment <span className="f-req">*</span></label>
        <input id="oc-app-date" type="date" className="f-input" value={date}
               onChange={e => setDate(e.target.value)} />
      </div>

      {natural && (
        <div className="f-group">
          <label className="check-row">
            <input type="checkbox" checked={sameAddress} onChange={e => setSameAddress(e.target.checked)} />
            Correspondence address is the same as the residential address
          </label>
          {!sameAddress && (
            <div className="form-grid" style={{ marginTop: 8 }} data-testid="corr-address">
              {[['line1', 'Flat / Floor / Block'], ['line2', 'Building'], ['line3', 'Street / Estate'],
                ['city', 'District / City'], ['country', 'Country / Region']].map(([key, lbl]) => (
                <div className="f-group" key={key}>
                  <label className="f-label" htmlFor={`oc-corr-${key}`}>{lbl}</label>
                  <input id={`oc-corr-${key}`} className="f-input" value={address[key] || ''}
                         onChange={e => setAddress(a => ({ ...a, [key]: e.target.value }))} />
                </div>
              ))}
              <div className="f-hint">This address is printed on the public record.</div>
            </div>
          )}
        </div>
      )}

      {naturalSecretary && (
        <label className="check-row">
          <input type="checkbox" checked={section5} onChange={e => setSection5(e.target.checked)} />
          This person ordinarily resides in Hong Kong (Section 5)
        </label>
      )}

      {corporateDirector && (
        <>
          <PartyPicker kind="person" selected={signer} onSelect={setSigner} label="Consent signed by" />
          <div className="f-group">
            <label className="f-label" htmlFor="oc-signer-cap">Their capacity in the body corporate</label>
            <select id="oc-signer-cap" className="f-select" value={signerCapacity}
                    onChange={e => setSignerCapacity(e.target.value)}>
              {CONSENT_CAPACITIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        </>
      )}

      {error && <div className="alert al-danger" role="alert"><div className="al-body">{error}</div></div>}
    </Drawer>
  )
}
