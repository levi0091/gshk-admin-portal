import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDate } from '../lib/format.js'
import { labelForDays } from '../lib/anniversary.js'
import useAbortableGet from '../lib/useAbortableGet.js'
import { useAuth } from '../context/AuthContext.jsx'
import FilterableTh from '../components/FilterableTh.jsx'
import FilterChips from '../components/FilterChips.jsx'
import EmptyRow from '../components/EmptyRow.jsx'
import { WorkflowBadge, WORKFLOW_LABEL } from '../components/CaseStatusBadge.jsx'
import NewCaseModal from '../components/NewCaseModal.jsx'
import {
  DATE, ENUM, ID, OWNER, RANGE, TEXT,
  appendTo, filtersFor, setColumn,
} from '../lib/tableFilters.js'

/**
 * Post-incorporation — the NAR1 case dashboard (wireframe_v11 `s2`).
 *
 * ONE ROW PER CASE, not per company. A company holding two outstanding annual
 * returns appears twice, and a row opens that case's workflow directly rather
 * than the company profile — the whole point of the screen is the filing, not
 * the company. Companies as such live on the Company Registry (`s9`).
 *
 * Every filter, count and sort is applied SERVER-side (`GET /cases?scope=dashboard`)
 * — the page never holds the full set, so filtering here would quietly describe
 * only the current page.
 *
 * NARROWING IS ALL ONE MECHANISM NOW (Levi 2026-09-03). It used to be four:
 * a phase segment, a workflow tab row, an overdue banner and a search box, each
 * with its own state and its own way of showing what it had done. The phase
 * segment is gone — this screen only ever listed post-incorporation cases, and
 * "Pre-incorporation" selected an empty table with an apology in it. The
 * workflow tab row is gone too: those seven badges are NAR1's process, and this
 * dashboard is meant to hold every post-incorporation form, so a permanent row
 * of one form's statuses is a filter that stops being true as soon as a second
 * form arrives. The badges are now the Workflow column's own filter — carrying
 * the same counts the tabs did — and everything else narrows through a column
 * header, with `FilterChips` naming whatever is applied.
 */

const PAGE_SIZE = 50

// "Action Required" vs "Pending" on the two stat cards: the split is who the
// next move belongs to. Completed belongs to neither. Each tile IS the filter
// for its own set, so the number and the rows can never disagree.
const ACTION_STATUSES = ['data_verification', 'client_verification', 'client_rejected',
                         'signing', 'submission']
const PENDING_STATUSES = ['awaiting_client']

const WORKFLOW_ORDER = [
  'data_verification', 'awaiting_client', 'client_verification',
  'client_rejected', 'signing', 'submission', 'completed',
]

const ANNIV_HINT =
  'Negative once the anniversary has passed, positive counting down to the ' +
  'next one. −42 to 0 is the statutory filing window — still filable. Below ' +
  '−42 the window has shut.'

