import { useCallback, useEffect, useId, useState } from 'react'
import { api } from '../../lib/api.js'
import { countryName } from '../../lib/crAddress.js'
import { fieldWarning } from '../../lib/formContract.js'
import AddressBlock from '../AddressBlock.jsx'
import ConfirmDialog from '../ConfirmDialog.jsx'
import './particulars.css'

/**
 * A person's identification and addresses, and which company files which
 * (Levi 2026-10-05, on Jacqueline's ND2B question 2: "We do have clients
 * holding 2 passports, say French and US passports. The same situation might
 * apply to addresses too ... in each residential address in the list it shows
 * which companies is using those addresses").
 *
 * Three cards, one rule: every entry names the companies that use it, and each
 * company keeps ONE colour across all three, so "what does Second Limited
 * file?" is answered by following one hue down the page. The colour is
 * reinforcement only — the company is always named — and the palette stays
 * clear of carrot (needs attention) and green (approved), as the document
 * chips do.
 *
 * Every write returns the refreshed book. The backend captures what CR holds
 * for each company before anything moves, so a company moved here appears on
 * the ND2B alert above, and one left where it was does not; `onChanged` lets
 * the page refresh that alert.
 */

const CO_COLOURS = 6
const ROLE = { director: 'Director', company_secretary: 'Company Secretary' }
const ID_TYPE = { hkid: 'Hong Kong Identity Card', passport: 'Passport',
  china_id: 'Mainland China Identity Card', other: 'Other Identity Document' }
const ADDRESS_KEYS = ['line1', 'line2', 'line3', 'city', 'state_region', 'postal_code', 'country']
const EMPTY = Object.fromEntries(ADDRESS_KEYS.map(k => [k, '']))

/** entity_id -> colour slot, by the company's place in the person's list: six
 * companies get six different colours (a hash let two collide), and every
 * card reads the same list, so a company keeps its colour across all three. */
export function companyColours(companies) {
  return Object.fromEntries((companies || []).map((c, i) => [c.entity_id, i % CO_COLOURS]))
}

function errorText(e, fallback) {
  return e?.detail?.message || (typeof e?.detail === 'string' ? e.detail : null)
    || e?.message || fallback
}

function CompanyChips({ ids, companies, empty }) {
  const byId = Object.fromEntries((companies || []).map(c => [c.entity_id, c]))
  const colour = companyColours(companies)
  if (!ids || ids.length === 0) return <div className="pb-unused">{empty}</div>
  return (
    <div className="pb-chips">
      {ids.map(id => (
        <span key={id} className={`co-chip co-c${colour[id] ?? 0}`}>
          {byId[id]?.company_name || 'A company'}
        </span>
      ))}
    </div>
  )
}

function Modal({ title, onClose, children, footer }) {
  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label={title}>
        <div className="modal-hdr">
          <div className="modal-title">{title}</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </div>
    </div>
  )
}

/** Tick the companies that use this entry. `locked` cannot be unticked here. */
function CompanyPicker({ title, companies, initial, locked = [], lockedNote, note, onSave,
                         onClose }) {
  const [picked, setPicked] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const colour = companyColours(companies)

  function toggle(id) {
    setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]))
  }

  async function save() {
    setBusy(true); setError(null)
    try { await onSave(picked) } catch (e) {
      setError(errorText(e, 'The companies could not be saved.')); setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button className="btn btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
      <button className="btn btn-action" onClick={save} disabled={busy}>
        {busy ? 'Saving…' : 'Save'}
      </button>
    </>}>
      <div className="pb-pick">
        {companies.map(c => {
          const isLocked = locked.includes(c.entity_id)
          return (
            <label key={c.entity_id} className="pb-pick-row">
              <input type="checkbox" checked={picked.includes(c.entity_id)} disabled={isLocked}
                     onChange={() => toggle(c.entity_id)} />
              <span className={`co-dot co-c${colour[c.entity_id] ?? 0}`} aria-hidden="true" />
              <span>
                <span className="pb-pick-name">{c.company_name || 'A company'}</span>
                <span className="pb-pick-role">
                  {(c.roles || []).map(r => ROLE[r] || r).join(' and ')}
                </span>
              </span>
            </label>
          )
        })}
      </div>
      {locked.length > 0 && lockedNote && <div className="f-hint" style={{ marginTop: 10 }}>{lockedNote}</div>}
      {note && <div className="f-hint" style={{ marginTop: 10 }}>{note}</div>}
      {error && <div className="ep-error" role="alert">{error}</div>}
    </Modal>
  )
}

