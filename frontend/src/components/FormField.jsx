import { optionsFor } from '../lib/lookups.js'

/**
 * One editable field. Renders a <select> when the field descriptor names a
 * lookup category, otherwise a plain input.
 *
 * Shared by the profile pages and the add modals so a field is defined once and
 * behaves the same wherever it appears.
 */
export default function FormField({ field, value, lookups, onChange }) {
  const { key, label, type, lookup, required, placeholder } = field
  const id = `f_${key}`

  // A boolean (nd2-change-requests, review B4). It reports a REAL boolean --
  // `e.target.checked`, never the string "true", which Python would read as
  // true for "false" too -- and renders the label beside the box rather than
  // above it, since the label IS the sentence the box answers.
  if (type === 'checkbox') {
    return (
      <div className={`f-group${field.full ? ' full' : ''}`}>
        <label className="f-label" htmlFor={id}
               style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
          <input
            id={id}
            type="checkbox"
            checked={value === true}
            onChange={e => onChange(key, e.target.checked)}
          />
          <span>{label}</span>
        </label>
      </div>
    )
  }

  const control = lookup ? (
    <select
      id={id}
      className="f-select"
      value={value ?? ''}
      onChange={e => onChange(key, e.target.value)}
    >
      <option value="">Select…</option>
      {optionsFor(lookups?.[lookup], value).map(o => (
        <option key={o.code} value={o.code}>{o.label}</option>
      ))}
    </select>
  ) : (
    <input
      id={id}
      className="f-input"
      type={type || 'text'}
      placeholder={placeholder || ''}
      value={value ?? ''}
      onChange={e => onChange(key, e.target.value)}
    />
  )

  return (
    <div className={`f-group${field.full ? ' full' : ''}`}>
      <label className="f-label" htmlFor={id}>
        {label}{required && <span className="f-req"> *</span>}
      </label>
      {control}
    </div>
  )
}

/**
 * The stored code rendered for display — "M" is not an answer to "Gender".
 * Falls back to the raw value when it isn't in the list, so legacy Viewpoint
 * values still show rather than vanishing.
 */
export function displayValue(field, value, lookups) {
  // React prints `true` as nothing, so a ticked box needs words (review B4).
  if (field.type === 'checkbox') return value === true ? 'Yes' : null
  if (value == null || value === '') return null
  if (!field.lookup) return value
  const values = lookups?.[field.lookup]
  const match = Array.isArray(values) && values.find(o => o.code === value)
  return match ? match.label : value
}
