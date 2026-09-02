import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  DATE, ENUM, OWNER, RANGE, TEXT_OPS, VALUELESS,
  draftFromFilters, filtersFromDraft,
} from '../lib/tableFilters.js'

/**
 * The funnel in a column header, and the popover it opens.
 *
 * WHY A POPOVER AND NOT AN INLINE CONTROL. Eleven columns cannot each carry a
 * visible filter box without burying the data the table exists to show. The
 * funnel is two states wide — dormant hairline, or solid carrot when this
 * column is narrowing the table — so a glance across the header row says which
 * columns are doing something. `FilterChips` says *what* they are doing.
 *
 * NOTHING NARROWS THE TABLE UNTIL APPLY. The popover edits a DRAFT copy; Escape
 * and a click outside close it and discard. That matters most for the checkbox
 * lists, where committing per tick would fire a server round-trip per checkbox
 * on a 5,930-row table. `Clear` is the exception and commits at once — dropping
 * a filter is unambiguous, and making it cost two clicks would be the pettiest
 * possible friction on the commonest action.
 *
 * Rendered through a PORTAL. The header lives inside `.tbl-wrap`, which is
 * `overflow-x: auto` so wide tables scroll — an absolutely positioned panel
 * would be clipped by exactly the scroller that makes the column reachable.
 */
