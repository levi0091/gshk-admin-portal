import { useState } from 'react'

/**
 * Who the verification email goes to (wireframe_v11 s5, "CC Recipients").
 *
 * THE LIST STARTS EMPTY (Levi 2026-10-29). It used to be seeded with every
 * current director, which meant a statutory notice could go to an address
 * nobody had looked at: an operator who pressed Send without reading the chip
 * row mailed the whole board. Each director with an address is now offered as a
 * SUGGESTION PILL instead, so reaching a director is one deliberate click and
 * the screen never implies the mail "will go to the directors". A chosen
 * address becomes a removable chip and its pill goes; removing the chip brings
 * the pill back, so a mis-click is undone by name rather than by retyping.
 *
 * Directors with NO address on record are rendered too, dashed and muted, with
 * the reason beside them. Omitting them would make a three-director board look
 * like a two-director board, which is the one thing an operator cannot notice
 * by looking.
 *
 * Renders as a BLOCK, not a card (Levi 2026-08-30). It used to be its own panel
 * below the send button, which put the addresses after the control that mails
 * them — an operator reviewed, pressed Send, and only then met the list of who
 * it went to. It now sits inside the send card between the review tick and the
 * button, in the order the decision is actually made.
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
  // PERMISSION, not a transient state. `disabled` covers "a send is running"
  // or "the recipients have not loaded" — temporary, and the controls come
  // back. `readOnly` means this role may never send at all, so the ways to
  // change the list are not rendered; the LIST itself still is, because who
  // the return is going to is exactly what a reader is here to check.
  readOnly = false,
}) {
  const [draft, setDraft] = useState('')
  const [addError, setAddError] = useState(null)

  // Which chips came from the company record, so a chip can carry the
  // director's name and a removed one can come back as a pill.
  const byEmail = new Map()
  for (const r of recipients || []) {
    if (r.email) byEmail.set(r.email.toLowerCase(), r)
  }
  const missing = (recipients || []).filter(r => !r.email)
  // Suggestions: directors with an address who are not (or no longer) chosen.
  const suggestions = (recipients || []).filter(
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
    <div className="recip-block">
      <div className="recip-hdr">
        <span className="sect-label">Recipients</span>
        <span className="recip-count">
          {to.length === 0 ? 'none yet'
            : `${to.length} address${to.length === 1 ? '' : 'es'}`}
        </span>
      </div>
      {/* Only for someone who can choose, and only pointing at suggestions
          that are actually there. */}
      {!readOnly && (
        <div className="f-hint" style={{ marginBottom: 10 }}>
          {suggestions.length > 0
            ? 'No one is added automatically. Choose who should receive it from the suggestions below, or type another address.'
            : 'No one is added automatically. Type the address it should go to.'}
        </div>
      )}

      {to.length === 0 && readOnly ? null : to.length === 0 ? (
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
                {!readOnly && (
                  <button type="button" className="chip-x" disabled={disabled}
                          aria-label={`Remove ${address}`}
                          onClick={() => remove(address)}>×</button>
                )}
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

      {readOnly && suggestions.length > 0 && (
        // A role that may not send still sees WHO the board can be reached at —
        // that is what a reviewer is here to check — as plain text, not a
        // control. Nothing is "chosen", so nothing is drawn as a recipient.
        <div style={{ marginTop: 12 }} data-testid="recipient-board">
          <div className="f-hint" style={{ marginBottom: 6 }}>On the board:</div>
          <div className="chip-row">
            {suggestions.map(r => (
              <span className="chip chip-plain" key={r.email}>
                <span className="chip-name">{r.name}</span>
                <span className="chip-addr">{r.email}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {!readOnly && suggestions.length > 0 && (
        <div style={{ marginTop: 12 }} data-testid="recipient-suggestions">
          <div className="f-hint" style={{ marginBottom: 6 }}>Suggested:</div>
          <div className="chip-row">
            {suggestions.map(r => (
              <button type="button" className="chip chip-suggest" key={r.email}
                      disabled={disabled}
                      aria-label={`Add ${r.name} (${r.email})`}
                      onClick={() => add(r.email)}>
                <span aria-hidden="true">+ </span>
                <span className="chip-name">{r.name}</span>
                <span className="chip-addr">{r.email}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!readOnly && (
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
      )}
      {addError && (
        <div className="f-hint" role="alert" style={{ color: '#C53030', marginTop: 6 }}>
          {addError}
        </div>
      )}
    </div>
  )
}
