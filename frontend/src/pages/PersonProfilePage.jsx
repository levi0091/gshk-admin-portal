import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'
import UploadDocumentModal from '../components/UploadDocumentModal.jsx'
import FormField, { displayValue } from '../components/FormField.jsx'
import AddressBlock from '../components/AddressBlock.jsx'
import { EMPTY_ADDRESS, addressPayload, addressChanged } from '../lib/address.js'
import { useLookups } from '../lib/lookups.js'
import { useFormContract, fieldWarning } from '../lib/formContract.js'
import FieldWarning, { WarningCount } from '../components/FieldWarning.jsx'
import { idNumberProblem } from '../lib/hkid.js'

// `lookup` names the controlled vocabulary a field draws from (migration 013,
// lifted from Viewpoint). Without it these were free-text, which is how the same
// nationality got in under several spellings.
//
// THE LABELS ARE NAR1'S, NOT VIEWPOINT'S (Brian's B12/B13, PRD §10.5). "Given
// Names" and CR's "Other Names" are the same field, and an operator reading
// the form and this screen side by side had no way to know that.
//
// MARITAL STATUS IS DELIBERATELY ABSENT (D3). The column is kept — no
// Viewpoint history is destroyed — but neither NAR1 nor NNC1 asks for it, so
// the screen does not either.
const EDITABLE = [
  { key: 'full_name', label: 'Full Name', full: true },
  { key: 'surname', label: 'Name in English (Surname)' },
  { key: 'given_names', label: 'Name in English (Other Names)' },
  { key: 'full_name_zh', label: 'Name in Chinese' },
  // A previous name and an alias are DIFFERENT facts. The ETL used to write
  // `former_name = FormerName or Aliases`, which filed a person's current
  // alias as a name they had abandoned.
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
  { key: 'email', label: 'Email Address' },
  { key: 'phone', label: 'Phone' },
]

// What an identity document holds, minus Place of Issue (B15 / D3): CR asks
// for the issuing COUNTRY, never the city, and the column is retained.
const ID_EDITABLE = [
  { key: 'id_number', label: 'ID Number' },
  { key: 'issuing_country', label: 'Issuing Country/Region', lookup: 'cr_country' },
  { key: 'issue_date', label: 'Issue Date', type: 'date' },
  { key: 'expiry_date', label: 'Expiry Date', type: 'date' },
  { key: 'reminder_date', label: 'Renewal Reminder', type: 'date' },
]

const RELATION_LABEL = {
  officer: 'Director', shareholder: 'Shareholder', beneficial_owner: 'Beneficial Owner',
}

function Kv({ label, children, warning = null }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">
        {children || <span className="td-muted">—</span>}
        <FieldWarning warning={warning} />
      </span>
    </div>
  )
}

function addressText(a) {
  if (!a) return null
  return [a.line1, a.line2, a.line3, a.city, a.country].filter(Boolean).join(', ') || null
}

/**
 * One identity document, and the only place the HKID check digit can bite.
 *
 * Brian's B14 asked for the checksum; what made it possible was Block 4
 * adding `PATCH /persons/{id}/identity-documents/{doc}`. Before that this card
 * was read-only and a validator would have been decoration.
 *
 * GRANDFATHERING (D4). A bad stored value is SHOWN but never blocks: 31 real
 * rows would fail, 29 of them Mainland China IDs filed under `id_type =
 * 'hkid'`, and freezing those records would punish the people least able to
 * fix them. The check only refuses a number somebody is typing right now —
 * which is also what the API does, so the two agree.
 */
function IdentityDocument({ doc, lookups, busy, onSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({})

  const start = () => {
    setDraft(Object.fromEntries(ID_EDITABLE.map(f => [f.key, doc[f.key] ?? ''])))
    setEditing(true)
  }

  // The stored value when reading, the typed one when editing.
  const problem = idNumberProblem(
    doc.id_type, editing ? draft.id_number : doc.id_number)

  async function save() {
    const changed = Object.fromEntries(
      Object.entries(draft).filter(([k, v]) => (doc[k] ?? '') !== v))
    if (!Object.keys(changed).length) { setEditing(false); return }
    if (await onSave(changed)) setEditing(false)
  }

  return (
    <div className="id-doc-group">
      <div className="id-doc-head">
        {(doc.id_type || '').toUpperCase()}
        {doc.is_primary && <span className="pri-pill">PRIMARY</span>}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {editing ? (
            <>
              <button className="btn-edit" onClick={() => setEditing(false)} disabled={busy}>
                Cancel
              </button>
              <button className="btn btn-primary btn-sm" onClick={save}
                      disabled={busy || !!problem}>
                {busy ? 'Saving…' : 'Save'}
              </button>
            </>
          ) : (
            <button className="btn-edit" onClick={start}>Edit</button>
          )}
        </span>
      </div>

      {editing ? (
        <div className="form-grid">
          {ID_EDITABLE.map(f => (
            <FormField
              key={f.key}
              field={f}
              value={draft[f.key]}
              lookups={lookups}
              onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))}
            />
          ))}
          {problem && (
            <div className="f-group full">
              <FieldWarning warning={{ kind: 'invalid', message: problem }} />
            </div>
          )}
        </div>
      ) : (
        <div className="kv-list">
          <Kv label="ID Number"
              warning={problem ? { kind: 'invalid', message: problem } : null}>
            {doc.id_number}
          </Kv>
          <Kv label="Issuing Country/Region">{doc.issuing_country}</Kv>
          {/* Place of Issue removed from the screen (B15 / D3). The column is
              kept, so no Viewpoint history is destroyed and the decision is
              reversible. */}
          <Kv label="Issue Date">{formatDate(doc.issue_date)}</Kv>
          <Kv label="Expiry Date">{formatDate(doc.expiry_date)}</Kv>
          <Kv label="Renewal Reminder">{formatDate(doc.reminder_date)}</Kv>
        </div>
      )}
    </div>
  )
}

