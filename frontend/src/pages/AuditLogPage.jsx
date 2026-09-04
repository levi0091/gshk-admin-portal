import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import useAbortableGet from '../lib/useAbortableGet.js'
import { formatDateTime } from '../lib/format.js'
import FilterableTh from '../components/FilterableTh.jsx'
import FilterChips from '../components/FilterChips.jsx'
import EmptyRow from '../components/EmptyRow.jsx'
import { DATE, ENUM, TEXT, appendTo, setColumn } from '../lib/tableFilters.js'
import {
  MODULES, MODULE_LABELS, SUBJECT_KIND_LABELS, subjectHref, subjectOf,
} from '../lib/auditVocabulary.js'

const PAGE_SIZE = 100

const ACTION_LABELS = {
  CASE_STATUS_CHANGED: 'Case status changed',
  CASE_FIELD_UPDATED: 'Case field updated',
  AML_STATUS_CHANGED: 'AML status changed',
  DOCUMENT_GENERATED: 'Document generated',
  DOCUMENT_UPLOADED: 'Document uploaded',
  DOCUMENT_VERSION_ADDED: 'New document version',
  DOCUMENT_DELETED: 'Document deleted',
  EMAIL_SENT: 'Email sent',
  TPSI_AUTH: 'CR session opened',
  TPSI_FILING_CREATED: 'CR filing prepared',
  TPSI_VALIDATE: 'CR form validated',
  TPSI_SIGN: 'CR form signed',
  TPSI_EDRIVE: 'CR form sent to e-Drive',
  TPSI_PREVIEWED: 'CR submission previewed',
  TPSI_BALANCE_CHECK: 'CR deposit balance checked',
  TPSI_STATUS: 'CR case status enquired',
  TPSI_CRED_SET: 'CR credential set',
  TPSI_CRED_ROTATE: 'CR credential rotated',
  TPSI_PW_CHANGE: 'CR password changed',
  TPSI_SUBMISSION_ATTEMPTED: 'TPSI submission attempted',
  TPSI_SUBMISSION_SUCCESS: 'TPSI submission succeeded',
  TPSI_SUBMISSION_FAILED: 'TPSI submission failed',
  CLIENT_APPROVAL_RECEIVED: 'Client approval received',
  COMPANY_CREATED: 'Company created',
  COMPANY_FLAG_CHANGED: 'Company flags changed',
  PERSON_CREATED: 'Person created',
  PERSON_FIELD_UPDATED: 'Person field updated',
  PARTY_LINKED: 'Party linked',
  PARTY_UPDATED: 'Party updated',
  PARTY_UNLINKED: 'Party unlinked',
  LEGACY_VP_EVENT: 'Viewpoint event',
}

const SOURCES = [
  { key: null, label: 'All' },
  { key: 'g_flowdesk', label: 'G-FlowDesk' },
  { key: 'viewpoint_import', label: 'Viewpoint (imported)' },
]

// The columns, in the order an auditor reads a row: WHEN, in WHICH module, WHAT
// happened, to WHICH record, what it became, and BY WHOM.
//
// Every one of them filters and sorts SERVER-SIDE. This table paginates 100
// rows at a time out of 226k+, so a filter applied in the browser would narrow
// the page that happened to arrive and answer a different question — see
// lib/tableFilters.js and backend/services/table_filters.py.
//
// The Subject column filters on `company_name`, which is the subject's NAME
// whichever kind it is (it has always held a person's name on person rows).
// Narrowing to one KIND is what the Module filter is for; a second control over
// the same distinction is how two headers start disagreeing.
const COLUMNS = [
  { col: 'created_at', label: 'Time (HKT)', sort: 'created_at',
    filter: { kind: DATE } },
  { col: 'module', label: 'Module', sort: 'module',
    filter: { kind: ENUM, options: MODULES } },
  { col: 'action_label', label: 'Action', sort: 'action_label',
    filter: { kind: TEXT, placeholder: 'Action or event code' } },
  { col: 'company_name', label: 'Case / Company / Person', sort: 'company_name',
    filter: { kind: TEXT, placeholder: 'Company, person or case' } },
  { col: 'new_value', label: 'What changed', sort: 'new_value',
    filter: { kind: TEXT, placeholder: 'New value' } },
  { col: 'user_display_name', label: 'User', sort: 'user_display_name',
    filter: { kind: TEXT, placeholder: 'Who did it' } },
]

