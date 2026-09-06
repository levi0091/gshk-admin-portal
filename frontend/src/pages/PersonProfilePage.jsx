import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate, formatDateTime } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'
import UploadDocumentModal from '../components/UploadDocumentModal.jsx'
import IdentityDocumentModal from '../components/IdentityDocumentModal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import {
  DocumentSection, SectionDocuments, DocumentHistory, RemoveDocumentBody,
} from '../components/DocumentSections.jsx'
import FormField, { displayValue } from '../components/FormField.jsx'
import AddressBlock from '../components/AddressBlock.jsx'
import { EMPTY_ADDRESS, addressPayload, addressChanged } from '../lib/address.js'
import { useLookups } from '../lib/lookups.js'
import { useFormContract, fieldWarning } from '../lib/formContract.js'
import FieldWarning, { WarningCount } from '../components/FieldWarning.jsx'
import { idNumberProblem } from '../lib/hkid.js'
import {
  useDocumentSections, groupBySection, fieldsForStoredDocument, identityRules,
} from '../lib/documentSections.js'
import { useAuth } from '../context/AuthContext.jsx'
import { ReadOnlyNote } from '../components/RequirePermission.jsx'
import { personProfileCaps } from '../lib/screenCapabilities.js'

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
  // A TCSP licence held by an INDIVIDUAL (migration 038). The Company Secretary
  // tile on every company profile prints "TCSP Licence No.", and it could only
  // ever read the number off a corporate party -- so a secretary who is a
  // licensed person rendered an em dash and there was no field anywhere in the
  // portal that would fill it. The AMLO licenses individuals as trust or company
  // service providers exactly as it licenses bodies corporate.
  { key: 'tcsp_licence_no', label: 'TCSP Licence No.' },
  { key: 'tcsp_exemption_reason', label: 'TCSP Exemption Reason' },
]

// What an identity document holds is now decided by its TYPE, and served from
// `/documents/sections` rather than fixed here (see lib/documentSections.js).
// CR has no country box beside <hkid> and a Hong Kong identity card does not
// expire, so an HKID card that offered Issuing Country, Issue Date and Expiry
// Date was inviting three answers CR has nowhere to put.
//
// Place of Issue stays off the screen (B15 / D3) — CR asks for the issuing
// COUNTRY, never the city — and Renewal Reminder has now joined it (Levi,
// 2026-09-04: nobody asked for it). Both COLUMNS are retained.

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