/** Document history: grouped by type, newest version current, older preserved. */
function DocumentHistory({ documents }) {
  if (!documents?.length) {
    return <div className="empty-state" style={{ padding: '16px 0' }}>No documents uploaded yet.</div>
  }
  return documents.map(doc => {
    const versions = [...(doc.document_versions || [])]
      .sort((a, b) => b.version_number - a.version_number)
    return (
      <div key={doc.id}>
        <div className="doc-hist-type">
          {doc.document_types?.label || doc.document_type_code}
          <span className="cnt">{versions.length} version{versions.length === 1 ? '' : 's'}</span>
        </div>
        {versions.map(v => {
          const isCurrent = v.version_number === doc.current_version
          return (
            <div className="doc-ver" key={v.id}>
              <span className="dv-l">
                <span className={`dv-tag ${isCurrent ? 'dv-cur' : 'dv-old'}`}>
                  {isCurrent ? 'CURRENT' : 'SUPERSEDED'}
                </span>
                <span>v{v.version_number} · {v.file_name}</span>
                <span className="dv-meta">{formatDate(v.created_at)}</span>
              </span>
              <button className="dv-dl" onClick={() => downloadDocument(doc.id)}>Download</button>
            </div>
          )
        })}
      </div>
    )
  })
}

export default function PersonProfilePage() {
  const { personId } = useParams()
  const navigate = useNavigate()
  const [person, setPerson] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({})
  const lookups = useLookups()
  const contract = useFormContract()
  const [busy, setBusy] = useState(false)
  const [showUpload, setShowUpload] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/persons/${personId}`)
      .then(setPerson)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [personId])

  useEffect(() => { load() }, [load])

  // A separate row from the person, so drafted and saved separately.
  const [addrDraft, setAddrDraft] = useState(null)

  function startEdit() {
    setDraft(Object.fromEntries(EDITABLE.map(f => [f.key, person[f.key] ?? ''])))
    setAddrDraft({ ...EMPTY_ADDRESS, ...(person.residential_address || {}) })
    setEditing(true)
  }

  async function saveEdit() {
    setBusy(true)
    const changed = Object.fromEntries(
      Object.entries(draft).filter(([k, v]) => (person[k] ?? '') !== v && v !== '')
    )
    try {
      if (Object.keys(changed).length) await api.patch(`/persons/${personId}`, changed)
      // Second, and separately: a rejected address (a line over CR's 60) must
      // not silently discard the field edits that already succeeded.
      if (addrDraft && addressChanged(addrDraft, person.residential_address)) {
        await api.put(`/persons/${personId}/residential-address`, addressPayload(addrDraft))
      }
      setEditing(false)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function saveIdentityDocument(documentId, changed) {
    setBusy(true)
    try {
      await api.patch(`/persons/${personId}/identity-documents/${documentId}`, changed)
      load()
      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="empty-state">Loading…</div>
  if (error) {
    return (
      <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
        Failed to load person: {error}
      </div>
    )
  }
  if (!person) return null

  const roles = person.role_rollup || []
  const idDocs = person.identity_documents || []
  const primary = idDocs.find(d => d.is_primary) || idDocs[0]

  // What CR would refuse, read off the same contract the API enforces (§5.3).
  const warnFor = (table, column, value) => fieldWarning(contract, table, column, value)
  const addressWarnings = Object.fromEntries(
    ['line1', 'line2', 'line3', 'city', 'country'].map(k =>
      [k, warnFor('addresses', k, person.residential_address?.[k])]))
  const personWarnings = [
    ...EDITABLE.map(f => warnFor('persons', f.key, person[f.key])),
    ...Object.values(addressWarnings),
  ].filter(Boolean)

  // Header pills: "Director ×2" — count how many companies per relation.
  const roleCounts = roles.reduce((acc, r) => {
    acc[r.relation] = (acc[r.relation] || 0) + 1
    return acc
  }, {})

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="breadcrumb">
            <span className="bc-link" onClick={() => navigate('/persons')}>Natural Person Registry</span>
            <span className="bc-sep">›</span>
            <span className="bc-cur">Person Profile</span>
          </div>
          <div className="profile-eyebrow">Person Profile</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div className="profile-name">{person.full_name}</div>
            {Object.entries(roleCounts).map(([rel, n]) => (
              <span key={rel} className={`role-tag ${rel === 'officer' ? 'role-dir' : rel === 'shareholder' ? 'role-shr' : 'role-bo'}`}>
                {RELATION_LABEL[rel] || rel} ×{n}
              </span>
            ))}
          </div>
          <div className="pg-sub">
            {[primary && `${(primary.id_type || '').toUpperCase()} ${primary.id_number}`,
              person.nationality,
              person.date_of_birth && `DOB ${formatDate(person.date_of_birth)}`]
              .filter(Boolean).join(' · ')}
          </div>
        </div>
        <div className="pg-actions">
          <button className="btn btn-outline" onClick={() => setShowUpload(true)}>Upload Document</button>
        </div>
      </div>

      {showUpload && (
        <UploadDocumentModal
          ownerKind="person"
          ownerId={personId}
          ownerName={person.full_name}
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); load() }}
        />
      )}

      <div className="detail-grid client-off">
        <div>
          {/* Personal Information */}
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">
                  Personal Information <WarningCount count={personWarnings.length} />
                </div>
                <div className="card-sub">Identity &amp; contact details held for this individual</div>
              </div>
              {editing ? (
                <div className="hdr-actions">
                  <button className="btn-edit" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
                  <button className="btn btn-primary btn-sm" onClick={saveEdit} disabled={busy}>
                    {busy ? 'Saving…' : 'Save'}
                  </button>
                </div>
              ) : (
                <button className="btn-edit" onClick={startEdit}>Edit</button>
              )}
            </div>

            {editing ? (
              <div className="form-grid">
                {EDITABLE.map(f => (
                  <FormField
                    key={f.key}
                    field={f}
                    value={draft[f.key]}
                    lookups={lookups}
                    onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))}
                  />
                ))}
                <div className="f-group full">
                  <div className="tile-sec-lbl">Residential Address</div>
                  <AddressBlock
                    value={addrDraft}
                    lookups={lookups}
                    warnings={Object.fromEntries(
                      ['line1', 'line2', 'line3', 'city', 'country'].map(k =>
                        [k, warnFor('addresses', k, addrDraft?.[k])]))}
                    onChange={(k, v) => setAddrDraft(a => ({ ...a, [k]: v }))}
                  />
                </div>
              </div>
            ) : (
              <div className="kv-list">
                {EDITABLE.map(f => (
                  <Kv key={f.key} label={f.label}
                      warning={warnFor('persons', f.key, person[f.key])}>
                    {f.type === 'date'
                      ? formatDate(person[f.key])
                      : displayValue(f, person[f.key], lookups)}
                  </Kv>
                ))}
                {/* The lines CR receives, not a joined string. */}
                <AddressBlock value={person.residential_address} readOnly
                              warnings={addressWarnings} />
              </div>
            )}
          </div>

          {/* Identity Documents */}
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">
                  Identity Documents <span className="count-pill">{idDocs.length}</span>
                </div>
                <div className="card-sub">Grouped by document type</div>
              </div>
            </div>
            {idDocs.length === 0 ? (
              <div className="empty-state" style={{ padding: '16px 0' }}>No identity documents on file.</div>
            ) : idDocs.map(d => (
              <IdentityDocument
                key={d.id}
                doc={d}
                lookups={lookups}
                busy={busy}
                onSave={changed => saveIdentityDocument(d.id, changed)}
              />
            ))}
          </div>

          {/* Document History */}
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">Document History</div>
                <div className="card-sub">
                  All uploads grouped by type · newest version is current, older versions preserved
                </div>
              </div>
            </div>
            <DocumentHistory documents={person.documents} />
          </div>

          {/* Appointments & Roles — read-only */}
          <div className="card">
            <div className="card-hdr">
              <div>
                <div className="card-title">
                  Appointments &amp; Roles <span className="count-pill">{roles.length}</span>
                </div>
                <div className="card-sub">Where this person holds a role</div>
              </div>
            </div>
            <div className="reveal-note" style={{ color: 'var(--indigo)', background: 'var(--indigo-10)' }}>
              Read-only here — roles are added &amp; edited on each company’s profile
            </div>
            {roles.length === 0 ? (
              <div className="empty-state" style={{ padding: '16px 0' }}>No appointments.</div>
            ) : roles.map((r, i) => (
              <div className="role-item" key={`${r.relation}-${r.entity_id}-${i}`}>
                <div>
                  <div className="role-item-main">
                    {RELATION_LABEL[r.relation] || r.relation} — {r.company_name || '—'}
                  </div>
                  <div className="role-item-sub">
                    {[r.role, r.appointed_date && `Appointed ${formatDate(r.appointed_date)}`,
                      r.is_current === false && 'Former'].filter(Boolean).join(' · ')}
                  </div>
                </div>
                <button className="role-open" onClick={() => navigate(`/companies/${r.entity_id}`)}>
                  Open →
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
