import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate, formatDateTime } from '../lib/format.js'
import { labelForDays } from '../lib/anniversary.js'
import { useAuth } from '../context/AuthContext.jsx'
import { WorkflowBadge, FormBadge } from '../components/CaseStatusBadge.jsx'
import CaseStepper from '../components/case/CaseStepper.jsx'
import { readFault } from '../components/case/FaultPanel.jsx'
import StageDataVerification from '../components/case/StageDataVerification.jsx'
import StageClientVerification from '../components/case/StageClientVerification.jsx'
import StageSigning from '../components/case/StageSigning.jsx'
import StageSubmission from '../components/case/StageSubmission.jsx'
import StageConfirmation from '../components/case/StageConfirmation.jsx'
import {
  STAGE_LABELS, reachedStage, isValidated, isSubmitted, describeError,
  persistedFailure,
} from '../components/case/workflow.js'
import { scrollToTop } from '../lib/scroll.js'

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
  const [confirmRestart, setConfirmRestart] = useState(false)

  // WHY THIS EXISTS. The failure banner sits above the stage content, and the
  // buttons that produce a failure — Validate, Send, Apply signature, Submit —
  // sit a screen or more below it. A correct, fully-rendered error that never
  // enters the viewport is experienced as "I pressed the button and nothing
  // happened", which is exactly how the verification 409 was reported before.
  //
  // Announcing it is not enough: `role="alert"` reaches a screen reader, not
  // someone looking at a button halfway down the page.
  const failureRef = useRef(null)
  const [restarting, setRestarting] = useState(false)

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

  // TO THE TOP OF THE PAGE, not merely to the banner (Levi 2026-08-31).
  // `scrollIntoView({block:'center'})` centred the banner and left the crumb,
  // the title and both status badges above the fold — and it scrolled whatever
  // the browser picked as the scrolling box, which is not necessarily the one
  // the app shell scrolls. `scrollToTop` finds the ancestor that is actually
  // overflowing (AppShell's <main class="app-main">) and puts it at 0.
  //
  // Keyed on the LIVE failure only. A refusal read back off the case renders
  // the same banner, but it is already on screen when the page opens — and
  // re-scrolling on every case reload would yank the operator to the top each
  // time they ticked a checkbox with an old rejection still on record.
  //
  // Guarded HERE as well as inside scrollToTop, and the belt-and-braces is
  // deliberate: this effect runs in the commit that renders the banner, so an
  // exception blanks the very error it exists to reveal. That regression has
  // already happened once. The guard must not depend on a collaborator keeping
  // its own try/catch.
  useEffect(() => {
    if (!failure) return
    try {
      scrollToTop(failureRef.current)
    } catch {
      /* Scrolling is a courtesy. Showing the error is not. */
    }
  }, [failure])

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

  // `onGo` is the stage's own "Continue to X →" button (v11 gives every panel
  // one). Separate from `onChanged`, which advances only when an action
  // genuinely unlocked the next stage — this is the operator saying they are
  // finished reading, which is a different event and must not be inferred.
  const goTo = n => { setStep(n); setNotice(null) }
  const stageProps = { caseRow: c, onChanged, onError: setFailure, onGo: goTo }

  // THE ONLY PLACE A CR REFUSAL IS DRAWN. The stages used to render the same
  // faults again in their own FaultPanel, so one rejection appeared twice on
  // one screen. The live failure wins when there is one; otherwise the banner
  // shows what CR said last, read back off the case, so a reload never leaves
  // a "Rejected at validation" badge with its reason nowhere on the page.
  const banner = failure || persistedFailure(c)

  async function restart() {
    setFailure(null); setConfirmRestart(false); setRestarting(true)
    try {
      await api.patch(`/cases/${c.id}`, { restart_verification: true })
      // Back to stage 1 explicitly. `onChanged` only ever moves FORWARD, so
      // without this the operator is left on Signing looking at a case that no
      // longer has a snapshot to sign.
      await load()
      setStep(1)
    } catch (e) {
      setFailure(describeError(e))
    } finally {
      setRestarting(false)
    }
  }

  return (
    <>
      {/* Breadcrumb, stage-as-title, case line, then the two badges side by
          side — the v11 header, which the shipped screen had replaced with the
          case number and a six-row property list. */}
      <div className="crumb">
        <button className="crumb-link" onClick={() => navigate('/dashboard')}>
          Post-incorporation
        </button>
        <span className="crumb-sep">›</span>
        {c.entity_id ? (
          <button className="crumb-link"
                  onClick={() => navigate(`/companies/${c.entity_id}`)}>
            {c.company_name || 'Company'}
          </button>
        ) : (
          <span>{c.company_name || 'Company'}</span>
        )}
        <span className="crumb-sep">›</span>
        <span>{c.case_type || 'NAR1'} · Annual Return{c.ar_period_year ? ` ${c.ar_period_year}` : ''}</span>
        <span className="crumb-sep">›</span>
        <span className="crumb-here">{STAGE_LABELS[current - 1]}</span>
      </div>

      <div className="pg-hdr">
        <div>
          <div className="pg-title">{STAGE_LABELS[current - 1]}</div>
          <div className="pg-sub">
            Case {c.case_no || '—'} · Annual Return ({c.case_type || 'NAR1'})
            {c.company_name ? ` · ${c.company_name}` : ''}
            {c.br_number ? ` · BRN ${c.br_number}` : ''}
            {annivText ? ' · ' : ''}
            {annivText && (
              <span className={due ? 'td-anniv-due' : ''}>{annivText}</span>
            )}
          </div>
        </div>
        <div className="pg-actions">
          {/* v11 states the module a screen belongs to, because permissions are
              granted per module and "why can't I press this" is otherwise
              unanswerable without opening the role. */}
          <span className="perm-tag">Module: <b>case_management</b></span>
          {/* In the HEADER, not inside stage 1 (v11). Restart is what you reach
              for when something is wrong at Client Verification or Signing —
              which is exactly where the button used to be unreachable, because
              it lived in a card two stages back. */}
          {/* GONE once the return is filed (Levi 2026-08-31). Restart cannot
              un-file a return — the backend refuses it with a 409 — and the
              button was still on offer on a Confirmation screen reading
              "Filed with CR", where its confirmation dialog promises to
              discard a snapshot and clear an approval that the filing in the
              register was built on. */}
          {canWrite && isValidated(c) && !isSubmitted(c) && (
            <button className="btn btn-outline" disabled={restarting}
                    onClick={() => setConfirmRestart(true)}>
              {restarting ? 'Restarting…' : 'Restart verification'}
            </button>
          )}
          {/* NO Save button, though v11 draws one beside Restart. Every stage
              here writes immediately — a tick PATCHes, a capacity choice
              PATCHes, a method change PATCHes — so there is nothing pending
              for Save to flush. A button that saves nothing is worse than no
              button: it teaches an operator that their edits are unsaved until
              they press it, which is false, and one day they will leave a
              screen believing they had not committed something they had. */}
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

      {/* Two vocabularies, never merged (D-6): where the case is with GSHK, and
          what CR has done with the filing. */}
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
            <span className="ls-key">Signing</span>
            <span>{c.signing_method === 'manual'
              ? 'Manual (wet signature)' : 'e-Sign via CR'}</span>
          </>
        )}
      </div>

      {banner && (
        <div ref={failureRef} className="alert al-danger" role="alert" style={{ marginBottom: 16 }}>
          <span className="al-icon">⚠</span>
          <div className="al-body">
            <b>{banner.message}</b>
            {/* Every reason the backend gathered — it collects them all so one
                pass can fix them all, and showing one would waste that.
                Rendered through readFault because CR sends (code, message)
                PAIRS: JSON.stringify put ["ERR_MSG_...","..."] on screen. */}
            {banner.problems && (
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {banner.problems.map((p, i) => {
                  const { field, msg } = readFault(p)
                  return (
                    <li key={i}>
                      {msg}
                      {field && <span className="td-muted"> ({field})</span>}
                    </li>
                  )
                })}
              </ul>
            )}
            {banner.hint && (
              <div style={{ marginTop: 4 }}
                   // A locked CR account is not an ordinary validation note:
                   // it stops every filing by that signatory until CR reinstates
                   // it, and further attempts keep it locked.
                   className={banner.kind === 'account_locked' ? 'f-strong' : undefined}>
                {banner.kind === 'account_locked' && <b>Account locked. </b>}
                {banner.hint}
              </div>
            )}
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
        // Moving somewhere clears the "that stage is locked" note. Leaving it up
        // would have it explaining a refusal the operator has already moved past.
        onGo={n => { setStep(n); setNotice(null) }}
        onLocked={setNotice}
      />

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

      {/* No audit trail here (Levi 2026-08-26). Every action on this case is
          already in the Audit Log module, and repeating it on the workflow
          screen means two places to check what happened. The trail stays where
          it is complete; this screen stays about the work in front of you. */}

      <div className="f-hint" style={{ marginTop: 12 }}>
        Created {formatDate(c.created_at)}
        {c.updated_at ? ` · last updated ${formatDateTime(c.updated_at)}` : ''}
      </div>

      {/* Restart discards a CR-SIGNED snapshot and clears every step taken
          since — client verification and signature included. Behind a
          confirmation for that reason; the first shipped version did it on one
          click. */}
      {confirmRestart && (
        <div className="modal-confirm" role="alertdialog"
             aria-label="Restart verification">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">
              Restart verification for {c.case_no || 'this case'}?
            </div>
            <div className="modal-confirm-text">
              The case goes back to Data Verification. The CR-signed snapshot is
              discarded, and the client verification and any signature recorded
              against it are cleared. The client will have to approve the return
              again.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline"
                      onClick={() => setConfirmRestart(false)}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={restart}>
                Restart — back to Data Verification
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
