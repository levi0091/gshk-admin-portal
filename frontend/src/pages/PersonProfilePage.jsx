import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'
import UploadDocumentModal from '../components/UploadDocumentModal.jsx'

const EDITABLE = [
  { key: 'full_name', label: 'Full Name', full: true },
  { key: 'given_names', label: 'Given Names' },
  { key: 'surname', label: 'Surname' },
  { key: 'full_name_zh', label: 'Chinese Name' },
  { key: 'former_name', label: 'Former Name' },
  { key: 'date_of_birth', label: 'Date of Birth', type: 'date' },
  { key: 'gender', label: 'Gender' },
  { key: 'nationality', label: 'Nationality' },
  { key: 'nationality_origin', label: 'Nationality Origin' },
  { key: 'place_of_birth', label: 'Place of Birth' },
  { key: 'marital_status', label: 'Marital Status' },
  { key: 'occupation', label: 'Occupation' },
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
]

const RELATION_LABEL = {
  officer: 'Director', shareholder: 'Shareholder', beneficial_owner: 'Beneficial Owner',
}

function Kv({ label, children }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">{children || <span className="td-muted">—</span>}</span>
    </div>
  )
}

function addressText(a) {
  if (!a) return null
  return [a.line1, a.line2, a.line3, a.city, a.country].filter(Boolean).join(', ') || null
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

  function startEdit() {
    setDraft(Object.fromEntries(EDITABLE.map(f => [f.key, person[f.key] ?? ''])))
    setEditing(true)
  }

  async function saveEdit() {
    setBusy(true)
    const changed = Object.fromEntries(
      Object.entries(draft).filter(([k, v]) => (person[k] ?? '') !== v && v !== '')
    )
    try {
      if (Object.keys(changed).length) await api.patch(`/persons/${personId}`, changed)
      setEditing(false)
      load()
    } catch (err) {
      setError(err.message)
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
            <span className="bc-link" onClick={() => navigate('/persons')}>Persons Registry</span>
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
                <div className="card-title">Personal Information</div>
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
                  <div className={`f-group${f.full ? ' full' : ''}`} key={f.key}>
                    <label className="f-label" htmlFor={f.key}>{f.label}</label>
                    <input id={f.key} className="f-input" type={f.type || 'text'}
                           value={draft[f.key] ?? ''}
                           onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="kv-list">
                {EDITABLE.map(f => (
                  <Kv key={f.key} label={f.label}>
                    {f.type === 'date' ? formatDate(person[f.key]) : person[f.key]}
                  </Kv>
                ))}
                <Kv label="Residential Address">{addressText(person.residential_address)}</Kv>
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
              <div className="id-doc-group" key={d.id}>
                <div className="id-doc-head">
                  {(d.id_type || '').toUpperCase()}
                  {d.is_primary && <span className="pri-pill">PRIMARY</span>}
                </div>
                <div className="kv-list">
                  <Kv label="ID Number">{d.id_number}</Kv>
                  <Kv label="Issuing Country/Region">{d.issuing_country}</Kv>
                  <Kv label="Place of Issue">{d.place_of_issue}</Kv>
                  <Kv label="Issue Date">{formatDate(d.issue_date)}</Kv>
                  <Kv label="Expiry Date">{formatDate(d.expiry_date)}</Kv>
                  <Kv label="Renewal Reminder">{formatDate(d.reminder_date)}</Kv>
                </div>
              </div>
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
