import { useState } from 'react'
import { officerChangeApi } from './api.js'
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
 */
export default function StageSigning({ data, reload, can, goTo }) {
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const manual = isManual(data)
  const signed = data.filing?.stage === 'signed'
  const consents = data.route?.consents || []

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
            <button className="btn btn-outline" disabled={!file || busy}
                    onClick={() => run(officerChangeApi.uploadSignedForm(data.id, file))}>
              {data.manual_signed_document_id ? 'Replace signed form' : 'Upload signed form'}
            </button>
          </div>
        )}
        {error && <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
          <div className="al-body">{error.message}</div></div>}
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-title">Signing — e-Sign via CR</div>
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
        {signed ? (
          <>
            <span className="badge b-live">Signed</span>
            <button className="btn btn-primary" onClick={() => goTo(4)}>Continue to Submission →</button>
          </>
        ) : (
          <button className="btn btn-primary" disabled={!can.tpsiWrite || busy}
                  onClick={() => run(officerChangeApi.sign(data.id))}>
            {busy ? 'Signing…' : 'Apply signatures'}
          </button>
        )}
      </div>
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
        <div className="al-body">{error.message}</div></div>}
    </div>
  )
}
