import { useState } from 'react'
import { formatDate } from '../../lib/format.js'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

const Tick = () => (
  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
       strokeWidth="2.6" aria-hidden="true"><path d="M3 8l3.5 3.5L13 4" /></svg>
)

/**
 * Data Verification's manual checks (Jacqueline A4, the mock-up on p. 25):
 * "Things the portal cannot confirm for you."
 *
 * The list is the backend's (`checks.manual_checks`) — KYC per new officer, a
 * resignation letter per leaver, the signed written resolution, and on the
 * manual route each new director's consent to act. A document check is DONE
 * when its file is attached, so attaching is the tick: there is no box to
 * tick over a missing letter. Done rows are green, as on the mock-up, and say
 * which file and when. A consent a director signed in G-FlowDesk arrives here
 * already attached.
 *
 * Without Officer changes (edit) the list is read, with no control drawn.
 */
export default function ManualChecks({ data, reload, can }) {
  const checks = data.manual_checks || []
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  if (checks.length === 0) return null

  async function run(code, promise) {
    setError(null); setBusy(code)
    try { await reload(await promise) } catch (e) { setError(errorOf(e).message) } finally { setBusy(null) }
  }

  function attach(check, file) {
    if (!file) return
    const call = check.entry_id
      ? officerChangeApi.uploadDocument(data.id, check.entry_id, file, check.document_type)
      : officerChangeApi.uploadCaseDocument(data.id, file, check.document_type, false)
    run(`${check.code}-${check.entry_id}`, call)
  }

  const open = checks.filter(c => !c.ok).length
  return (
    <div className="card">
      <div className="card-hdr">
        <div>
          <div className="card-title">Manual checks</div>
          <div className="card-sub">
            Things the portal cannot confirm for you. Each is recorded against the case, and
            all of them are needed before the form leaves Data Verification.
          </div>
        </div>
        <span className={`badge ${open ? 'b-pending-aml' : 'b-live'}`}>
          {open ? `${open} to do` : 'All done'}
        </span>
      </div>
      <div className="oc-checks">
        {checks.map(check => {
          const key = `${check.code}-${check.entry_id}`
          return (
            <div key={key} className="oc-check" data-check={check.code}
                 data-ok={String(Boolean(check.ok))}>
              {check.kind === 'tick' && can.write ? (
                <label className="oc-check-main">
                  <input type="checkbox" className="oc-check-box" checked={Boolean(check.ok)}
                         disabled={busy === key}
                         onChange={e => run(key, officerChangeApi.setKyc(data.id, check.entry_id,
                           e.target.checked))} />
                  <span className="oc-check-label">{check.label}</span>
                </label>
              ) : (
                <div className="oc-check-main">
                  <span className="oc-check-mark" aria-hidden="true">{check.ok ? <Tick /> : null}</span>
                  <span className="oc-check-label">{check.label}</span>
                </div>
              )}
              {check.kind === 'document' && (
                <div className="oc-check-sub">
                  {check.document ? (
                    <>Attached: <b>{check.document.file_name}</b>
                      {check.document.uploaded_at ? ` · uploaded ${formatDate(check.document.uploaded_at)}` : ''}</>
                  ) : 'Nothing attached yet.'}
                  {can.write && (
                    <label className="oc-check-file">
                      {busy === key ? 'Uploading…' : check.document ? 'Replace' : 'Attach'}
                      <input type="file" className="visually-hidden"
                             aria-label={check.document
                               ? `Replace the file for ${check.label}`
                               : `Attach a file for ${check.label}`}
                             disabled={busy === key}
                             onChange={e => { attach(check, e.target.files?.[0]); e.target.value = '' }} />
                    </label>
                  )}
                </div>
              )}
              {check.kind === 'tick' && (
                <div className="oc-check-sub">Screening of the incoming officer, as for NAR1's AML check.</div>
              )}
            </div>
          )
        })}
      </div>
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 10 }}>
        <div className="al-body">{error}</div></div>}
    </div>
  )
}
