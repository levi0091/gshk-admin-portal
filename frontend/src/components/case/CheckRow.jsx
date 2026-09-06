/**
 * A large click target for a yes/no fact an admin is asserting.
 *
 * `readOnly` renders THE SAME FACT WITH NOTHING TO CLICK, rather than removing
 * the row. This is the same exception the company profile's flag toggles make:
 * whether AML screening has been cleared is information a reader needs — it is
 * why the case is or is not allowed to advance — so deleting it would hide the
 * answer along with the control. What goes is the button, the `aria-pressed`
 * and the hover; what stays is the tick and the words, plus an explicit
 * Yes/No so the state does not rest on a tick mark alone.
 *
 * `disabled` remains for the ordinary in-flight case (a save is running). That
 * is temporary and the control comes back; `readOnly` never does.
 */
export default function CheckRow({ checked, onToggle, disabled, readOnly = false,
                                   title, sub }) {
  if (readOnly) {
    return (
      <div className={`check-row is-static${checked ? ' checked' : ''}`}
           data-testid={`check-${title}`}>
        <span className="check-box" aria-hidden="true">
          <svg width="12" height="12" fill="none" stroke="#fff" strokeWidth="3"
               viewBox="0 0 16 16" aria-hidden="true">
            <path d="M3 8l3.5 3.5L13 4" />
          </svg>
        </span>
        <span className="check-txt">
          <b>{title}</b>
          <span className="check-state">{checked ? 'Yes' : 'No'}</span>
          {sub && <div className="cx-sub">{sub}</div>}
        </span>
      </div>
    )
  }

  return (
    <button
      type="button"
      className={`check-row${checked ? ' checked' : ''}`}
      aria-pressed={checked}
      disabled={disabled}
      onClick={() => onToggle(!checked)}
    >
      <span className="check-box">
        <svg width="12" height="12" fill="none" stroke="#fff" strokeWidth="3"
             viewBox="0 0 16 16" aria-hidden="true">
          <path d="M3 8l3.5 3.5L13 4" />
        </svg>
      </span>
      <span className="check-txt">
        <b>{title}</b>
        {sub && <div className="cx-sub">{sub}</div>}
      </span>
    </button>
  )
}