function AddressForm({ title, kind, companies, start, usedBy, correcting, lookups, onSave,
                       onClose }) {
  const [draft, setDraft] = useState({ ...EMPTY, ...(start || {}) })
  const [picked, setPicked] = useState([])
  const [makeDefault, setMakeDefault] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const byId = Object.fromEntries(companies.map(c => [c.entity_id, c]))
  const colour = companyColours(companies)

  async function save() {
    setBusy(true); setError(null)
    const address = Object.fromEntries(ADDRESS_KEYS.map(k => [k, draft[k] || null]))
    try {
      await onSave(correcting ? address
        : { kind, ...address, entity_ids: picked, make_default: makeDefault })
    } catch (e) {
      setError(errorText(e, 'The address could not be saved.')); setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button className="btn btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
      <button className="btn btn-action" onClick={save}
              disabled={busy || !(draft.line1 || draft.line2 || draft.line3)}>
        {busy ? 'Saving…' : correcting ? 'Save correction' : 'Add address'}
      </button>
    </>}>
      <AddressBlock value={draft} lookups={lookups}
                    onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))} />
      {correcting ? (
        <div className="f-hint" style={{ marginTop: 12 }}>
          Corrects this address for every company using it
          {usedBy.length ? `: ${usedBy.map(id => byId[id]?.company_name || 'a company').join(', ')}` : ''}.
          To give one company a different address, add a new address instead.
        </div>
      ) : (
        <>
          {companies.length > 0 && (
            <div className="pb-form-sec">
              <div className="tile-sec-lbl">Used by</div>
              <div className="pb-pick">
                {companies.map(c => (
                  <label key={c.entity_id} className="pb-pick-row">
                    <input type="checkbox" checked={picked.includes(c.entity_id)}
                           onChange={() => setPicked(p => (p.includes(c.entity_id)
                             ? p.filter(x => x !== c.entity_id) : [...p, c.entity_id]))} />
                    <span className={`co-dot co-c${colour[c.entity_id] ?? 0}`} aria-hidden="true" />
                    <span className="pb-pick-name">{c.company_name || 'A company'}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {kind === 'residential' && (
            <label className="check-row" style={{ marginTop: 12 }}>
              <input type="checkbox" checked={makeDefault} onChange={e => setMakeDefault(e.target.checked)} />
              Make this the default residential address
            </label>
          )}
          <div className="f-hint" style={{ marginTop: 10 }}>
            A company moved to a new address has to be reported to the Companies Registry
            with an ND2B within 15 days.
          </div>
        </>
      )}
      {error && <div className="ep-error" role="alert">{error}</div>}
    </Modal>
  )
}

function AddressCard({ kind, data, canEdit, lookups, contract, write }) {
  const titleId = useId()
  const [open, setOpen] = useState(null)
  const [error, setError] = useState(null)
  // For the actions that open no dialog of their own to show a refusal in.
  const act = promise => { setError(null); return write(promise).catch(e => {
    setError(errorText(e, 'That change could not be saved.')); setOpen(null) }) }
  const residential = kind === 'residential'
  const entries = data[kind] || []
  const companies = data.companies || []
  const title = residential ? 'Residential addresses' : 'Correspondence addresses'
  const warnings = address => Object.fromEntries(
    ['line1', 'line2', 'line3', 'city', 'country'].map(k =>
      [k, fieldWarning(contract, 'addresses', k, address?.[k])]))

  return (
    <section className="card mb-16 pb-card" aria-labelledby={titleId}>
      <div className="card-hdr">
        <div>
          <div className="card-title" id={titleId}>{title}</div>
          <div className="card-sub">
            {residential
              ? 'Filed privately with the Companies Registry. A company not given its own address files the default.'
              : 'Shown on the public register. A company not given one uses its residential address.'}
          </div>
        </div>
        {canEdit && (
          <button className="btn btn-outline btn-sm" onClick={() => setOpen({ type: 'new' })}>New</button>
        )}
      </div>

      {entries.length === 0 && (
        <div className="pb-empty">
          {residential ? 'No residential address on record.' : 'No company has its own correspondence address.'}
          {canEdit ? ' Add one with New.' : ''}
        </div>
      )}
      {entries.map(entry => (
        <div className="pb-entry" key={entry.address_id} data-entry={entry.address_id}>
          <div className="pb-entry-main">
            {entry.is_default && <span className="pb-badge">Default</span>}
            <AddressBlock value={entry.address} readOnly lookups={lookups}
                          warnings={warnings(entry.address)} />
            <CompanyChips ids={entry.used_by} companies={companies}
                          empty="No company uses this address." />
          </div>
          {canEdit && (
            <div className="pb-actions">
              {companies.length > 0 && (
                <button className="btn btn-ghost btn-sm" onClick={() => setOpen({ type: 'companies', entry })}>
                  Companies…
                </button>
              )}
              <button className="btn btn-ghost btn-sm" onClick={() => setOpen({ type: 'edit', entry })}>Edit</button>
              {residential && !entry.is_default && (
                <button className="btn btn-ghost btn-sm"
                        onClick={() => act(api.post(`/persons/${data.personId}/addresses/${entry.address_id}/default`, {}))}>
                  Make default
                </button>
              )}
              {!entry.is_default && entry.used_by.length === 0 && (
                <button className="btn btn-ghost btn-sm" onClick={() => setOpen({ type: 'remove', entry })}>
                  Remove
                </button>
              )}
            </div>
          )}
        </div>
      ))}
      {!residential && (data.correspondence_same_as_residential || []).length > 0 && (
        <div className="pb-entry pb-entry-same" data-entry="same-as-residential">
          <div className="pb-entry-main">
            <div className="pb-same">Same as residential address</div>
            <CompanyChips ids={data.correspondence_same_as_residential} companies={companies} />
          </div>
        </div>
      )}

      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 10 }}>
        <div className="al-body">{error}</div></div>}

      {open?.type === 'new' && (
        <AddressForm title={`New ${kind} address`} kind={kind} companies={companies}
                     lookups={lookups} onClose={() => setOpen(null)}
                     onSave={body => write(api.post(`/persons/${data.personId}/addresses`, body))
                       .then(() => setOpen(null))} />
      )}
      {open?.type === 'edit' && (
        <AddressForm title="Correct this address" kind={kind} companies={companies}
                     start={open.entry.address} usedBy={open.entry.used_by} correcting
                     lookups={lookups} onClose={() => setOpen(null)}
                     onSave={body => write(api.put(`/persons/${data.personId}/addresses/${open.entry.address_id}`, body))
                       .then(() => setOpen(null))} />
      )}
      {open?.type === 'companies' && (
        <CompanyPicker
          title="Companies using this address" companies={companies}
          initial={open.entry.used_by}
          // A company filing the default only because it has no address of its
          // own cannot be "unticked" off it — it has to be given another one.
          locked={open.entry.is_default ? open.entry.used_by : []}
          lockedNote="A company using the default stays on it until you choose another address for it."
          note={residential
            ? 'A company ticked here stops using its current residential address.'
            : 'A company unticked here goes back to using its residential address.'}
          onClose={() => setOpen(null)}
          onSave={ids => write(api.put(`/persons/${data.personId}/addresses/${open.entry.address_id}/companies`,
            { kind, entity_ids: ids })).then(() => setOpen(null))} />
      )}
      {open?.type === 'remove' && (
        <ConfirmDialog title="Remove address" onCancel={() => setOpen(null)}
                       confirmLabel="Remove"
                       onConfirm={() => act(api.del(`/persons/${data.personId}/addresses/${open.entry.address_id}?kind=${kind}`))
                         .then(() => setOpen(null))}>
          <p>This address leaves {kind === 'residential' ? 'the residential' : 'the correspondence'} list.
            No company uses it, so nothing is filed differently.</p>
        </ConfirmDialog>
      )}
    </section>
  )
}

