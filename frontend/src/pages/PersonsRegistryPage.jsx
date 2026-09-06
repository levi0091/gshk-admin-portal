import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import useAbortableGet from '../lib/useAbortableGet.js'
import { formatDate } from '../lib/format.js'
import RoleTags, { initials } from '../components/RoleTags.jsx'
import AddPersonModal from '../components/AddPersonModal.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { ReadOnlyNote } from '../components/RequirePermission.jsx'
import { personsRegistryCaps } from '../lib/screenCapabilities.js'
import FilterableTh from '../components/FilterableTh.jsx'
import FilterChips from '../components/FilterChips.jsx'
import EmptyRow from '../components/EmptyRow.jsx'
import {
  DATE, ENUM, TEXT, appendTo, filtersFor, setColumn,
} from '../lib/tableFilters.js'

const PAGE_SIZE = 50

// The role tabs and the Roles column's funnel write the same filter, for the
// same reason the company registry's Type does: one state, two ways in. The API
// answers one role at a time, so the column's list is radios.
const TABS = [
  { key: null, label: 'All', count: 'all' },
  { key: 'director', label: 'Directors', count: 'director' },
  { key: 'shareholder', label: 'Shareholders', count: 'shareholder' },
  { key: 'secretary', label: 'Secretaries', count: 'secretary' },
  { key: 'beneficial_owner', label: 'Beneficial Owners', count: 'beneficial_owner' },
]

const ID_TYPES = [
  { value: 'hkid', label: 'HKID' },
  { value: 'passport', label: 'Passport' },
  { value: 'china_id', label: 'China ID' },
  { value: 'other', label: 'Other' },
]

const COLUMNS = [
  { col: 'full_name', label: 'Name', sort: 'full_name',
    filter: { kind: TEXT, placeholder: 'Full name' } },
  // The cell shows the type and the number together. The funnel filters the
  // TYPE, because that is the question with a closed set of answers; a specific
  // number is what the search box above already looks for (it searches
  // `primary_id_number` among other things), so a second box for it here would
  // be a duplicate control with a narrower reach.
  { col: 'primary_id_type', label: 'Identity', sort: 'primary_id_number',
    filter: { kind: ENUM, options: ID_TYPES } },
  // Nationality has NO Viewpoint lookup — it is free-text demonyms — so this is
  // a text match and "has no value" is a question worth asking of it.
  { col: 'nationality', label: 'Nationality', sort: 'nationality',
    filter: { kind: TEXT, placeholder: 'e.g. British' } },
  { col: 'role', label: 'Roles', sort: null,
    filter: {
      kind: ENUM, single: true,
      options: TABS.filter(t => t.key).map(t => ({ value: t.key, label: t.label })),
    } },
  { col: 'updated_at', label: 'Last Updated', sort: 'updated_at', filter: { kind: DATE } },
]

