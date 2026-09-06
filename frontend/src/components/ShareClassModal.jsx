import { useState } from 'react'
import FormField from './FormField.jsx'
import { useLookups, optionsFor } from '../lib/lookups.js'

/**
 * One class of shares — CR's section 11 — added or edited in a dialog.
 *
 * WHY A DIALOG AND NOT AN INLINE FORM. The editor used to render inside the
 * tile as a `.form-grid`, with its Cancel and Save in a
 * `.f-group.full.hdr-actions`. `.f-group` is a column flex box, so the two
 * buttons stacked vertically and centred — the only pair of buttons in the app
 * that did not sit side by side at the bottom right, and on the Add path they
 * appeared above the row they belonged to. Every other add/edit in this app is
 * a modal with a right-aligned footer (`LinkPartyModal`, `AddCompanyModal`,
 * `UploadDocumentModal`); this now is too, so there is one shape to learn.
 */

//: CR's own headings, in CR's order.
//:
//: "Total Number" is a COUNT of shares and "Total Amount" is money. The schema
//: could not tell them apart until migration 028 and they genuinely differ on
//: 60 of Viewpoint's 5,740 rows — 200 shares worth HK$20,000 — so the labels
//: are load-bearing, not decoration.
export const SHARE_CLASS_FIELDS = [
  { key: 'class_name', label: 'Class of Shares' },
  // CR's 54 codes, NOT the 162 ISO ones in `lookup_values`: CR wants RMB where
  // ISO says CNY. EUR/HKD/USD are served first (routers/lookups.py).
  { key: 'currency', label: 'Currency', lookup: 'cr_currency' },
  { key: 'total_issued', label: 'Total Number' },
  { key: 'issued_amount', label: 'Total Amount' },
  { key: 'total_paid', label: 'Total Amount Paid up or Regarded as Paid up' },
]

//: The value the Class of Shares dropdown carries for "none of these".
const OTHER = '__other__'

/**
 * Class of Shares: a dropdown over the four names GSHK actually uses, and a
 * text box for anything else.
 *
 * CR VALIDATES NOTHING HERE — `clsOfShares` is free text of 100 characters on
 * both forms — so the dropdown cannot be closed. What it fixes is spelling.
 * `share_classes` has a UNIQUE (entity_id, class_name), so "Ordinary" and
 * "ORDINARY" typed on two different days become two classes of one class, and
 * Schedule 1 then files the same members twice under both.
 */
function ClassOfShares({ value, options, onChange }) {
  const known = options.some(o => o.code === value)
  // A stored name that isn't in the list keeps the box open on it rather than
  // silently snapping to the first option — 5,740 legacy rows exist.
  const [freeform, setFreeform] = useState(!!value && !known)
  const select = freeform ? OTHER : (value ?? '')

  return (
    <div className="f-group full">
      <label className="f-label" htmlFor="f_class_name_pick">Class of Shares</label>
      <select id="f_class_name_pick" className="f-select" value={select}
              onChange={e => {
                if (e.target.value === OTHER) { setFreeform(true); onChange('') }
                else { setFreeform(false); onChange(e.target.value) }
              }}>
        <option value="">Select…</option>
        {options.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
        <option value={OTHER}>Other…</option>
      </select>
      {freeform && (
        <input id="f_class_name" className="f-input" type="text"
               style={{ marginTop: 8 }} aria-label="Class of Shares (other)"
               placeholder="e.g. Redeemable Preference"
               value={value ?? ''} onChange={e => onChange(e.target.value)} />
      )}
    </div>
  )
}

export default function ShareClassModal({ row, busy, onClose, onSave }) {
  const isEdit = !!row
  const lookups = useLookups()
  const [draft, setDraft] = useState(() => Object.fromEntries(
    SHARE_CLASS_FIELDS.map(f => [f.key, (row?.[f.key] ?? '').toString()])))

  const set = (k, v) => setDraft(d => ({ ...d, [k]: v }))

  async function save() {
    // On edit, only what changed: the API writes one audit row per changed
    // field, so re-sending untouched values is noise in the trail.
    const changed = isEdit
      ? Object.fromEntries(Object.entries(draft).filter(
          ([k, v]) => String(row?.[k] ?? '') !== String(v)))
      : draft
    if (await onSave(changed)) onClose()
  }

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog"
           aria-label={isEdit ? 'Edit Class of Shares' : 'Add Class of Shares'}>
        <div className="modal-hdr">
          <div className="modal-title">
            {isEdit ? 'Edit Class of Shares' : 'Add Class of Shares'}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          <div className="upload-owner-line">
            Section 11 of the annual return — what this company’s share capital
            <b> is</b>, whether or not anyone currently holds it.
          </div>
          <div className="form-grid">
            <ClassOfShares
              value={draft.class_name}
              options={optionsFor(lookups?.share_class_name, null)}
              onChange={v => set('class_name', v)}
            />
            {SHARE_CLASS_FIELDS.filter(f => f.key !== 'class_name').map(f => (
              <FormField key={f.key} field={{ ...f, full: true }} value={draft[f.key]}
                         lookups={lookups} onChange={set} />
            ))}
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : isEdit ? 'Save Changes' : 'Add Class'}
          </button>
        </div>
      </div>
    </div>
  )
}
