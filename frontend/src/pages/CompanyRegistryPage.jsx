import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import useAbortableGet from '../lib/useAbortableGet.js'
import StatusBadge, { FlagBadges } from '../components/StatusBadge.jsx'
import AddCompanyModal from '../components/AddCompanyModal.jsx'
import SortableTh from '../components/SortableTh.jsx'
import { labelForDays, signedDaysToAnniversary } from '../lib/anniversary.js'

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
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [flag, setFlag] = useState(null)
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')
  // Opens on the actionable set (PRD W-3). A default, not a lock — Clear shows
  // everything. Signed, so "<= 60" also keeps companies already inside the
  // 42-day filing window, which are the urgent ones.
  const [annivOp, setAnnivOp] = useState('lte')
  const [annivDays, setAnnivDays] = useState('60')

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  useEffect(() => {
    const t = setTimeout(() => { setQuery(search); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  const params = new URLSearchParams({
    page: String(page), page_size: String(PAGE_SIZE),
  })
  if (query) params.set('search', query)
  if (flag) params.set('flag', flag)
  if (sort) { params.set('sort', sort); params.set('dir', dir) }
  // Both or neither — the API rejects half a comparison, and rightly so.
  if (annivOp && annivDays !== '' && !Number.isNaN(Number(annivDays))) {
    params.set('anniv_op', annivOp)
    params.set('anniv_days', String(Number(annivDays)))
  }

  // Cancels the previous request on every toggle — UAT W-8. See the hook.
  const { data, loading, error } = useAbortableGet(`/companies?${params}`)

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

      <div className="anniv-bar">
        <span className="anniv-lbl">Days to anniversary</span>
        <select aria-label="Comparison" value={annivOp}
                onChange={e => { setAnnivOp(e.target.value); setPage(1) }}>
          <option value="lte">≤</option>
          <option value="gte">≥</option>
          <option value="eq">=</option>
        </select>
        <input type="number" aria-label="Day count" value={annivDays}
               onChange={e => { setAnnivDays(e.target.value); setPage(1) }} />
        <span className="anniv-unit">days</span>
        {annivOp === 'lte' && annivDays === '60' && (
          <span className="anniv-default">Default</span>
        )}
        <button className="btn btn-outline btn-sm"
                onClick={() => { setAnnivDays(''); setAnnivOp('lte'); setPage(1) }}>
          Clear
        </button>
        <div className="anniv-hint">
          A passed anniversary counts <b>negative</b> while the return is still inside the
          42-day statutory filing window, so <b>≤ 60</b> keeps the companies already overdue
          for action — the ones a plain “days remaining” filter would drop. This is a
          starting view, not a lock: <b>Clear</b> shows every company.
        </div>
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
                  {/* Sortable since migration 019: the company_registry view
                      exposes days_to_anniversary, so the server orders all
                      5,930 rows. Sorting the visible 50 would have looked
                      right and been wrong. */}
                  <SortableTh col="days_to_anniversary" sort={sort} dir={dir} onSort={onSort}>
                    Days to anniversary
                  </SortableTh>
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
                        // Prefer the server's number so the text and the sort
                        // order are the same fact. Fall back to computing it
                        // only if the payload predates the view.
                        const days = 'days_to_anniversary' in c
                          ? c.days_to_anniversary
                          : signedDaysToAnniversary(c.incorporation_date)
                        const { text, due } = labelForDays(days)
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
