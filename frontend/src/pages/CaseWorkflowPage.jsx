import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate, formatDateTime } from '../lib/format.js'
import { labelForDays } from '../lib/anniversary.js'
import { useAuth } from '../context/AuthContext.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { WorkflowBadge, FormBadge } from '../components/CaseStatusBadge.jsx'
import AuditTrailTab from '../components/AuditTrailTab.jsx'
import CaseStepper from '../components/case/CaseStepper.jsx'
import StageDataVerification from '../components/case/StageDataVerification.jsx'
import StageClientVerification from '../components/case/StageClientVerification.jsx'
import StageSigning from '../components/case/StageSigning.jsx'
import StageSubmission from '../components/case/StageSubmission.jsx'
import StageConfirmation from '../components/case/StageConfirmation.jsx'
import { STAGE_LABELS, reachedStage } from '../components/case/workflow.js'

/**
 * The NAR1 case workflow (wireframe_v11 `s20`).
 *
 * Five stages behind a gate that is enforced here, not merely drawn: a return
 * cannot be signed before the client approved it, or filed before it was
 * signed. The gate is derived from the case record every time it renders, so it
 * cannot drift out of step with what the backend actually knows.
 *
 * Two status badges in the header, never merged (D-6): the WORKFLOW status is
 * where the case is with GSHK, the FORM status is what the Companies Registry
 * has done with the filing. See components/CaseStatusBadge.jsx.
 *
 * Every stage reports back through `onChanged`, which re-reads the case rather
 * than patching local state. The backend derives the workflow status from two
 * records, and guessing at the new one here is exactly how a screen starts
 * disagreeing with the trail it shares.
 */

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
  const { hasPermission, isSuperAdmin } = useAuth()

  const can = (mod, perm) => isSuperAdmin || hasPermission(mod, perm)
  const canWrite = can('nar1', 'write')
  const canValidate = can('tpsi', 'write')
  const canSubmit = can('tpsi', 'submit')
  const canReadTpsi = can('tpsi', 'read')

  const [caseRow, setCaseRow] = useState(undefined)
  const [loadError, setLoadError] = useState(null)
  const [failure, setFailure] = useState(null)
  const [notice, setNotice] = useState(null)
  const [step, setStep] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await api.get(`/cases/${caseId}`)
      setCaseRow(data)
      // Open on the furthest stage that is actually reachable, the first time
      // only — re-reading after an action must not yank the operator forward
      // out of the stage they are still working in.
      setStep(s => s ?? reachedStage(data))
      return data
    } catch (e) {
      setLoadError(e.message)
      setCaseRow(null)
      return null
    }
  }, [caseId])

  useEffect(() => { load() }, [load])

  const onChanged = useCallback(async () => {
    setFailure(null)
    const fresh = await load()
    if (!fresh) return
    // Advance by ONE stage, and only when the action genuinely unlocked it.
    // Never move backwards (a restart must not eject the operator mid-read) and
    // never skip ahead — each stage has something to show for what just
    // happened before the next one is asked for.
    setStep(s => {
      const from = s ?? 1
      const reached = reachedStage(fresh)
      return reached > from ? from + 1 : from
    })
  }, [load])

  if (caseRow === undefined) {
    return <div className="empty-state" style={{ padding: 32 }}>Loading case…</div>
  }
  if (loadError) {
    return (
      <div style={{ padding: 24, background: '#FEE2E2', borderRadius: 8, color: '#B91C1C', fontSize: 13 }}>
        Failed to load this case: {loadError}
      </div>
    )
  }
  if (!caseRow) return null

  const c = caseRow
  const { text: annivText, due } = labelForDays(c.days_to_anniversary)
  const current = step ?? 1

  const stageProps = { caseRow: c, onChanged, onError: setFailure }

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">{c.case_no || 'Case'}</div>
          <div className="pg-sub">
            {c.company_name}{c.br_number ? ` · BRN ${c.br_number}` : ''}
            {' · '}{STAGE_LABELS[current - 1]}
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

      {failure && (
        <div className="alert al-danger" role="alert" style={{ marginBottom: 16 }}>
          <span className="al-icon">⚠</span>
          <div className="al-body">
            {failure.message}
            {failure.hint && <div style={{ marginTop: 4 }}>{failure.hint}</div>}
          </div>
        </div>
      )}
      {notice && (
        <div className="alert al-info" role="status" style={{ marginBottom: 16 }}>
          <span className="al-icon">ℹ</span><div className="al-body">{notice}</div>
        </div>
      )}

      <CaseStepper
        caseRow={c}
        step={current}
        onGo={setStep}
        onLocked={setNotice}
      />

      <div className="card mb-16">
        <div className="kv-list">
          <Kv label="Case type"><span className="badge b-inactive">{c.case_type || 'NAR1'}</span></Kv>
          <Kv label="Company status"><StatusBadge status={c.case_status} /></Kv>
          <Kv label="Workflow status"><WorkflowBadge status={c.workflow_status} /></Kv>
          <Kv label="CR form status"><FormBadge stage={c.form_status?.code} /></Kv>
          <Kv label="Days to anniversary">
            <span className={due ? 'td-anniv-due' : ''}>{annivText}</span>
          </Kv>
          <Kv label="Signing method">
            {c.signing_method
              ? (c.signing_method === 'manual' ? 'Manual (wet signature)' : 'e-Sign via CR')
              : <span className="td-muted">Not chosen yet</span>}
          </Kv>
        </div>
      </div>

      {current === 1 && (
        <StageDataVerification {...stageProps} canWrite={canWrite} canValidate={canValidate} />
      )}
      {current === 2 && (
        <StageClientVerification {...stageProps} canWrite={canWrite} />
      )}
      {current === 3 && (
        <StageSigning {...stageProps} canWrite={canWrite && canValidate} />
      )}
      {current === 4 && (
        <StageSubmission {...stageProps} canSubmit={canSubmit} />
      )}
      {current === 5 && (
        <StageConfirmation caseRow={c} canRead={canReadTpsi} onError={setFailure} />
      )}

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

      <div className="f-hint" style={{ marginTop: 12 }}>
        Created {formatDate(c.created_at)}
        {c.updated_at ? ` · last updated ${formatDateTime(c.updated_at)}` : ''}
      </div>
    </>
  )
}
