import { useState, useEffect, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import StatusBadge from '../components/StatusBadge.jsx'
import AddCompanyModal from '../components/AddCompanyModal.jsx'
import SortableTh from '../components/SortableTh.jsx'

const PAGE_SIZE = 50

// Filter tabs, in wireframe_v7 order. Carrot = action on me, indigo = waiting on
// others, green = done. These stay at 0 until the NAR1/NNC1 case workflows land.
const TABS = [
  { key: null, label: 'All', cls: '' },
  { key: 'pending_aml', label: 'Pending AML', cls: 'ft-action' },
  { key: 'to_verify', label: 'To Verify', cls: 'ft-action' },
  { key: 'client_rejected', label: 'Client Rejected', cls: 'ft-action' },
  { key: 'pending_client', label: 'Pending Client', cls: 'ft-pending' },
  { key: 'submitted_to_cr', label: 'Submitted to CR', cls: 'ft-pending' },
  { key: 'cr_approved', label: 'CR Approved', cls: 'ft-done' },
]

export default function DashboardPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState(null)
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setQuery(search); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams({
      scope: 'dashboard', page: String(page), page_size: String(PAGE_SIZE),
    })
    if (query) params.set('search', query)
    if (status) params.set('status', status)
    if (sort) { params.set('sort', sort); params.set('dir', dir) }

    api.get(`/companies?${params}`)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [query, status, page, sort, dir])

  const companies = data?.companies || []
  const counts = data?.status_counts || {}
  const tiles = data?.tiles || {}
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Dashboard</div>
          <div className="pg-sub">Client companies — pending work first, most recently updated on top</div>
        </div>
        <div className="pg-actions">
          <button className="btn btn-action" onClick={() => setShowAdd(true)}>
            + Add Company
          </button>
        </div>
      </div>

      {showAdd && (
        <AddCompanyModal
          onClose={() => setShowAdd(false)}
          onCreated={c => navigate(`/companies/${c.id}`)}
        />
      )}

      <div className="stats-grid">
        <div className="stat-card accent-left">
          <div className="stat-lbl">Action Required</div>
          <div className="stat-val stat-accent">{tiles.action_required ?? 0}</div>
          <div className="stat-sub">Pending AML · To Verify · Client Rejected</div>
        </div>
        <div className="stat-card accent-indigo">
          <div className="stat-lbl">Pending</div>
          <div className="stat-val" style={{ color: 'var(--indigo)' }}>{tiles.pending ?? 0}</div>
          <div className="stat-sub">Pending Client · Submitted to CR</div>
        </div>
      </div>

      <div className="search-wrap">
        <svg className="search-icon" width="14" height="14" fill="none" stroke="currentColor"
             strokeWidth="2" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="5" /><path d="M11 11l3 3" strokeLinecap="round" />
        </svg>
        <input
          className="search-input"
          type="text"
          aria-label="Search Company or BRN"
          placeholder="Search Company or BRN"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      <div className="filter-tabs" role="tablist">
        {TABS.map(tab => (
          <button
            key={tab.label}
            role="tab"
            aria-selected={status === tab.key}
            className={`filter-tab ${tab.cls} ${status === tab.key ? 'active' : ''}`}
            onClick={() => { setStatus(tab.key); setPage(1) }}
          >
            {tab.label}
            <span className="filter-count">
              {tab.key === null ? (counts.all ?? 0) : (counts[tab.key] ?? 0)}
            </span>
          </button>
        ))}
      </div>

      {/* Only true while the default ordering is in force. */}
      <div className="sort-note" style={{ visibility: sort ? 'hidden' : 'visible' }}>
        <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2"
             viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 3v10M4 13l-2-2M4 13l2-2M9 4h5M9 8h3M9 12h1" strokeLinecap="round" />
        </svg>
        Sorted by pending work first, then most recently updated. Non-client companies are in the
        {' '}
        <span style={{ color: 'var(--indigo)', cursor: 'pointer', fontWeight: 600 }}
              onClick={() => navigate('/registry')}>Company Registry</span>.
      </div>

      {error ? (
        <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
          Failed to load dashboard: {error}
        </div>
      ) : (
        <>
          <div className="tbl-wrap tbl-stack">
            <table>
              <thead>
                <tr>
                  {[
                    ['vp_source_key', 'Entity ID'],
                    ['updated_at', 'Last Updated'],
                    ['company_name', 'Company Name'],
                    ['br_number', 'BRN'],
                    ['status', 'Status'],
                    ['active_workflow', 'Workflow'],
                    ['created_at', 'Create Date'],
                    ['incorporation_date', 'Incorporation Date'],
                  ].map(([col, label]) => (
                    <SortableTh key={col} col={col} sort={sort} dir={dir} onSort={onSort}>
                      {label}
                    </SortableTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={8} className="empty-state">Loading…</td></tr>
                ) : companies.length === 0 ? (
                  <tr><td colSpan={8} className="empty-state">No companies match this view.</td></tr>
                ) : companies.map((c, i) => (
                  <Fragment key={c.id}>
                    {/* Separator at the pending → completed boundary (wireframe_v7).
                        Only rendered when the page actually contains both. */}
                    {i > 0 && companies[i - 1].has_pending_case && !c.has_pending_case && (
                      <tr className="tbl-group-row">
                        <td colSpan={8}>Completed — no pending case</td>
                      </tr>
                    )}
                  <tr className="clickable" onClick={() => navigate(`/companies/${c.id}`)}>
                    <td data-label="Entity ID"><span className="td-id">{c.vp_source_key || '—'}</span></td>
                    <td data-label="Last Updated"><span className="td-muted">{formatDate(c.updated_at)}</span></td>
                    <td data-label="Company Name"><span className="td-primary">{c.company_name}</span></td>
                    <td data-label="BRN"><span className="td-muted">{c.br_number || '—'}</span></td>
                    <td data-label="Status"><StatusBadge status={c.status} /></td>
                    <td data-label="Workflow">
                      {c.active_workflow
                        ? <span className="filing-tag">{c.active_workflow.toUpperCase()}</span>
                        : <span className="td-muted">—</span>}
                    </td>
                    <td data-label="Create Date"><span className="td-muted">{formatDate(c.created_at)}</span></td>
                    <td data-label="Incorporation Date"><span className="td-muted">{formatDate(c.incorporation_date)}</span></td>
                  </tr>
                  </Fragment>
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
