import { useState } from 'react'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import CheckRow from './CheckRow.jsx'
import ReturnDataCard from './ReturnDataCard.jsx'
import { describeError, isValidated, rebuildBeforeValidate } from './workflow.js'

/**
 * Stage 1 — Data Verification (FE-3).
 *
 * Two manual pre-checks the portal cannot do for itself, then the CR
 * validation that produces the immutable snapshot everything downstream is
 * built from.
 *
 * `prepare` and `validate` are two calls on purpose: prepare maps the company
 * to CR's schema and creates the filing (no CR contact), validate is what CR
 * actually answers. Splitting them means a mapping failure reads as a mapping
 * failure instead of arriving disguised as a CR rejection.
 */
export default function StageDataVerification({ caseRow, canWrite, canValidate, onChanged, onError, onGo }) {
  const [busy, setBusy] = useState(null)

  const validated = isValidated(caseRow)
  const faults = caseRow.form_status?.failed ? caseRow.form_status.faults : null

  // "CR validation stays locked until they are ticked" (wireframe_v11 s20).
  // The two checks are assertions about work done OUTSIDE the portal — AML
  // screening, and the e-Filing accounts CR will look for when the return is
  // signed. Validating first is not harmful (validateFormNar1 is free), but it
  // lets a case reach the client with neither done, and the frozen snapshot
  // makes that expensive to walk back.
  const prechecksDone = Boolean(caseRow.aml_cleared) && Boolean(caseRow.accounts_ready)

  async function patch(field, value) {
    onError(null)
    try {
      await api.patch(`/cases/${caseRow.id}`, { [field]: value })
      onChanged()
    } catch (e) {
      onError(describeError(e))
    }
  }

  async function runValidation() {
    onError(null); setBusy('validate')
    try {
      // REBUILD BEFORE RE-ASKING. `validate` re-sends the filing's STORED
      // request_xml verbatim, so skipping prepare on a retry sent CR the same
      // bytes it had already refused — and every correction the operator had
      // just made (an address, the signing capacity) was invisible. On case
      // NAR-2026-0065 that showed up as CR naming a signatory in a capacity the
      // case had not said for hours.
      //
      // `prepare` refreshes the case's own draft in place (REBUILDABLE_STAGES),
      // so this no longer orphans a second filing the way it once would have.
      // A validated filing is deliberately NOT rebuilt: its snapshot is what
      // the client approves and what gets filed, and `Restart verification` is
      // the sanctioned way to discard one.
      let filingId = caseRow.filing_id
      if (rebuildBeforeValidate(caseRow)) {
        const filing = await api.post('/tpsi/filings/prepare', {
          entity_id: caseRow.entity_id,
          nar1_case_id: caseRow.id,
        })
        filingId = filing.id
      }
      await api.post(`/tpsi/filings/${filingId}/validate`, {})
      onChanged()
    } catch (e) {
      onError(describeError(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      {/* v11 opens this stage by saying what validation DOES, because the
          frozen snapshot is the one concept the rest of the workflow rests on
          and nothing later explains it. Shown before validation only — once
          the snapshot exists, the success alert below says the same thing in
          the past tense and two copies read as two different snapshots. */}
      {!validated && (
        <div className="alert al-info" role="note" style={{ marginBottom: 16 }}>
          <span className="al-icon">ℹ</span>
          <div className="al-body">
            <b>Review the return data, then validate with the CR Portal.</b>{' '}
            Validation calls TPSI <code>validateFormNar1</code> and{' '}
            <b>freezes an immutable snapshot</b> — from here the case reads its
            own snapshot, not the live profile.
          </div>
        </div>
      )}

      {/* The return itself, first — the wireframe opens this stage with the
          data, and everything below it is a decision about that data. */}
      <ReturnDataCard caseId={caseRow.id} reloadKey={caseRow.updated_at}
                      onChanged={onChanged} />

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Manual checks</div>
            <div className="card-sub">
              Two things the portal cannot confirm for you. Tick them once they
              are genuinely done — they are recorded against the case.
            </div>
          </div>
        </div>

        <CheckRow
          checked={Boolean(caseRow.aml_cleared)}
          disabled={!canWrite || busy !== null}
          onToggle={v => patch('aml_cleared', v)}
          title="AML screening cleared"
          sub="Anti-money-laundering checks completed for this client."
        />
        <CheckRow
          checked={Boolean(caseRow.accounts_ready)}
          disabled={!canWrite || busy !== null}
          onToggle={v => patch('accounts_ready', v)}
          title="e-Reg accounts created"
          sub="Every signatory holds an individual e-Filing account with the Companies Registry, and CR has associated it with this company."
        />
        {/* The wireframe's presentor note, without naming the account. Two
            different CR identities meet on this screen and confusing them
            wastes a filing window: GSHK's presenter account is what SUBMITS
            and pays, and it is already configured — the tick above is about
            the signatory's own e-Filing account, which is what CR checks
            against `selectPersonId` when the return is signed. The presenter's
            id and deposit account stay a super-admin-only field. */}
        <div className="f-hint" style={{ padding: '10px 4px 2px' }}>
          This is <b>not</b> GSHK's presenter account. That one submits the
          return and pays the fee, and is already set up; this tick is about the
          account the <b>signatory</b> signs with.
        </div>
      </div>

      <div className="card mb-16">
        <div className="card-hdr">
          <div>
            <div className="card-title">Companies Registry validation</div>
            <div className="card-sub">
              Builds the NAR1 from this company's live record and asks CR to
              check it. Nothing is filed and nothing is charged.
            </div>
          </div>
        </div>

        {validated ? (
          <>
            <div className="alert al-success" role="status" style={{ marginBottom: 14 }}>
              <span className="al-icon">✓</span>
              <div className="al-body">
                <b>CR-signed snapshot frozen{caseRow.validated_at ? ` ${formatDateTime(caseRow.validated_at)}` : ''}.</b>{' '}
                Everything from here — the PDF the client sees, the signature and
                the filing — is built from this exact snapshot, not from the live
                company record.
              </div>
            </div>
            {/* "Restart verification" is NOT here any more — it moved to the
                page header (v11), where it is reachable from Client
                Verification and Signing too. Those are the stages you are
                standing on when you discover the snapshot is wrong, and the
                button used to be two stages behind you. */}
            <div className="ab-note" style={{ marginTop: 12 }}>
              Changed the company details since? Use <b>Restart verification</b>{' '}
              at the top of the page to discard the snapshot and validate again.
            </div>
          </>
        ) : (
          <>
            {/* NO FaultPanel here. CR's refusal is drawn ONCE, in the page
                banner at the top (Levi 2026-08-31) — it used to appear both
                places at once and one rejection read as two problems. The
                banner shows the live failure, and falls back to the faults
                stored on the case (`persistedFailure`) so a reload still says
                why. `faults` is still read below to space and caption the
                action bar. */}
            <div className="action-bar" style={{ marginTop: faults?.length ? 16 : 0 }}>
              <div className="ab-note">
                {!prechecksDone
                  ? 'Tick both manual checks above before validating with CR.'
                  : caseRow.filing_id
                    ? 'Re-checks the corrected details with CR.'
                    : 'Builds the return and asks CR to check it.'}
              </div>
              <div className="ab-actions">
                <span className="perm-tag">
                  Requires <b>tpsi:read</b> — validation is free
                </span>
                <button className="btn btn-action"
                        disabled={!canValidate || !prechecksDone || busy !== null}
                        onClick={runValidation}>
                  {busy === 'validate' ? 'Checking with CR…' : 'Validate with CR'}
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {validated && onGo && (
        <div className="action-bar">
          <div className="ab-note">
            The client sees this return next, as a PDF built from the snapshot.
          </div>
          <div className="ab-actions">
            <button className="btn btn-primary" onClick={() => onGo(2)}>
              Continue to Client Verification →
            </button>
          </div>
        </div>
      )}
    </>
  )
}
