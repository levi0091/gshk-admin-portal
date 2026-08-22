import { useNavigate, useParams } from 'react-router-dom'
import { formatDate, formatDateTime } from '../lib/format.js'
import { labelForDays } from '../lib/anniversary.js'
import useAbortableGet from '../lib/useAbortableGet.js'
import StatusBadge from '../components/StatusBadge.jsx'
import { WorkflowBadge, FormBadge } from '../components/CaseStatusBadge.jsx'
import AuditTrailTab from '../components/AuditTrailTab.jsx'

/**
 * The NAR1 case screen (wireframe_v11 `s20`) — HEADER ONLY so far.
 *
 * FE-0 delivers the route and the shell: the dashboard opens a case directly
 * (that is the point of the case dashboard), so `/cases/{id}` has to resolve to
 * something real rather than a 404. What it shows is genuinely what the backend
 * knows — the case, both statuses, the deadline and the audit trail.
 *
 * The five workflow STAGES (Data Verification → Client Verification → Signing →
 * Submission → Confirmation, e-Sign and manual paths) are FE-2, FE-3 and FE-4.
 * They are deliberately not stubbed with dead buttons here: a control that looks
 * live and does nothing is worse than an honest absence, and these particular
 * buttons spend money at the Companies Registry.
 */

// Same shape as CompanyProfilePage's Kv — one definition of what a label/value
// row looks like across the portal.
function Kv({ label, children }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">{children ?? <span className="td-muted">—</span>}</span>
    </div>
  )
}

export default function CaseWorkflowPage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { data: c, loading, error } = useAbortableGet(`/cases/${caseId}`)

  if (loading) return <div className="empty-state" style={{ padding: 32 }}>Loading case…</div>

  if (error) {
    return (
      <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
        Failed to load this case: {error}
      </div>
    )
  }
  if (!c) return null

  const { text: annivText, due } = labelForDays(c.days_to_anniversary)

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">{c.case_no || 'Case'}</div>
          <div className="pg-sub">
            {c.company_name}
            {c.br_number ? ` · BRN ${c.br_number}` : ''}
          </div>
        </div>
        <div className="pg-actions">
          <button className="btn btn-outline" onClick={() => navigate('/dashboard')}>
            Back to cases
          </button>
          {c.entity_id && (
            <button className="btn btn-outline"
                    onClick={() => navigate(`/companies/${c.entity_id}`)}>
              Company profile
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-hdr">
          <div>
            <div className="card-title">Case summary</div>
            <div className="card-sub">
              Where this return stands with us, and what the Companies Registry
              has done with it
            </div>
          </div>
        </div>
        <div className="kv-list">
          <Kv label="Case type">
            <span className="badge b-inactive">{c.case_type || 'NAR1'}</span>
          </Kv>
          <Kv label="Company status"><StatusBadge status={c.case_status} /></Kv>
          {/* Two questions, two answers — never merged. See CaseStatusBadge. */}
          <Kv label="Workflow status"><WorkflowBadge status={c.workflow_status} /></Kv>
          <Kv label="CR form status">
            <FormBadge stage={c.form_status?.code} />
          </Kv>
          <Kv label="Days to anniversary">
            <span className={due ? 'td-anniv-due' : ''}>{annivText}</span>
          </Kv>
          <Kv label="Signing method">
            {c.signing_method
              ? (c.signing_method === 'manual' ? 'Manual (wet signature)' : 'e-Sign via CR')
              : <span className="td-muted">Not chosen yet</span>}
          </Kv>
          <Kv label="Verification sent">
            {c.verification_sent_at
              ? formatDateTime(c.verification_sent_at)
              : <span className="td-muted">Not sent</span>}
          </Kv>
          <Kv label="Client response">
            {c.client_response_at
              ? `${c.client_approved ? 'Approved' : 'Declined'} · ${formatDate(c.client_response_at)}`
              : <span className="td-muted">No response recorded</span>}
          </Kv>
        </div>

        {/* CR returns every fault at once so one pass can fix them all — so show
            every one, not just the first. */}
        {c.form_status?.failed && c.form_status.faults?.length > 0 && (
          <div style={{ margin: '16px 0 0', padding: '12px 14px', background: '#FEE2E2',
                        border: '1px solid #C53030', borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#C53030', marginBottom: 6 }}>
              The Companies Registry rejected this form
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: 'var(--t-body)' }}>
              {c.form_status.faults.map((f, i) => (
                <li key={i}>{typeof f === 'string' ? f : (f.faultString || JSON.stringify(f))}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-hdr">
          <div>
            <div className="card-title">Workflow</div>
            <div className="card-sub">
              The five filing stages are not built yet. Until they are, a NAR1 is
              driven from the Companies Registry portal and recorded here.
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-hdr">
          <div>
            <div className="card-title">Audit trail</div>
            <div className="card-sub">Every recorded action on this case</div>
          </div>
        </div>
        {/* audit_log.case_id holds the ENTITY id, not the case id — see
            routers/audit.py and the _audit_target() helper in routers/cases.py. */}
        <AuditTrailTab caseId={c.entity_id} />
      </div>
    </>
  )
}