const formatTs = formatDateTime

/**
 * What actually happened.
 *
 * Imported Viewpoint rows all carry action_type='LEGACY_VP_EVENT', which says
 * nothing — the real action is Viewpoint's own description (EventLog.Description,
 * e.g. "Get Started HK Limited Appointed as Secretary"). Prefer that; fall back
 * to the native action label.
 */
function actionOf(e) {
  // The GENERIC action from the event-type registry — the same name whether the
  // change happened in Viewpoint or G-FlowDesk. Never the per-record description
  // ("Master File Details of Miss Ilze TSERKEZIS Changed"), which cannot be
  // grouped or filtered.
  if (e.action_label) return e.action_label
  return ACTION_LABELS[e.action_type] || e.action_type
}

/**
 * Anything the audit trail hands us, as text React can actually render.
 *
 * THE WHOLE SCREEN WENT DOWN WITHOUT THIS. `before_state`/`after_state` are
 * free-form JSONB written by ~50 call sites over two years, and one of them
 * (`POST /companies/{id}/share-classes`) put a whole object in `new`. React
 * refuses to render an object as a child — error #31 — and because it throws
 * during render it takes the entire Audit Log with it, not just that row. One
 * row on page 1 was enough.
 *
 * So this is a boundary, not a patch for one caller. The trail's job is to
 * display whatever history contains, including rows written before anyone
 * thought about how they would look, and no future payload may be able to
 * blank the page. The backend now writes that particular row per-field like
 * every other edit; this stays regardless.
 *
 * An object renders as `key: value; key: value` — the same shape the backend
 * uses when it flattens a map into `new_value`, so the two read alike.
 */
function asText(value) {
  if (value == null) return null
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value.map(asText).filter(v => v != null && v !== '').join(', ') || null
  }
  if (typeof value === 'object') {
    const parts = Object.entries(value)
      .map(([k, v]) => [k, asText(v)])
      .filter(([, v]) => v != null && v !== '')
      .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
    return parts.length ? parts.join('; ') : null
  }
  return String(value)
}

/**
 * What changed, as a list of {label, old, new} — every value already text.
 *
 * Viewpoint-imported rows carry `changed_fields`, decoded out of the EventString
 * by the ETL (migration 014). Native rows record a single field edit in
 * before_state/after_state. Both end up in the same shape so the two sources
 * render identically — which is the whole point of the shared audit model.
 */
function changesOf(e) {
  return rawChangesOf(e).map(c => ({
    label: asText(c.label),
    old: asText(c.old),
    new: asText(c.new),
  }))
}

function rawChangesOf(e) {
  if (e.changed_fields?.length) return e.changed_fields

  if (e.after_state?.field) {
    return [{
      label: String(e.after_state.field).replace(/_/g, ' '),
      old: e.before_state?.old,
      new: e.after_state.new,
    }]
  }
  if (e.action_type === 'COMPANY_FLAG_CHANGED' && e.after_state) {
    return Object.keys(e.after_state).map(f => ({
      label: f.replace(/_/g, ' '),
      old: e.before_state?.[f],
      new: e.after_state[f],
    }))
  }
  if (e.old_value || e.new_value) {
    return [{ label: null, old: e.old_value, new: e.new_value }]
  }
  return []
}

function Change({ e }) {
  const changes = changesOf(e)
  if (!changes.length) return <span className="td-muted">—</span>
  return (
    <span style={{ fontSize: 12 }}>
      {changes.map((c, i) => (
        <span key={i} style={{ display: 'block' }}>
          {c.label && <span className="td-muted">{c.label}: </span>}
          {c.old ? <span className="diff-old">{c.old}</span> : null}
          {c.old && c.new ? <span className="td-muted"> → </span> : null}
          {c.new ? <span className="diff-new">{c.new}</span> : null}
        </span>
      ))}
    </span>
  )
}

/**
 * WHICH RECORD the row is about — a kind chip, the name, and a link.
 *
 * A row whose subject never resolved falls back to the raw Viewpoint key, drawn
 * muted and unlinked so it reads as "we could not identify this" rather than as
 * a name.
 */