export default function PersonsRegistryPage() {
  const navigate = useNavigate()
  const { hasPermission } = useAuth()
  const canWrite = personsRegistryCaps(hasPermission).addPerson
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')
  const [filters, setFilters] = useState([])

  const role = filtersFor(filters, 'role')[0]?.value?.[0] || null

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  function onFilter(column, next) {
    setFilters(f => setColumn(f, column.col, next))
    setPage(1)
  }

  function setRole(key) {
    setFilters(f => setColumn(f, 'role',
      key ? [{ col: 'role', op: 'in', value: [key] }] : []))
    setPage(1)
  }

  function removeColumns(cols) {
    setFilters(f => f.filter(x => !cols.includes(x.col)))
    setPage(1)
  }

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  if (query) params.set('search', query)
  // `role` reads one of four boolean flags on the view rather than comparing a
  // column, so it keeps its own API parameter.
  if (role) params.set('role', role)
  if (sort) { params.set('sort', sort); params.set('dir', dir) }
  appendTo(params, filters.filter(f => f.col !== 'role'))

  // Cancels the previous request on every toggle — UAT W-8. See the hook.
  const { data, loading, error } = useAbortableGet(`/persons?${params}`)

  const persons = data?.persons || []
  const counts = data?.role_counts || {}
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className="pg-hdr">
        <div>
          {/* NAR1's own vocabulary (Brian's B1 / B10). */}
          <div className="pg-title">Natural Person Registry</div>
          <div className="pg-sub">
            All individuals across every company — directors, shareholders, secretaries &amp; beneficial owners
          </div>
        </div>
        <div className="pg-actions">
          {/* `persons:read` gets this list; creating a person is
              `persons:write`, and without it the button is not rendered — see
              the company registry. */}
          {canWrite && (
            <button className="btn btn-action" onClick={() => setShowAdd(true)}>
              + Add Person
            </button>
          )}
        </div>
      </div>

      {!canWrite && (
        <ReadOnlyNote module="persons" what="every person in the registry"
                      verb="Adding one" />
      )}

      {showAdd && (
        <AddPersonModal
          onClose={() => setShowAdd(false)}
          onCreated={p => navigate(`/persons/${p.id}`)}
        />
      )}

      <div className="search-wrap">
        <svg className="search-icon" width="14" height="14" fill="none" stroke="currentColor"
             strokeWidth="2" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="5" /><path d="M11 11l3 3" strokeLinecap="round" />
        </svg>
        <input
          className="search-input"
          type="text"
          aria-label="Search name, email or ID number"
          placeholder="Search name, email or ID number"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      <div className="filter-tabs" role="tablist">
        {TABS.map(tab => (
          <button
            key={tab.label}
            role="tab"
            aria-selected={role === tab.key}
            className={`filter-tab ${role === tab.key ? 'active' : ''}`}
            onClick={() => setRole(tab.key)}
          >
            {tab.label}
            <span className="filter-count">{counts[tab.count] ?? 0}</span>
          </button>
        ))}
      </div>

      <FilterChips
        columns={COLUMNS}
        filters={filters}
        onRemove={removeColumns}
        onClearAll={() => { setFilters([]); setPage(1) }}
      />

      {error ? (
        <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
          Failed to load persons: {error}
        </div>
      ) : (
        <>
          <div className="tbl-wrap tbl-stack">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map(column => (
                    <FilterableTh key={column.col} column={column} sort={sort} dir={dir}
                                  onSort={onSort} filters={filters} onFilter={onFilter} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={COLUMNS.length} className="empty-state">Loading…</td></tr>
                ) : persons.length === 0 ? (
                  <tr><td colSpan={COLUMNS.length} className="empty-state">
                    <EmptyRow
                      filtered={filters.length > 0}
                      onClear={() => { setFilters([]); setPage(1) }}
                    />
                  </td></tr>
                ) : persons.map(p => (
                  <tr key={p.id} className="clickable" onClick={() => navigate(`/persons/${p.id}`)}>
                    <td data-label="Name">
                      <span className="person-cell">
                        <span className="person-av">{initials(p.full_name)}</span>
                        <span className="td-primary">{p.full_name}</span>
                      </span>
                    </td>
                    <td data-label="Identity">
                      <span className="td-muted">
                        {p.primary_id_number
                          ? `${(p.primary_id_type || '').toUpperCase()} · ${p.primary_id_number}`
                          : '—'}
                      </span>
                    </td>
                    <td data-label="Nationality">
                      <span className="td-muted">{p.nationality || '—'}</span>
                    </td>
                    <td data-label="Roles"><RoleTags person={p} /></td>
                    <td data-label="Last Updated">
                      <span className="td-muted">{formatDate(p.updated_at)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && total > 0 && (
            <div className="pager">
              <span>
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
              </span>
              <div className="pager-btns">
                <button className="btn btn-outline btn-sm" disabled={page <= 1}
                        onClick={() => setPage(p => p - 1)}>Previous</button>
                <button className="btn btn-outline btn-sm" disabled={page >= lastPage}
                        onClick={() => setPage(p => p + 1)}>Next</button>
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}
