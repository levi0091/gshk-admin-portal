import { useState, useEffect } from 'react'
import { api } from '../lib/api.js'

/**
 * Link an EXISTING person or corporate party to a company — never creates a
 * duplicate party record. Exactly one of person_id / corporate_entity_id is
 * sent; the backend rejects both/neither with a 422.
 *
 * relation: 'officers' | 'shareholders' | 'beneficial-owners'
 */
export const RELATION_META = {
  officers: {
    title: 'Director / Officer',
    fields: [
      { key: 'role', label: 'Role', type: 'select',
        options: ['director', 'company_secretary', 'reserve_director', 'authorised_rep'] },
      { key: 'position', label: 'Position' },
      { key: 'appointed_date', label: 'Appointed', type: 'date' },
      { key: 'resigned_date', label: 'Resigned', type: 'date' },
      { key: 'resignation_reason', label: 'Resignation Reason' },
    ],
  },
  // entity_officers scoped to role='company_secretary' — role is fixed server-side,
  // so it isn't an editable field here.
  secretaries: {
    title: 'Company Secretary',
    fields: [
      { key: 'position', label: 'Position' },
      { key: 'appointed_date', label: 'Appointed', type: 'date' },
      { key: 'resigned_date', label: 'Resigned', type: 'date' },
      { key: 'resignation_reason', label: 'Resignation Reason' },
    ],
  },
  shareholders: {
    title: 'Shareholder',
    fields: [
      { key: 'share_class_id', label: 'Share Class ID', required: true },
      { key: 'shares_held', label: 'Shares Held', type: 'number' },
      { key: 'amount_paid', label: 'Amount Paid', type: 'number' },
    ],
  },
  'beneficial-owners': {
    title: 'Beneficial Owner',
    fields: [
      { key: 'owner_type', label: 'Owner Type' },
      { key: 'percent_interest', label: 'Interest %', type: 'number' },
      { key: 'percent_vote', label: 'Voting %', type: 'number' },
      { key: 'date_from', label: 'From', type: 'date' },
      { key: 'date_to', label: 'To', type: 'date' },
    ],
  },
}

export default function LinkPartyModal({ companyId, relation, link, onClose, onSaved }) {
  const meta = RELATION_META[relation]
  const isEdit = !!link

  const [partyKind, setPartyKind] = useState('person')
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [selected, setSelected] = useState(null)
  const [attrs, setAttrs] = useState(
    isEdit ? Object.fromEntries(meta.fields.map(f => [f.key, link[f.key] ?? ''])) : {}
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

  async function handleSave() {
    setError('')
    if (!isEdit && !selected) return setError('Select a party to link')

    const body = Object.fromEntries(
      Object.entries(attrs).filter(([, v]) => v !== '' && v != null)
    )
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
                       placeholder={partyKind === 'person' ? 'Search Persons Registry' : 'Search Company Registry'}
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
            {meta.fields.map(f => (
              <div className="f-group" key={f.key}>
                <label className="f-label" htmlFor={f.key}>
                  {f.label} {f.required && <span className="f-req">*</span>}
                </label>
                {f.type === 'select' ? (
                  <select id={f.key} className="f-select" value={attrs[f.key] ?? ''}
                          onChange={e => setAttrs(a => ({ ...a, [f.key]: e.target.value }))}>
                    <option value="">Select…</option>
                    {f.options.map(o => <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>)}
                  </select>
                ) : (
                  <input id={f.key} className="f-input" type={f.type || 'text'}
                         value={attrs[f.key] ?? ''}
                         onChange={e => setAttrs(a => ({ ...a, [f.key]: e.target.value }))} />
                )}
              </div>
            ))}
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
