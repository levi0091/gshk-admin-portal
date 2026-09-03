/**
 * The per-column filter model, shared by every listing screen.
 *
 * A filter is `{ col, op, value }` and goes on the wire as a repeated
 * `filter=<col>:<op>:<value>` query parameter — the grammar
 * `backend/services/table_filters.py` parses. A column may hold more than one
 * filter; that is how a range is said (`gte` and `lte` on the same column), and
 * the backend ANDs them.
 *
 * EVERYTHING HERE IS SERVER-SIDE. These screens paginate over thousands of
 * rows, so a filter applied in the browser would narrow the 50 rows that
 * happened to arrive and quietly answer a different question. Nothing in this
 * file touches row data; it only builds the request and describes it back.
 *
 * The DRAFT is the popover's working copy. It is a per-kind shape that is easy
 * to bind inputs to (`{ op, value }`, `{ picked: [] }`, `{ min, max }`), and it
 * converts to and from the flat filter list at the edges. Keeping it separate
 * is what lets the popover be cancelled: nothing narrows the table until Apply.
 */

/** How a column is filtered. Each kind owns a draft shape and an editor. */
export const TEXT = 'text'
export const ENUM = 'enum'
export const RANGE = 'range'
export const DATE = 'date'
export const OWNER = 'owner'
/** A uuid column. Text-shaped in the editor, but exact-match only. */
export const ID = 'id'

export const TEXT_OPS = [
  { value: 'contains', label: 'contains' },
  { value: 'eq', label: 'is exactly' },
  { value: 'empty', label: 'is empty' },
  { value: 'notempty', label: 'has any value' },
]

/**
 * A uuid has no useful "contains": half an id identifies nothing, and the
 * server refuses the op outright (`table_filters._OPS_FOR_KIND`) because
 * Postgres has no `uuid ~~* unknown` operator and asking for one 500s the whole
 * listing. Offering the op and letting the server reject it would be a control
 * that is broken by design.
 */
export const ID_OPS = [
  { value: 'eq', label: 'is' },
  { value: 'empty', label: 'is empty' },
  { value: 'notempty', label: 'has any value' },
]

/** The op list a text-shaped editor should offer for `kind`. */
export function opsFor(kind) {
  return kind === ID ? ID_OPS : TEXT_OPS
}

const defaultOp = kind => (kind === ID ? 'eq' : 'contains')

/** Ops that stand alone — the value box is meaningless beside them. */
export const VALUELESS = ['empty', 'notempty']

/** `filter=` query parameter values, one per filter. */
export function toParams(filters) {
  return filters.map(f => {
    const v = Array.isArray(f.value) ? f.value.join(',') : (f.value ?? '')
    return `${f.col}:${f.op}:${v}`
  })
}

/**
 * Append every filter to a URLSearchParams as repeated `filter` entries.
 *
 * Sorted, because the request path IS the cache key `useAbortableGet` compares
 * on. The backend ANDs the filters, so their order carries no meaning — but
 * unsorted, re-picking the same three checkboxes in a different sequence would
 * build a different URL and refetch a set the screen is already showing.
 */
export function appendTo(params, filters) {
  for (const p of toParams(filters).sort()) params.append('filter', p)
  return params
}

export function filtersFor(filters, col) {
  return filters.filter(f => f.col === col)
}

/** Replace every filter on `col` with `next` (which may be empty). */
export function setColumn(filters, col, next) {
  return [...filters.filter(f => f.col !== col), ...next]
}

export function hasFilter(filters, col) {
  return filters.some(f => f.col === col)
}

// ─── draft ↔ filters ──────────────────────────────────────────────────────

/** Read a column's current filters back into an editable draft. */
export function draftFromFilters(column, filters) {
  const mine = filtersFor(filters, column.col)
  switch (column.filter.kind) {
    case ENUM:
      return { picked: mine[0]?.value ? [...mine[0].value] : [] }
    case RANGE:
    case DATE: {
      const lo = mine.find(f => f.op === 'gte')
      const hi = mine.find(f => f.op === 'lte')
      return { min: lo ? String(lo.value) : '', max: hi ? String(hi.value) : '' }
    }
    case OWNER: {
      const own = mine.find(f => f.op === 'eq')
      const name = filtersFor(filters, column.filter.nameCol)[0]
      return { mine: Boolean(own), name: name ? String(name.value) : '' }
    }
    default: {
      const f = mine[0]
      return {
        op: f?.op || defaultOp(column.filter.kind),
        value: f && !VALUELESS.includes(f.op) ? String(f.value) : '',
      }
    }
  }
}

