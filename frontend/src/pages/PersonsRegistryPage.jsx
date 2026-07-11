import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import RoleTags, { initials } from '../components/RoleTags.jsx'
import AddPersonModal from '../components/AddPersonModal.jsx'
import SortableTh from '../components/SortableTh.jsx'

const PAGE_SIZE = 50

const TABS = [
  { key: null, label: 'All', count: 'all' },
  { key: 'director', label: 'Directors', count: 'director' },
  { key: 'shareholder', label: 'Shareholders', count: 'shareholder' },
  { key: 'secretary', label: 'Secretaries', count: 'secretary' },
  { key: 'beneficial_owner', label: 'Beneficial Owners', count: 'beneficial_owner' },
]

export default function PersonsRegistryPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [role, setRole] = useState(null)
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
    if (query) params.set('search', query)
    if (role) params.set('role', role)
    if (sort) { params.set('sort', sort); params.set('dir', dir) }

    api.get(`/persons?${params}`)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [query, role, page, sort, dir])

  const persons = data?.persons || []
  const counts = data?.role_counts || {}
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Persons Registry</div>
          <div className="pg-sub">
            All individuals across every company — directors, shareholders, secretaries &amp; beneficial owners
          </div>
        </div>
        <div className="pg-actions">
          <button className="btn btn-action" onClick={() => setShowAdd(true)}>+ Add Person</button>
        </div>
      </div>

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
            onClick={() => { setRole(tab.key); setPage(1) }}
          >
            {tab.label}
            <span className="filter-count">{counts[tab.count] ?? 0}</span>
          </button>
        ))}
      </div>

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
                  {[
                    ['full_name', 'Name'],
                    ['primary_id_number', 'Identity'],
                    ['nationality', 'Nationality'],
                    [null, 'Roles'],
                    ['updated_at', 'Last Updated'],
                  ].map(([col, label]) => (
                    <SortableTh key={label} col={col} sort={sort} dir={dir} onSort={onSort}>
                      {label}
                    </SortableTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={5} className="empty-state">Loading…</td></tr>
                ) : persons.length === 0 ? (
                  <tr><td colSpan={5} className="empty-state">No persons match this view.</td></tr>
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
