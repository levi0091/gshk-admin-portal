import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api.js'
import SortableTh from '../components/SortableTh.jsx'

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

function formatTs(iso) {
  return new Date(iso).toLocaleString('en-HK', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
    timeZone: 'Asia/Hong_Kong',
  })
}

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

/** What changed: old → new. */
function changeOf(e) {
  // Native field edits record {field, old} / {field, new}.
  if (e.after_state?.field) {
    const field = String(e.after_state.field).replace(/_/g, ' ')
    return { field, old: e.before_state?.old, next: e.after_state.new }
  }
  if (e.action_type === 'COMPANY_FLAG_CHANGED' && e.after_state) {
    const field = Object.keys(e.after_state)[0]
    return { field: field?.replace(/_/g, ' '), old: String(e.before_state?.[field]), next: String(e.after_state[field]) }
  }
  // Imported rows lift the scalar change out of the EventString.
  if (e.old_value || e.new_value) {
    return { field: null, old: e.old_value || null, next: e.new_value || null }
  }
  if (e.action_type === 'LEGACY_VP_EVENT' && e.metadata?.descr) {
    return { field: null, old: null, next: e.metadata.descr }
  }
  return null
}

function Change({ e }) {
  const c = changeOf(e)
  if (!c) return <span className="td-muted">—</span>
  return (
    <span style={{ fontSize: 12 }}>
      {c.field && <span className="td-muted">{c.field}: </span>}
      {c.old ? <span className="diff-old">{c.old}</span> : null}
      {c.old && c.next ? <span className="td-muted"> → </span> : null}
      {c.next ? <span className="diff-new">{c.next}</span> : null}
    </span>
  )
}

export default function AuditLogPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [source, setSource] = useState(null)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState(null)
  const [dir, setDir] = useState('desc')

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
    const params = new URLSearchParams({ page: String(page), limit: String(PAGE_SIZE) })
    if (source) params.set('source', source)
    if (query) params.set('search', query)
    if (sort) { params.set('sort', sort); params.set('dir', dir) }

    api.get(`/audit/?${params}`)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [source, query, page, sort, dir])

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
               aria-label="Search company, action, event code or user"
               placeholder="Search company, action, event code or user"
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
                  {[
                    ['created_at', 'Time (HKT)'],
                    ['action_label', 'Action'],
                    ['company_name', 'Company / Case'],
                    ['new_value', 'What changed'],
                    ['user_display_name', 'User'],
                  ].map(([col, label]) => (
                    <SortableTh key={col} col={col} sort={sort} dir={dir} onSort={onSort}
                                style={col === 'created_at' ? { width: 150 } : undefined}>
                      {label}
                    </SortableTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={5} className="empty-state">Loading…</td></tr>
                ) : entries.length === 0 ? (
                  <tr><td colSpan={5} className="empty-state">No audit events match this view.</td></tr>
                ) : entries.map(e => (
                  <tr key={e.id}>
                    <td data-label="Time">
                      <span className="td-muted" style={{ whiteSpace: 'nowrap' }}>{formatTs(e.created_at)}</span>
                    </td>
                    <td data-label="Action">
                      <span className="td-primary" style={{ fontSize: 12.5 }}>{actionOf(e)}</span>
                      {e.event_code && <span className="filing-tag">{e.event_code}</span>}
                    </td>
                    <td data-label="Company / Case">
                      {e.company_name ? (
                        e.case_id ? (
                          <span className="bc-link" style={{ color: 'var(--indigo)', fontWeight: 600, fontSize: 12 }}
                                onClick={() => navigate(`/companies/${e.case_id}`)}>
                            {e.company_name}
                          </span>
                        ) : (
                          <span className="td-primary" style={{ fontSize: 12 }}>{e.company_name}</span>
                        )
                      ) : e.source_keycode ? (
                        <span className="td-muted" title="Viewpoint key — no matching record">
                          {e.source_keycode}
                        </span>
                      ) : (
                        <span className="td-muted">—</span>
                      )}
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
