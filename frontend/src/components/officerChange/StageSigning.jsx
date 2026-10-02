import { useState } from 'react'
import { officerChangeApi } from './api.js'
import CrRefusal from './CrRefusal.jsx'
import EffectiveDatesPanel from './EffectiveDatesPanel.jsx'
import { errorOf, isManual } from './workflow.js'

/**
 * Stage 3 (spec §5; answers 8, 9, 10, 17).
 *
 * e-Sign: one press. Each new director's consent is signed from THEIR stored
 * e-Registry account, then the overall signature from the signed-in user's own
 * e-Service account, in one call to CR. No password is typed here.
 *
 * Manual: the form is prepared and signed on CR's portal. An ND2A offers NO
 * download (answer 10 — the operator already has it from CR's portal); an ND2B
 * keeps one. Uploading the signed PDF does not move the case on (answer 9):
 * Continue is its own press, so a wrong file is caught here.
 *
 * Both routes first ask for any effective date left blank when the client was
 * sent the form (Jacqueline A1: "place the effective date button on the
 * 'Signing – e-Page' and 'Signing – Paper' pages before we complete the
 * signature"). On e-Sign that also means CR validates here, after the dates.
 */
export default function StageSigning({ data, reload, can, goTo }) {
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const manual = isManual(data)
  const signed = data.filing?.stage === 'signed'
  const validated = data.filing?.stage === 'validated' || signed
  const consents = data.route?.consents || []
  const datesPending = (data.dates_missing || []).length > 0
  const mismatches = consents.filter(c => c.id_mismatch)

  async function run(promise) {
    setError(null); setBusy(true)
    try { await reload(await promise) } catch (e) { setError(errorOf(e)) } finally { setBusy(false) }
  }

  async function download() {
    try {
      const blob = await officerChangeApi.preview(data.id, 'staff')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${data.case_type}-${data.case_no}.pdf`; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError(errorOf(e)) }
  }

  if (manual) {
    return (
      <>
      {!data.manual_signed_document_id && <EffectiveDatesPanel data={data} reload={reload} can={can} />}
      <div className="card">
        <div className="card-title">Signing — manual (CR portal)</div>
        {data.form_code === 'Nd2a' ? (
          <p className="f-hint" style={{ marginTop: 6 }}>
            Prepare the ND2A on the Companies Registry's portal, have it signed, and upload the
            signed PDF here.
          </p>
        ) : (
          <div className="oc-send-row">
            <span className="f-hint">Download the ND2B, have it signed, then upload the signed PDF.</span>
            <button className="btn btn-outline" onClick={download}>Download form</button>
          </div>
        )}
        {data.manual_signed_document_id ? (
          <div className="oc-send-row">
            <span className="badge b-live">Signed form uploaded</span>
            <span className="f-hint">Version {data.manual_signed_document_version || 1}, saved to the company's documents.</span>
            <button className="btn btn-primary" onClick={() => goTo(4)}>Continue to Submission →</button>
          </div>
        ) : null}
        {can.write && (
          <div className="oc-send-row">
            <input type="file" accept="application/pdf" aria-label="Signed form (PDF)"
                   onChange={e => setFile(e.target.files?.[0] || null)} />
            <button className="btn btn-outline" disabled={!file || busy || datesPending}
                    onClick={() => run(officerChangeApi.uploadSignedForm(data.id, file))}>
              {data.manual_signed_document_id ? 'Replace signed form' : 'Upload signed form'}
            </button>
            {datesPending && <span className="f-hint">Enter the effective dates above first.</span>}
          </div>
        )}
        {error && <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
          <div className="al-body">{error.message}</div></div>}
      </div>
      </>
    )
  }

  return (
    <>
    {!validated && <EffectiveDatesPanel data={data} reload={reload} can={can} />}
    <div className="card">
      <div className="card-title">Signing — e-Sign via CR</div>
      {mismatches.length > 0 && (
        // Jacqueline, note 1: e-Reg is not updated when CR's register is.
        <div className="alert al-warn" role="alert" style={{ marginTop: 10 }}>
          <div className="al-body">{mismatches.map(c => <div key={c.entry_id}>{c.id_mismatch}</div>)}</div>
        </div>
      )}
      <ul style={{ margin: '10px 0 0', paddingLeft: 18 }}>
        {consents.map(c => (
          <li key={c.entry_id}>
            Consent to act: <b>{c.signer_name}</b>
            {c.eservice_user_id ? ` (e-Registry ${c.eservice_user_id})` : ''}
            {c.signed_at ? ' — signed' : ''}
          </li>
        ))}
        <li>The form itself: signed with your own e-Service account, for {data.signatory?.name}
          {data.signatory?.selected_capacity || data.signatory?.default_capacity
            ? ` as ${data.signatory.selected_capacity || data.signatory.default_capacity}` : ''}.</li>
      </ul>
      {consents.length === 0 && (
        <p className="f-hint">No consent signature is needed on this form — only the overall signature.</p>
      )}
      <div className="oc-send-row">
        {!validated ? (
          can.tpsiWrite ? (
            <>
              <button className="btn btn-primary" disabled={busy || datesPending}
                      onClick={() => run(officerChangeApi.validate(data.id))}>
                {busy ? 'Validating…' : 'Validate with CR'}
              </button>
              <span className="f-hint">
                {datesPending ? 'Enter the effective dates above first; CR checks them.'
                  : 'CR checks the form, dates included, before it is signed.'}
              </span>
            </>
          ) : <span className="f-hint">Validating with CR needs Companies Registry filing (Edit).</span>
        ) : signed ? (
          <>
            <span className="badge b-live">Signed</span>
            <button className="btn btn-primary" onClick={() => goTo(4)}>Continue to Submission →</button>
          </>
        ) : can.tpsiWrite ? (
          <button className="btn btn-primary" disabled={busy}
                  onClick={() => run(officerChangeApi.sign(data.id))}>
            {busy ? 'Signing…' : 'Apply signatures'}
          </button>
        ) : (
          <span className="f-hint">Signing needs Companies Registry filing (Edit).</span>
        )}
      </div>
      <CrRefusal error={error} />
    </div>
    </>
  )
}
