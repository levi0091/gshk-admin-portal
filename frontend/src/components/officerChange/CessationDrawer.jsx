import { useState } from 'react'
import Drawer from './Drawer.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

const ROLE = { director: 'Director', company_secretary: 'Company Secretary' }

/**
 * One key per current officer, whichever register holds them. A secretary on
 * the secretary register only has no officer row yet (`officer_id` null), so
 * it is chosen by its register id and the entry promotes it.
 */
export function officerRef(o) {
  if (o?.officer_id) return o.officer_id
  return o?.secretary_id ? `cs:${o.secretary_id}` : ''
}

function reasonFor(o) {
  return o?.party_type === 'individual' ? (o.date_of_death ? 'D' : 'R') : ''
}

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/**
 * Add or edit a cessation (spec §2): the officer, CR's reason — for a natural
 * person only, pre-set to Deceased when the profile carries a date of death —
 * and the date. Nothing else: the officer's particulars come from their
 * profile, and alternate directors are out of scope.
 *
 * A DEATH ASKS FOR ITS DATE (Levi 2026-10-18). Deceased used to be pre-set only
 * for people whose imported record already carried a date of death, and there
 * was nowhere to enter one. It is required on a death, pre-filled from the
 * profile, and written to the person's profile once the form is filed. A
 * person ceases on the day they die, so the cessation date follows it — until
 * the operator types one of their own.
 *
 * `preselect` is an `officerRef`, set when the operator pressed Cease on an
 * officer's row on the company profile.
 */
export default function CessationDrawer({ data, entry, preselect, onClose, onSaved }) {
  const editing = Boolean(entry)
  const officers = data.officers || []
  const initial = !editing && preselect && officers.find(o => !o.pending && (
    officerRef(o) === preselect
    // The profile's Secretary tile reads the register, so it sends `cs:<id>`
    // even for a secretary who also has an officer row.
    || (preselect.startsWith('cs:') && (o.secretary_ids || []).includes(preselect.slice(3)))))
  const [officerId, setOfficerId] = useState(entry?.officer_id || (initial ? officerRef(initial) : ''))
  const officer = officers.find(o => officerRef(o) === officerId)
  const individual = editing ? entry.party_type === 'individual' : officer?.party_type === 'individual'
  const [reason, setReason] = useState(entry?.cessation_reason || reasonFor(initial))
  const [died, setDied] = useState(entry?.date_of_death || initial?.date_of_death || '')
  const [date, setDate] = useState(entry?.effective_date || initial?.date_of_death || '')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const name = editing ? entry.party?.name : officer?.name

  function choose(id) {
    const next = officers.find(o => officerRef(o) === id)
    setOfficerId(id)
    setReason(reasonFor(next))
    setDied(next?.date_of_death || '')
    if (!date || date === died) setDate(next?.date_of_death || '')
  }

  function changeDied(value) {
    if (!date || date === died) setDate(value)
    setDied(value)
  }

  async function save() {
    setError(null); setSaving(true)
    const who = officerId.startsWith('cs:')
      ? { secretary_id: officerId.slice(3) } : { officer_id: officerId }
    const person = individual
      ? { cessation_reason: reason, date_of_death: reason === 'D' ? died : null } : {}
    try {
      const next = editing
        ? await officerChangeApi.updateEntry(data.id, entry.id, { effective_date: date, ...person })
        : await officerChangeApi.addEntry(data.id, {
          kind: 'cessation', ...who, effective_date: date, ...person })
      onSaved(next)
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setSaving(false)
    }
  }

  // The date may wait until Signing (Jacqueline A1).
  const ready = (editing || officerId) && (!individual || reason)
    && (!individual || reason !== 'D' || died)
  return (
    <Drawer title={editing ? 'Edit cessation' : 'Add cessation'}
            sub="An officer leaving the company. CR is told the date and, for a person, the reason."
            onClose={onClose}
            footer={<>
              <button className="btn btn-outline" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" disabled={!ready || saving} onClick={save}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Add cessation'}
              </button>
            </>}>
      <div className="f-group">
        <label className="f-label" htmlFor="oc-officer">Officer <span className="f-req">*</span></label>
        {editing ? (
          <div className="f-static">{entry.party?.name} · {ROLE[entry.capacity]}</div>
        ) : (
          <select id="oc-officer" className="f-select" value={officerId}
                  onChange={e => choose(e.target.value)}>
            <option value="">Choose a current officer…</option>
            {officers.map(o => (
              <option key={officerRef(o)} value={officerRef(o)} disabled={o.pending}>
                {o.name} — {ROLE[o.role]}{o.pending ? ' (already on this form)' : ''}
              </option>
            ))}
          </select>
        )}
        {officer?.register_only && (
          <div className="f-hint">
            Held on the secretary register only. Adding this cessation also records
            them on the company&apos;s officer list, so the filing can end both.
          </div>
        )}
      </div>

      {individual && (
        <fieldset className="f-group" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="f-label">Reason for cessation <span className="f-req">*</span></legend>
          <label className="check-row">
            <input type="radio" name="oc-reason" value="R" checked={reason === 'R'}
                   onChange={() => setReason('R')} /> Resignation / Others
          </label>
          <label className="check-row">
            <input type="radio" name="oc-reason" value="D" checked={reason === 'D'}
                   onChange={() => setReason('D')} /> Deceased
          </label>
        </fieldset>
      )}

      {individual && reason === 'D' && (
        <div className="f-group">
          <label className="f-label" htmlFor="oc-died">Date of death <span className="f-req">*</span></label>
          <input id="oc-died" type="date" className="f-input" value={died} max={todayIso()}
                 onChange={e => changeDied(e.target.value)} />
          <div className="f-hint">
            Not on CR&apos;s form. It is saved to {name || 'the person'}&apos;s profile once the form is filed.
          </div>
        </div>
      )}

      <div className="f-group">
        <label className="f-label" htmlFor="oc-ces-date">Date of cessation</label>
        <input id="oc-ces-date" type="date" className="f-input" value={date}
               onChange={e => setDate(e.target.value)} />
        <div className="f-hint">
          Optional. Leave blank to fill in the most recent date at Signing — the
          Companies Registry must receive the form within 15 days of the change.
        </div>
      </div>

      {error && <div className="alert al-danger" role="alert"><div className="al-body">{error}</div></div>}
    </Drawer>
  )
}
