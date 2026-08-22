/**
 * Everything the Companies Registry objected to, in one list.
 *
 * The backend deliberately collects EVERY `webServiceFaultBeans` entry rather
 * than the first, because CR returns them all at once and an operator should
 * fix them in a single pass instead of one per round-trip. Rendering only the
 * first would throw that away and turn one correction into five.
 */
export default function FaultPanel({ faults, title = 'The Companies Registry refused this form' }) {
  const rows = faults || []
  if (rows.length === 0) return null

  return (
    <div className="fault-box" role="alert">
      <div className="fault-hd">
        <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2"
             viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" /><path d="M12 8v5M12 16h.01" strokeLinecap="round" />
        </svg>
        {title}
        <span className="fh-count">{rows.length}</span>
      </div>
      <div className="fault-list">
        {rows.map((f, i) => {
          // CR's shape varies: sometimes a bare string, sometimes
          // {faultString, fieldName}. Neither is worth losing.
          const field = typeof f === 'string' ? null : (f.fieldName || f.field || null)
          const msg = typeof f === 'string'
            ? f
            : (f.faultString || f.message || JSON.stringify(f))
          return (
            <div className="fault-row" key={i}>
              {field && <span className="fault-field">{field}</span>}
              <span className="fault-msg">{msg}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
