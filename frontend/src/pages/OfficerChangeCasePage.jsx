import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { formatDate, formatDateTime } from '../lib/format.js'
import { WorkflowBadge, FormBadge } from '../components/CaseStatusBadge.jsx'
import CloseCaseModal from '../components/case/CloseCaseModal.jsx'
import { crStatus, stageTone } from '../components/case/workflow.js'
import { ClosedPanel } from './CaseWorkflowPage.jsx'
import { officerChangeApi } from '../components/officerChange/api.js'
import {
  STAGES, FORM_TITLE, capsFor, deadlineText, errorOf, isClosed, isFiled, stageDone,
  stageIndexFor,
} from '../components/officerChange/workflow.js'
import StageClientVerification from '../components/officerChange/StageClientVerification.jsx'
import StageDataVerification from '../components/officerChange/StageDataVerification.jsx'
import StageSigning from '../components/officerChange/StageSigning.jsx'
import StageSubmission from '../components/officerChange/StageSubmission.jsx'
import StageConfirmation from '../components/officerChange/StageConfirmation.jsx'
import StageCrStatus from '../components/officerChange/StageCrStatus.jsx'
import '../components/officerChange/officerChange.css'

const Tick = () => (
  <svg width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2.5"
       viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8l3.5 3.5L13 4" /></svg>
)

/**
 * An ND2A or ND2B case (spec §5): the NAR1 case page's header, stepper and six
 * stages, with the officer change's own stage components.
 *
 * Every stage receives exactly `{ data, reload, can, goTo }`. `reload(next)`
 * takes the composite a write route returned (every officer-change write
 * answers with it) or, without one, re-reads it — so the page never patches
 * local state and guesses at what the backend now says.
 */
