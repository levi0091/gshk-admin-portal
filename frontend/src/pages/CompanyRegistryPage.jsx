import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import useAbortableGet from '../lib/useAbortableGet.js'
import StatusBadge, {
  COMPANY_STATUSES, FlagBadges, statusOptions,
} from '../components/StatusBadge.jsx'
import AddCompanyModal from '../components/AddCompanyModal.jsx'
import FilterableTh from '../components/FilterableTh.jsx'
import FilterChips from '../components/FilterChips.jsx'
import EmptyRow from '../components/EmptyRow.jsx'
import { labelForDays, signedDaysToAnniversary } from '../lib/anniversary.js'
import {
  ENUM, RANGE, TEXT, appendTo, filtersFor, setColumn,
} from '../lib/tableFilters.js'

const PAGE_SIZE = 50

// Flag filter tabs (wireframe_v7 s9). A company may be both client and
// corporate party, so these sets overlap — they are filters, not partitions.
//
// The tabs and the Type column's own funnel write the SAME filter. Two controls
// over one flag is fine; two STATES over one flag is how a tab and a header
// start disagreeing about what the table is showing, so `flag` lives in the
// filter list like everything else and is lifted back out when the request is
// built (the API takes it as its own parameter).
const TABS = [
  { key: null, label: 'All', cls: '', count: 'all' },
  { key: 'client', label: 'Clients', cls: '', count: 'client' },
  { key: 'corporate_party', label: 'Corporate Parties', cls: 'ft-action', count: 'corporate_party' },
  { key: 'non_client', label: 'Non-client', cls: '', count: 'non_client' },
]

// THE OPENING VIEW, and the reason it has two bounds (Levi 2026-09-03).
// A passed anniversary counts NEGATIVE while the return is still inside the
// 42-day statutory filing window, so a plain "days remaining" filter drops the
// companies that are already overdue — exactly the urgent ones. −42 is the far
// edge of that window and 60 reaches the returns coming up.
//
// It used to be a single comparison (`≤ 60`) pinned open in a bar of its own
// above the table. The bar is gone: this is the Days-to-anniversary column's
// filter now, like every other column's, and it takes both bounds because the
// questions worth asking here are ranges — "inside the window", "due next
// month" — not one-sided comparisons.
const ANNIV_DEFAULT = [
  { col: 'days_to_anniversary', op: 'gte', value: -42 },
  { col: 'days_to_anniversary', op: 'lte', value: 60 },
]

const ANNIV_HINT =
  'Negative once the anniversary has passed, positive counting down to the ' +
  'next one. −42 to 0 is the statutory filing window — still filable. Below ' +
  '−42 the window has shut. Clear both bounds to see every company.'

const COLUMNS = [
  { col: 'company_name', label: 'Company Name', sort: 'company_name',
    filter: { kind: TEXT, placeholder: 'Company name' } },
  // Brian's B2. Sortable like the English name — the column is on the
  // `company_registry` view already, so the server orders all 5,930 rows.
  { col: 'company_name_zh', label: 'Chinese Name', sort: 'company_name_zh',
    filter: { kind: TEXT, placeholder: '中文名稱' } },
  { col: 'br_number', label: 'BRN', sort: 'br_number',
    filter: { kind: TEXT, placeholder: 'Business Registration No.' } },
  { col: 'cr_number', label: 'CR No.', sort: 'cr_number',
    filter: { kind: TEXT, placeholder: 'Companies Registry No.' } },
  // The Type cell shows two overlapping flags, and the API answers one of them
  // at a time — so this is a RADIO list, not a checkbox list, and it writes the
  // same `flag` the tabs above do.
  { col: 'flag', label: 'Type', sort: 'is_client',
    filter: {
      kind: ENUM, single: true,
      options: TABS.filter(t => t.key).map(t => ({ value: t.key, label: t.label })),
    } },
  // The three a COMPANY can be, not the eleven the column can hold — see
  // COMPANY_STATUSES. The eight left out belong to an incorporation in flight.
  { col: 'status', label: 'Status', sort: 'status',
    filter: { kind: ENUM, options: statusOptions(COMPANY_STATUSES) } },
  // Sortable since migration 019: the company_registry view exposes
  // days_to_anniversary, so the server orders all 5,930 rows. Sorting the
  // visible 50 would have looked right and been wrong.
  { col: 'days_to_anniversary', label: 'Days to anniversary', sort: 'days_to_anniversary',
    filter: { kind: RANGE, unit: 'days', hint: ANNIV_HINT } },
]

export default function CompanyRegistryPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')
  // Opens on the actionable set (PRD W-3). A default, not a lock — the chip
  // above the table names it and drops it in one click.
  const [filters, setFilters] = useState(ANNIV_DEFAULT)

  const flag = filtersFor(filters, 'flag')[0]?.value?.[0] || null

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  function onFilter(column, next) {
    setFilters(f => setColumn(f, column.col, next))
    setPage(1)
  }

  function setFlag(key) {
    setFilters(f => setColumn(f, 'flag',
      key ? [{ col: 'flag', op: 'in', value: [key] }] : []))
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

  const params = new URLSearchParams({
    page: String(page), page_size: String(PAGE_SIZE),
  })
  if (query) params.set('search', query)
  // `flag` has its own API parameter — it selects between two boolean columns
  // rather than comparing one, so it cannot ride the generic column grammar.
  if (flag) params.set('flag', flag)
  if (sort) { params.set('sort', sort); params.set('dir', dir) }
  appendTo(params, filters.filter(f => f.col !== 'flag'))

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
          {/* NAR1's own vocabulary (Brian's B1). It reads broader than it
              sounds: a company IS a body corporate, so this list holds client
              companies as well as the corporate parties that act for them. */}
          <div className="pg-title">Body Corporate Registry</div>
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
            onClick={() => setFlag(tab.key)}
          >
            {tab.label}
            <span className="filter-count">{flagCounts[tab.count] ?? 0}</span>
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
          Failed to load company registry: {error}
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
                ) : companies.length === 0 ? (
                  <tr><td colSpan={COLUMNS.length} className="empty-state">
                    <EmptyRow
                      filtered={filters.length > 0}
                      onClear={() => { setFilters([]); setPage(1) }}
                    />
                  </td></tr>
                ) : companies.map(c => (
                  <tr key={c.id} className="clickable" onClick={() => navigate(`/companies/${c.id}`)}>
                    <td data-label="Company Name"><span className="td-primary">{c.company_name}</span></td>
                    <td data-label="Chinese Name">
                      <span className="td-muted">{c.company_name_zh || '—'}</span>
                    </td>
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
