import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'
import { useLookups, optionsFor } from '../lib/lookups.js'

/**
 * Link an EXISTING person or corporate party to a company — never creates a
 * duplicate party record. Exactly one of person_id / corporate_entity_id is
 * sent; the backend rejects both/neither with a 422.
 *
 * relation: 'officers' | 'secretaries' | 'shareholders' | 'beneficial-owners'
 *
 * A field descriptor is one of:
 *   {}                        a text box
 *   { type: 'date'|'number' } the matching input
 *   { options: [...] }        a fixed <select> of {value,label}
 *   { lookup: 'name' }        a <select> filled from /lookups
 *   { source: 'shareClasses' } a <select> of THIS company's classes of shares
 *   { type: 'boolean' }       a two-value <select> that sends a real boolean
 */

//: Whether a link is live or historical. Rendered as a dropdown rather than a
//: checkbox because the two answers need naming: "Former" is not "unticked".
//:
//: THIS IS HOW A SHARE TRANSFER IS RECORDED (Levi 2026-09-04). Setting the
//: outgoing holder to Former drops them from the return — `nar1_mapper`'s
//: `_schedule_1` skips a holding with `is_current` false — while keeping the
//: row, so the register still shows who held the shares and the audit trail
//: shows when that stopped. Remove is for a link that should never have
//: existed; it destroys the record of the holding along with the holding.
const CURRENT_FIELD = {
  key: 'is_current', label: 'Status', type: 'boolean',
  options: [{ value: 'true', label: 'Current' }, { value: 'false', label: 'Former' }],
}

export const RELATION_META = {
  officers: {
    title: 'Director / Officer',
    fields: [
      // `company_secretary` is NOT offered here even though the enum has it.
      // The Directors tile reads `entity_officers` with `role != company_secretary`
      // and the Company Secretary tile reads the complement, so choosing it
      // made the row vanish from the tile you were editing and reappear in
      // another one further down the page — which reads as a save that deleted
      // the record. A secretary is added from the Company Secretary tile.
      { key: 'role', label: 'Role', options: [
        'director', 'reserve_director', 'authorised_rep',
      ].map(v => ({ value: v, label: v.replace(/_/g, ' ') })) },
      { key: 'position', label: 'Position' },
      { key: 'appointed_date', label: 'Appointed', type: 'date' },
      { key: 'resigned_date', label: 'Resigned', type: 'date' },
      { key: 'resignation_reason', label: 'Resignation Reason' },
      CURRENT_FIELD,
    ],
  },
  // entity_officers scoped to role='company_secretary' — role is fixed server-side,
  // so it isn't an editable field here. Everything else matches the officer
  // form: the two tiles write the same table and had drifted apart, so a
  // secretary could be given a resignation reason by the API and by no screen.
  secretaries: {
    title: 'Company Secretary',
    fields: [
      { key: 'position', label: 'Position' },
      { key: 'appointed_date', label: 'Appointed', type: 'date' },
      { key: 'resigned_date', label: 'Resigned', type: 'date' },
      { key: 'resignation_reason', label: 'Resignation Reason' },
      CURRENT_FIELD,
    ],
  },
  shareholders: {
    title: 'Shareholder',
    fields: [
      // WAS A FREE-TEXT BOX LABELLED "Share Class ID". It sent whatever was
      // typed at a `uuid NOT NULL REFERENCES share_classes(id)` column, so "1"
      // produced a database error the browser could only report as "Could not
      // reach the server". Nothing about that message named the field, and the
      // operator could not have guessed that the box wanted a uuid.
      { key: 'share_class_id', label: 'Class of Shares', required: true,
        source: 'shareClasses',
        empty: 'This company has no share capital recorded yet — add a class '
             + 'under Share Capital first.' },
      { key: 'shares_held', label: 'Shares Held', type: 'number' },
      { key: 'amount_paid', label: 'Amount Paid', type: 'number' },
      CURRENT_FIELD,
    ],
  },
  'beneficial-owners': {
    title: 'Beneficial Owner',
    fields: [
      { key: 'owner_type', label: 'Owner Type', lookup: 'bo_owner_type' },
      // Companies Ordinance s.653D, replacing Interest % and Voting %
      // (migration 038). Those two could not express the second condition at
      // all: a controller with no shares and a veto is significant, and two
      // numeric columns render that as 0/0 — which reads as "not a
      // controller". The columns are kept and still writable by the API;
      // neither CR form has ever read either of them.
      { key: 'nature_of_control', label: 'Nature of Control over the Company',
        lookup: 'bo_nature_of_control', full: true },
      { key: 'date_from', label: 'From', type: 'date' },
      { key: 'date_to', label: 'To', type: 'date' },
      CURRENT_FIELD,
    ],
  },
}

/** The stored value as the form holds it — everything is a string in an input. */
function toFormValue(v) {
  if (v === true) return 'true'
  if (v === false) return 'false'
  return v ?? ''
}

