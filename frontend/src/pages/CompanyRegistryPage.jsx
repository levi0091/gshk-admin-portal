import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import StatusBadge, { FlagBadges } from '../components/StatusBadge.jsx'
import AddCompanyModal from '../components/AddCompanyModal.jsx'
import SortableTh from '../components/SortableTh.jsx'
import { anniversaryLabel } from '../lib/anniversary.js'

const PAGE_SIZE = 50

// Flag filter tabs (wireframe_v7 s9). A company may be both client and
// corporate party, so these sets overlap — they are filters, not partitions.
const TABS = [
  { key: null, label: 'All', cls: '', count: 'all' },
  { key: 'client', label: 'Clients', cls: '', count: 'client' },
  { key: 'corporate_party', label: 'Corporate Parties', cls: 'ft-action', count: 'corporate_party' },
  { key: 'non_client', label: 'Non-client', cls: '', count: 'non_client' },
]

export default function CompanyRegistryPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [flag, setFlag] = useState(null)
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
    const params = new URLSearchParams({
      page: String(page), page_size: String(PAGE_SIZE),
    })
    if (query) params.set('search', query)
    if (flag) params.set('flag', flag)
    if (sort) { params.set('sort', sort); params.set('dir', dir) }

    api.get(`/companies?${params}`)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [query, flag, page, sort, dir])

  const companies = data?.companies || []
  const flagCounts = data?.flag_counts || {}
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Company Registry</div>
          <div className="pg-sub">All companies — clients and corporate parties</div>
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

      <div className="search-wrap">
        <svg className="search-icon" width="14" height="14" fill="none" stroke="currentColor"
             strokeWidth="2" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="5" /><path d="M11 11l3 3" strokeLinecap="round" />
        </svg>
        <input
          className="search-input"
          type="text"
          aria-label="Search company, BRN or CR number"
          placeholder="Search company, BRN or CR number"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      <div className="filter-tabs" role="tablist">
        {TABS.map(tab => (
          <button
            key={tab.label}
            role="tab"
            aria-selected={flag === tab.key}
            className={`filter-tab ${tab.cls} ${flag === tab.key ? 'active' : ''}`}
            onClick={() => { setFlag(tab.key); setPage(1) }}
          >
            {tab.label}
            <span className="filter-count">{flagCounts[tab.count] ?? 0}</span>
          </button>
        ))}
      </div>

      {error ? (
        <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
          Failed to load company registry: {error}
        </div>
      ) : (
        <>
          <div className="tbl-wrap tbl-stack">
            <table>
              <thead>
                <tr>
                  {[
                    ['company_name', 'Company Name'],
                    ['br_number', 'BRN'],
                    ['cr_number', 'CR No.'],
                    ['is_client', 'Type'],
                    ['status', 'Status'],
                  ].map(([col, label]) => (
                    <SortableTh key={col} col={col} sort={sort} dir={dir} onSort={onSort}>
                      {label}
                    </SortableTh>
                  ))}
                  {/* Not a SortableTh: days-to-anniversary is derived from
                      incorporation_date, and this table sorts server-side on
                      real columns only. Sorting it needs backend support. */}
                  <th scope="col">
                    <div className="th-inner">Days to anniversary</div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={6} className="empty-state">Loading…</td></tr>
                ) : companies.length === 0 ? (
                  <tr><td colSpan={6} className="empty-state">No companies match this view.</td></tr>
                ) : companies.map(c => (
                  <tr key={c.id} className="clickable" onClick={() => navigate(`/companies/${c.id}`)}>
                    <td data-label="Company Name"><span className="td-primary">{c.company_name}</span></td>
                    <td data-label="BRN"><span className="td-muted">{c.br_number || '—'}</span></td>
                    <td data-label="CR No."><span className="td-muted">{c.cr_number || '—'}</span></td>
                    <td data-label="Type">
                      <FlagBadges isClient={c.is_client} isCorporateParty={c.is_corporate_party} />
                    </td>
                    <td data-label="Status"><StatusBadge status={c.status} /></td>
                    <td data-label="Days to anniversary" aria-label="Days to anniversary">
                      {(() => {
                        const { text, due } = anniversaryLabel(c.incorporation_date)
                        return <span className={due ? 'td-anniv-due' : 'td-muted'}>{text}</span>
                      })()}
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
