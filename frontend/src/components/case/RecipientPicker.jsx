import { useState } from 'react'

/**
 * Who the verification email goes to (wireframe_v11 s5, "CC Recipients").
 *
 * Every current director is seeded by the backend and shown as a removable
 * chip, because a three-director board is one message with three recipients —
 * not three separate sends, and not one send to whichever director sorted
 * first.
 *
 * Directors with NO address on record are rendered too, dashed and muted, with
 * the reason beside them. Omitting them would make a three-director board look
 * like a two-director board, which is the one thing an operator cannot notice
 * by looking.
 */

//: Deliberately the same shape the backend enforces (routers/cases._ADDRESS).
//: Client-side validation here is a courtesy — it stops a typo before a round
//: trip — and the server still refuses anything this misses.
const ADDRESS = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

export function isAddress(value) {
  return ADDRESS.test((value || '').trim())
}

export default function RecipientPicker({
  recipients, to, onChange, disabled, maxRecipients = 20,
}) {
  const [draft, setDraft] = useState('')
  const [addError, setAddError] = useState(null)

  // Which chips came from the company record, so a removed director can be put
  // back by name rather than retyped from memory.
  const byEmail = new Map()
  for (const r of recipients || []) {
    if (r.email) byEmail.set(r.email.toLowerCase(), r)
  }
  const missing = (recipients || []).filter(r => !r.email)
  const dropped = (recipients || []).filter(
    r => r.email && !to.some(a => a.toLowerCase() === r.email.toLowerCase()))

  function add(address) {
    const value = (address || '').trim()
    if (!value) return
    if (!isAddress(value)) {
      setAddError(`"${value}" is not an email address.`)
      return
    }
    if (to.some(a => a.toLowerCase() === value.toLowerCase())) {
      // Not an error the operator has to clear — the address is already there,
      // which is what they were asking for.
      setDraft(''); setAddError(null)
      return
    }
    if (to.length >= maxRecipients) {
      setAddError(`One verification email carries at most ${maxRecipients} recipients.`)
      return
    }
    onChange([...to, value])
    setDraft(''); setAddError(null)
  }

  function remove(address) {
    onChange(to.filter(a => a.toLowerCase() !== address.toLowerCase()))
    setAddError(null)
  }

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">Recipients</div>
          <div className="card-sub">
            Every current director is added automatically. Remove anyone who
            should not receive it, or add someone else.
          </div>
        </div>
      </div>

      {to.length === 0 ? (
        <div className="alert al-warn" role="alert">
          <span className="al-icon">⚠</span>
          <div className="al-body">
            No recipients. Add at least one address before sending.
          </div>
        </div>
      ) : (
        <div className="chip-row" data-testid="recipient-chips">
          {to.map(address => {
            const known = byEmail.get(address.toLowerCase())
            return (
              <span className="chip" key={address}>
                {known && <span className="chip-name">{known.name}</span>}
                <span className="chip-addr">{address}</span>
                <button type="button" className="chip-x" disabled={disabled}
                        aria-label={`Remove ${address}`}
                        onClick={() => remove(address)}>×</button>
              </span>
            )
          })}
        </div>
      )}

      {missing.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="f-hint" style={{ marginBottom: 6 }}>
            On the board, but not reachable by email:
          </div>
          <div className="chip-row">
            {missing.map(r => (
              <span className="chip chip-missing" key={r.person_id || r.name}
                    title={r.reason || 'no email address on record'}>
                {r.name} — {r.reason || 'no email address on record'}
              </span>
            ))}
          </div>
        </div>
      )}

      {dropped.length > 0 && (
        <div className="f-hint" style={{ marginTop: 12 }}>
          Removed from this send: {dropped.map(r => r.name).join(', ')}.
        </div>
      )}

      <div className="recip-add">
        <input className="f-input" value={draft} disabled={disabled}
               aria-label="Add a recipient"
               placeholder="someone.else@example.com"
               onChange={e => { setDraft(e.target.value); setAddError(null) }}
               // Enter adds the address rather than submitting anything — this
               // sits above a Send button and must never reach it.
               onKeyDown={e => {
                 if (e.key === 'Enter') { e.preventDefault(); add(draft) }
               }} />
        <button type="button" className="btn btn-outline"
                disabled={disabled || !draft.trim()}
                onClick={() => add(draft)}>Add recipient</button>
      </div>
      {addError && (
        <div className="f-hint" role="alert" style={{ color: '#C53030', marginTop: 6 }}>
          {addError}
        </div>
      )}
    </div>
  )
}
