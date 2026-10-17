/**
 * A refusal, as the officer-change stages show it: our sentence, then CR's own
 * words (each fault arrives as `[code, message]`), then what to do about the
 * refusals CR TEST has taught us to recognise. CR's words are never replaced —
 * an operator ringing CR quotes CR.
 */
function faultText(p) {
  if (Array.isArray(p)) return p.filter(Boolean).join(': ')
  if (p && typeof p === 'object') return p.message || JSON.stringify(p)
  return String(p)
}

export default function CrRefusal({ error }) {
  if (!error) return null
  const problems = error.problems || []
  const hints = error.hints || []
  return (
    <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
      <div className="al-body">
        <b>{error.message}</b>
        {problems.length > 0 && (
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {problems.map(p => <li key={faultText(p)}>{faultText(p)}</li>)}
          </ul>
        )}
        {hints.map(h => <p key={h} style={{ margin: '8px 0 0' }}>{h}</p>)}
      </div>
    </div>
  )
}
