/** A large click target for a yes/no fact an admin is asserting. */
export default function CheckRow({ checked, onToggle, disabled, title, sub }) {
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
