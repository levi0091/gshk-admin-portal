import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api.js'
import { formatDate, formatDateTime } from '../lib/format.js'
import { labelForDays } from '../lib/anniversary.js'
import { useAuth } from '../context/AuthContext.jsx'
import { WorkflowBadge, FormBadge } from '../components/CaseStatusBadge.jsx'
import CaseStepper from '../components/case/CaseStepper.jsx'
import RefusalDetail from '../components/case/RefusalDetail.jsx'
import StageDataVerification from '../components/case/StageDataVerification.jsx'
import StageClientVerification from '../components/case/StageClientVerification.jsx'
import StageSigning from '../components/case/StageSigning.jsx'
import StageSubmission from '../components/case/StageSubmission.jsx'
import StageConfirmation from '../components/case/StageConfirmation.jsx'
import {
  STAGE_LABELS, reachedStage, isValidated, isSubmitted, isClosed, describeError,
  persistedFailure,
} from '../components/case/workflow.js'
import CloseCaseModal from '../components/case/CloseCaseModal.jsx'
import { scrollToTop } from '../lib/scroll.js'
import { caseWorkflowCaps } from '../lib/screenCapabilities.js'

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

  // `hasPermission` already returns true for a super admin; the `||` is kept
  // for the tests that mock the context without that behaviour.
  const can = (mod, perm) => isSuperAdmin || hasPermission(mod, perm)
  // Which control needs which module and level: `lib/screenCapabilities.js`,
  // enumerated across every combination by the permission matrix test.
  const caps = caseWorkflowCaps(can)
  const canWrite = caps.editCase
  const canClose = caps.closeCase
  const canValidate = caps.validate
  const canSubmit = caps.submit
  const canReadTpsi = can('tpsi', 'read')

  const [caseRow, setCaseRow] = useState(undefined)
  const [loadError, setLoadError] = useState(null)
  const [failure, setFailure] = useState(null)
  const [notice, setNotice] = useState(null)
  const [step, setStep] = useState(null)
  const [confirmRestart, setConfirmRestart] = useState(false)
  const [confirmClose, setConfirmClose] = useState(false)

  // WHY THIS EXISTS. The failure banner sits above the stage content, and the
  // buttons that produce a failure — Validate, Send, Apply signature, Submit —
  // sit a screen or more below it. A correct, fully-rendered error that never
  // enters the viewport is experienced as "I pressed the button and nothing
  // happened", which is exactly how the verification 409 was reported before.
  //
  // Announcing it is not enough: `role="alert"` reaches a screen reader, not
  // someone looking at a button halfway down the page.
  const failureRef = useRef(null)
  const noticeRef = useRef(null)
  const [restarting, setRestarting] = useState(false)

  // THE STANDARD (Levi 2026-09-03): every stage reports through `onError` and
  // `onWarn`, both of which render HERE and both of which scroll the page to
  // them. Stages used to choose between bubbling up and drawing their own
  // alert beside the button, and the workflow ended up doing both at once for
  // the same failure — a detailed banner at the top and a vaguer restatement
  // half a page down (which is what a submit refusal looked like on the day
  // this was reported). Scrolling is what makes one surface sufficient.
  const warn = useCallback((title, text) => {
    setNotice(text ? { tone: 'warn', title, text } : null)
  }, [])
  const inform = useCallback(text => {
    setNotice(text ? { tone: 'info', text } : null)
  }, [])

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
  //
  // A WARN notice scrolls too. A partial send — "two directors have it, the
  // third does not" — is a failure the operator has to act on, and it appears
  // at the same place for the same reason.
  const alarm = failure || (notice?.tone === 'warn' ? notice : null)
  useEffect(() => {
    if (!alarm) return
    try {
      scrollToTop(failureRef.current || noticeRef.current)
    } catch {
      /* Scrolling is a courtesy. Showing the error is not. */
    }
  }, [alarm])

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
  // `reachedStage` answers 0 for a closed case — no stage is reachable — and
  // `step` follows it, so `STAGE_LABELS[current - 1]` is `STAGE_LABELS[-1]`:
  // undefined, rendering the page title and the last breadcrumb crumb BLANK.
  // The screen has a name of its own here, and it is the one the badge uses.
  const heading = isClosed(c) ? 'Closed' : STAGE_LABELS[current - 1]

  // `onGo` is the stage's own "Continue to X →" button (v11 gives every panel
  // one). Separate from `onChanged`, which advances only when an action
  // genuinely unlocked the next stage — this is the operator saying they are
  // finished reading, which is a different event and must not be inferred.
  const goTo = n => { setStep(n); setNotice(null) }
  // `onWarn(title, text)` is the second half of the standard: an outcome that
  // is not a refusal but still needs acting on — a send that reached two of
  // three directors. It renders in the same place as an error and scrolls the
  // same way, so no stage has a reason to grow an alert of its own.
  const stageProps = {
    caseRow: c, onChanged, onError: setFailure, onWarn: warn, onGo: goTo,
  }

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
        <span className="crumb-here">{heading}</span>
      </div>

      <div className="pg-hdr">
        <div>
          <div className="pg-title">{heading}</div>
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
              unanswerable without opening the role.

              IT USED TO SAY `case_management`, WHICH IS NOT A MODULE. Nothing
              of that name exists in `role_permissions` and no role can be given
              it, so the one tag whose entire job is to answer "what do I ask
              for" named something an administrator could not grant. This screen
              runs on `nar1` for the case and `tpsi` for the CR calls — two
              modules, held independently, which is why the stages below refuse
              separately. */}
          <span className="perm-tag">Modules: <b>nar1</b>, <b>tpsi</b></span>
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
          {/* And GONE once the case is closed, for the same reason it is gone
              once the return is filed: the backend refuses it with a 409, and
              its confirmation promises to send the case "back to Data
              Verification" — a stage a closed case can never re-enter. */}
          {canWrite && !isClosed(c) && isValidated(c) && !isSubmitted(c) && (
            <button className="btn btn-outline" disabled={restarting}
                    onClick={() => setConfirmRestart(true)}>
              {restarting ? 'Restarting…' : 'Restart verification'}
            </button>
          )}
          {/* CLOSE, and it is the last thing on the bar for a reason: it ends
              the case and there is no undo. Withheld once CR holds the return
              — the backend refuses that with a 409, and a button whose one
              outcome is a refusal is a broken control, exactly as Restart's
              own `isSubmitted` guard reasons. Withheld on an already-closed
              case too, though that branch renders the closed panel and never
              reaches this bar. */}
          {canClose && !isClosed(c) && !isSubmitted(c) && (
            <button className="btn btn-outline btn-danger-outline"
                    onClick={() => setConfirmClose(true)}>
              Close case
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
            {/* Before anything else: the money did not move. The operator has
                just pressed a button labelled with a four-figure sum, and no
                amount of detail below is read calmly until that is settled. */}
            {banner.reassurance && (
              <div style={{ marginTop: 4 }}>{banner.reassurance}</div>
            )}

            {/* THE EVIDENCE, one card per fault. Every reason the backend
                gathered — it collects them all so one pass can fix them all,
                and showing one would waste that.

                Cards rather than the bullet list this replaced: a mismatch has
                TWO values and a bullet can only hold a sentence, which is how
                "on the form X, in the profile Y" used to arrive as a
                semicolon-spliced paragraph. */}
            <RefusalDetail differences={banner.differences}
                           problems={banner.problems} />

            {/* WHAT TO DO, under the evidence, with the actual control beside
                it. Restart lives in the page header too, but by the time an
                operator has read three fault cards the header is a place they
                have to go looking for. */}
            {banner.remedy && (
              <div className="rf-remedy">
                <div className="rf-remedy-txt">{banner.remedy}</div>
                {/* Offered only where restarting is genuinely the remedy —
                    never for a check that could not run — and only to someone
                    holding the permission and on a case that can still be
                    restarted. Those are the same conditions the header button
                    applies; disagreeing with it would put a button here that
                    fails when pressed. */}
                {banner.offerRestart && canWrite && !isClosed(c)
                  && isValidated(c) && !isSubmitted(c) && (
                  <button className="btn btn-outline btn-sm" disabled={restarting}
                          onClick={() => setConfirmRestart(true)}>
                    {restarting ? 'Restarting…' : 'Restart verification'}
                  </button>
                )}
              </div>
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
        <div ref={noticeRef} className={`alert al-${notice.tone || 'info'}`}
             role={notice.tone === 'warn' ? 'alert' : 'status'}
             style={{ marginBottom: 16 }}>
          <span className="al-icon">{notice.tone === 'warn' ? '⚠' : 'ℹ'}</span>
          <div className="al-body">
            {notice.title && <b>{notice.title}</b>}
            <div style={{ marginTop: notice.title ? 4 : 0 }}>{notice.text}</div>
          </div>
        </div>
      )}

      {/* THE WHOLE SCREEN, in place of the stepper and the five stages.
          A closed case has no stage to be in and nothing left to do in it, and
          every panel below writes: rendering them greyed would be five
          disabled controls where the honest answer is one sentence. What stays
          is the header, both badges, and the record of what happened — closing
          ends the WORK, not the record, and the company profile and the audit
          trail are both one click away in the bar above. */}
      {isClosed(c) ? (
        <ClosedPanel caseRow={c} />
      ) : (
        <>
        <CaseStepper
          caseRow={c}
          step={current}
          // Moving somewhere clears the "that stage is locked" note. Leaving it up
          // would have it explaining a refusal the operator has already moved past.
          onGo={n => { setStep(n); setNotice(null) }}
          // A locked stage is guidance, not a failure — it informs, and it does
          // not scroll the page out from under a click on the stepper.
          onLocked={inform}
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
        </>
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

      {/* Its own component, not another `modal-confirm` card: closing asks for
          a REASON and for the case number to be typed back, and neither fits a
          340px confirmation tile. See CloseCaseModal for why it asks for both. */}
      {confirmClose && (
        <CloseCaseModal
          caseRow={c}
          onClose={() => setConfirmClose(false)}
          onClosed={async () => {
            setConfirmClose(false)
            setFailure(null)
            setNotice(null)
            await load()
          }}
        />
      )}
    </>
  )
}


/**
 * What is left of a case that ended: who closed it, when, and why.
 *
 * The reason is quoted rather than paraphrased — it is somebody's own words and
 * the only record of why this case stopped. `white-space: pre-wrap` on
 * `.closed-why` keeps their line breaks; React escapes the text, so a reason
 * containing markup is shown, not run.
 */
export function ClosedPanel({ caseRow: c }) {
  // "Closed 5 Sept 2026, 10:00 by Levi Z." — and NOT "Levi Z..". Display names
  // ending in a full stop are ordinary (initials), and appending the sentence's
  // own one unconditionally doubles it.
  const lead = `Closed ${formatDateTime(c.closed_at)}`
    + (c.closed_by_name ? ` by ${c.closed_by_name}` : '')
  const opener = lead.endsWith('.') ? lead : `${lead}.`

  return (
    <div className="closed-panel" role="status">
      <div className="closed-hd">
        <span aria-hidden="true">■</span>
        This case was closed and cannot be reopened
      </div>
      <div className="closed-sub">
        {opener}{' '}
        Nothing further was filed with the Companies Registry for this return.
        If it is going ahead after all, open a new case from the company
        profile.
      </div>

      {c.closed_reason && (
        <div className="closed-why">
          <div className="closed-why-l">Reason given</div>
          {c.closed_reason}
        </div>
      )}
    </div>
  )
}
