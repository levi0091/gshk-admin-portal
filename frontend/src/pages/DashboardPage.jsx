import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate } from '../lib/format.js'
import { labelForDays } from '../lib/anniversary.js'
import useAbortableGet from '../lib/useAbortableGet.js'
import { useAuth } from '../context/AuthContext.jsx'
import SortableTh from '../components/SortableTh.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { WorkflowBadge } from '../components/CaseStatusBadge.jsx'
import NewCaseModal from '../components/NewCaseModal.jsx'

/**
 * Post-incorporation — the NAR1 case dashboard (wireframe_v11 `s2`).
 *
 * ONE ROW PER CASE, not per company. A company holding two outstanding annual
 * returns appears twice, and a row opens that case's workflow directly rather
 * than the company profile — the whole point of the screen is the filing, not
 * the company. Companies as such live on the Company Registry (`s9`).
 *
 * This replaced the old company dashboard, which read `/companies?scope=dashboard`
 * and could not represent two open cases against one company at all.
 *
 * Every filter, count and sort is applied SERVER-side (`GET /cases?scope=dashboard`)
 * — the page never holds the full set, so filtering here would quietly describe
 * only the current page.
 */

const PAGE_SIZE = 50

// The seven workflow badges, in v11 order. Carrot = act on me, indigo = waiting
// on someone else, red = refused, green = done. Keys are the backend's derived
// `workflow_status` codes (services/nar1_case_status.py).
const TABS = [
  { key: null, label: 'All', cls: '' },
  { key: 'data_verification', label: 'Data Verification', cls: 'ft-action' },
  { key: 'awaiting_client', label: 'Awaiting Client', cls: 'ft-pending' },
  { key: 'client_verification', label: 'Client Verification', cls: 'ft-action' },
  { key: 'client_rejected', label: 'Client Rejected', cls: 'ft-danger' },
  { key: 'signing', label: 'Signing', cls: 'ft-action' },
  { key: 'submission', label: 'Submission', cls: 'ft-action' },
  { key: 'completed', label: 'Completed', cls: 'ft-done' },
]

// "Action Required" vs "Pending" on the two stat cards: the split is who the
// next move belongs to. Completed belongs to neither.
const ACTION_STATUSES = ['data_verification', 'client_verification', 'client_rejected',
                         'signing', 'submission']
const PENDING_STATUSES = ['awaiting_client']

// v11 order. `null` = not sortable: the backend whitelists what may reach
// PostgREST's order clause (nar1_cases._SORTABLE), and offering a header the
// server would 422 on is a broken control, not a feature.
//
// v11 also draws an "Incorporation Date" column. It is NOT here, because
// `nar1_case_registry` (migration 024) does not select it — the column would
// render an em dash on every row forever, which reads as missing data rather
// than as a missing feature. Restoring it is a one-line addition of
// `e.incorporation_date` to that view (company_registry already exposes it via
// `e.*`) plus a migration; that is backend work, not this block's.
const COLUMNS = [
  ['case_no', 'Case ID'],
  [null, 'Case Type'],
  [null, 'Entity ID'],
  ['updated_at', 'Last Updated'],
  ['company_name', 'Company Name'],
  ['br_number', 'BRN'],
  ['case_status', 'Status'],
  ['workflow_status', 'Workflow'],
  ['days_to_anniversary', 'Days to anniversary'],
  ['created_at', 'Create Date'],
  // Sorts on `created_by_name`, not the uuid — ordering the dashboard by a
  // value nobody can read off the screen is not a sort.
  ['created_by_name', 'Created By'],
]

