import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { liveCaseWarning } from '../lib/liveCase.js'
import { formatDate } from '../lib/format.js'
import { downloadDocument } from '../lib/download.js'
import StatusBadge from '../components/StatusBadge.jsx'
import UploadDocumentModal from '../components/UploadDocumentModal.jsx'
import LinkPartyModal from '../components/LinkPartyModal.jsx'
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
  { key: 'case_notes', label: 'Case Notes' },
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

function DocumentList({ documents }) {
  if (!documents?.length) {
    return <div className="empty-state" style={{ padding: '16px 0' }}>No documents uploaded yet.</div>
  }
  return documents.map(d => (
    <div className="doc-item" key={d.id}>
      <span className="doc-name">
        {/* What the document IS, not just the file it happened to be uploaded as. */}
        {d.document_types?.label || d.document_type_code}
        {d.current_version > 1 && <span className="filing-tag">v{d.current_version}</span>}
        <span className="td-muted" style={{ display: 'block', fontSize: 11, fontWeight: 400 }}>
          {d.title && d.title !== d.file_name ? `${d.title} · ` : ''}{d.file_name}
        </span>
      </span>
      <button className="doc-dl" onClick={() => downloadDocument(d.id)}>Download</button>
    </div>
  ))
}

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
  const [showUpload, setShowUpload] = useState(false)
  const [newCase, setNewCase] = useState(false)
  const { hasPermission, isSuperAdmin } = useAuth()
  // nar1:read shows cases; nar1:write is what opens one.
  const canOpenCase = isSuperAdmin || hasPermission('nar1', 'write')
  // { relation, link? } — link present means "edit attributes" (OQ-1), absent means "add".
  const [linkModal, setLinkModal] = useState(null)

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
    setDraft(Object.fromEntries(EDITABLE.map(f => [f.key, company[f.key] ?? ''])))
    setAddrDraft({ ...EMPTY_ADDRESS, ...(company.registered_address || {}) })
    setEditing(true)
  }

  async function unlinkParty(relation, linkId) {
    if (!window.confirm('Remove this party from the company?')) return
    setBusy(true)
    try {
      await api.del(`/companies/${companyId}/${relation}/${linkId}`)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // Send only fields that actually changed — the backend writes one audit
  // entry per changed field, so sending untouched fields would be noise.
  function changedFields() {
    return Object.fromEntries(
      Object.entries(draft).filter(([k, v]) => (company[k] ?? '') !== v && v !== '')
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
    if (!force && Object.keys(changed).length) {
      const warning = liveCaseWarning(company)
      if (warning) { setConflict(warning); return }
    }
    setConflict(null)
    setBusy(true)
    try {
      if (Object.keys(changed).length) {
        await api.patch(`/companies/${companyId}`, changed)
      }
      // Separate request because it writes a different table, and it goes
      // second so a rejected address (a line over CR's 60) does not silently
      // discard the field edits that already succeeded.
      if (addrDraft && addressChanged(addrDraft, company.registered_address)) {
        await api.put(`/companies/${companyId}/registered-address`, addressPayload(addrDraft))
      }
      setEditing(false)
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

  /** Point one statutory register at an address, or at nothing (OQ-3). */
  async function setRecordLocation(recordType, addressId) {
    setBusy(true)
    try {
      await api.put(`/companies/${companyId}/record-locations/${recordType}`,
                    { address_id: addressId || null })
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
        Failed to load company: {error}
      </div>
    )
  }
  if (!company) return null

  const isClient = !!company.is_client
  const isCorp = !!company.is_corporate_party

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
        <div className="pg-actions">
          <button className="btn btn-outline" onClick={() => setShowUpload(true)}>Upload Document</button>
        </div>
      </div>

      {newCase && (
        <NewCaseModal
          entity={company}
          onClose={() => setNewCase(false)}
          onCreated={c => navigate(`/cases/${c.id}`)}
        />
      )}

      {showUpload && (
        <UploadDocumentModal
          ownerKind="entity"
          ownerId={companyId}
          ownerName={company.company_name}
          existingTypes={(company.documents || []).map(d => d.document_type_code)}
          onClose={() => setShowUpload(false)}
          onUploaded={() => { setShowUpload(false); load() }}
        />
      )}

      {linkModal && (
        <LinkPartyModal
          companyId={companyId}
          relation={linkModal.relation}
          link={linkModal.link}
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
                <div className="card-sub">Core company details, filings &amp; documents</div>
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
                <Kv label="Company Phone">
                  {company.contacts?.find(c => c.contact_type === 'phone')?.contact_value}
                </Kv>
                <Kv label="Create Date">{formatDate(company.created_at)}</Kv>
                <Kv label="Incorporation Date">{formatDate(company.incorporation_date)}</Kv>
              </div>
            )}

            <div className="tile-sec-lbl">Filings &amp; Company Documents</div>
            <DocumentList documents={company.documents} />
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
              </div>
              <div className="kv-list">
                <Kv label="Company Type">{company.company_type}</Kv>
                <Kv label="TCSP Licence">{company.tcsp_licence_no}</Kv>
                <Kv label="TCSP Exemption">{company.tcsp_exemption_reason}</Kv>
              </div>
            </div>
          )}

          {/* Share capital — CR's section 11, in its own right (B7). The
              return states what the company's capital IS, whether or not
              anyone currently holds it, so this is not the same list as the
              share classes hanging off each shareholding. */}
          {isClient && (
            <ShareCapitalTile classes={company.share_classes}
                              lookups={lookups} warnFor={warnFor} busy={busy}
                              onSave={saveShareClass} onCreate={createShareClass} />
          )}

          {/* NAR1 section 16 (OQ-3). */}
          {isClient && (
            <RecordLocationsTile company={company} busy={busy}
                                 onSet={setRecordLocation} />
          )}

          {/* Client-only party tiles */}
          {isClient && (
            <>
              <PartyTile title="Director(s)" sub="Appointed directors"
                         rows={company.officers} relation="officers" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'officers' })}
                         onEdit={row => setLinkModal({ relation: 'officers', link: row })}
                         onRemove={id => unlinkParty('officers', id)}
                         render={o => (
                           <>
                             <Kv label="Role">{o.role}</Kv>
                             <Kv label="Appointed">{formatDate(o.appointed_date)}</Kv>
                             {o.resigned_date && <Kv label="Resigned">{formatDate(o.resigned_date)}</Kv>}
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

              <PartyTile title="Shareholder(s)" sub="Members of the company"
                         rows={company.shareholders} relation="shareholders" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'shareholders' })}
                         onEdit={row => setLinkModal({ relation: 'shareholders', link: row })}
                         onRemove={id => unlinkParty('shareholders', id)}
                         render={s => (
                           <>
                             {/* CR's shareCapitalList states the class and its
                                 currency beside the holding, not just a count. */}
                             <Kv label="Class of Shares">{s.share_classes?.class_name}</Kv>
                             <Kv label="Total Number">{figure(s.shares_held)}</Kv>
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
                         onRemove={id => unlinkParty('secretaries', id)}
                         render={s => (
                           <>
                             {/* TCSP licence comes from the linked corporate party. */}
                             <Kv label="TCSP Licence No.">{s.corporate_entity?.tcsp_licence_no}</Kv>
                             <Kv label="Position">{s.position}</Kv>
                             <Kv label="Appointed">{formatDate(s.appointed_date)}</Kv>
                             {s.resigned_date && <Kv label="Resigned">{formatDate(s.resigned_date)}</Kv>}
                           </>
                         )} />

              <PartyTile title="Beneficial Owner(s)" sub="Significant controllers"
                         rows={company.beneficial_owners} relation="beneficial-owners" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'beneficial-owners' })}
                         onEdit={row => setLinkModal({ relation: 'beneficial-owners', link: row })}
                         onRemove={id => unlinkParty('beneficial-owners', id)}
                         render={b => (
                           <>
                             <Kv label="Owner Type">{b.owner_type}</Kv>
                             <Kv label="Interest %">{b.percent_interest}</Kv>
                             <Kv label="Voting %">{b.percent_vote}</Kv>
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
//: CR's section 11 headings, in CR's order. `lookup` names the vocabulary the
//: editor draws from — currency is CR's 54 codes, NOT the 162 ISO ones in
//: `lookup_values`, because CR wants RMB where ISO says CNY.
const SHARE_CLASS_FIELDS = [
  { key: 'class_name', label: 'Class of Shares' },
  { key: 'currency', label: 'Currency', lookup: 'cr_currency' },
  { key: 'total_issued', label: 'Total Number' },
  { key: 'issued_amount', label: 'Total Amount' },
  { key: 'total_paid', label: 'Total Amount Paid up or Regarded as Paid up' },
]

function ShareCapitalTile({ classes, lookups, warnFor, busy, onSave, onCreate }) {
  const rows = classes || []
  // The id being edited, 'new' while adding, or null.
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState({})

  const warnings = rows.flatMap(row =>
    SHARE_CLASS_FIELDS.map(f => warnFor('share_classes', f.key, row[f.key]))
      .filter(Boolean))

  const startEdit = (row) => {
    setDraft(Object.fromEntries(
      SHARE_CLASS_FIELDS.map(f => [f.key, row[f.key] ?? ''])))
    setEditing(row.id)
  }
  const startAdd = () => {
    setDraft(Object.fromEntries(SHARE_CLASS_FIELDS.map(f => [f.key, ''])))
    setEditing('new')
  }

  async function save() {
    // Figures go as STRINGS: CR counts characters, and a number that
    // round-trips through JSON as 1.0000000001e14 is not what was typed.
    const ok = editing === 'new'
      ? await onCreate(draft)
      : await onSave(editing, Object.fromEntries(
          Object.entries(draft).filter(
            ([k, v]) => String(rows.find(r => r.id === editing)?.[k] ?? '') !== String(v))))
    if (ok) setEditing(null)
  }

  const editor = (
    <div className="form-grid">
      {SHARE_CLASS_FIELDS.map(f => (
        <FormField key={f.key} field={{ ...f, full: true }} value={draft[f.key]}
                   lookups={lookups}
                   onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))} />
      ))}
      <div className="f-group full hdr-actions">
        <button className="btn-edit" onClick={() => setEditing(null)} disabled={busy}>
          Cancel
        </button>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )

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
        {editing === null && (
          <button className="btn btn-outline btn-sm" onClick={startAdd}>
            + Add a class
          </button>
        )}
      </div>

      {editing === 'new' && editor}

      {rows.length === 0 && editing !== 'new' ? (
        // 219 client companies are in this state, and it stops them filing.
        // Saying "None" would read as "nothing to do here".
        <div className="empty-state" style={{ padding: '16px 0' }}>
          No share capital recorded. The Companies Registry requires at least one
          class of shares for a company having a share capital.
        </div>
      ) : rows.map(row => (
        // No separate heading: "Class of Shares" is CR's own first heading and
        // is right there in the list. Repeating it above would show the same
        // value twice under two different names.
        <div className="member-block" key={row.id || row.class_name}>
          {editing === row.id ? editor : (
            <>
              <div className="member-name">
                <span style={{ marginLeft: 'auto' }}>
                  <button className="btn-edit" onClick={() => startEdit(row)}>Edit</button>
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
            </>
          )}
        </div>
      ))}
    </div>
  )
}