function IdentityCard({ data, canEdit, lookups, write }) {
  const titleId = useId()
  const [open, setOpen] = useState(null)
  const companies = data.companies || []
  const docs = data.identity || []
  return (
    <section className="card mb-16 pb-card" aria-labelledby={titleId}>
      <div className="card-hdr">
        <div>
          <div className="card-title" id={titleId}>Identification by company</div>
          <div className="card-sub">
            Each company files one document of each type; a company not given one files the
            primary. Add or remove documents under Identity Documents.
          </div>
        </div>
      </div>
      {docs.length === 0 && <div className="pb-empty">No identity document on record.</div>}
      {docs.map(doc => (
        <div className="pb-entry" key={doc.document_id} data-entry={doc.document_id}>
          <div className="pb-entry-main">
            <div className="pb-doc">
              <span className="pb-doc-type">{ID_TYPE[doc.id_type] || doc.id_type}</span>
              <span className="pb-doc-number">{doc.id_number}</span>
              {doc.issuing_country && (
                <span className="td-muted">{countryName(doc.issuing_country, lookups)}</span>
              )}
              {doc.is_primary && <span className="pb-badge">Primary</span>}
            </div>
            <CompanyChips ids={doc.used_by} companies={companies}
                          empty="No company files this document." />
          </div>
          {canEdit && companies.length > 0 && (
            <div className="pb-actions">
              <button className="btn btn-ghost btn-sm" onClick={() => setOpen(doc)}>Companies…</button>
            </div>
          )}
        </div>
      ))}
      {open && (
        <CompanyPicker
          title={`Companies filing this document — ${ID_TYPE[open.id_type] || open.id_type} ${open.id_number}`}
          companies={companies} initial={open.used_by}
          locked={open.is_primary ? open.used_by : []}
          lockedNote="A company filing the primary stays on it until you choose another document for it."
          note="A company ticked here files this document in place of its current one of the same type."
          onClose={() => setOpen(null)}
          onSave={ids => write(api.put(`/persons/${data.personId}/identity-documents/${open.document_id}/companies`,
            { entity_ids: ids })).then(() => setOpen(null))} />
      )}
    </section>
  )
}

