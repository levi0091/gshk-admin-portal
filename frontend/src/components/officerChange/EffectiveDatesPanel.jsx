import { useState } from 'react'
import { hongKongTodayISO } from '../../lib/anniversary.js'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/** Every change whose date was left blank when the client was sent the form. */
export function deferredChanges(data) {
  const out = []
  for (const entry of data.entries || []) {
    const name = entry.party?.name || 'An officer'
    if (entry.kind === 'change') {
      for (const item of entry.items || []) {
        if (item.deferred && !item.omitted) {
          out.push({ key: `${entry.id}:${item.key}`, entryId: entry.id, itemKey: item.key,
                     label: `${name} — ${item.label || item.key}`, value: item.effective_date || '' })
        }
      }
    } else if (entry.date_deferred) {
      out.push({ key: entry.id, entryId: entry.id, itemKey: null, label: name,
                 value: entry.effective_date || '' })
    }
  }
  return out
}

/**
 * The effective dates left blank when the client was sent the form
 * (Jacqueline A1: "most of our clients ... prefer to let us fill in the most
 * recent date ... we can place the effective date button on the 'Signing –
 * e-Page' and 'Signing – Paper' pages before we complete the signature").
 *
 * Only a date that was blank in the client's copy can be entered here — one
 * they saw is changed by restarting verification. Nothing is signed or filed
 * while one is still empty (the backend refuses too), and none may be after
 * today: CR records what has happened.
 */
export default function EffectiveDatesPanel({ data, reload, can }) {
  const rows = deferredChanges(data)
  const [draft, setDraft] = useState(() => Object.fromEntries(rows.map(r => [r.key, r.value])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (rows.length === 0) return null

  const changed = rows.filter(r => (draft[r.key] || '') !== (r.value || '') && draft[r.key])

  async function save() {
    setBusy(true); setError(null)
    try {
      let last = null
      for (const row of changed) {
        last = await officerChangeApi.setEffectiveDate(data.id, row.entryId, draft[row.key], row.itemKey)
      }
      await reload(last)
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setBusy(false)
    }
  }

  const missing = (data.dates_missing || []).length
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-hdr">
        <div>
          <div className="card-title">Effective dates</div>
          <div className="card-sub">
            The client was told these dates would be confirmed when GSHK files. Enter the most
            recent date for each; the Companies Registry must receive the form within 15 days of it.
          </div>
        </div>
        {missing > 0 && <span className="badge b-pending-aml">{missing} to enter</span>}
      </div>
      <div className="oc-dates">
        {rows.map(row => (
          <div className="oc-date-row" key={row.key}>
            <label htmlFor={`oc-date-${row.key}`}>Effective date — {row.label}</label>
            {can.write ? (
              <input id={`oc-date-${row.key}`} type="date" className="f-input"
                     max={hongKongTodayISO()} value={draft[row.key] || ''}
                     onChange={e => setDraft(d => ({ ...d, [row.key]: e.target.value }))} />
            ) : (
              <span id={`oc-date-${row.key}`} className="td-muted">{row.value || 'Not entered yet'}</span>
            )}
          </div>
        ))}
      </div>
      {can.write && (
        <div className="oc-send-row">
          <button className="btn btn-primary" disabled={busy || changed.length === 0} onClick={save}>
            {busy ? 'Saving…' : 'Save dates'}
          </button>
        </div>
      )}
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 10 }}>
        <div className="al-body">{error}</div></div>}
    </div>
  )
}
