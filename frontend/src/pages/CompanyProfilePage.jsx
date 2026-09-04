import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { liveCaseWarning } from '../lib/liveCase.js'
import { formatDate } from '../lib/format.js'
import StatusBadge from '../components/StatusBadge.jsx'
import UploadDocumentModal from '../components/UploadDocumentModal.jsx'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import LinkPartyModal from '../components/LinkPartyModal.jsx'
import ShareClassModal, { SHARE_CLASS_FIELDS } from '../components/ShareClassModal.jsx'
import { useDocumentSections, groupBySection } from '../lib/documentSections.js'
import {
  DocumentSection, SectionDocuments, DocumentHistory, RemoveDocumentBody,
} from '../components/DocumentSections.jsx'
import FormField, { displayValue } from '../components/FormField.jsx'
import AddressBlock from '../components/AddressBlock.jsx'
import { EMPTY_ADDRESS, addressPayload, addressChanged } from '../lib/address.js'
import { useLookups } from '../lib/lookups.js'
import { useFormContract, fieldWarning } from '../lib/formContract.js'
import FieldWarning, { WarningCount } from '../components/FieldWarning.jsx'
import NewCaseModal from '../components/NewCaseModal.jsx'
import { useAuth } from '../context/AuthContext.jsx'

const EDITABLE = [
  { key: 'company_name', label: 'Company Name' },
  { key: 'company_name_zh', label: 'Chinese Name' },
  { key: 'br_number', label: 'BRN' },
  { key: 'cr_number', label: 'CR No.' },
  // CR takes P / N / G on `coyType` and nothing else. A legacy free-text value
  // is still offered back by `optionsFor`, flagged — dropping it would blank
  // the column on the next save.
  { key: 'company_type', label: 'Company Type', lookup: 'cr_company_type' },
  // Brian's B5. The description is NOT here on purpose: CR derives `natureDesc`
  // from `nature` after web-form validation, so the operator picks a code and
  // the description follows. A typed description could disagree with the code
  // it is supposed to describe.
  { key: 'business_nature_code', label: 'Business Nature Code',
    lookup: 'cr_business_nature' },
  // Brian's B6.
  { key: 'mortgages_total', label: 'Mortgages and Charges' },
  { key: 'incorporation_place', label: 'Country of Incorporation', lookup: 'cr_country' },
  { key: 'incorporation_date', label: 'Incorporation Date', type: 'date' },
  { key: 'case_notes', label: 'Case Notes', full: true },
]

//: The company's telephone number. NOT in EDITABLE because it is not a column
//: on `entities` — it is a `contacts` row, so it saves through its own
//: endpoint, exactly as the registered address does.
//:
//: It had no editor at all until now: `company_phone` was accepted at creation,
//: written to `contacts` and printed here, and then unreachable. CR's NAR1 maps
//: `telNo` straight off it, so a number mistyped on the New Company form went
//: onto a statutory filing with no way to correct it.
const PHONE_FIELD = { key: 'company_phone', label: 'Company Phone', type: 'tel' }

/** The preferred phone contact, or none. */
function companyPhone(company) {
  const rows = (company?.contacts || []).filter(c => c.contact_type === 'phone')
  return (rows.find(c => c.is_preferred) || rows[0])?.contact_value || ''
}

//: What the Corporate Party Details tile edits — the fields that only mean
//: anything when this company acts as somebody else's officer or member.
//: Company Type is shown there too but is edited above, in Company Information;
//: one field with two editors is one field that can be saved twice.
const CORP_EDITABLE = [
  { key: 'tcsp_licence_no', label: 'TCSP Licence No.' },
  { key: 'tcsp_exemption_reason', label: 'TCSP Exemption Reason' },
]

function Kv({ label, children, warning = null }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">
        {children ?? <span className="td-muted">—</span>}
        <FieldWarning warning={warning} />
      </span>
    </div>
  )
}

/** A money or share figure as CR prints it, or an em dash. */
function figure(value) {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString() : String(value)
}

function addressText(a) {
  if (!a) return null
  return [a.line1, a.line2, a.line3, a.city, a.country].filter(Boolean).join(', ') || null
}


/** A linked party is either a person or a corporate entity — never both. */
function partyName(row) {
  return row.persons?.full_name
    || row.corporate_entity?.company_name
    || row.corporate_name
    || '—'
}

function FlagToggle({ on, label, sub, onToggle, busy }) {
  return (
    <button
      type="button"
      className={`flag-toggle${on ? '' : ' is-off'}`}
      onClick={onToggle}
      disabled={busy}
      role="switch"
      aria-checked={on}
      aria-label={label}
    >
      <span className={`flag-switch ${on ? 'on' : 'off'}`}><span className="flag-knob" /></span>
      <span className="flag-tog-txt">
        <span className="flag-tog-lbl">{label}</span>
        <span className="flag-tog-sub">{sub}</span>
      </span>
    </button>
  )
}

