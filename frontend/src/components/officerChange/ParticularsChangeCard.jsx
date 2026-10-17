import { useState } from 'react'
import { Link } from 'react-router-dom'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'
import { officerRef } from './CessationDrawer.jsx'
import { formatDate } from '../../lib/format.js'
import { crAddressLines } from '../../lib/crAddress.js'
import { useLookups } from '../../lib/lookups.js'

const ROLE = { director: 'Director', company_secretary: 'Company Secretary' }
const ADDRESS_KEYS = new Set(['residential_address', 'correspondence_address', 'address'])

/**
 * An address in CR's five labelled lines (Jacqueline B3: "Please list the
 * address format"), "(blank)" where a line is empty — so the operator sees
 * which line moved, not two run-on strings to compare by eye.
 */
function AddressValue({ value, lookups }) {
  if (!value) return <span className="oc-blank">—</span>
  return (
    <dl className="oc-addr">
      {crAddressLines(value, lookups).map(line => (
        <div key={line.label} className="oc-addr-line">
          <dt>{line.label}</dt>
          <dd>{line.value || <span className="oc-blank">(blank)</span>}</dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * ND2B (answer 14): the operator does NOT type changes here. Each officer's
 * card lists only what differs between what CR holds and their profile now,
 * read-only. The operator gives each line its effective date, and may omit a
 * line that is genuine but not for this form. A value that is wrong is put
 * right on the profile, and the line disappears on the next load.
 */
export default function ParticularsChangeCard({ data, reload, can }) {
  const entries = (data.entries || []).filter(e => e.kind === 'change')
  const editable = data.editable && can.write
  const onCase = new Set(entries.map(e => e.officer_id).filter(Boolean))
  // Keyed by `officerRef`: a secretary held only on the register has no officer
  // row yet (officer_id null) and is added by its register id.
  const available = (data.officers || []).filter(o => !o.officer_id || !onCase.has(o.officer_id))
  function addOfficer(ref) {
    const who = ref.startsWith('cs:') ? { secretary_id: ref.slice(3) } : { officer_id: ref }
    run(officerChangeApi.addEntry(data.id, { kind: 'change', ...who }))
  }
  const lookups = useLookups()
  const [adding, setAdding] = useState('')
  const [omitting, setOmitting] = useState(null)
  const [removing, setRemoving] = useState(null)
  const [error, setError] = useState(null)

  async function run(promise) {
    setError(null)
    try { await reload(await promise) } catch (e) { setError(errorOf(e).message) }
  }

  const setItem = (entry, key, change) =>
    run(officerChangeApi.updateEntry(data.id, entry.id, { items: [{ key, ...change }] }))

  return (
    <div className="card">
      <div className="card-hdr">
        <div>
          <div className="card-title">Changes on this form</div>
          <div className="card-sub">
            What each officer's profile now says that the Companies Registry does not know yet.
            To correct a value, change it on the profile.
          </div>
        </div>
        {editable && available.length > 0 && (
          <div className="row gap-8">
            <select className="f-select" aria-label="Officer to add" value={adding}
                    onChange={e => setAdding(e.target.value)}>
              <option value="">Add an officer…</option>
              {available.map(o => (
                <option key={officerRef(o)} value={officerRef(o)}>{o.name} — {ROLE[o.role]}</option>
              ))}
            </select>
            <button className="btn btn-primary" disabled={!adding}
                    onClick={() => { addOfficer(adding); setAdding('') }}>Add officer</button>
          </div>
        )}
      </div>

      {data.anniversary_default && entries.some(e => (e.items || []).some(
        i => !i.omitted && i.effective_date === data.anniversary_default)) && (
        // Jacqueline B1: dated the anniversary unless there is a special request,
        // so the ND2B and the NAR1 made up to that date say the same thing.
        <div className="f-hint" style={{ marginBottom: 10 }}>
          Dated the anniversary, {formatDate(data.anniversary_default)}, so this ND2B matches the
          NAR1 made up to that date. Change a line's date if the client asked for another.
        </div>
      )}

      {entries.length === 0 && (
        <div className="empty-state" style={{ padding: 16 }}>Add the officer whose particulars changed.</div>
      )}

      {entries.map(entry => (
        <div className="oc-pc" key={entry.id} data-testid={`entry-${entry.id}`}>
          <div className="oc-pc-hd">
            <span className="oc-pc-name">{entry.party?.name}</span>
            <span className="td-muted">{ROLE[entry.capacity]}</span>
            {entry.party?.profile_path && <Link to={entry.party.profile_path}>Open profile</Link>}
            {editable && (
              <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}
                      onClick={() => setRemoving(entry)}>Remove officer</button>
            )}
          </div>
          {(entry.items || []).length === 0 ? (
            <div className="f-hint">No changes on the profile since CR was last told.</div>
          ) : (
            <table className="oc-pc-items">
              <thead><tr><th>Item</th><th>Registered with CR</th><th>Now</th>
                <th>Effective date</th><th /></tr></thead>
              <tbody>
                {entry.items.map(item => (
                  <tr key={item.key} className={item.omitted ? 'omitted' : ''}>
                    <td>({item.cr_item}) {item.label}</td>
                    <td className="oc-old">{ADDRESS_KEYS.has(item.key)
                      ? <AddressValue value={item.old} lookups={lookups} /> : item.old_text}</td>
                    <td className="oc-new">{ADDRESS_KEYS.has(item.key)
                      ? <AddressValue value={item.new} lookups={lookups} /> : item.new_text}</td>
                    <td>
                      {/* A role that may not edit sees the date, not a dead input. */}
                      {editable ? (
                        <input type="date" className="f-input" aria-label={`Effective date — ${item.label}`}
                               value={item.effective_date || ''} disabled={item.omitted}
                               onChange={e => setItem(entry, item.key, { effective_date: e.target.value })} />
                      ) : (
                        <span className="td-muted">{item.effective_date ? formatDate(item.effective_date) : '—'}</span>
                      )}
                    </td>
                    <td>
                      {editable && (item.omitted
                        ? <button className="btn btn-ghost btn-sm"
                                  onClick={() => setItem(entry, item.key, { omitted: false })}>Include</button>
                        : <button className="btn btn-ghost btn-sm"
                                  onClick={() => setOmitting({ entry, item })}>Omit</button>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}

      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
        <div className="al-body">{error}</div></div>}

      {omitting && (
        <div className="modal-confirm" role="alertdialog" aria-label="Omit this change">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Leave "{omitting.item.label}" off this ND2B?</div>
            <div className="modal-confirm-text">
              The change stays on {omitting.entry.party?.name}'s profile and stays pending: the
              Companies Registry has still not been told. If the value is wrong rather than
              unwanted, change it back on the profile instead.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setOmitting(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={() => {
                setItem(omitting.entry, omitting.item.key, { omitted: true }); setOmitting(null)
              }}>Omit</button>
            </div>
          </div>
        </div>
      )}
      {removing && (
        <div className="modal-confirm" role="alertdialog" aria-label="Remove officer">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Remove {removing.party?.name} from this form?</div>
            <div className="modal-confirm-text">Their changes stay on the profile and stay pending.</div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setRemoving(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={() => {
                run(officerChangeApi.removeEntry(data.id, removing.id)); setRemoving(null)
              }}>Remove</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