export default function OfficerChangeCasePage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { hasPermission, isSuperAdmin } = useAuth()
  const can = useCallback((mod, perm) => isSuperAdmin || hasPermission(mod, perm),
    [isSuperAdmin, hasPermission])
  const caps = capsFor(can)

  const [data, setData] = useState(undefined)
  const [loadError, setLoadError] = useState(null)
  const [step, setStep] = useState(null)
  const [notice, setNotice] = useState(null)
  const [confirmRestart, setConfirmRestart] = useState(false)
  const [confirmClose, setConfirmClose] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const fresh = await officerChangeApi.get(caseId)
      setData(fresh)
      setStep(s => s ?? Math.max(stageIndexFor(fresh), 1))
      return fresh
    } catch (e) {
      setLoadError(errorOf(e).message)
      setData(null)
      return null
    }
  }, [caseId])

  useEffect(() => { load() }, [load])

  const reload = useCallback(async (next) => {
    if (next && typeof next === 'object' && next.id) {
      setData(next.case && next.case.id ? next.case : next)
      return next
    }
    return load()
  }, [load])

  if (data === undefined) {
    return <div className="empty-state" style={{ padding: 32 }}>Loading case…</div>
  }
  if (loadError || !data) {
    return (
      <div className="alert al-danger" role="alert">
        <span className="al-icon">⚠</span>
        <div className="al-body">Failed to load this case: {loadError}</div>
      </div>
    )
  }

  const c = data
  const reached = stageIndexFor(c)
  const current = Math.min(step ?? 1, Math.max(reached, 1))
  const heading = isClosed(c) ? 'Closed' : STAGES[current - 1]
  const due = deadlineText(c.deadline)
  const goTo = (n) => {
    if (n <= Math.max(reached, 1)) { setStep(n); setNotice(null) }
  }
  const stageProps = { data: c, reload, can: caps, goTo }

  async function restart() {
    setConfirmRestart(false); setBusy(true)
    try {
      await reload(await officerChangeApi.patch(c.id, { restart_verification: true }))
      setStep(1)
      setNotice({ tone: 'info', text: 'Verification restarted. The change list can be edited again.' })
    } catch (e) {
      setNotice({ tone: 'warn', text: errorOf(e).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="oc-page">
      <div className="crumb">
        <button className="crumb-link" onClick={() => navigate('/dashboard')}>Post-incorporation</button>
        <span className="crumb-sep">›</span>
        {c.entity_id ? (
          <button className="crumb-link" onClick={() => navigate(`/companies/${c.entity_id}`)}>
            {c.company_name || 'Company'}
          </button>
        ) : <span>{c.company_name || 'Company'}</span>}
        <span className="crumb-sep">›</span>
        <span>{c.case_type} · {FORM_TITLE[c.form_code]}</span>
        <span className="crumb-sep">›</span>
        <span className="crumb-here">{heading}</span>
      </div>

      <div className="pg-hdr">
        <div>
          <div className="pg-title">{heading}</div>
          <div className="pg-sub">
            Case {c.case_no || '—'} · {FORM_TITLE[c.form_code]} ({c.case_type})
            {c.company_name ? ` · ${c.company_name}` : ''}
            {c.br_number ? ` · BRN ${c.br_number}` : ''}
            {c.deadline?.date && (
              <> · Due at CR {formatDate(c.deadline.date)}
                {due && !isFiled(c) && (
                  <> (<span className={due.overdue ? 'oc-deadline-over' : ''}>{due.text}</span>)</>
                )}
              </>
            )}
          </div>
        </div>
        <div className="pg-actions">
          <span className="perm-tag">Modules: <b>officer_changes</b>, <b>tpsi</b></span>
          {caps.write && c.verification_sent_at && !isFiled(c) && !isClosed(c) && (
            <button className="btn btn-outline" disabled={busy}
                    onClick={() => setConfirmRestart(true)}>
              {busy ? 'Restarting…' : 'Restart verification'}
            </button>
          )}
          {caps.write && !isClosed(c) && !isFiled(c) && (
            <button className="btn btn-outline btn-danger-outline"
                    onClick={() => setConfirmClose(true)}>Close case</button>
          )}
          <button className="btn btn-outline" onClick={() => navigate('/dashboard')}>Back to cases</button>
          {c.entity_id && (
            <button className="btn btn-outline" onClick={() => navigate(`/companies/${c.entity_id}`)}>
              Company profile
            </button>
          )}
        </div>
      </div>

      <div className="live-strip mb-16">
        <span className="ls-key">Workflow</span>
        <WorkflowBadge status={c.workflow_status} />
        <span className="ls-div" />
        <span className="ls-key">CR form</span>
        {c.form_status?.code
          ? <FormBadge stage={c.form_status.code} />
          : <span className="td-muted">Not sent to CR yet</span>}
        {c.signing_method && (
          <>
            <span className="ls-div" />
            <span className="ls-key">Route</span>
            <span>{c.signing_method === 'manual' ? 'Manual (CR portal)' : 'e-Sign via CR'}</span>
          </>
        )}
      </div>

      {notice && (
        <div className={`alert al-${notice.tone || 'info'}`} role={notice.tone === 'warn' ? 'alert' : 'status'}
             style={{ marginBottom: 16 }}>
          <span className="al-icon">{notice.tone === 'warn' ? '⚠' : 'ℹ'}</span>
          <div className="al-body">{notice.text}</div>
        </div>
      )}

      {isClosed(c) ? <ClosedPanel caseRow={c} /> : (
        <>
          <div className="stepper" role="tablist" aria-label="Case stages">
            {STAGES.map((label, i) => {
              const n = i + 1
              const done = stageDone(c, n)
              const unlocked = n <= Math.max(reached, 1)
              const active = n === current
              const tone = n === 6 ? stageTone(c, 6) : null
              let cls = 'step'
              if (done) cls += ' done'
              else if (active) cls += ' active'
              else if (unlocked) cls += ' avail'
              else cls += ' locked'
              if (unlocked) cls += ' clickable'
              if (tone && !done) cls += ` tone-${tone}`
              const state = n === 6 && unlocked ? crStatus(c).label
                : done ? 'Done' : active ? 'In progress' : unlocked ? 'Available' : 'Locked'
              return (
                <div key={label} className={cls} role="tab" aria-selected={active}
                     aria-disabled={!unlocked} tabIndex={unlocked ? 0 : -1}
                     onClick={() => unlocked ? goTo(n) : setNotice({
                       tone: 'info', text: `Complete "${STAGES[Math.max(reached, 1) - 1]}" to unlock ${label}.` })}
                     onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && unlocked) { e.preventDefault(); goTo(n) } }}>
                  <div className={`step-line${n > 1 && stageDone(c, n - 1) ? ' filled' : ''}`} />
                  <div className="step-num">{done ? <Tick /> : n}</div>
                  <div className="step-lbl">{label}</div>
                  <div className="step-state">{state}</div>
                </div>
              )
            })}
          </div>

          {current === 1 && <StageClientVerification {...stageProps} />}
          {current === 2 && <StageDataVerification {...stageProps} />}
          {current === 3 && <StageSigning {...stageProps} />}
          {current === 4 && <StageSubmission {...stageProps} />}
          {current === 5 && <StageConfirmation {...stageProps} />}
          {current === 6 && <StageCrStatus {...stageProps} />}
        </>
      )}

      <div className="f-hint" style={{ marginTop: 12 }}>
        Created {formatDate(c.created_at)}
        {c.updated_at ? ` · last updated ${formatDateTime(c.updated_at)}` : ''}
      </div>

      {confirmRestart && (
        <div className="modal-confirm" role="alertdialog" aria-label="Restart verification">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Restart verification for {c.case_no}?</div>
            <div className="modal-confirm-text">
              The case goes back to Client Verification. The form sent to the client
              {c.verification_sent_at ? ` on ${formatDateTime(c.verification_sent_at)}` : ''} is
              discarded, its Confirm link stops working, and any answer, check or signature
              recorded since is cleared. The change list can then be edited and sent again.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setConfirmRestart(false)}>Cancel</button>
              <button className="btn btn-danger" onClick={restart}>Restart — back to Client Verification</button>
            </div>
          </div>
        </div>
      )}
      {confirmClose && (
        <CloseCaseModal caseRow={c} closePath={`/officer-changes/${c.id}/close`}
                        onClose={() => setConfirmClose(false)}
                        onClosed={async () => { setConfirmClose(false); await load() }} />
      )}
    </div>
  )
}