// `DocumentList` was here: one flat list of every company document with a
// Download and nothing else. It is now the shared `SectionDocuments` under one
// card per category, with Remove beside Download — the same shape as the person
// profile, because a company's documents are filed exactly the same way
// (Levi 2026-09-04: "this is the same for the body corporation upload document
// features").
//
// LEVI'S ITEM 13 ON 2026-09-04 ASKS FOR THE OPPOSITE, and it is not resolved
// here: "no need to have multiple sections for different document types. just
// split based on history and current 2 sections so it is clear." Collapsing
// these cards would cost the per-section upload picker (which is what stops a
// document being filed under the wrong type) and the Remove button, both of
// which landed the same day — so the layout is left as it is and the question
// is Levi's to settle. What item 13 also asked for and nobody had done, the
// document TYPE made prominent and coloured, is delivered in
// `components/DocumentSections.jsx`.

export default function CompanyProfilePage() {
  const { companyId } = useParams()
  const navigate = useNavigate()
  const [company, setCompany] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({})
  const lookups = useLookups()
  const contract = useFormContract()
  const [busy, setBusy] = useState(false)
  //: The live-case warning, held until the operator decides. null = no
  //: conflict, or already acknowledged.
  const [conflict, setConflict] = useState(null)
  // The section whose upload dialog is open, or null. One piece of state
  // rather than one flag per section.
  const [uploadInto, setUploadInto] = useState(null)
  // The document the Remove dialog is about, or null.
  const [removing, setRemoving] = useState(null)
  const [newCase, setNewCase] = useState(false)
  const { hasPermission, isSuperAdmin } = useAuth()
  // nar1:read shows cases; nar1:write is what opens one.
  const canOpenCase = isSuperAdmin || hasPermission('nar1', 'write')
  // { relation, link? } — link present means "edit attributes" (OQ-1), absent means "add".
  const [linkModal, setLinkModal] = useState(null)
  const {
    sections, ready: sectionsReady, error: sectionsError,
  } = useDocumentSections('company')
  // The Corporate Party tile edits two fields nothing else on the profile
  // touches, so it holds its own draft rather than joining `draft` — opening
  // one editor must not put the other card into edit mode.
  const [corpEditing, setCorpEditing] = useState(false)
  const [corpDraft, setCorpDraft] = useState({})

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/companies/${companyId}`)
      .then(setCompany)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [companyId])

  useEffect(() => { load() }, [load])

  async function toggleFlag(flag) {
    setBusy(true)
    try {
      await api.patch(`/companies/${companyId}/flags`, { [flag]: !company[flag] })
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // The address is a SEPARATE row, not a column on the company, so it is
  // drafted and saved separately — `registered_address_id` only ever repoints.
  const [addrDraft, setAddrDraft] = useState(null)

  function startEdit() {
    setDraft({
      ...Object.fromEntries(EDITABLE.map(f => [f.key, company[f.key] ?? ''])),
      company_phone: companyPhone(company),
    })
    setAddrDraft({ ...EMPTY_ADDRESS, ...(company.registered_address || {}) })
    setEditing(true)
  }

  async function confirmRemoveDocument() {
    setBusy(true)
    try {
      await api.del(`/documents/${removing.id}`)
      setRemoving(null)
      load()
    } catch (err) {
      setRemoving(null)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // NAMES THE PARTY, AND SAYS WHAT IS LOST. "Remove this party from the
  // company?" named nobody — with eight directors on screen there was no way
  // to tell which row the dialog belonged to — and it did not say that the
  // delete is permanent. Ceasing an appointment and deleting the record that
  // it existed are different acts with the same button, so the difference has
  // to be in the sentence.
  async function unlinkParty(relation, row) {
    const who = partyName(row)
    if (!window.confirm(
      `Remove ${who} from this company?\n\n`
      + 'This deletes the record that they ever held the role — it is not the '
      + 'same as ending it. To end an appointment or a shareholding, press '
      + 'Edit and set Status to Former, which keeps the history and takes them '
      + 'off the return.')) return
    setBusy(true)
    try {
      await api.del(`/companies/${companyId}/${relation}/${row.id}`)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Send only fields that actually changed — the backend writes one audit
  // entry per changed field, so sending untouched fields would be noise.
  //
  // AN EMPTIED FIELD IS A CHANGE. This used to drop `v === ''` as well, which
  // meant deleting a value and pressing Save did nothing at all and looked
  // exactly like a save that worked — the field came back on the next load. A
  // blank is a legitimate answer (a company can stop having a Chinese name; a
  // CR number typed into the wrong box has to be removable) and the API stores
  // it as NULL. A field that was already empty still sends nothing, because
  // `company[k] ?? ''` is then `''` too.
  function changedFields() {
    return Object.fromEntries(
      Object.entries(draft)
        .filter(([k]) => k !== PHONE_FIELD.key)
        .filter(([k, v]) => (company[k] ?? '') !== v)
    )
  }

  //` force` is a PARAMETER, not a state flag: the override arrives by the
  // operator pressing a button, and routing that through setState would have
  // saveEdit re-enter before React had applied it.
  async function saveEdit(force = false) {
    // A case past Data Verification is holding a FROZEN snapshot of this data.
    // The edit is allowed — the wireframe is explicit that it is — but the
    // operator has to be told that the return already validated, sent to the
    // client or filed with CR will no longer match this record.
    const changed = changedFields()
    const phoneChanged = (draft.company_phone ?? '') !== companyPhone(company)
    if (!force && (Object.keys(changed).length || phoneChanged)) {
      const warning = liveCaseWarning(company)
      if (warning) { setConflict(warning); return }
    }
    setConflict(null)
    setBusy(true)
    try {
      if (Object.keys(changed).length) {
        await api.patch(`/companies/${companyId}`, changed)
      }
      // Separate requests because they write different tables, and they go
      // after the field patch so a rejected address (a line over CR's 60) does
      // not silently discard the field edits that already succeeded.
      if (addrDraft && addressChanged(addrDraft, company.registered_address)) {
        await api.put(`/companies/${companyId}/registered-address`, addressPayload(addrDraft))
      }
      if (phoneChanged) {
        await api.put(`/companies/${companyId}/company-phone`,
                      { company_phone: draft.company_phone || null })
      }
      setEditing(false)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function startCorpEdit() {
    setCorpDraft(Object.fromEntries(
      CORP_EDITABLE.map(f => [f.key, company[f.key] ?? ''])))
    setCorpEditing(true)
  }

  async function saveCorpDetails() {
    const changed = Object.fromEntries(
      Object.entries(corpDraft).filter(([k, v]) => (company[k] ?? '') !== v))
    if (!Object.keys(changed).length) { setCorpEditing(false); return }
    setBusy(true)
    try {
      await api.patch(`/companies/${companyId}`, changed)
      setCorpEditing(false)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** Edit one class of shares — CR's section 11. */
  async function saveShareClass(shareClassId, changed) {
    if (!Object.keys(changed).length) return true
    setBusy(true)
    try {
      await api.patch(`/companies/${companyId}/share-classes/${shareClassId}`, changed)
      load()
      return true
    } catch (err) {
      // The API refuses a currency CR does not take and a figure over its
      // length. Surfacing the reason is the whole point of refusing here
      // rather than at CR, after the fee.
      setError(err.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  /** Give a company share capital it never had — 219 are in that state. */
  async function createShareClass(values) {
    setBusy(true)
    try {
      await api.post(`/companies/${companyId}/share-classes`, values)
      load()
      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  // No `setRecordLocation` here on purpose. The Statutory Records tile was
  // removed on 2026-09-02 — it claimed to be NAR1 s16 (it is s15), listed
  // thirteen registers (CR's schema carries two), and s15 is only asked when
  // the records are NOT at the registered office, which for this whole book
  // they are. The table, endpoints and ETL backfill are still there for the
  // minority of companies whose records sit elsewhere.

  if (loading) return <div className="empty-state">Loading…</div>
  if (error) {
    return (
      <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
        Failed to load company: {error}
      </div>
    )
  }
  if (!company) return null

  const isClient = !!company.is_client
  const isCorp = !!company.is_corporate_party

  // Uploads filed under the section their type belongs to (migration 036).
  // Removed ones are dropped here and kept in Document History — that is what a
  // soft delete is for.
  const liveDocs = (company.documents || []).filter(d => d.status !== 'deleted')
  const bySection = groupBySection(liveDocs, sections)
  const sectionLabels = Object.fromEntries(sections.map(s => [s.key, s.label]))

  // What CR would refuse, read off the same contract the API enforces.
  const warnFor = (table, column, value) => fieldWarning(contract, table, column, value)
  const addressWarnings = Object.fromEntries(
    ['line1', 'line2', 'line3', 'city', 'country'].map(k =>
      [k, warnFor('addresses', k, company.registered_address?.[k])]))
  const infoWarnings = [
    ...EDITABLE.map(f => warnFor('entities', f.key, company[f.key])),
    ...Object.values(addressWarnings),
  ].filter(Boolean)

  // The §11.1 blocking set, computed server-side so the screen and the API
  // agree about what "filable" means (OQ-2).
  const filingProblems = company.filing_problems || []
  const businessName = (company.business_names || [])
    .map(b => [b.business_name, b.business_name_zh].filter(Boolean).join(' · '))
    .filter(Boolean).join(', ')

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="breadcrumb">
            <span className="bc-link" onClick={() => navigate('/dashboard')}>Dashboard</span>
            <span className="bc-sep">›</span>
            <span className="bc-cur">Company Profile</span>
          </div>
          <div className="profile-eyebrow">Company Profile</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div className="profile-name">{company.company_name}</div>
            <StatusBadge status={company.status} />
          </div>
          <div className="pg-sub">
            {[company.vp_source_key, company.br_number && `BRN ${company.br_number}`,
              company.incorporation_date && `Incorporated ${formatDate(company.incorporation_date)}`]
              .filter(Boolean).join(' · ')}
          </div>

          <div className="flag-panel">
            <FlagToggle on={isClient} label="Is Client" busy={busy}
                        sub="Reveals client tiles + Cases pane"
                        onToggle={() => toggleFlag('is_client')} />
            <FlagToggle on={isCorp} label="Is Corporate Party" busy={busy}
                        sub="Acts as director / secretary / shareholder elsewhere"
                        onToggle={() => toggleFlag('is_corporate_party')} />
          </div>
        </div>
        {/* No page-level Upload button: it offered every document type at
            once from a place that named no section. Each section carries its
            own. */}
      </div>

      {newCase && (
        <NewCaseModal
          entity={company}
          onClose={() => setNewCase(false)}
          onCreated={c => navigate(`/cases/${c.id}`)}
        />
      )}

      {uploadInto && (
        <UploadDocumentModal
          ownerKind="entity"
          ownerId={companyId}
          ownerName={company.company_name}
          category={uploadInto.key}
          sectionLabel={uploadInto.label}
          existingTypes={(bySection[uploadInto.key] || []).map(d => d.document_type_code)}
          onClose={() => setUploadInto(null)}
          onUploaded={() => { setUploadInto(null); load() }}
        />
      )}

      {removing && (
        <ConfirmDialog
          title="Remove document"
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={confirmRemoveDocument}
        >
          <RemoveDocumentBody doc={removing} />
        </ConfirmDialog>
      )}

      {linkModal && (
        <LinkPartyModal
          companyId={companyId}
          relation={linkModal.relation}
          link={linkModal.link}
          // The Class of Shares dropdown is THIS company's classes. Passed down
          // rather than fetched: the profile already holds them, and a second
          // request would be a second answer that can disagree with the tile
          // rendered right behind the modal.
          shareClasses={company.share_classes}
          onClose={() => setLinkModal(null)}
          onSaved={() => { setLinkModal(null); load() }}
        />
      )}

      <div className={`detail-grid${isClient ? '' : ' client-off'}`}>
        <div>
          {/* Company Information */}
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">
                  Company Information <WarningCount count={infoWarnings.length} />
                </div>
                {/* Not "filings & documents" any more — those moved to their
                    own card below, so saying it here pointed at a section that
                    is no longer part of this one. */}
                <div className="card-sub">Core company details</div>
              </div>
              {editing ? (
                <div className="hdr-actions">
                  <button className="btn-edit" onClick={() => setEditing(false)} disabled={busy}>Cancel</button>
                  <button className="btn btn-primary btn-sm" onClick={() => saveEdit()} disabled={busy}>
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
                    field={{ ...f, full: true }}
                    value={draft[f.key]}
                    lookups={lookups}
                    onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))}
                  />
                ))}
                <div className="f-group full">
                  <div className="tile-sec-lbl">Registered Office</div>
                  <AddressBlock
                    value={addrDraft}
                    lookups={lookups}
                    warnings={Object.fromEntries(
                      ['line1', 'line2', 'line3', 'city', 'country'].map(k =>
                        [k, warnFor('addresses', k, addrDraft?.[k])]))}
                    onChange={(k, v) => setAddrDraft(a => ({ ...a, [k]: v }))}
                  />
                </div>
                {/* Below the address because it saves the same way — its own
                    table, its own request. */}
                <FormField field={{ ...PHONE_FIELD, full: true }}
                           value={draft[PHONE_FIELD.key]} lookups={lookups}
                           onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))} />
              </div>
            ) : (
              <div className="kv-list">
                <Kv label="Company Name" warning={warnFor('entities', 'company_name', company.company_name)}>
                  <span className="font-semibold">{company.company_name}</span>
                </Kv>
                <Kv label="Chinese Name">{company.company_name_zh}</Kv>
                {/* Brian's B9. Already in `business_names` for 5,026 companies
                    and never shown; CR asks for it as `brName`. */}
                <Kv label="Business Name">{businessName || null}</Kv>
                <Kv label="Entity ID">{company.vp_source_key}</Kv>
                <Kv label="BRN">{company.br_number}</Kv>
                <Kv label="CR No.">{company.cr_number}</Kv>
                <Kv label="Status"><StatusBadge status={company.status} /></Kv>
                <Kv label="Company Type"
                    warning={warnFor('entities', 'company_type', company.company_type)}>
                  {displayValue({ lookup: 'cr_company_type' }, company.company_type, lookups)}
                </Kv>
                {/* B5. Code and description together: the code is what CR
                    validates, the description is what a human recognises. */}
                <Kv label="Business Nature">
                  {company.business_nature_code
                    ? `${company.business_nature_code} — ${company.business_nature_desc || ''}`.trim()
                    : null}
                </Kv>
                {/* B6. */}
                <Kv label="Mortgages and Charges"
                    warning={warnFor('entities', 'mortgages_total', company.mortgages_total)}>
                  {company.mortgages_total}
                </Kv>
                <Kv label="Country of Incorporation">
                  {displayValue({ lookup: 'cr_country' }, company.incorporation_place, lookups)}
                </Kv>
                {/* The five lines CR receives, not a joined string — an
                    address that files correctly and one that does not look
                    identical once you comma-join them. */}
                <AddressBlock value={company.registered_address} readOnly
                              warnings={addressWarnings} />
                <Kv label="Company Phone">{companyPhone(company) || null}</Kv>
                <Kv label="Create Date">{formatDate(company.created_at)}</Kv>
                <Kv label="Incorporation Date">{formatDate(company.incorporation_date)}</Kv>
                {/* CASE NOTES WERE EDITABLE AND DISPLAYED NOWHERE. Typing a
                    note, saving it and reloading looked identical to never
                    having typed one. */}
                <Kv label="Case Notes">{company.case_notes}</Kv>
              </div>
            )}

          </div>

          {/* Documents, one card per section — the same shape as the person
              profile. "Unavailable" is not "none": if the catalogue could not
              be loaded, say so rather than rendering empty sections. */}
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
                {sectionsError} — this company’s documents are not shown below
                because the section list is unavailable, not because there are
                none. Reload the page.
              </div>
            </div>
          )}

          {sections.map(section => (
            <DocumentSection key={section.key} section={section}
                             count={(bySection[section.key] || []).length}
                             onAdd={() => setUploadInto(section)}>
              {(bySection[section.key] || []).length === 0 ? (
                <div className="empty-state" style={{ padding: '16px 0' }}>
                  Nothing uploaded yet.
                </div>
              ) : (
                <SectionDocuments
                  documents={bySection[section.key]}
                  busy={busy}
                  onRemove={doc => setRemoving(doc)}
                />
              )}
            </DocumentSection>
          ))}

          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">Document History</div>
                <div className="card-sub">
                  Every upload, by section and type · newest version is current, older versions preserved
                </div>
              </div>
            </div>
            <DocumentHistory documents={company.documents} sectionLabels={sectionLabels} />
          </div>

          {/* Corporate Party Details — gated on is_corporate_party */}
          {isCorp && (
            <div className="card mb-16 corp-tile">
              <div className="reveal-note">Shown because <b>Is Corporate Party</b> is On</div>
              <div className="card-hdr">
                <div>
                  <div className="card-title">Corporate Party Details</div>
                  <div className="card-sub">
                    Held when this company acts as a director, secretary or shareholder of another
                  </div>
                </div>
                {/* WAS READ-ONLY. The TCSP licence is the one thing this tile is
                    for, the Company Secretary tile on every OTHER company prints
                    it, and there was no screen anywhere in the portal that could
                    set it — so it showed an em dash for a licensed provider and
                    stayed that way. */}
                {corpEditing ? (
                  <div className="hdr-actions">
                    <button className="btn-edit" onClick={() => setCorpEditing(false)} disabled={busy}>
                      Cancel
                    </button>
                    <button className="btn btn-primary btn-sm" onClick={saveCorpDetails} disabled={busy}>
                      {busy ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                ) : (
                  <button className="btn-edit" onClick={startCorpEdit}>Edit</button>
                )}
              </div>
              {corpEditing ? (
                <div className="form-grid">
                  {CORP_EDITABLE.map(f => (
                    <FormField key={f.key} field={{ ...f, full: true }}
                               value={corpDraft[f.key]} lookups={lookups}
                               onChange={(k, v) => setCorpDraft(d => ({ ...d, [k]: v }))} />
                  ))}
                </div>
              ) : (
                <div className="kv-list">
                  <Kv label="Company Type">
                    {displayValue({ lookup: 'cr_company_type' }, company.company_type, lookups)}
                  </Kv>
                  <Kv label="TCSP Licence No.">{company.tcsp_licence_no}</Kv>
                  <Kv label="TCSP Exemption Reason">{company.tcsp_exemption_reason}</Kv>
                </div>
              )}
            </div>
          )}

          {/* Share capital — CR's section 11, in its own right (B7). The
              return states what the company's capital IS, whether or not
              anyone currently holds it, so this is not the same list as the
              share classes hanging off each shareholding. */}
          {isClient && (
            <ShareCapitalTile classes={company.share_classes}
                              warnFor={warnFor} busy={busy}
                              onSave={saveShareClass} onCreate={createShareClass} />
          )}

          {/* Client-only party tiles */}
          {isClient && (
            <>
              <PartyTile title="Director(s)" sub="Appointed directors"
                         rows={company.officers} relation="officers" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'officers' })}
                         onEdit={row => setLinkModal({ relation: 'officers', link: row })}
                         onRemove={row => unlinkParty('officers', row)}
                         render={o => (
                           <>
                             <Kv label="Role">{(o.role || '').replace(/_/g, ' ')}</Kv>
                             {/* POSITION AND RESIGNATION REASON ARE SHOWN
                                 (Levi 2026-09-04). Both were editable in the
                                 modal and printed nowhere, so typing one and
                                 saving it looked identical to not typing it.
                                 Conditional because an empty Position on a
                                 director who has none is a row of nothing. */}
                             {o.position && <Kv label="Position">{o.position}</Kv>}
                             <Kv label="Appointed">{formatDate(o.appointed_date)}</Kv>
                             {o.resigned_date && <Kv label="Resigned">{formatDate(o.resigned_date)}</Kv>}
                             {o.resignation_reason && (
                               <Kv label="Resignation Reason">{o.resignation_reason}</Kv>
                             )}
                             {/* B3's substantive half: every director's contact
                                 details, which the tile did not show at all. */}
                             <Kv label="Email Address">{o.persons?.email}</Kv>
                             <Kv label="Residential Address">
                               {addressText(o.persons?.residential_address)}
                             </Kv>
                             {/* D2 — a director may give company A and company
                                 B different correspondence addresses, as the
                                 law allows, so it hangs off the APPOINTMENT. */}
                             <Kv label="Correspondence Address">
                               {addressText(o.correspondence_address)}
                             </Kv>
                           </>
                         )} />

              {/* A TRANSFER IS TWO EDITS, NOT A DELETE (Levi's Q9: "what
                  happens when a shareholder loses his/her share to someone
                  else"). The register has to keep showing who held the shares
                  before, and the audit trail has to show when that stopped —
                  both of which a DELETE destroys. Setting the outgoing holder
                  to Former is what drops them from the return: `nar1_mapper`'s
                  `_schedule_1` skips a holding with `is_current` false. The
                  note says so on the tile, because the two buttons on offer
                  are Edit and Remove and Remove is the one that reads like
                  "this person no longer holds shares". */}
              <PartyTile title="Shareholder(s)" sub="Members of the company"
                         rows={company.shareholders} relation="shareholders" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'shareholders' })}
                         onEdit={row => setLinkModal({ relation: 'shareholders', link: row })}
                         onRemove={row => unlinkParty('shareholders', row)}
                         note={'Transferring shares? Edit the outgoing holder and set '
                             + 'Status to Former, then add the new holder — or raise an '
                             + 'existing holder’s Shares Held. Remove deletes the record '
                             + 'that they ever held the shares.'}
                         render={s => (
                           <>
                             {/* CR's shareCapitalList states the class and its
                                 currency beside the holding, not just a count. */}
                             <Kv label="Class of Shares">{s.share_classes?.class_name}</Kv>
                             {/* "Total Number" is CR's heading for the CLASS
                                 total in section 11 — the number of shares in
                                 issue. Using it here for one member's holding
                                 put the same words on two different figures on
                                 the same screen. This is what the modal calls
                                 it, and what it is. */}
                             <Kv label="Shares Held">{figure(s.shares_held)}</Kv>
                             <Kv label="Currency">{s.share_classes?.currency}</Kv>
                             <Kv label="Amount Paid">{figure(s.amount_paid)}</Kv>
                             {/* B4 — a shareholder needs an address, natural
                                 person and body corporate alike. They are
                                 different FACTS: a company has a registered
                                 office, not a residence. */}
                             <Kv label={s.corporate_entity_id
                               ? 'Registered Office' : 'Residential Address'}>
                               {addressText(s.corporate_entity?.registered_address
                                 || s.persons?.residential_address)}
                             </Kv>
                           </>
                         )} />

              <PartyTile title="Company Secretary" sub="Secretarial service provider"
                         rows={company.secretaries} relation="secretaries" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'secretaries' })}
                         onEdit={row => setLinkModal({ relation: 'secretaries', link: row })}
                         onRemove={row => unlinkParty('secretaries', row)}
                         render={s => (
                           <>
                             {/* THE LICENCE MAY BE THE PERSON'S. This read only
                                 `corporate_entity` and printed an em dash for a
                                 secretary who is an individual — and the AMLO
                                 licenses individuals as TCSPs exactly as it
                                 licenses bodies corporate. `persons` now
                                 carries the column (migration 038). */}
                             <Kv label="TCSP Licence No.">
                               {s.corporate_entity?.tcsp_licence_no || s.persons?.tcsp_licence_no}
                             </Kv>
                             {s.position && <Kv label="Position">{s.position}</Kv>}
                             <Kv label="Appointed">{formatDate(s.appointed_date)}</Kv>
                             {s.resigned_date && <Kv label="Resigned">{formatDate(s.resigned_date)}</Kv>}
                             {/* Editable in the modal and printed nowhere —
                                 the same gap as the director tile. */}
                             {s.resignation_reason && (
                               <Kv label="Resignation Reason">{s.resignation_reason}</Kv>
                             )}
                             <Kv label="Email Address">{s.persons?.email}</Kv>
                             <Kv label={s.corporate_entity_id
                               ? 'Registered Office' : 'Residential Address'}>
                               {addressText(s.corporate_entity?.registered_address
                                 || s.persons?.residential_address)}
                             </Kv>
                           </>
                         )} />

              <PartyTile title="Beneficial Owner(s)" sub="Significant controllers"
                         rows={company.beneficial_owners} relation="beneficial-owners" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'beneficial-owners' })}
                         onEdit={row => setLinkModal({ relation: 'beneficial-owners', link: row })}
                         onRemove={row => unlinkParty('beneficial-owners', row)}
                         render={b => (
                           <>
                             {/* The stored code rendered as its sentence. The
                                 raw value was printed before, so the tile read
                                 "significant_controller". */}
                             <Kv label="Owner Type">
                               {displayValue({ lookup: 'bo_owner_type' }, b.owner_type, lookups)}
                             </Kv>
                             {/* Companies Ordinance s.653D. REPLACES Interest %
                                 and Voting % (Levi 2026-09-04): two numeric
                                 columns could not express "has the right to
                                 exercise significant influence or control",
                                 which is the second of the two conditions and
                                 the one that has nothing to do with a
                                 percentage. The columns are kept in the
                                 database; nothing filed reads them. */}
                             <Kv label="Nature of Control over the Company">
                               {displayValue({ lookup: 'bo_nature_of_control' },
                                             b.nature_of_control, lookups)}
                             </Kv>
                             {b.date_from && <Kv label="From">{formatDate(b.date_from)}</Kv>}
                             {b.date_to && <Kv label="To">{formatDate(b.date_to)}</Kv>}
                             <Kv label={b.corporate_entity_id
                               ? 'Registered Office' : 'Residential Address'}>
                               {addressText(b.corporate_entity?.registered_address
                                 || b.persons?.residential_address)}
                             </Kv>
                           </>
                         )} />
            </>
          )}
        </div>

        {/* Cases pane — client entities only (§6 visibility) */}
        {isClient && (
          <div>
            <div className="card">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Cases</div>
                  <div className="card-sub">NAR1 &amp; NNC1 workflow cases</div>
                </div>
                {/* The annual return is started from the company it is for.
                    Without this the only route was the dashboard, where you
                    then had to search back to the company you were already on. */}
                {canOpenCase && (
                  <button className="btn btn-outline btn-sm"
                          disabled={filingProblems.length > 0}
                          onClick={() => setNewCase(true)}>
                    + New case
                  </button>
                )}
              </div>
              {/* WHY THE REFUSAL IS PRINTED HERE. 453 of 5,930 client
                  companies cannot produce a valid return (OQ-2), and a
                  disabled button with no explanation is the exact shape of
                  "I clicked it and nothing happened". The reason belongs
                  beside the control that is refusing, not in a page banner a
                  screen and a half above it. */}
              {filingProblems.length > 0 && (
                <div className="reveal-note" role="note">
                  <b>This company cannot file an annual return yet.</b>
                  <ul className="filing-problems">
                    {filingProblems.map(p => <li key={p.field}>{p.message}</li>)}
                  </ul>
                </div>
              )}
              <CasesPane cases={company.cases} onOpen={id => navigate(`/cases/${id}`)} />
            </div>
          </div>
        )}
      </div>

      {/* The edit is NOT blocked — the wireframe is explicit that the profile
          changes and the case snapshot does not. What is required is that the
          operator be told which return will stop matching this record. */}
      {conflict && (
        <div className="modal-confirm" role="alertdialog"
             aria-label="Edit conflicts with a live case">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">{conflict.title}</div>
            <div className="modal-confirm-text">{conflict.body}</div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setConflict(null)}>
                Cancel edit
              </button>
              <button className="btn btn-danger" onClick={() => saveEdit(true)}>
                Save anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/**
 * Share capital, under CR's own headings (Brian's B7).
 *
 * WHY THE HEADINGS MATTER. "Total Number" is a COUNT of shares and "Total
 * Amount" is money, and the schema could not tell them apart until migration
 * 028: `total_issued` stood in for both. On 60 of Viewpoint's 5,740 rows they
 * genuinely differ — 200 shares worth HK$20,000, 1,000 worth HK$5,000,000 —
 * so a screen that showed one number under an ambiguous label was showing the
 * wrong one and no one could tell.
 */
function ShareCapitalTile({ classes, warnFor, busy, onSave, onCreate }) {
  const rows = classes || []
  // The row being edited, the string 'new' while adding, or null. The editor
  // itself is a dialog now (components/ShareClassModal.jsx) — inline, its two
  // buttons stacked vertically inside a column flex box, which is the one
  // place in the app where Cancel sat on top of Save.
  const [editing, setEditing] = useState(null)

  const warnings = rows.flatMap(row =>
    SHARE_CLASS_FIELDS.map(f => warnFor('share_classes', f.key, row[f.key]))
      .filter(Boolean))

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">
            Share Capital <span className="count-pill">{rows.length}</span>
            <WarningCount count={warnings.length} />
          </div>
          <div className="card-sub">
            Section 11 of the annual return — one row per class of shares
          </div>
        </div>
        <button className="btn btn-outline btn-sm" onClick={() => setEditing('new')}>
          + Add a class
        </button>
      </div>

      {editing && (
        <ShareClassModal
          // The draft is seeded once, on mount. Without a key, going from one
          // row's editor straight to another's would reuse the first row's
          // draft — and silently save it over the second row.
          key={editing === 'new' ? 'new' : editing.id}
          row={editing === 'new' ? null : editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSave={values => (editing === 'new' ? onCreate(values) : onSave(editing.id, values))}
        />
      )}

      {rows.length === 0 ? (
        // 219 client companies are in this state, and it stops them filing.
        // Saying "None" would read as "nothing to do here".
        <div className="empty-state" style={{ padding: '16px 0' }}>
          No share capital recorded. The Companies Registry requires at least one
          class of shares for a company having a share capital.
        </div>
      ) : rows.map(row => (
        <div className="member-block" key={row.id || row.class_name}>
          <div className="member-name">
            {/* The class NAME heads its own block. It used to be omitted on the
                grounds that "Class of Shares" is the first row of the list
                below — but with several classes that made every block start
                with an empty title bar carrying nothing but an Edit button. */}
            {row.class_name || <span className="td-muted">Unnamed class</span>}
            {row.currency && <span className="member-role-tag">{row.currency}</span>}
            <span style={{ marginLeft: 'auto' }}>
              <button className="btn-edit" onClick={() => setEditing(row)}>Edit</button>
            </span>
          </div>
          <div className="kv-list">
            {SHARE_CLASS_FIELDS.map(f => (
              <Kv key={f.key} label={f.label}
                  warning={warnFor('share_classes', f.key, row[f.key])}>
                {f.key === 'class_name' || f.key === 'currency'
                  ? row[f.key] : figure(row[f.key])}
              </Kv>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * A party tile. When `relation` is given the tile is editable: add a link, edit
 * its attributes (OQ-1) or remove it. company_secretaries has no linking
 * endpoint, so that tile stays read-only.
 */
function PartyTile({ title, sub, rows, render, nameOf = partyName, relation, onAdd, onEdit, onRemove, busy, note }) {
  const list = rows || []
  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">{title} <span className="count-pill">{list.length}</span></div>
          <div className="card-sub">{sub}</div>
        </div>
        {relation && (
          <button className="btn btn-outline btn-sm" onClick={onAdd}>+ Add</button>
        )}
      </div>
      {note && <div className="reveal-note" role="note">{note}</div>}
      {list.length === 0 ? (
        <div className="empty-state" style={{ padding: '16px 0' }}>None linked.</div>
      ) : list.map(row => (
        <div className="member-block" key={row.id}>
          <div className="member-name">
            {nameOf(row)}
            {/* Brian's B10 — NAR1 says Body Corporate, so the portal does. */}
            {row.corporate_entity_id && <span className="member-role-tag">Body Corporate</span>}
            {row.is_current === false && <span className="member-role-tag">Former</span>}
            {relation && (
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                <button className="btn-edit" onClick={() => onEdit(row)}>Edit</button>
                <button className="btn-edit" disabled={busy}
                        onClick={() => onRemove(row)}>Remove</button>
              </span>
            )}
          </div>
          <div className="kv-list">{render(row)}</div>
        </div>
      ))}
    </div>
  )
}

function CasesPane({ cases, onOpen }) {
  const all = [
    ...(cases?.nar1 || []).map(c => ({ ...c, kind: 'NAR1 — Annual Return' })),
    ...(cases?.nnc1 || []).map(c => ({ ...c, kind: 'NNC1 — Incorporation' })),
  ]
  const [open, setOpen] = useState(null)

  if (all.length === 0) {
    return <div className="empty-state" style={{ padding: '16px 0' }}>No cases yet.</div>
  }
  return all.map(c => (
    <div className={`case-acc${open === c.id ? ' open' : ''}`} key={c.id}>
      <div className="case-acc-hdr"
           onClick={() => (onOpen ? onOpen(c.id) : setOpen(open === c.id ? null : c.id))}>
        <span className="case-chevron">❯</span>
        <div className="case-acc-titles">
          <div className="case-acc-type">{c.kind}</div>
          <div className="case-acc-id">Case ID: {c.id.slice(0, 8)}</div>
        </div>
        <StatusBadge status={c.status} />
      </div>
      {open === c.id && (
        <div className="case-acc-body">
          <div className="kv-list">
            <Kv label="Status">{c.status}</Kv>
            <Kv label="Created">{formatDate(c.created_at)}</Kv>
          </div>
        </div>
      )}
    </div>
  ))
}
