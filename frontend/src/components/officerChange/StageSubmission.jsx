import { useState } from 'react'
import PdfFrame, { usePdfBlob } from '../case/PdfPreview.jsx'
import ProfileChangesList from './ProfileChangesList.jsx'
import { officerChangeApi } from './api.js'
import { errorOf, isFiled, isManual } from './workflow.js'

/**
 * Stage 4 (spec §5, answers 11 and 12). First what filing will change — the
 * profiles, and which supporting files go to which profile — then:
 *
 *   e-Sign  the form CR validated, on screen; a tick that it was checked; and
 *           File with CR behind a confirmation — free, but irreversible, so
 *           the portal's rule for submitForm holds: preview, then confirm twice;
 *   manual  CR's receipt details, typed from the receipt of the filing made on
 *           CR's portal, with the receipt attached — NAR1's manual path.
 *
 * A write-back problem after CR has the form is a WARNING on a filed case,
 * never a failure: CR holds the form whatever happened after.
 *
 * Controls a role may not use are not drawn (Levi 2026-09-04); a sentence says
 * which grant they need instead.
 */
export default function StageSubmission({ data, reload, can, goTo }) {
  const manual = isManual(data)
  const filed = isFiled(data)
  const [armed, setArmed] = useState(false)
  const [confirmingFile, setConfirmingFile] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [receipt, setReceipt] = useState({ caseNo: '', transactionDate: '', transactionTime: '', refNo: '' })
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  // The staff copy of the form CR validated — what is about to be filed.
  const showPreview = !manual && !filed
  const preview = usePdfBlob(
    showPreview ? `/officer-changes/${data.id}/preview?audience=staff` : null,
    `${data.updated_at}|${data.filing?.stage}`)

  function writeBackWarning(res) {
    const errors = [...(res?.write_back?.errors || []),
      ...(res?.documents_filed || []).filter(d => d.error).map(d => `${d.file_name || 'A document'}: ${d.error}`)]
    setWarning(errors.length ? errors : null)
  }

  async function fileWithCr() {
    setConfirmingFile(false); setError(null); setBusy(true)
    try {
      const res = await officerChangeApi.submit(data.id)
      writeBackWarning(res)
      await reload(res)
    } catch (e) { setError(errorOf(e)) } finally { setBusy(false); setArmed(false) }
  }

  async function record() {
    setConfirming(false); setError(null); setBusy(true)
    try {
      if (file) await officerChangeApi.uploadReceipt(data.id, file)
      const res = await officerChangeApi.recordFiling(data.id, {
        caseNo: receipt.caseNo, transactionDate: receipt.transactionDate,
        ...(receipt.transactionTime ? { transactionTime: receipt.transactionTime } : {}),
        ...(receipt.refNo ? { refNo: receipt.refNo } : {}),
      })
      writeBackWarning(res)
      await reload(res)
    } catch (e) { setError(errorOf(e)) } finally { setBusy(false) }
  }

  const receiptReady = receipt.caseNo.trim() && receipt.transactionDate
    && (file || data.manual_receipt_document_id)

  return (
    <>
      <ProfileChangesList changes={data.profile_changes} documents={data.documents} done={false} />

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">{manual ? 'Record the filing made on CR\'s portal' : 'File with the Companies Registry'}</div>
        {filed ? (
          <div className="oc-send-row">
            <span className="badge b-live">Filed</span>
            <button className="btn btn-primary" onClick={() => goTo(5)}>Continue to Confirmation →</button>
          </div>
        ) : manual ? (
          can.tpsiSubmit ? (
            <>
              <div className="form-grid" style={{ marginTop: 10 }}>
                <div className="f-group">
                  <label className="f-label" htmlFor="oc-r-case">CR case number <span className="f-req">*</span></label>
                  <input id="oc-r-case" className="f-input" value={receipt.caseNo}
                         onChange={e => setReceipt(r => ({ ...r, caseNo: e.target.value }))} />
                </div>
                <div className="f-group">
                  <label className="f-label" htmlFor="oc-r-date">Transaction date <span className="f-req">*</span></label>
                  <input id="oc-r-date" type="date" className="f-input" value={receipt.transactionDate}
                         onChange={e => setReceipt(r => ({ ...r, transactionDate: e.target.value }))} />
                </div>
                <div className="f-group">
                  <label className="f-label" htmlFor="oc-r-time">Transaction time</label>
                  <input id="oc-r-time" className="f-input" placeholder="HH:MM" value={receipt.transactionTime}
                         onChange={e => setReceipt(r => ({ ...r, transactionTime: e.target.value }))} />
                </div>
                <div className="f-group">
                  <label className="f-label" htmlFor="oc-r-ref">CR document reference</label>
                  <input id="oc-r-ref" className="f-input" value={receipt.refNo}
                         onChange={e => setReceipt(r => ({ ...r, refNo: e.target.value }))} />
                </div>
                <div className="f-group">
                  <label className="f-label" htmlFor="oc-r-file">CR receipt <span className="f-req">*</span></label>
                  <input id="oc-r-file" type="file" accept="application/pdf,image/png,image/jpeg"
                         onChange={e => setFile(e.target.files?.[0] || null)} />
                  {data.manual_receipt_document_id && !file && <div className="f-hint">A receipt is already attached.</div>}
                </div>
              </div>
              <div className="oc-send-row">
                <button className="btn btn-primary" disabled={!receiptReady || busy}
                        onClick={() => setConfirming(true)}>{busy ? 'Recording…' : 'Record filing'}</button>
              </div>
            </>
          ) : (
            <p className="f-hint" style={{ marginTop: 8 }}>
              Recording the filing needs Companies Registry filing (File with CR).
            </p>
          )
        ) : (
          <>
            <p className="f-hint" style={{ margin: '6px 0 10px' }}>
              This is the form the Companies Registry validated and that has been signed. Check it before filing.
            </p>
            <PdfFrame url={preview.url} error={preview.error}
                      fileName={`${data.case_type}-${data.case_no}-signed.pdf`}
                      pills={[{ label: 'As it will be filed — all pages', tone: '' }]}
                      label="signed form" />
            {can.tpsiSubmit ? (
              <div className="oc-send-row">
                <label className="check-row">
                  <input type="checkbox" checked={armed} onChange={e => setArmed(e.target.checked)} />
                  I have checked this form. Filing it with the Companies Registry cannot be undone.
                </label>
                <button className="btn btn-primary" disabled={!armed || busy}
                        onClick={() => setConfirmingFile(true)}>
                  {busy ? 'Filing…' : `File ${data.case_type} with CR`}
                </button>
              </div>
            ) : (
              <p className="f-hint" style={{ marginTop: 8 }}>
                Filing needs Companies Registry filing (File with CR).
              </p>
            )}
          </>
        )}
        {warning && (
          <div className="alert al-warn" role="alert" style={{ marginTop: 12 }}>
            <div className="al-body"><b>Filed with CR — but some follow-up did not complete.</b>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{warning.map(w => <li key={w}>{w}</li>)}</ul>
            </div>
          </div>
        )}
        {error && (
          <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
            <div className="al-body"><b>{error.message}</b></div>
          </div>
        )}
      </div>

      {confirmingFile && (
        <div className="modal-confirm" role="alertdialog" aria-label={`File ${data.case_type} with CR`}>
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">File {data.case_type} {data.case_no} with the Companies Registry?</div>
            <div className="modal-confirm-text">
              The signed form goes to CR now and cannot be withdrawn. The officers&apos; profiles are
              updated and the supporting documents saved to each profile straight after.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setConfirmingFile(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={fileWithCr}>File with CR</button>
            </div>
          </div>
        </div>
      )}

      {confirming && (
        <div className="modal-confirm" role="alertdialog" aria-label="Record filing">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Record {data.case_type} as filed?</div>
            <div className="modal-confirm-text">
              CR case {receipt.caseNo} on {receipt.transactionDate}. The profiles are updated and the
              supporting documents saved to each officer's profile. This cannot be undone here.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setConfirming(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={record}>Record filing</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
