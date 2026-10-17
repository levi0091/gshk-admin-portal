import { useState } from 'react'

/**
 * The company rules, as the backend evaluated them (`rules.evaluate`).
 *
 * Jacqueline A6 (2026-10-01): "This part doesn't need to be shown in full ...
 * keep the three main things below so our team members can understand easily"
 * — how many directors and secretaries the company will have, who the
 * directors are, and who the secretary is. Those three lines are the card.
 * A breached rule is always listed beneath them (it stops the send, and the
 * reason must be where the eye is); every other check — the ones that pass and
 * the notices — sits behind "Show all checks".
 */
export default function RulesPanel({ rules }) {
  const [open, setOpen] = useState(false)
  if (!rules) return null
  const checks = rules.checks || []
  const breaches = checks.filter(c => !c.ok && c.level !== 'notice')
  const rest = checks.filter(c => !breaches.includes(c))
  const lines = rules.lines || (rules.summary ? [rules.summary] : [])
  return (
    <div className="card" style={{ marginTop: 16 }} aria-label="Company rules">
      <div className="card-hdr">
        <div className="card-title">After these changes</div>
        {rules.blocking
          ? <span className="badge b-client-rejected">Breach — cannot send</span>
          : <span className="badge b-live">All rules met</span>}
      </div>
      <div className="oc-board-lines">
        {lines.map(line => <p key={line}>{line}</p>)}
      </div>
      {breaches.length > 0 && (
        <ul className="oc-rules" aria-label="Rules breached">
          {breaches.map(c => <Check key={c.code} check={c} />)}
        </ul>
      )}
      {rest.length > 0 && (
        <button type="button" className="btn btn-ghost btn-sm oc-rules-toggle"
                aria-expanded={open} onClick={() => setOpen(o => !o)}>
          {open ? 'Hide checks' : `Show all checks (${rest.length})`}
        </button>
      )}
      {open && (
        <ul className="oc-rules">
          {rest.map(c => <Check key={c.code} check={c} />)}
        </ul>
      )}
    </div>
  )
}

function Check({ check: c }) {
  const tone = c.ok ? 'ok' : c.level === 'notice' ? 'notice' : 'bad'
  return (
    <li className={`oc-rule ${tone}`} data-code={c.code}>
      <span className="oc-rule-mark" aria-hidden="true">
        {tone === 'ok' ? '✓' : tone === 'notice' ? '!' : '✕'}
      </span>
      <span>{c.text}</span>
    </li>
  )
}
