/**
 * Sortable column header (wireframe_v7 .th-inner / .th-sort).
 *
 * Sorting is server-side: the tables are paginated, so sorting only the rows on
 * the current page would be misleading.
 *
 * `col` is the backend column name (whitelisted server-side). Pass col={null}
 * for a column that cannot be sorted (e.g. a derived one).
 */
export default function SortableTh({ col, sort, dir, onSort, children, style }) {
  const active = col && sort === col
  const nextDir = active && dir === 'asc' ? 'desc' : 'asc'

  if (!col) return <th style={style}>{children}</th>

  return (
    <th
      style={{ ...style, cursor: 'pointer', userSelect: 'none' }}
      onClick={() => onSort(col, nextDir)}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      title={`Sort by ${typeof children === 'string' ? children : col}`}
    >
      <div className={`th-inner${active ? ' th-sort-active' : ''}`}>
        {children}
        <span className="th-sort">{active ? (dir === 'asc' ? '↑' : '↓') : '⇅'}</span>
      </div>
    </th>
  )
}