export default function ColumnFilter({ column, filters, onApply }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(() => draftFromFilters(column, filters))
  const btnRef = useRef(null)

  const active = isActive(column, filters)

  function openPanel(e) {
    e.stopPropagation()          // never sort as a side effect of filtering
    setDraft(draftFromFilters(column, filters))
    setOpen(v => !v)
  }

  // Stable, because the panel's document-level key and mousedown listeners
  // depend on it — a fresh identity every render would tear them down and
  // re-add them on every keystroke in the value box.
  const close = useCallback(() => {
    setOpen(false)
    btnRef.current?.focus()
  }, [])

  function apply(next = draft) {
    onApply(filtersFromDraft(column, next))
    close()
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={`th-filter${active ? ' is-on' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={active ? `Filter ${column.label} (filtered)` : `Filter ${column.label}`}
        title={active ? `${column.label} — filtered` : `Filter ${column.label}`}
        onClick={openPanel}
      >
        <FunnelIcon filled={active} />
      </button>

      {open && (
        <Panel
          anchor={btnRef}
          column={column}
          draft={draft}
          setDraft={setDraft}
          onApply={apply}
          onClear={() => apply(emptyDraft(column))}
          onClose={close}
        />
      )}
    </>
  )
}

function FunnelIcon({ filled }) {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true"
         fill={filled ? 'currentColor' : 'none'} stroke="currentColor"
         strokeWidth="1.4" strokeLinejoin="round">
      <path d="M1.2 2.4h9.6L7 6.7v3.6L5 9.3V6.7z" />
    </svg>
  )
}

// ─── the panel ────────────────────────────────────────────────────────────

function Panel({ anchor, column, draft, setDraft, onApply, onClear, onClose }) {
  const ref = useRef(null)
  const pos = useAnchoredPosition(anchor, ref)

  // Escape closes without committing, and an outside click does the same. Both
  // are "I changed my mind", so neither may leave a half-edited draft applied.
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') { e.stopPropagation(); onClose() }
    }
    function onDown(e) {
      if (ref.current?.contains(e.target) || anchor.current?.contains(e.target)) return
      onClose()
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('mousedown', onDown, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('mousedown', onDown, true)
    }
  }, [anchor, onClose])

  useEffect(() => {
    ref.current?.querySelector('input, select, button')?.focus()
  }, [])

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={`Filter ${column.label}`}
      className="colf"
      style={pos}
      onClick={e => e.stopPropagation()}
      onKeyDown={e => { if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') onApply() }}
    >
      <div className="colf-hdr">{column.label}</div>
      <div className="colf-body">
        <Editor column={column} draft={draft} setDraft={setDraft} />
      </div>
      <div className="colf-foot">
        <button type="button" className="colf-clear" onClick={onClear}>Clear</button>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => onApply()}>
          Apply
        </button>
      </div>
    </div>,
    document.body,
  )
}

/** Anchor under the funnel, flipped left when the panel would leave the page. */
function useAnchoredPosition(anchor, panel) {
  const [pos, setPos] = useState({ top: -9999, left: -9999 })

  useLayoutEffect(() => {
    function place() {
      const a = anchor.current?.getBoundingClientRect()
      if (!a) return
      const w = panel.current?.offsetWidth || 248
      const h = panel.current?.offsetHeight || 200
      const left = Math.max(8, Math.min(a.left, window.innerWidth - w - 8))
      // Below the header by default; above it when there is no room below, so
      // the last rows of a long page can still reach their own filters.
      const below = a.bottom + 6
      const top = below + h > window.innerHeight - 8 && a.top - h - 6 > 8
        ? a.top - h - 6
        : below
      setPos({ top, left })
    }
    place()
    // `true` catches the table's own horizontal scroller, not just the window.
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [anchor, panel])

  return { position: 'fixed', top: pos.top, left: pos.left }
}

// ─── editors, one per column kind ─────────────────────────────────────────

function Editor({ column, draft, setDraft }) {
  const kind = column.filter.kind
  if (kind === ENUM) return <EnumEditor column={column} draft={draft} setDraft={setDraft} />
  if (kind === RANGE) return <RangeEditor column={column} draft={draft} setDraft={setDraft} />
  if (kind === DATE) return <DateEditor draft={draft} setDraft={setDraft} />
  if (kind === OWNER) return <OwnerEditor draft={draft} setDraft={setDraft} />
  return <TextEditor column={column} draft={draft} setDraft={setDraft} />
}

function TextEditor({ column, draft, setDraft }) {
  const needsValue = !VALUELESS.includes(draft.op)
  return (
    <>
      <select className="colf-select" aria-label="Condition" value={draft.op}
              onChange={e => setDraft({ ...draft, op: e.target.value })}>
        {TEXT_OPS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {needsValue && (
        <input className="colf-input" type="text" aria-label={`${column.label} value`}
               placeholder={column.filter.placeholder || 'Type a value'}
               value={draft.value}
               onChange={e => setDraft({ ...draft, value: e.target.value })} />
      )}
    </>
  )
}

function EnumEditor({ column, draft, setDraft }) {
  const options = column.filter.options || []
  const picked = draft.picked || []
  // `single` columns are the ones the API can only answer one value for (the
  // registry's Type flag, the person registry's role). They get RADIOS, because
  // a checkbox that silently unticks its neighbour is a control lying about
  // what it does.
  const single = Boolean(column.filter.single)
  const toggle = v => setDraft({
    picked: single
      ? (picked.includes(v) ? [] : [v])
      : (picked.includes(v) ? picked.filter(x => x !== v) : [...picked, v]),
  })
  return (
    <>
      <div className="colf-bulk">
        {!single && (
          <button type="button" onClick={() => setDraft({ picked: options.map(o => o.value) })}>
            Select all
          </button>
        )}
        <button type="button" onClick={() => setDraft({ picked: [] })}>
          {single ? 'Any' : 'None'}
        </button>
      </div>
      <div className="colf-list">
        {options.map(o => (
          <label key={o.value} className="colf-opt">
            <input type={single ? 'radio' : 'checkbox'} name={`colf-${column.col}`}
                   checked={picked.includes(o.value)}
                   onChange={() => toggle(o.value)} />
            <span className="colf-opt-lbl">{o.label}</span>
            {o.count != null && <span className="colf-opt-count">{o.count}</span>}
          </label>
        ))}
      </div>
    </>
  )
}

function RangeEditor({ column, draft, setDraft }) {
  const unit = column.filter.unit
  return (
    <>
      <div className="colf-pair">
        <label className="colf-field">
          <span>From</span>
          <input type="number" aria-label={`${column.label} lower bound`}
                 placeholder="any" value={draft.min}
                 onChange={e => setDraft({ ...draft, min: e.target.value })} />
        </label>
        <span className="colf-dash">–</span>
        <label className="colf-field">
          <span>To</span>
          <input type="number" aria-label={`${column.label} upper bound`}
                 placeholder="any" value={draft.max}
                 onChange={e => setDraft({ ...draft, max: e.target.value })} />
        </label>
        {unit && <span className="colf-unit">{unit}</span>}
      </div>
      {column.filter.hint && <p className="colf-hint">{column.filter.hint}</p>}
    </>
  )
}

function DateEditor({ draft, setDraft }) {
  return (
    <div className="colf-pair colf-pair-stack">
      <label className="colf-field">
        <span>From</span>
        <input type="date" aria-label="From date" value={draft.min}
               onChange={e => setDraft({ ...draft, min: e.target.value })} />
      </label>
      <label className="colf-field">
        <span>To</span>
        <input type="date" aria-label="To date" value={draft.max}
               onChange={e => setDraft({ ...draft, max: e.target.value })} />
      </label>
    </div>
  )
}

function OwnerEditor({ draft, setDraft }) {
  return (
    <>
      <div className="colf-seg" role="radiogroup" aria-label="Whose cases">
        <button type="button" role="radio" aria-checked={draft.mine}
                className={draft.mine ? 'on' : ''}
                onClick={() => setDraft({ ...draft, mine: true })}>
          Only mine
        </button>
        <button type="button" role="radio" aria-checked={!draft.mine}
                className={!draft.mine ? 'on' : ''}
                onClick={() => setDraft({ ...draft, mine: false })}>
          Everyone
        </button>
      </div>
      <input className="colf-input" type="text" aria-label="Creator name contains"
             placeholder="…or a name" value={draft.name}
             disabled={draft.mine}
             onChange={e => setDraft({ ...draft, name: e.target.value })} />
      <p className="colf-hint">
        Cases opened before the portal recorded an author show no name at all.
      </p>
    </>
  )
}

// ─── helpers ──────────────────────────────────────────────────────────────

function emptyDraft(column) {
  switch (column.filter.kind) {
    case ENUM: return { picked: [] }
    case RANGE:
    case DATE: return { min: '', max: '' }
    case OWNER: return { mine: false, name: '' }
    default: return { op: 'contains', value: '' }
  }
}

/** Does this column narrow the table right now? Drives the solid funnel. */
export function isActive(column, filters) {
  if (column.filter?.kind === OWNER) {
    return filters.some(f => f.col === column.col || f.col === column.filter.nameCol)
  }
  return filters.some(f => f.col === column.col)
}