/**
 * Turn a draft back into filters. Returns `[]` for a draft that says nothing —
 * an empty text box is not a filter for the empty string, it is no filter, and
 * sending one would narrow the table to rows nobody asked about.
 */
export function filtersFromDraft(column, draft) {
  const { col } = column
  switch (column.filter.kind) {
    case ENUM:
      return draft.picked?.length ? [{ col, op: 'in', value: [...draft.picked] }] : []
    case RANGE: {
      const out = []
      if (isNum(draft.min)) out.push({ col, op: 'gte', value: Number(draft.min) })
      if (isNum(draft.max)) out.push({ col, op: 'lte', value: Number(draft.max) })
      return out
    }
    case DATE: {
      const out = []
      if (draft.min) out.push({ col, op: 'gte', value: draft.min })
      if (draft.max) out.push({ col, op: 'lte', value: draft.max })
      return out
    }
    case OWNER: {
      const out = []
      if (draft.mine) out.push({ col, op: 'eq', value: column.filter.meId })
      const name = (draft.name || '').trim()
      if (name) out.push({ col: column.filter.nameCol, op: 'contains', value: name })
      return out
    }
    default: {
      if (VALUELESS.includes(draft.op)) return [{ col, op: draft.op, value: '' }]
      const v = (draft.value || '').trim()
      return v ? [{ col, op: draft.op || defaultOp(column.filter.kind), value: v }] : []
    }
  }
}

/**
 * Which columns a draft writes to. An owner draft touches two (the uuid and
 * the display name), so "replace this column's filters" has to know that or
 * clearing the popover would leave the name filter behind, invisible.
 */
export function columnsTouched(column) {
  return column.filter.kind === OWNER
    ? [column.col, column.filter.nameCol]
    : [column.col]
}

function isNum(v) {
  return v !== '' && v != null && !Number.isNaN(Number(v))
}

// ─── describing what is applied ───────────────────────────────────────────

/**
 * One removable chip per active filter group, in column order.
 *
 * This is the honest half of the feature. With eleven columns, a tinted header
 * two screens to the right explains nothing about why the table holds 20 rows
 * out of 5,930 — and a filter applied by default, which two of these screens
 * do on first paint, is a lie unless it names itself somewhere the operator
 * cannot miss. Every chip carries the column it came from and clears it.
 */
export function chipsFor(columns, filters) {
  const chips = []
  for (const column of columns) {
    if (!column.filter) continue
    const own = filtersFor(filters, column.col)
    const extra = column.filter.kind === OWNER
      ? filtersFor(filters, column.filter.nameCol)
      : []
    if (!own.length && !extra.length) continue
    chips.push({
      key: column.col,
      label: column.label,
      text: describe(column, own, extra),
      cols: columnsTouched(column),
    })
  }
  return chips
}

function describe(column, own, extra) {
  const kind = column.filter.kind
  if (kind === ENUM) {
    const picked = own[0]?.value || []
    const labels = picked.map(v =>
      column.filter.options.find(o => o.value === v)?.label ?? v)
    if (own[0]?.op === 'empty') return 'No value'
    if (own[0]?.op === 'notempty') return 'Any value'
    return labels.length > 2 ? `${labels.length} selected` : labels.join(', ')
  }
  if (kind === RANGE || kind === DATE) {
    const lo = own.find(f => f.op === 'gte')?.value
    const hi = own.find(f => f.op === 'lte')?.value
    const unit = kind === RANGE ? ` ${column.filter.unit || ''}`.trimEnd() : ''
    if (lo != null && hi != null) return `${lo} to ${hi}${unit}`
    if (lo != null) return `${lo}${unit} or more`
    if (hi != null) return `${hi}${unit} or less`
    return ''
  }
  if (kind === OWNER) {
    const parts = []
    if (own.some(f => f.op === 'eq')) parts.push('Me')
    if (extra.length) parts.push(`name contains “${extra[0].value}”`)
    return parts.join(' · ')
  }
  const f = own[0]
  if (!f) return ''
  if (f.op === 'empty') return 'No value'
  if (f.op === 'notempty') return 'Any value'
  if (f.op === 'eq') return `is “${f.value}”`
  return `contains “${f.value}”`
}