export default function ParticularsByCompany({ personId, canEdit, lookups, contract = null,
                                               refreshKey, onChanged }) {
  const [data, setData] = useState(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    api.get(`/persons/${personId}/particulars-by-company`)
      .then(d => { setData(d); setFailed(false) })
      .catch(() => setFailed(true))
  }, [personId])

  useEffect(() => { load() }, [load, refreshKey])

  // Every write answers with the refreshed book. A refusal is rethrown so the
  // dialog that asked can show it where the operator is looking.
  async function write(promise) {
    const next = await promise
    if (next && Array.isArray(next.residential)) setData(next)
    else load()
    onChanged?.()
    return next
  }

  if (failed) {
    return (
      <div className="card mb-16">
        <div className="card-title">Identification and addresses</div>
        <div className="card-note card-note-warn" role="status">
          This person&apos;s addresses and identity documents by company could not be loaded.
          Reload the page to try again.
        </div>
      </div>
    )
  }
  if (!data || !Array.isArray(data.residential)) return null
  const book = { ...data, personId }
  return (
    <>
      <IdentityCard data={book} canEdit={canEdit} lookups={lookups} write={write} />
      <AddressCard kind="residential" data={book} canEdit={canEdit} lookups={lookups}
                   contract={contract} write={write} />
      <AddressCard kind="correspondence" data={book} canEdit={canEdit} lookups={lookups}
                   contract={contract} write={write} />
    </>
  )
}