export default function LinkPartyModal({ companyId, relation, link, shareClasses,
                                         onClose, onSaved }) {
  const meta = RELATION_META[relation]
  const isEdit = !!link
  const lookups = useLookups()

  const [partyKind, setPartyKind] = useState('person')
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [attrs, setAttrs] = useState(
    isEdit ? Object.fromEntries(meta.fields.map(f => [f.key, toFormValue(link[f.key])])) : {}
  )
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Party search — only when linking. On edit the party is immutable
  // (unlink + relink to re-point), so we don't offer a picker.
  useEffect(() => {
    if (isEdit || !search) { setResults([]); return }
    const t = setTimeout(() => {
      const path = partyKind === 'person'
        ? `/persons?search=${encodeURIComponent(search)}&page_size=10`
        : `/companies?search=${encodeURIComponent(search)}&flag=corporate_party&page_size=10`
      api.get(path)
        .then(d => setResults(partyKind === 'person' ? d.persons : d.companies))
        .catch(err => setError(err.message))
    }, 300)
    return () => clearTimeout(t)
  }, [search, partyKind, isEdit])

  /** The <option> list for one descriptor, whatever it draws from. */
  function optionsOf(f) {
    if (f.options) return f.options
    if (f.source === 'shareClasses') {
      return (shareClasses || []).map(c => ({
        value: c.id,
        // The currency is part of the identity of a class, not decoration:
        // a company can hold an HKD and a USD Ordinary, and CR's section 11
        // states both. Showing the name alone makes them indistinguishable.
        label: [c.class_name, c.currency].filter(Boolean).join(' · '),
      }))
    }
    if (f.lookup) {
      return optionsFor(lookups?.[f.lookup], attrs[f.key] || null)
        .map(o => ({ value: o.code, label: o.label }))
    }
    return null
  }

  async function handleSave() {
    setError('')
    if (!isEdit && !selected) return setError('Select a party to link')
    const missing = meta.fields.find(f => f.required && !attrs[f.key])
    if (missing) return setError(`${missing.label} is required`)

    const body = {}
    for (const f of meta.fields) {
      const raw = attrs[f.key]
      if (raw === '' || raw == null) continue
      // A boolean has to arrive as one: `is_current: "false"` is a non-empty
      // string, which Python reads as true and the register then shows a
      // transferred-out member as still holding the shares.
      body[f.key] = f.type === 'boolean' ? raw === 'true' : raw
    }
    setSaving(true)
    try {
      if (isEdit) {
        await api.patch(`/companies/${companyId}/${relation}/${link.id}`, body)
      } else {
        // exactly one of person_id / corporate_entity_id
        if (partyKind === 'person') body.person_id = selected.id
        else body.corporate_entity_id = selected.id
        await api.post(`/companies/${companyId}/${relation}`, body)
      }
      onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label={isEdit ? `Edit ${meta.title}` : `Add ${meta.title}`}>
        <div className="modal-hdr">
          <div className="modal-title">{isEdit ? `Edit ${meta.title}` : `Add ${meta.title}`}</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          {error && (
            <div style={{ marginBottom: 14, padding: 10, background: '#FEE2E2', borderRadius: 6, color: '#B91C1C', fontSize: 12 }}>
              {error}
            </div>
          )}

          {isEdit ? (
            <div className="upload-owner-line">
              Editing <b>{link.persons?.full_name || link.corporate_entity?.company_name || link.corporate_name}</b>
              {' '}— to change the party itself, remove this link and add a new one.
            </div>
          ) : (
            <>
              <div className="filter-tabs" role="tablist" style={{ marginBottom: 12 }}>
                <button role="tab" aria-selected={partyKind === 'person'}
                        className={`filter-tab ${partyKind === 'person' ? 'active' : ''}`}
                        onClick={() => { setPartyKind('person'); setSelected(null); setResults([]) }}>
                  Person
                </button>
                <button role="tab" aria-selected={partyKind === 'corporate'}
                        className={`filter-tab ${partyKind === 'corporate' ? 'active' : ''}`}
                        onClick={() => { setPartyKind('corporate'); setSelected(null); setResults([]) }}>
                  Corporate Party
                </button>
              </div>

              <div className="f-group" style={{ marginBottom: 12 }}>
                <label className="f-label" htmlFor="party_search">
                  Find {partyKind === 'person' ? 'person' : 'corporate party'} <span className="f-req">*</span>
                </label>
                <input id="party_search" className="f-input" type="text"
                       aria-label="Search parties"
                       placeholder={partyKind === 'person' ? 'Search Natural Person Registry' : 'Search Body Corporate Registry'}
                       value={selected ? (selected.full_name || selected.company_name) : search}
                       onChange={e => { setSelected(null); setSearch(e.target.value) }} />
              </div>

              {!selected && results.length > 0 && (
                <div className="tbl-wrap" style={{ marginBottom: 14, maxHeight: 180, overflowY: 'auto' }}>
                  {results.map(r => (
                    <div key={r.id} className="doc-item" style={{ padding: '8px 12px', cursor: 'pointer' }}
                         onClick={() => { setSelected(r); setResults([]) }}>
                      <span className="doc-name">{r.full_name || r.company_name}</span>
                      <span className="td-muted">{r.primary_id_number || r.br_number || ''}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="form-grid">
            {meta.fields.map(f => {
              const options = optionsOf(f)
              const noOptions = options && options.length === 0 && f.empty
              return (
                <div className={`f-group${f.full ? ' full' : ''}`} key={f.key}>
                  <label className="f-label" htmlFor={f.key}>
                    {f.label} {f.required && <span className="f-req">*</span>}
                  </label>
                  {options ? (
                    <select id={f.key} className="f-select" value={attrs[f.key] ?? ''}
                            disabled={options.length === 0}
                            onChange={e => setAttrs(a => ({ ...a, [f.key]: e.target.value }))}>
                      <option value="">Select…</option>
                      {options.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  ) : (
                    <input id={f.key} className="f-input" type={f.type || 'text'}
                           value={attrs[f.key] ?? ''}
                           onChange={e => setAttrs(a => ({ ...a, [f.key]: e.target.value }))} />
                  )}
                  {/* An empty dropdown with no explanation is the same dead end
                      the free-text box was — it just fails earlier. */}
                  {noOptions && <span className="f-hint">{f.empty}</span>}
                </div>
              )
            })}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Link Party'}
          </button>
        </div>
      </div>
    </div>
  )
}