const ID_TYPE_LABEL = {
  hkid: 'Hong Kong Identity Card',
  passport: 'Passport',
  china_id: 'Mainland China Identity Card',
  other: 'Other Identity Document',
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
 *
 * `isPrimary` is the EFFECTIVE primary, not the column: see the page body.
 */
function IdentityDocument({
  doc, identityFields, lookups, busy, isPrimary, canChoosePrimary,
  onSave, onMakePrimary, onRemove,
  // An identity RECORD is written through `persons:write` — it is part of the
  // person, not an upload. Its SCAN is a document, so downloading it asks
  // `documents:read` instead. Two facts, two permissions.
  canWrite = true, canDownloadScan = true,
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({})

  // Which fields this TYPE carries — an HKID takes a number and nothing else.
  // Read, never assumed: a stored value outside the type's fields is shown too,
  // so a Viewpoint HKID that came with an issuing country does not lose it.
  const shown = fieldsForStoredDocument(identityFields, doc)
  const required = identityRules(identityFields, doc.id_type).required || []

  const start = () => {
    setDraft(Object.fromEntries(shown.map(f => [f.key, doc[f.key] ?? ''])))
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
        {ID_TYPE_LABEL[doc.id_type] || (doc.id_type || '').toUpperCase()}
        {isPrimary && <span className="pri-pill">PRIMARY</span>}
        <span className="id-doc-actions">
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
            <>
              {/* Only where there is a choice to make. One document is the
                  primary one by definition, and a button that cannot change
                  anything is noise. */}
              {canChoosePrimary && canWrite && (
                <button className="btn-edit" onClick={onMakePrimary}
                        disabled={busy}>
                  Make primary
                </button>
              )}
              {doc.scan_document_id && canDownloadScan && (
                <button className="btn-edit"
                        onClick={() => downloadDocument(doc.scan_document_id)}>
                  Download scan
                </button>
              )}
              {canWrite && (
                <>
                  <button className="btn-edit" onClick={start}>Edit</button>
                  <button className="btn-edit btn-edit-danger" onClick={onRemove}
                          disabled={busy}>
                    Remove
                  </button>
                </>
              )}
            </>
          )}
        </span>
      </div>

      {editing ? (
        <div className="form-grid">
          {shown.map(f => (
            <FormField
              key={f.key}
              field={{ ...f, required: required.includes(f.key) }}
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
          {shown.map(f => (
            <Kv key={f.key} label={f.label}
                warning={f.key === 'id_number' && problem
                  ? { kind: 'invalid', message: problem } : null}>
              {f.type === 'date'
                ? formatDate(doc[f.key])
                : displayValue(f, doc[f.key], lookups)}
            </Kv>
          ))}
        </div>
      )}
    </div>
  )
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
  const {
    sections, identity_fields: identityFields,
    ready: sectionsReady, error: sectionsError,
  } = useDocumentSections('person')
  const [busy, setBusy] = useState(false)
  // The section whose upload dialog is open, or null. One piece of state
  // rather than one flag per section — a second dialog can never open behind
  // the first.
  const [uploadInto, setUploadInto] = useState(null)
  const { hasPermission } = useAuth()
  // `persons:read` opened this page. The person's own fields and their
  // identity RECORDS are `persons:write`; uploaded files are the separate
  // `documents` module, which a role can hold independently. Which control
  // needs which is declared in `lib/screenCapabilities.js` and enumerated by
  // the permission matrix test; the API enforces each on its own.
  const caps = personProfileCaps(hasPermission)
  const canWrite = caps.editPerson
  const canUploadDoc = caps.uploadDocument
  const canRemoveDoc = caps.removeDocument
  const canDownloadDoc = caps.downloadDocument

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

  // What the Remove dialog is about, or null. One piece of state for both kinds
  // of removal — an identity record and an uploaded file are removed
  // differently, and `kind` is what the confirm text and the request key off.
  const [removing, setRemoving] = useState(null)

  async function confirmRemove() {
    setBusy(true)
    try {
      await (removing.kind === 'identity'
        ? api.del(`/persons/${personId}/identity-documents/${removing.doc.id}`)
        : api.del(`/documents/${removing.doc.id}`))
      setRemoving(null)
      load()
    } catch (err) {
      setRemoving(null)
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

  // Uploads filed under the section their type belongs to (migration 036).
  // Removed ones are dropped here and kept in Document History, which is what a
  // soft delete is for.
  const live = (person.documents || []).filter(d => d.status !== 'deleted')
  const bySection = groupBySection(live, sections)
  const sectionLabels = Object.fromEntries(sections.map(s => [s.key, s.label]))

  // WHICH DOCUMENT THE SYSTEM ACTUALLY QUOTES. `person_registry` and
  // `audit_subject.primary_id_number` both order on `is_primary DESC,
  // created_at ASC`, so a person with no primary flagged at all — 483 of DEV's
  // HKID rows are in that state — is still quoted by their oldest document.
  // Marking that one PRIMARY is the truth; marking none would be a screen
  // disagreeing with the registry beside it.
  const primaryDoc = idDocs.find(d => d.is_primary)
    || [...idDocs].sort((a, b) =>
      String(a.created_at || '').localeCompare(String(b.created_at || '')))[0]

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
        {/* No page-level Upload button. It offered every document type at once
            from a place that named no section, which is how a passport got
            filed as an "Identity Document Scan". Each section carries its own. */}
      </div>

      {uploadInto?.is_identity && (
        <IdentityDocumentModal
          personId={personId}
          personName={person.full_name}
          types={uploadInto.types}
          identityFields={identityFields}
          existing={idDocs}
          lookups={lookups}
          onClose={() => setUploadInto(null)}
          onSaved={() => { setUploadInto(null); load() }}
        />
      )}

      {/* The two removals are not the same act and the dialog says which one
          this is. A file is soft-deleted and stays in the history; an identity
          record is deleted outright, because `nar1_mapper` reads that table and
          would go on FILING a number the operator had removed. */}
      {removing?.kind === 'identity' && (
        <ConfirmDialog
          title="Remove identity document"
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={confirmRemove}
        >
          <p>
            Removing the{' '}
            <b>{ID_TYPE_LABEL[removing.doc.id_type] || removing.doc.id_type}</b>{' '}
            <b>{removing.doc.id_number}</b> from {person.full_name}.
          </p>
          <p className="confirm-note">
            The number is deleted — it is recorded in the audit trail and nowhere
            else. {removing.doc.scan_document_id
              ? 'The scan is kept, and stays in Document History.'
              : 'There is no scan attached.'}
            {' '}NAR1 and NNC1 carry an HKID or passport number for every
            individual, so a person left holding neither blocks their return.
          </p>
        </ConfirmDialog>
      )}

      {removing?.kind === 'document' && (
        <ConfirmDialog
          title="Remove document"
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={confirmRemove}
        >
          <RemoveDocumentBody doc={removing.doc} />
        </ConfirmDialog>
      )}

      {uploadInto && !uploadInto.is_identity && (
        <UploadDocumentModal
          ownerKind="person"
          ownerId={personId}
          ownerName={person.full_name}
          category={uploadInto.key}
          sectionLabel={uploadInto.label}
          existingTypes={(bySection[uploadInto.key] || []).map(d => d.document_type_code)}
          onClose={() => setUploadInto(null)}
          onUploaded={() => { setUploadInto(null); load() }}
        />
      )}

      {!canWrite && (
        <ReadOnlyNote module="persons" what="this person's details and identity documents" />
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
              ) : canWrite && (
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

          {/* "Unavailable" is not "none". If the section catalogue could not be
              loaded, say so — rendering an empty Identity Documents card would
              tell the operator this director has no passport on file. */}
          {!sectionsReady && (
            <div className="card mb-16">
              <div className="empty-state" style={{ padding: '16px 0' }}>Loading documents…</div>
            </div>
          )}
          {sectionsReady && sectionsError && (
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Documents</div>
                  <div className="card-sub">Sections could not be loaded</div>
                </div>
              </div>
              <div className="reveal-note" style={{ color: '#B91C1C', background: '#FEE2E2' }}>
                {sectionsError} — this person’s identity documents are not shown
                below because the section list is unavailable, not because there
                are none. Reload the page.
              </div>
            </div>
          )}

          {/* One card per section, present whether or not it holds anything. */}
          {sections.map(section => section.is_identity ? (
            <DocumentSection key={section.key} section={section}
                             count={idDocs.length}
                             onAdd={() => setUploadInto(section)}
                             /* An identity document is created through
                                POST /persons/{id}/identity-documents, which is
                                gated on `persons:write` — NOT on `documents`,
                                even though it can carry a scan. */
                             canAdd={canWrite}>
              {idDocs.length === 0 ? (
                <div className="empty-state" style={{ padding: '16px 0' }}>
                  No identity documents on file. CR files every director by their
                  HKID or passport number — a person holding neither blocks the return.
                </div>
              ) : idDocs.map(d => (
                <IdentityDocument
                  key={d.id}
                  doc={d}
                  identityFields={identityFields}
                  lookups={lookups}
                  busy={busy}
                  isPrimary={d.id === primaryDoc?.id}
                  canChoosePrimary={idDocs.length > 1 && d.id !== primaryDoc?.id}
                  canWrite={canWrite}
                  canDownloadScan={canDownloadDoc}
                  onSave={changed => saveIdentityDocument(d.id, changed)}
                  onMakePrimary={() => saveIdentityDocument(d.id, { is_primary: true })}
                  onRemove={() => setRemoving({ kind: 'identity', doc: d })}
                />
              ))}
            </DocumentSection>
          ) : (
            <DocumentSection key={section.key} section={section}
                             count={(bySection[section.key] || []).length}
                             onAdd={() => setUploadInto(section)}
                             canAdd={canUploadDoc}>
              {(bySection[section.key] || []).length === 0 ? (
                <div className="empty-state" style={{ padding: '16px 0' }}>
                  Nothing uploaded yet.
                </div>
              ) : (
                <SectionDocuments
                  documents={bySection[section.key]}
                  busy={busy}
                  onRemove={doc => setRemoving({ kind: 'document', doc })}
                  canDownload={canDownloadDoc}
                  canRemove={canRemoveDoc}
                />
              )}
            </DocumentSection>
          ))}

          {/* Document History */}
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">Document History</div>
                <div className="card-sub">
                  Every upload, by section and type · newest version is current, older versions preserved
                </div>
              </div>
            </div>
            <DocumentHistory documents={person.documents} sectionLabels={sectionLabels}
                             canDownload={canDownloadDoc} />
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