function Subject({ e, onOpen }) {
  const subject = subjectOf(e)
  if (!subject) return <span className="td-muted">—</span>

  const kind = SUBJECT_KIND_LABELS[e.subject_kind]
  const href = subject.raw ? null : subjectHref(e)

  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
      {kind && <span className="filing-tag">{kind}</span>}
      {href ? (
        <span
          className="bc-link"
          style={{ color: 'var(--indigo)', fontWeight: 600, fontSize: 12 }}
          onClick={() => onOpen(href)}
        >
          {subject.name}
        </span>
      ) : (
        <span
          className={subject.raw ? 'td-muted' : 'td-primary'}
          style={{ fontSize: 12 }}
          title={subject.raw ? 'Viewpoint key — no matching record' : undefined}
        >
          {subject.name}
        </span>
      )}
      {subject.ref && (
        <span className="td-muted" style={{ fontSize: 11.5 }}>({subject.ref})</span>
      )}
    </span>
  )
}

export default function AuditLogPage() {
  const navigate = useNavigate()
  const [source, setSource] = useState(null)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('desc')
  // No default filter. This screen is the record of what happened, and opening
  // it on a narrowed set would mean the answer to "did anyone touch this" is
  // conditioned on a choice nobody made.
  const [filters, setFilters] = useState([])

  function onSort(col, nextDir) {
    setSort(col)
    setDir(nextDir)
    setPage(1)
  }

  function onFilter(column, next) {
    setFilters(f => setColumn(f, column.col, next))
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

  const params = new URLSearchParams({ page: String(page), limit: String(PAGE_SIZE) })
  if (source) params.set('source', source)
  if (query) params.set('search', query)
  if (sort) { params.set('sort', sort); params.set('dir', dir) }
  appendTo(params, filters)

  // Cancels the previous request on every toggle — UAT W-8. See the hook.
  const { data, loading, error } = useAbortableGet(`/audit/?${params}`)

  const entries = data?.entries || []
  const total = data?.total || 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Audit Log</div>
          <div className="pg-sub">
            All system activity — read-only · {total.toLocaleString()} entries
          </div>
        </div>
      </div>

      <div className="search-wrap">
        <svg className="search-icon" width="14" height="14" fill="none" stroke="currentColor"
             strokeWidth="2" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="5" /><path d="M11 11l3 3" strokeLinecap="round" />
        </svg>
        <input className="search-input" type="text"
               aria-label="Search company, person, reference, action or user"
               placeholder="Search company, person, reference, action or user"
               value={search} onChange={e => setSearch(e.target.value)} />
      </div>

      <div className="filter-tabs" role="tablist">
        {SOURCES.map(s => (
          <button key={s.label} role="tab" aria-selected={source === s.key}
                  className={`filter-tab ${source === s.key ? 'active' : ''}`}
                  onClick={() => { setSource(s.key); setPage(1) }}>
            {s.label}
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
          Failed to load audit log: {error}
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
                ) : entries.length === 0 ? (
                  <tr><td colSpan={COLUMNS.length} className="empty-state">
                    <EmptyRow
                      filtered={filters.length > 0}
                      onClear={() => { setFilters([]); setPage(1) }}
                    />
                  </td></tr>
                ) : entries.map(e => (
                  <tr key={e.id}>
                    <td data-label="Time">
                      <span className="td-muted" style={{ whiteSpace: 'nowrap' }}>{formatTs(e.created_at)}</span>
                    </td>
                    <td data-label="Module">
                      {e.module ? (
                        <span className="td-primary" style={{ fontSize: 12 }}>
                          {MODULE_LABELS[e.module] || e.module}
                        </span>
                      ) : (
                        <span className="td-muted">—</span>
                      )}
                    </td>
                    <td data-label="Action">
                      <span className="td-primary" style={{ fontSize: 12.5 }}>{actionOf(e)}</span>
                      {e.event_code && <span className="filing-tag">{e.event_code}</span>}
                    </td>
                    <td data-label="Case / Company / Person">
                      <Subject e={e} onOpen={navigate} />
                    </td>
                    <td data-label="What changed" style={{ maxWidth: 340 }}>
                      <Change e={e} />
                    </td>
                    <td data-label="User">
                      <span className="td-muted">
                        {e.user_display_name || e.created_by || '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {!loading && total > 0 && (
            <div className="pager">
              <span>
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total.toLocaleString()}
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
