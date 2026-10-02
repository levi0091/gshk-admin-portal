import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { crAddressLines } from '../lib/crAddress.js'
import AddressBlock from './AddressBlock.jsx'

const ROLE = { director: 'Director', company_secretary: 'Company Secretary' }
const KEYS = ['line1', 'line2', 'line3', 'city', 'state_region', 'postal_code', 'country']

function pick(address) {
  return Object.fromEntries(KEYS.map(k => [k, (address || {})[k] || '']))
}

/**
 * The correspondence address of each appointment (Jacqueline B4, AQ5).
 *
 * "In the individual profile, the correspondence address part and residential
 * address part are not shown separately." They are different facts: the
 * residential address is the person's (and private — CR's PI sheet), while a
 * correspondence address belongs to ONE appointment and is public, and a
 * director may give each company a different one. So one row per company,
 * reading "Same as residential address" or the address in CR's own lines.
 *
 * Edit writes that appointment only. The backend captures what CR holds for
 * that company first, so the change is reported as an ND2B for that company
 * and no other. Without `persons:write` there is no Edit button at all.
 */
export default function CorrespondenceAddressCard({ personId, canEdit, lookups }) {
  const [rows, setRows] = useState(null)
  const [editing, setEditing] = useState(null)
  const [same, setSame] = useState(true)
  const [draft, setDraft] = useState(pick(null))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    api.get(`/persons/${personId}/correspondence-addresses`)
      .then(d => setRows(Array.isArray(d?.correspondence_addresses) ? d.correspondence_addresses : []))
      .catch(() => setRows([]))
  }, [personId])

  useEffect(() => { load() }, [load])

  if (!rows || rows.length === 0) return null

  function open(row) {
    setEditing(row); setSame(!row.address); setDraft(pick(row.address)); setError(null)
  }

  async function save() {
    setSaving(true); setError(null)
    try {
      const body = same ? { same_as_residential: true } : pick(draft)
      const next = await api.put(
        `/persons/${personId}/appointments/${editing.officer_id}/correspondence-address`, body)
      setRows(Array.isArray(next?.correspondence_addresses) ? next.correspondence_addresses : rows)
      setEditing(null)
    } catch (e) {
      setError(e?.detail?.message || e?.message || 'The address could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">Correspondence Address</div>
          <div className="card-sub">
            Given to each company separately and shown on the public register. The
            residential address above is filed privately.
          </div>
        </div>
      </div>
      {rows.map(row => (
        <div className="role-item" key={row.officer_id}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="role-item-main">{row.company_name || 'A company'}</div>
            <div className="role-item-sub">{ROLE[row.role] || row.role}</div>
            {row.address ? (
              <div className="kv-list" style={{ marginTop: 6 }}>
                {crAddressLines(row.address, lookups).map(line => (
                  <div className="kv-row" key={line.label}>
                    <span className="kv-key">{line.label}</span>
                    <span className="kv-val">{line.value || <span className="td-muted">—</span>}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="f-hint" style={{ marginTop: 4 }}>Same as residential address</div>
            )}
          </div>
          {canEdit && (
            <button className="btn-edit" onClick={() => open(row)}>Edit</button>
          )}
        </div>
      ))}

      {editing && (
        <div className="overlay" onClick={e => { if (e.target === e.currentTarget) setEditing(null) }}>
          <div className="modal" role="dialog"
               aria-label={`Correspondence address — ${editing.company_name || 'this company'}`}>
            <div className="modal-hdr">
              <div className="modal-title">
                Correspondence address — {editing.company_name || 'this company'}
              </div>
              <button className="modal-close" onClick={() => setEditing(null)} aria-label="Close">×</button>
            </div>
            <div className="modal-body">
              <label className="check-row" style={{ marginBottom: 12 }}>
                <input type="checkbox" checked={same} onChange={e => setSame(e.target.checked)} />
                Same as residential address
              </label>
              {!same && (
                <AddressBlock value={draft} lookups={lookups}
                              onChange={(k, v) => setDraft(d => ({ ...d, [k]: v }))} />
              )}
              <div className="f-hint" style={{ marginTop: 10 }}>
                Applies to this appointment only. The Companies Registry must be told
                with an ND2B for this company within 15 days.
              </div>
              {error && <div className="ep-error" role="alert">{error}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setEditing(null)} disabled={saving}>
                Cancel
              </button>
              <button className="btn btn-action" onClick={save}
                      disabled={saving || (!same && !(draft.line1 || draft.line2 || draft.line3))}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
