/**
 * Everything the Companies Registry objected to, in one list.
 *
 * The backend deliberately collects EVERY `webServiceFaultBeans` entry rather
 * than the first, because CR returns them all at once and an operator should
 * fix them in a single pass instead of one per round-trip. Rendering only the
 * first would throw that away and turn one correction into five.
 */
/**
 * One fault, whatever shape it arrived in.
 *
 * CR's own faults reach us as a [severity, message] PAIR — verified live on
 * 2026-08-27: a rejected validate stored
 *   faults: [["ERROR", "Please check selectPersonId field."]]
 * Rendering that as an object printed raw JSON at the operator. The other two
 * shapes are ours: the mapper's plain-string problems, and the {faultString,
 * fieldName} form the API docs describe.
 */
export function readFault(f) {
  if (typeof f === 'string') return { field: null, msg: f }

  // [severity, message] — CR's actual wire shape.
  if (Array.isArray(f)) {
    if (f.length >= 2) return { field: String(f[0]), msg: String(f[1]) }
    return { field: null, msg: String(f[0] ?? '') }
  }

  if (f && typeof f === 'object') {
    return {
      field: f.fieldName || f.field || f.severity || null,
      msg: f.faultString || f.message || f.msg || JSON.stringify(f),
    }
  }

  return { field: null, msg: String(f) }
}

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
          const { field, msg } = readFault(f)
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