/**
 * Where each statutory register is kept — NAR1 section 16 (OQ-3).
 *
 * Every register CR asks about is listed, answered or not: a register with
 * nowhere recorded is the answer the return has to show, and omitting the row
 * would render an unanswered question as an answered one.
 *
 * THE EDITOR IS A CHOICE AMONG ADDRESSES THIS COMPANY ALREADY HAS, plus "not
 * recorded". That is deliberate rather than a shortcut: addresses are created
 * by copy-on-write through the company and person address endpoints, and there
 * is no endpoint that mints a free-standing one. In practice a register is
 * kept at the registered office or at GSHK's, both of which are already here.
 */
function RecordLocationsTile({ company, busy, onSet }) {
  const rows = company.record_locations || []

  // Every distinct address the company already knows about, by id.
  const options = new Map()
  const offer = (id, address) => {
    if (id && address && !options.has(id)) options.set(id, addressText(address))
  }
  offer(company.registered_address?.id, company.registered_address)
  for (const row of rows) offer(row.address_id, row.address)

  const recorded = rows.filter(r => r.address_id).length

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">
            Statutory Records <span className="count-pill">{recorded}/{rows.length}</span>
          </div>
          <div className="card-sub">
            Section 16 — where each register is kept
          </div>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="empty-state" style={{ padding: '16px 0' }}>
          No registers recorded.
        </div>
      ) : (
        <div className="kv-list">
          {rows.map(row => (
            <div className="kv-row" key={row.record_type}>
              <span className="kv-key">
                <label htmlFor={`rl_${row.record_type}`}>{row.label}</label>
              </span>
              <span className="kv-val">
                <select
                  id={`rl_${row.record_type}`}
                  className="f-select"
                  disabled={busy}
                  value={row.address_id || ''}
                  onChange={e => onSet(row.record_type, e.target.value)}
                >
                  <option value="">Not recorded</option>
                  {[...options.entries()].map(([id, label]) => (
                    <option key={id} value={id}>{label}</option>
                  ))}
                </select>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * A party tile. When `relation` is given the tile is editable: add a link, edit
 * its attributes (OQ-1) or remove it. company_secretaries has no linking
 * endpoint, so that tile stays read-only.
 */
function PartyTile({ title, sub, rows, render, nameOf = partyName, relation, onAdd, onEdit, onRemove, busy }) {
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
                        onClick={() => onRemove(row.id)}>Remove</button>
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