// v11 order. `sort: null` = not sortable: the backend whitelists what may reach
// PostgREST's order clause (nar1_cases._SORTABLE), and offering a header the
// server would 422 on is a broken control, not a feature. `filter` likewise
// names only columns `nar1_cases._FILTERABLE` will accept.
//
// v11 also draws an "Incorporation Date" column. It is NOT here, because
// `nar1_case_registry` (migration 024) does not select it — the column would
// render an em dash on every row forever, which reads as missing data rather
// than as a missing feature.
function buildColumns(meId, counts) {
  return [
    { col: 'case_no', label: 'Case ID', sort: 'case_no',
      filter: { kind: TEXT, placeholder: 'NAR-2026-…' } },
    { col: 'case_type', label: 'Case Type', sort: null,
      filter: { kind: ENUM, options: [{ value: 'NAR1', label: 'NAR1' }] } },
    { col: 'entity_id', label: 'Entity ID', sort: null,
      filter: { kind: ID, placeholder: 'Company UUID' } },
    { col: 'company_name', label: 'Company Name', sort: 'company_name',
      filter: { kind: TEXT, placeholder: 'Company name' } },
    { col: 'br_number', label: 'BRN', sort: 'br_number',
      filter: { kind: TEXT, placeholder: 'Business Registration No.' } },
    // STATUS IS GONE (Levi 2026-09-04: "not very useful and taking up space").
    // `case_status` and `workflow_status` are two names for one position in the
    // same pipeline, and the next column already gives the useful half: Status
    // read "Draft" on every open case, because a case leaves draft only when it
    // is filed, while Workflow said which of Data Verification / Client
    // Verification / Signing it was actually sitting in. A column whose value is
    // identical on every visible row is a column that costs width and answers
    // nothing.
    //
    // The FIELD is untouched — it still drives the case detail, the workflow
    // derivation and `nar1_case_status.derive()`, and the backend still accepts
    // it as a filter and a sort. Only this listing stops showing it.
    // The counts the removed tab row used to carry, kept where the filter now
    // lives. Losing them would have made this change a straight downgrade for
    // anyone who read the dashboard by scanning those numbers.
    { col: 'workflow_status', label: 'Workflow', sort: 'workflow_status',
      filter: {
        kind: ENUM,
        options: WORKFLOW_ORDER.map(value => ({
          value, label: WORKFLOW_LABEL[value], count: counts?.[value],
        })),
      } },
    { col: 'days_to_anniversary', label: 'Days to anniversary', sort: 'days_to_anniversary',
      filter: { kind: RANGE, unit: 'days', hint: ANNIV_HINT } },
    // Levi 2026-09-04: Last Updated belongs beside Create Date, not between the
    // identifiers and the company. The two dates answer the same question —
    // when did this case move — and reading them a screen apart meant scrolling
    // between halves of one answer.
    { col: 'updated_at', label: 'Last Updated', sort: 'updated_at', filter: { kind: DATE } },
    { col: 'created_at', label: 'Create Date', sort: 'created_at', filter: { kind: DATE } },
    // Sorts on `created_by_name`, not the uuid — ordering the dashboard by a
    // value nobody can read off the screen is not a sort. The FILTER is on the
    // uuid, because "mine" is an exact identity and two people can share a name.
    { col: 'created_by', label: 'Created By', sort: 'created_by_name',
      filter: { kind: OWNER, meId, nameCol: 'created_by_name' } },
  ]
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const { hasPermission, isSuperAdmin, profile, profileLoading } = useAuth()
  // nar1:read shows the cases; nar1:write is what opens and drives one.
  const canOpenCase = isSuperAdmin || hasPermission('nar1', 'write')
  const meId = profile?.id
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [showAdd, setShowAdd] = useState(false)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('asc')
  // `null` = the opening set has not been decided yet. See the effect below.
  const [filters, setFilters] = useState(null)

  // THE DASHBOARD OPENS ON YOUR OWN CASES (Levi 2026-09-03). It needs the
  // profile to know who that is, and `RequireAuth` renders this page before
  // /auth/me resolves — so the default is applied once, when the id arrives,
  // rather than read during the first render where it is not there yet.
  //
  // If the profile settles WITHOUT an id (a failed /auth/me), open unfiltered
  // instead of waiting forever: a dashboard showing everyone's cases is a
  // worse default but a working screen, and the chip row will say plainly that
  // nothing is applied.
  useEffect(() => {
    if (filters !== null) return
    if (meId) setFilters([{ col: 'created_by', op: 'eq', value: meId }])
    else if (!profileLoading) setFilters([])
  }, [meId, profileLoading, filters])

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  function onFilter(column, next) {
    setFilters(f => {
      let out = f || []
      // An owner filter writes two columns (the uuid and the display name), so
      // replacing "this column" has to clear both or the name filter survives
      // invisibly behind a funnel that reads as off.
      for (const c of (column.filter.kind === OWNER
        ? [column.col, column.filter.nameCol] : [column.col])) {
        out = out.filter(x => x.col !== c)
      }
      return [...out, ...next]
    })
    setPage(1)
  }

  function removeColumns(cols) {
    setFilters(f => (f || []).filter(x => !cols.includes(x.col)))
    setPage(1)
  }

  // Debounce the search box so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setQuery(search); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [search])

  const applied = filters || []
  // `workflow_status` rides its own query parameter rather than the generic
  // `filter=` grammar: it is the one column the backend must keep OUT of the
  // count queries, because those counts are what you pick a status from.
  const wfPicked = filtersFor(applied, 'workflow_status')[0]?.value || []
  const colFilters = applied.filter(f => f.col !== 'workflow_status')

  const params = new URLSearchParams({
    scope: 'dashboard', page: String(page), page_size: String(PAGE_SIZE),
  })
  if (query) params.set('search', query)
  if (wfPicked.length) params.set('workflow_status', wfPicked.join(','))
  if (sort) { params.set('sort', sort); params.set('dir', dir) }
  appendTo(params, colFilters)

  // Held back until the opening filter set is decided, so the screen never
  // fires one request for every case and a second for yours.
  const { data, loading, error } = useAbortableGet(
    filters === null ? null : `/cases?${params}`)

  const rows = data?.rows || []
  const counts = data?.counts || {}
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const columns = useMemo(() => buildColumns(meId, counts), [meId, counts])

  const sum = keys => keys.reduce((n, k) => n + (counts[k] ?? 0), 0)
  const actionCount = sum(ACTION_STATUSES)
  const pendingCount = sum(PENDING_STATUSES)

  const same = (a, b) => a.length === b.length && a.every(v => b.includes(v))
  const actionOn = same(wfPicked, ACTION_STATUSES)
  const pendingOn = same(wfPicked, PENDING_STATUSES)

  /** A tile is the filter for its own set: click to apply, click again to drop. */
  function toggleTile(statuses, on) {
    setFilters(f => setColumn(f || [], 'workflow_status',
      on ? [] : [{ col: 'workflow_status', op: 'in', value: statuses }]))
    setPage(1)
  }

  // Rows already past the anniversary and still filable. Counted from the page
  // in view, so the banner says "on this page" rather than implying a total it
  // has not been given — the server sends no separate overdue count.
  const overdueHere = rows.filter(r => r.days_to_anniversary != null
                                    && r.days_to_anniversary <= 0).length
  const annivFilters = filtersFor(applied, 'days_to_anniversary')
  const overdueOnly = annivFilters.length === 1
    && annivFilters[0].op === 'lte' && annivFilters[0].value === 0

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
          {/* Writes the same Days-to-anniversary filter the column header does,
              so it shows up as a chip and the funnel lights like any other. */}
          <button className="info-banner-cta"
                  onClick={() => {
                    setFilters(f => setColumn(f || [], 'days_to_anniversary',
                      overdueOnly ? [] : [{ col: 'days_to_anniversary', op: 'lte', value: 0 }]))
                    setPage(1)
                  }}>
            {overdueOnly ? 'Show all' : 'Review overdue'}
          </button>
        </div>
      )}

      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(2,minmax(0,1fr))', maxWidth: 560 }}>
        <button type="button" aria-pressed={actionOn}
                className={`stat-card accent-left is-filter${actionOn ? ' is-on' : ''}`}
                onClick={() => toggleTile(ACTION_STATUSES, actionOn)}>
          <div className="stat-lbl">Action Required</div>
          <div className="stat-val stat-accent">{actionCount}</div>
          <div className="stat-sub">Data Verification · Client response · Signing · Submission</div>
          <span className="stat-on-note">
            {actionOn ? 'Filtering — click to clear' : 'Click to filter'}
          </span>
        </button>
        <button type="button" aria-pressed={pendingOn}
                className={`stat-card accent-indigo is-filter${pendingOn ? ' is-on' : ''}`}
                onClick={() => toggleTile(PENDING_STATUSES, pendingOn)}>
          <div className="stat-lbl">Pending</div>
          <div className="stat-val" style={{ color: 'var(--indigo)' }}>{pendingCount}</div>
          <div className="stat-sub">Awaiting client response</div>
          <span className="stat-on-note">
            {pendingOn ? 'Filtering — click to clear' : 'Click to filter'}
          </span>
        </button>
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

      <FilterChips
        columns={columns}
        filters={applied}
        onRemove={removeColumns}
        onClearAll={() => { setFilters([]); setPage(1) }}
      />

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
      ) : (
        <>
          <div className="tbl-wrap tbl-stack">
            <table>
              <thead>
                <tr>
                  {columns.map(column => (
                    <FilterableTh key={column.col} column={column} sort={sort} dir={dir}
                                  onSort={onSort} filters={applied} onFilter={onFilter} />
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading || filters === null ? (
                  <tr><td colSpan={columns.length} className="empty-state">Loading…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={columns.length} className="empty-state">
                    <EmptyRow
                      filtered={applied.length > 0}
                      onClear={() => { setFilters([]); setPage(1) }}
                    />
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
                      <td data-label="Company Name"><span className="td-primary">{c.company_name}</span></td>
                      <td data-label="BRN"><span className="td-muted">{c.br_number || '—'}</span></td>
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
                      <td data-label="Last Updated"><span className="td-muted">{formatDate(c.updated_at)}</span></td>
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
