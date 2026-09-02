import ColumnFilter, { isActive } from './ColumnFilter.jsx'

/**
 * A column header that can sort AND filter.
 *
 * Both live in the same cell because they are the same question asked two ways
 * — "show me this column's order" and "show me only these of its values" — and
 * separating them would put half the column's controls somewhere the operator
 * has to hunt for. The header itself is still the sort target, exactly as
 * `SortableTh` made it; the funnel stops the click before it becomes a sort.
 *
 * `column` is a descriptor: `{ col, label, sort, filter }`. `sort` is the
 * backend column name the server will accept in its order clause (null when
 * the column is derived and cannot be ordered); `filter` is the descriptor
 * `ColumnFilter` reads, or null for a column with nothing worth filtering on.
 */
export default function FilterableTh({ column, sort, dir, onSort, filters, onFilter }) {
  const sortable = Boolean(column.sort)
  const active = sortable && sort === column.sort
  const nextDir = active && dir === 'asc' ? 'desc' : 'asc'
  const filtered = column.filter ? isActive(column, filters) : false

  return (
    <th
      className={filtered ? 'th-filtered' : undefined}
      style={sortable ? { cursor: 'pointer', userSelect: 'none' } : undefined}
      onClick={sortable ? () => onSort(column.sort, nextDir) : undefined}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      title={sortable ? `Sort by ${column.label}` : undefined}
    >
      <div className={`th-inner${active ? ' th-sort-active' : ''}`}>
        <span className="th-lbl">{column.label}</span>
        {sortable && <span className="th-sort">{active ? (dir === 'asc' ? '↑' : '↓') : '⇅'}</span>}
        {column.filter && (
          <ColumnFilter
            column={column}
            filters={filters}
            onApply={next => onFilter(column, next)}
          />
        )}
      </div>
    </th>
  )
}
