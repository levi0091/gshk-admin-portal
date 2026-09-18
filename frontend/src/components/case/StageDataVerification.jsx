import { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import { downloadValidatedPdf } from '../../lib/download.js'
import CheckRow from './CheckRow.jsx'
import PdfFrame, { usePdfBlob } from './PdfPreview.jsx'
import ReturnDataCard from './ReturnDataCard.jsx'
import { crDate } from './ReturnYearCard.jsx'
import { describeError, isValidated, rebuildBeforeValidate } from './workflow.js'
import { ActionWithheld } from '../RequirePermission.jsx'

/**
 * What moved between the return the client approved and the one CR validated,
 * as the warning above the validated form (Levi 2026-09-18).
 *
 * Every row is a box printed differently on the two forms, and every one with
 * a page is boxed in orange on that page of the form below — the list and the
 * highlights come from the same comparison, so neither can mention a change
 * the other does not show. A row with no page is a value that is no longer on
 * the form at all (a director removed), which the list is the only place to
 * say.
 */
export function ValidationChanges({ comparison }) {
  if (!comparison) return null
  if (!comparison.compared) {
    // NOT "no changes". There is no approved copy to compare with — the case
    // was never sent, or was sent before the mailed bytes were kept.
    return (
      <div className="alert al-info" role="status" style={{ marginBottom: 14 }}>
        <span className="al-icon">ℹ</span>
        <div className="al-body">
          There is no copy of the return the client was sent to compare this
          with, so differences cannot be marked. Check it against the client's
          email before signing.
        </div>
      </div>
    )
  }
  const changes = comparison.changes || []
  if (changes.length === 0) {
    return (
      <div className="alert al-success" role="status" style={{ marginBottom: 14 }}>
        <span className="al-icon">✓</span>
        <div className="al-body">
          <b>Identical to the return the client approved.</b> Every box on the
          form CR validated prints the same as the copy they were sent.
        </div>
      </div>
    )
  }
  return (
    <div className="alert al-warn" role="alert" style={{ marginBottom: 14 }}>
      <span className="al-icon">⚠</span>
      <div className="al-body">
        <b>
          {changes.length === 1
            ? 'One field differs'
            : `${changes.length} fields differ`}{' '}
          from the return the client approved.
        </b>{' '}
        They are marked in orange on the form below. The client approved the
        version emailed to them; this is the version that will be signed and
        filed. If a difference matters to them, contact them — or use{' '}
        <b>Restart verification</b> to send the corrected return for approval.
        <div className="tbl-wrap" style={{ marginTop: 10 }}>
          <table>
            <thead>
              <tr>
                <th>Page</th>
                <th>Field</th>
                <th>Client approved</th>
                <th>CR validated</th>
              </tr>
            </thead>
            <tbody>
              {changes.map(c => (
                <tr key={`${c.section}|${c.field}|${c.approved}|${c.validated}`}>
                  <td className="td-muted">
                    {c.pages?.length ? c.pages.join(', ') : '—'}
                  </td>
                  <td>
                    <div className="td-primary">{c.field}</div>
                    <div className="td-muted">{c.section}</div>
                    {c.note && <div className="td-muted"><i>{c.note}</i></div>}
                  </td>
                  <td>
                    {c.approved == null
                      ? <i className="td-muted">(blank)</i>
                      : <span className="diff-old">{c.approved}</span>}
                  </td>
                  <td>
                    {c.validated == null
                      ? <i className="td-muted">(removed)</i>
                      : <span className="diff-new">{c.validated}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/**
 * Stage 2 — Data Verification (FE-3).
 *
 * THE SECOND STAGE SINCE 2026-09-17, not the first: the client has already
 * approved the return by the time this is reachable. That is what makes the
 * divergence notice below necessary — a CR rejection here is fixed by editing
 * the company record and re-validating, and the approval stands, so the
 * document that gets filed can move away from the one the director saw.
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
  const [comparison, setComparison] = useState(null)
  const [comparisonError, setComparisonError] = useState(null)
  const [yearInfo, setYearInfo] = useState(null)
  const [saving, setSaving] = useState(false)

  const validated = isValidated(caseRow)
  const faults = caseRow.form_status?.failed ? caseRow.form_status.faults : null
  const year = caseRow.return_year ?? caseRow.ar_period_year

  // THE VALIDATED FORM (Levi 2026-09-18). Revealed once CR has validated, and
  // re-fetched whenever a new validated copy lands — a restart and a fresh
  // validation give a new filing and a new timestamp, and either changes the
  // key. Before validation there is nothing CR has accepted to show.
  const validatedKey = `${caseRow.filing_id}|${caseRow.validated_at}`
  const { url: validatedUrl, error: validatedError } = usePdfBlob(
    validated ? `/cases/${caseRow.id}/validation/preview` : null, validatedKey)

  useEffect(() => {
    if (!validated) { setComparison(null); return undefined }
    let cancelled = false
    setComparisonError(null)
    api.get(`/cases/${caseRow.id}/validation/comparison`)
      .then(r => { if (!cancelled) setComparison(r) })
      .catch(e => { if (!cancelled) setComparisonError(describeError(e)) })
    return () => { cancelled = true }
  }, [caseRow.id, validated, validatedKey])

  // WHEN CR WILL TAKE IT. CR refuses to validate a return whose made-up date
  // is still ahead, in two faults one of which reads as if a LATE return were
  // refused. So the date is on screen before anybody presses Validate, and the
  // button waits for it. The backend refuses independently.
  useEffect(() => {
    if (validated) return undefined
    let cancelled = false
    api.get(`/cases/${caseRow.id}/return-year`)
      .then(r => { if (!cancelled) setYearInfo(r) })
      .catch(() => { if (!cancelled) setYearInfo(null) })   // advisory only
    return () => { cancelled = true }
  }, [caseRow.id, validated, caseRow.updated_at])
  const earlyUntil = yearInfo?.return_date && yearInfo?.today
    && yearInfo.return_date > yearInfo.today ? yearInfo.return_date : null

  async function downloadValidated() {
    setSaving(true)
    try {
      const name = `NAR1_${(caseRow.company_name || 'return').replace(/[^\w]+/g, '_')}`
        + `${year ? `_${year}` : ''}_validated.pdf`
      await downloadValidatedPdf(caseRow.id, name)
    } catch (e) {
      onError(describeError(e))
    } finally {
      setSaving(false)
    }
  }
  // Fields that have moved since the client approved. `?? []` rather than a
  // truthiness test: the backend sends an empty list for "nothing changed" AND
  // for "no snapshot kept" (a case sent before migration 046), and neither is
  // something to warn about — `approval_snapshot_kept` tells them apart, and
  // nothing on this screen needs to.
  const divergence = caseRow.approval_divergence ?? []

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

      {/* WHAT MOVED SINCE THE CLIENT APPROVED IT (migration 046).

          This is the cost of sending the client first, made visible. A CR
          rejection is fixed by editing the company record and re-validating,
          and the approval deliberately stands — so without this the return
          filed could differ from the one a director said yes to and nothing on
          screen would say so.

          A WARNING, NEVER A REFUSAL. It blocks nothing and offers no button:
          the operator decides whether the change is worth mailing a director
          over, and does that by hand (Levi 2026-09-17). Restart verification,
          in the header, is how a case goes back to the client properly.

          BEFORE VALIDATION ONLY since 2026-09-18. Once CR has validated, the
          validated-form viewer below compares the approved copy with CR's own
          copy, box by box, and marks each change on the form — two lists
          measuring slightly different things would read as two opinions. */}
      {!validated && divergence.length > 0 && (
        <div className="alert al-warn" role="status" style={{ marginBottom: 16 }}>
          <span className="al-icon">⚠</span>
          <div className="al-body">
            <b>
              {divergence.length === 1
                ? 'One field has changed'
                : `${divergence.length} fields have changed`}
              {' '}since the client approved this return.
            </b>{' '}
            They approved the version emailed to them; this is what would be
            filed. If the difference matters to them, email them and use{' '}
            <b>Restart verification</b> to send the corrected return.
            <ul className="mt-8">
              {divergence.map(d => (
                <li key={d.path}>
                  <b>{d.field}</b>: {d.validated ?? <i>(absent)</i>}
                  {' → '}
                  {d.current ?? <i>(absent)</i>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* The return itself, first — the wireframe opens this stage with the
          data, and everything below it is a decision about that data. */}
      <ReturnDataCard caseId={caseRow.id} reloadKey={caseRow.updated_at}
                      onChanged={onChanged} canWrite={canWrite} />

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

        {/* `readOnly` rather than `disabled` without `nar1:write`: whether
            these were ticked is the reason the case can or cannot advance, so
            the FACT has to stay readable even when the tick is not on offer. */}
        <CheckRow
          checked={Boolean(caseRow.aml_cleared)}
          readOnly={!canWrite}
          disabled={busy !== null}
          onToggle={v => patch('aml_cleared', v)}
          title="AML screening cleared"
          sub="Anti-money-laundering checks completed for this client."
        />
        <CheckRow
          checked={Boolean(caseRow.accounts_ready)}
          readOnly={!canWrite}
          disabled={busy !== null}
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
            {earlyUntil && (
              // Pre-emptive, so a note and not an alert: nothing was refused.
              <div className="card-note card-note-warn" role="status"
                   style={{ marginBottom: 12 }}>
                <b>CR will not validate the {yearInfo.year} return until{' '}
                {crDate(earlyUntil)}</b> — the company's incorporation
                anniversary in {yearInfo.year}, which is the date the return is
                made up to. An annual return cannot be made up to a future
                date. Validate on or after that day; if this case should be
                filing an earlier year, restart verification and choose it on
                Client Verification.
              </div>
            )}
            <div className="action-bar" style={{ marginTop: faults?.length ? 16 : 0 }}>
              <div className="ab-note">
                {!prechecksDone
                  ? 'Tick both manual checks above before validating with CR.'
                  : earlyUntil
                    ? `Available from ${crDate(earlyUntil)}.`
                    : caseRow.filing_id
                      ? 'Re-checks the corrected details with CR.'
                      : 'Builds the return and asks CR to check it.'}
              </div>
              <div className="ab-actions">
                {canValidate ? (
                  <>
                    {/* `tpsi:write`, not `tpsi:read` as this tag used to say.
                        Validating REBUILDS the draft first (`filings/prepare`,
                        `tpsi:write`) and only then asks CR to check it
                        (`filings/{id}/validate`, `tpsi:read`) — so a role with
                        read alone could never complete the action this tag was
                        promising it. Still free: CR charges for the submit. */}
                    <span className="perm-tag">
                      Requires <b>tpsi:write</b> — validation is free
                    </span>
                    <button className="btn btn-action"
                            disabled={!prechecksDone || busy !== null
                                      || Boolean(earlyUntil)}
                            onClick={runValidation}>
                      {busy === 'validate' ? 'Checking with CR…' : 'Validate with CR'}
                    </button>
                  </>
                ) : (
                  <ActionWithheld module="tpsi" permission="write"
                                  action="validating with CR" />
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {/* THE RETURN CR VALIDATED (Levi 2026-09-18) — revealed once it
          exists, and replaced whenever a new validated copy comes back.
          Client Verification keeps showing what the client approved; this
          shows what will be signed and filed, with every box that differs
          from the approved copy marked, and the list of those differences
          above it. */}
      {validated && (
        <div className="card mb-16">
          <div className="card-hdr">
            <div>
              <div className="card-title">The return CR validated</div>
              <div className="card-sub">
                Validated by the Companies Registry
                {caseRow.validated_at ? ` on ${formatDateTime(caseRow.validated_at)}` : ''}.
                This is the version that will be signed and filed.
              </div>
            </div>
            <div className="row gap-8">
              <button type="button" className="btn btn-outline btn-sm"
                      disabled={saving} onClick={downloadValidated}>
                {saving ? 'Preparing…' : 'Download PDF'}
              </button>
              <button type="button" className="btn btn-outline btn-sm"
                      disabled={!validatedUrl}
                      onClick={() => window.open(validatedUrl, '_blank', 'noopener')}>
                Open full screen
              </button>
            </div>
          </div>

          {comparisonError ? (
            <div className="card-note card-note-warn" role="status"
                 style={{ marginBottom: 14 }}>
              <b>The differences from the approved return could not be worked
              out.</b> {comparisonError.message}
            </div>
          ) : (
            <ValidationChanges comparison={comparison} />
          )}

          <PdfFrame
            url={validatedUrl}
            error={validatedError}
            label="CR-validated NAR1"
            fileName={`NAR1${year ? ` ${year}` : ''} — as validated by CR`}
            pills={[
              { label: 'Rendered from the CR-validated XML', tone: 'ok' },
              ...(comparison?.changes?.length
                ? [{ label: `${comparison.changes.length} change`
                    + `${comparison.changes.length === 1 ? '' : 's'} marked`,
                     tone: 'warn' }]
                : []),
            ]}
          />
        </div>
      )}

      {validated && onGo && (
        <div className="action-bar">
          {/* The client has already approved by the time this stage is
              reachable (2026-09-17) — they are stage 1 now — so what comes
              next is the signature, not the email. */}
          <div className="ab-note">
            The Companies Registry has accepted this return for filing. It is
            signed next.
          </div>
          <div className="ab-actions">
            <button className="btn btn-primary" onClick={() => onGo(3)}>
              Continue to Signing →
            </button>
          </div>
        </div>
      )}
    </>
  )
}
