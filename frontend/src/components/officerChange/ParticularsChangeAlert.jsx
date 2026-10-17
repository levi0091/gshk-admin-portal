import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api.js'
import { errorOf } from './workflow.js'
import { useStartOfficerChange } from './ReportChangeMenu.jsx'
import './entryPoints.css'

const CAPACITY = { director: 'Director', company_secretary: 'Company Secretary' }

/**
 * "Changed here — the Companies Registry has not been told" (answers 14, 16).
 *
 * Shown on a person's profile, and on a body corporate's company profile, when
 * a particular CR holds for one of their appointments differs from what CR was
 * last told. One row per company they serve, each with the changed items, and
 * the way to file it: Start ND2B, or Open the ND2B already carrying them.
 *
 * DISMISS IS FOR DATA, NOT FOR CHANGES. Most profiles were loaded from the
 * previous system and then corrected by hand, and those corrections are not
 * events CR needs to hear about. Dismissing records the profile as what CR is
 * taken to hold, for every company listed; the trail keeps what was dismissed,
 * and there is nothing on the screen that brings it back — which the
 * confirmation says before it happens.
 *
 * `caps` decides what is DRAWN, never what is disabled: view, start (open a
 * case), open (read one) and dismiss, each from `screenCapabilities`.
 */
export default function ParticularsChangeAlert({ kind, id, caps, refreshKey }) {
  const base = kind === 'company' ? `/companies/${id}` : `/persons/${id}`
  const [rows, setRows] = useState([])
  const [confirming, setConfirming] = useState(false)
  // One company at a time (Jacqueline BQ2): "some clients may have different
  // passport information or address information for each of their companies".
  const [confirmingOne, setConfirmingOne] = useState(null)
  const [dismissing, setDismissing] = useState(false)
  const [error, setError] = useState(null)
  const { start, busy, error: startError } = useStartOfficerChange(null)

  const load = useCallback(() => {
    if (!caps?.view) return
    api.get(`${base}/particulars-changes`)
      .then(d => setRows(Array.isArray(d?.changes) ? d.changes : []))
      .catch(() => setRows([]))
  }, [base, caps?.view])

  // `refreshKey` is the profile's own `updated_at`: an edit saved on the page
  // can raise a change (or, edited back, remove one), and the alert must say
  // so without a reload — that is the moment the operator is looking.
  useEffect(() => { load() }, [load, refreshKey])

  if (!caps?.view || rows.length === 0) return null

  async function dismiss() {
    setDismissing(true); setError(null)
    try {
      await api.post(`${base}/particulars-changes/dismiss`, {})
      setConfirming(false)
      setRows([])
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setDismissing(false)
    }
  }

  async function dismissOne(row) {
    setDismissing(true); setError(null)
    try {
      await api.post(`${base}/particulars-changes/dismiss`, { entity_id: row.entity_id })
      setConfirmingOne(null)
      setRows(rs => rs.filter(r => r.entity_id !== row.entity_id))
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setDismissing(false)
    }
  }

  function startNd2b(row) {
    const entry = row.officer_id
      ? { kind: 'change', officer_id: row.officer_id }
      : { kind: 'change', secretary_id: row.secretary_id }
    start('Nd2b', { company: row.entity_id, entry })
  }

  const companies = rows.length
  return (
    <section className="ep-alert" aria-label="Particulars changed since CR was last told">
      <div className="ep-alert-hd">
        <div>
          <div className="ep-alert-title">
            Changed here, not yet filed with the Companies Registry
          </div>
          <div className="ep-alert-sub">
            {companies === 1 ? 'One appointment is' : `${companies} appointments are`} affected.
            Each needs an ND2B within 15 days of the change, unless the edit only
            corrected data loaded from the previous system.
          </div>
        </div>
        {caps.dismiss && (
          <button type="button" className="btn btn-outline btn-sm" onClick={() => setConfirming(true)}>
            Dismiss
          </button>
        )}
      </div>

      <ul className="ep-alert-rows">
        {rows.map(row => (
          <li key={`${row.entity_id}-${row.capacity}`} className="ep-alert-row">
            <div className="ep-alert-who">
              <span className="ep-alert-company">{row.company_name || 'A company'}</span>
              <span className="ep-alert-cap">{CAPACITY[row.capacity] || row.capacity}</span>
            </div>
            <dl className="ep-items">
              {(row.items || []).map(item => (
                <div key={item.key} className="ep-item">
                  <dt>{item.label}</dt>
                  <dd>
                    <span className="ep-old">{item.old_text || '—'}</span>
                    <span className="ep-to" aria-label="changed to">→</span>
                    <span className="ep-new">{item.new_text || '—'}</span>
                  </dd>
                </div>
              ))}
            </dl>
            <div className="ep-alert-act">
              {caps.dismiss && !row.open_case && (
                <button type="button" className="btn btn-ghost btn-sm"
                        onClick={() => setConfirmingOne(row)}>Not for this company</button>
              )}
              {row.open_case ? (
                caps.open && (
                  <Link className="btn btn-outline btn-sm" to={`/officer-changes/${row.open_case.id}`}>
                    Open {row.open_case.case_no || 'ND2B'}
                  </Link>
                )
              ) : caps.start && (
                <button type="button" className="btn btn-action btn-sm" disabled={busy}
                        onClick={() => startNd2b(row)}>
                  {busy ? 'Opening…' : 'Start ND2B'}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {(startError || error) && <div className="ep-error" role="alert">{startError || error}</div>}

      {confirmingOne && (
        <div className="overlay" onClick={e => { if (e.target === e.currentTarget) setConfirmingOne(null) }}>
          <div className="modal modal-sm" role="alertdialog" aria-label="Dismiss for this company">
            <div className="modal-hdr">
              <div className="modal-title">Not for {confirmingOne.company_name || 'this company'}?</div>
              <button className="modal-close" onClick={() => setConfirmingOne(null)} aria-label="Close">×</button>
            </div>
            <div className="modal-body confirm-body">
              <p>
                The Companies Registry is taken to hold the particulars on this profile for{' '}
                {confirmingOne.company_name || 'this company'} only. No ND2B is asked for there;
                the other companies listed keep their alert.
              </p>
              <p>Use it when this company keeps different details, or the edit only
                corrected loaded data. The audit trail keeps what was dismissed.</p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setConfirmingOne(null)} disabled={dismissing}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={() => dismissOne(confirmingOne)} disabled={dismissing}>
                {dismissing ? 'Dismissing…' : 'Dismiss for this company'}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirming && (
        <div className="overlay" onClick={e => { if (e.target === e.currentTarget) setConfirming(false) }}>
          <div className="modal modal-sm" role="alertdialog" aria-label="Dismiss these changes">
            <div className="modal-hdr">
              <div className="modal-title">Dismiss these changes?</div>
              <button className="modal-close" onClick={() => setConfirming(false)} aria-label="Close">×</button>
            </div>
            <div className="modal-body confirm-body">
              <p>
                Use this only when the edits corrected data loaded from the previous
                system — not when something actually changed.
              </p>
              <p>
                The particulars on this profile become what the Companies Registry is
                taken to hold, for {companies === 1 ? 'this appointment' : `all ${companies} appointments`}.
                No ND2B will be asked for them, and this cannot be undone from the
                screen. The audit trail keeps what was dismissed.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setConfirming(false)} disabled={dismissing}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={dismiss} disabled={dismissing}>
                {dismissing ? 'Dismissing…' : 'Dismiss'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