export default function DashboardPage() {
  const navigate = useNavigate()
  const { hasPermission, isSuperAdmin } = useAuth()
  // nar1:read shows the cases; nar1:write is what opens and drives one.
  const canOpenCase = isSuperAdmin || hasPermission('nar1', 'write')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState(null)
  const [phase, setPhase] = useState('all')
  const [overdueOnly, setOverdueOnly] = useState(false)
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

  const params = new URLSearchParams({
    scope: 'dashboard', page: String(page), page_size: String(PAGE_SIZE),
  })
  if (query) params.set('search', query)
  if (status) params.set('workflow_status', status)
  if (sort) { params.set('sort', sort); params.set('dir', dir) }
  // "Review overdue" — the anniversary has passed and the return is still
  // inside the 42-day window. The server counts negative days for exactly that
  // state, so `≤ 0` is the whole filter. Both parameters or neither: the
  // backend 422s on a half-supplied pair.
  if (overdueOnly) { params.set('anniv_op', 'lte'); params.set('anniv_days', '0') }

  const { data, loading, error } = useAbortableGet(`/cases?${params}`)

  const rows = data?.rows || []
  const counts = data?.counts || {}
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const sum = keys => keys.reduce((n, k) => n + (counts[k] ?? 0), 0)
  const actionCount = sum(ACTION_STATUSES)
  const pendingCount = sum(PENDING_STATUSES)

  // Rows already past the anniversary and still filable. Counted from the page
  // in view, so the banner says "on this page" rather than implying a total it
  // has not been given — the server sends no separate overdue count.
  const overdueHere = rows.filter(r => r.days_to_anniversary != null
                                    && r.days_to_anniversary <= 0).length

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Post-incorporation</div>
          <div className="pg-sub">
            Open cases — one row per case, so a company with two outstanding
            returns appears twice. Pending work first.
          </div>
        </div>
        <div className="pg-actions">
          {/* This screen lists CASES, so its action opens one. "+ Add Company"
              belonged to the Company Registry and left no way at all to start
              the work the dashboard is actually about. Gated on nar1:write:
              read lets you watch the cases, write lets you open and drive one. */}
          {canOpenCase && (
            <button className="btn btn-action" onClick={() => setShowAdd(true)}>
              + Open Case
            </button>
          )}
        </div>
      </div>

      {showAdd && (
        <NewCaseModal
          onClose={() => setShowAdd(false)}
          onCreated={c => navigate(`/cases/${c.id}`)}
        />
      )}

      {overdueHere > 0 && (
        <div className="info-banner warn">
          <svg width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2"
               viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 9v4M12 17h.01M10.3 3.3 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0Z"
                  strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="info-banner-txt">
            <b>
              {overdueHere} {overdueHere === 1 ? 'case has' : 'cases have'} passed
              the NAR1 anniversary.
            </b>{' '}
            A company's annual return (NAR1) must reach the Companies Registry
            within <b>42 days</b> of its incorporation anniversary. Late delivery
            incurs escalating registration fees and possible prosecution — review
            and file now.
          </div>
          <button className="info-banner-cta"
                  onClick={() => { setOverdueOnly(v => !v); setPage(1) }}>
            {overdueOnly ? 'Show all' : 'Review overdue'}
          </button>
        </div>
      )}

      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(2,minmax(0,1fr))', maxWidth: 560 }}>
        <div className="stat-card accent-left">
          <div className="stat-lbl">Action Required</div>
          <div className="stat-val stat-accent">{actionCount}</div>
          <div className="stat-sub">Data Verification · Client response · Signing · Submission</div>
        </div>
        <div className="stat-card accent-indigo">
          <div className="stat-lbl">Pending</div>
          <div className="stat-val" style={{ color: 'var(--indigo)' }}>{pendingCount}</div>
          <div className="stat-sub">Awaiting client response</div>
        </div>
      </div>

      {/* Pre-incorporation (NNC1) has no cases yet — the toggle is present
          because v11 places it here, and selecting it says so plainly rather
          than showing an empty table that looks like a loading failure. */}
      <div className="seg seg-inline" role="tablist" aria-label="Incorporation phase">
        {[['all', 'All cases'], ['post', 'Post-incorporation'], ['pre', 'Pre-incorporation']]
          .map(([key, label]) => (
            <button key={key} role="tab" aria-selected={phase === key}
                    className={`seg-btn ${phase === key ? 'active' : ''}`}
                    onClick={() => { setPhase(key); setPage(1) }}>
              {label}
            </button>
          ))}
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

      <div className="sort-note" style={{ visibility: sort ? 'hidden' : 'visible' }}>
        <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2"
             viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 3v10M4 13l-2-2M4 13l2-2M9 4h5M9 8h3M9 12h1" strokeLinecap="round" />
        </svg>
        Sorted by date created — newest first. Click <b>Days to anniversary</b>{' '}
        to order by filing deadline instead. Companies due for NAR1 are found on the{' '}
        <span style={{ color: 'var(--indigo)', cursor: 'pointer', fontWeight: 600 }}
              onClick={() => navigate('/registry')}>Body Corporate Registry</span>.
      </div>

      {error ? (
        <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
          Failed to load cases: {error}
        </div>
      ) : phase === 'pre' ? (
        <div className="empty-state" style={{ padding: 32 }}>
          Pre-incorporation cases (NNC1) are not built yet. Switch to
          Post-incorporation to see NAR1 cases.
        </div>
      ) : (
        <>
          <div className="tbl-wrap tbl-stack">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map(([col, label]) => (
                    col
                      ? <SortableTh key={label} col={col} sort={sort} dir={dir} onSort={onSort}>
                          {label}
                        </SortableTh>
                      : <th key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={COLUMNS.length} className="empty-state">Loading…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={COLUMNS.length} className="empty-state">
                    No cases match this view.
                  </td></tr>
                ) : rows.map(c => {
                  const { text, due } = labelForDays(c.days_to_anniversary)
                  return (
                    <tr key={c.id} className="clickable"
                        onClick={() => navigate(`/cases/${c.id}`)}>
                      <td data-label="Case ID"><span className="td-id">{c.case_no || '—'}</span></td>
                      <td data-label="Case Type">
                        <span className="badge b-inactive">{c.case_type || 'NAR1'}</span>
                      </td>
                      <td data-label="Entity ID"><span className="td-id">{c.entity_id || '—'}</span></td>
                      <td data-label="Last Updated"><span className="td-muted">{formatDate(c.updated_at)}</span></td>
                      <td data-label="Company Name"><span className="td-primary">{c.company_name}</span></td>
                      <td data-label="BRN"><span className="td-muted">{c.br_number || '—'}</span></td>
                      <td data-label="Status"><StatusBadge status={c.case_status} /></td>
                      <td data-label="Workflow">
                        {/* Levi 2026-08-30: one badge, the case's own workflow
                            status. The CR form status (FormBadge) used to stack
                            underneath; it still answers a real question, but it
                            answers it on the case detail, where there is room to
                            act on it. A list scanned for "what needs me next"
                            reads better with one word per row than two. */}
                        <WorkflowBadge status={c.workflow_status} />
                      </td>
                      <td data-label="Days to anniversary" aria-label="Days to anniversary">
                        <span className={due ? 'td-anniv-due' : 'td-muted'}>{text}</span>
                      </td>
                      <td data-label="Create Date"><span className="td-muted">{formatDate(c.created_at)}</span></td>
                      {/* Cases opened before migration 021 added the column carry
                          no author. An em dash says "not recorded"; the user's
                          own name would be a lie about who opened it. */}
                      <td data-label="Created By">
                        <span className="td-muted">{c.created_by_name || '—'}</span>
                      </td>
                    </tr>
                  )
                })}
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
