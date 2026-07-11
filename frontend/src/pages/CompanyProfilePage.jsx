import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import StatusBadge from '../components/StatusBadge.jsx'
import UploadDocumentModal from '../components/UploadDocumentModal.jsx'
import LinkPartyModal from '../components/LinkPartyModal.jsx'

const EDITABLE = [
  { key: 'company_name', label: 'Company Name' },
  { key: 'company_name_zh', label: 'Chinese Name' },
  { key: 'br_number', label: 'BRN' },
  { key: 'cr_number', label: 'CR No.' },
  { key: 'company_type', label: 'Company Type' },
  { key: 'incorporation_date', label: 'Incorporation Date', type: 'date' },
  { key: 'case_notes', label: 'Case Notes' },
]

function Kv({ label, children }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">{children ?? <span className="td-muted">—</span>}</span>
    </div>
  )
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
  async function download(id) {
    const { url } = await api.get(`/documents/${id}/download`)
    window.open(url, '_blank', 'noopener')
  }
  if (!documents?.length) {
    return <div className="empty-state" style={{ padding: '16px 0' }}>No documents uploaded yet.</div>
  }
  return documents.map(d => (
    <div className="doc-item" key={d.id}>
      <span className="doc-name">
        {d.title || d.file_name || d.document_type_code}
        {d.current_version > 1 && <span className="filing-tag">v{d.current_version}</span>}
      </span>
      <button className="doc-dl" onClick={() => download(d.id)}>Download</button>
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
  const [busy, setBusy] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
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

  function startEdit() {
    setDraft(Object.fromEntries(EDITABLE.map(f => [f.key, company[f.key] ?? ''])))
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

  async function saveEdit() {
    setBusy(true)
    // Send only fields that actually changed — the backend writes one audit
    // entry per changed field, so sending untouched fields would be noise.
    const changed = Object.fromEntries(
      Object.entries(draft).filter(([k, v]) => (company[k] ?? '') !== v && v !== '')
    )
    try {
      if (Object.keys(changed).length) {
        await api.patch(`/companies/${companyId}`, changed)
      }
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
        Failed to load company: {error}
      </div>
    )
  }
  if (!company) return null

  const isClient = !!company.is_client
  const isCorp = !!company.is_corporate_party

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
                <div className="card-title">Company Information</div>
                <div className="card-sub">Core company details, filings &amp; documents</div>
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
                  <div className="f-group full" key={f.key}>
                    <label className="f-label" htmlFor={f.key}>{f.label}</label>
                    <input id={f.key} className="f-input" type={f.type || 'text'}
                           value={draft[f.key] ?? ''}
                           onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="kv-list">
                <Kv label="Company Name"><span className="font-semibold">{company.company_name}</span></Kv>
                <Kv label="Chinese Name">{company.company_name_zh}</Kv>
                <Kv label="Entity ID">{company.vp_source_key}</Kv>
                <Kv label="BRN">{company.br_number}</Kv>
                <Kv label="CR No.">{company.cr_number}</Kv>
                <Kv label="Status"><StatusBadge status={company.status} /></Kv>
                <Kv label="Company Type">{company.company_type}</Kv>
                <Kv label="Registered Address">{addressText(company.registered_address)}</Kv>
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
                <Kv label="Country of Incorporation">{company.incorporation_place}</Kv>
                <Kv label="TCSP Licence">{company.tcsp_licence_no}</Kv>
                <Kv label="TCSP Exemption">{company.tcsp_exemption_reason}</Kv>
              </div>
            </div>
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
                             <Kv label="Email">{o.persons?.email}</Kv>
                           </>
                         )} />

              <PartyTile title="Shareholder(s)" sub="Members of the company"
                         rows={company.shareholders} relation="shareholders" busy={busy}
                         onAdd={() => setLinkModal({ relation: 'shareholders' })}
                         onEdit={row => setLinkModal({ relation: 'shareholders', link: row })}
                         onRemove={id => unlinkParty('shareholders', id)}
                         render={s => (
                           <>
                             <Kv label="Shares Held">{s.shares_held}</Kv>
                             <Kv label="Share Class">{s.share_classes?.class_name}</Kv>
                             <Kv label="Amount Paid">{s.amount_paid}</Kv>
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
              </div>
              <CasesPane cases={company.cases} />
            </div>
          </div>
        )}
      </div>
    </>
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
            {row.corporate_entity_id && <span className="member-role-tag">Corporate</span>}
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

function CasesPane({ cases }) {
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
      <div className="case-acc-hdr" onClick={() => setOpen(open === c.id ? null : c.id)}>
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
