import { useState } from 'react'
import { Link } from 'react-router-dom'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

const ROLE = { director: 'Director', company_secretary: 'Company Secretary' }

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
  const onCase = new Set(entries.map(e => e.officer_id))
  const available = (data.officers || []).filter(o => !onCase.has(o.officer_id))
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
                <option key={o.officer_id} value={o.officer_id}>{o.name} — {ROLE[o.role]}</option>
              ))}
            </select>
            <button className="btn btn-primary" disabled={!adding}
                    onClick={() => { run(officerChangeApi.addEntry(data.id,
                      { kind: 'change', officer_id: adding })); setAdding('') }}>Add officer</button>
          </div>
        )}
      </div>

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
                    <td className="oc-old">{item.old_text}</td>
                    <td className="oc-new">{item.new_text}</td>
                    <td>
                      <input type="date" className="f-input" aria-label={`Effective date — ${item.label}`}
                             value={item.effective_date || ''} disabled={!editable || item.omitted}
                             onChange={e => setItem(entry, item.key, { effective_date: e.target.value })} />
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
