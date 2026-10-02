import { useState } from 'react'
import { Link } from 'react-router-dom'
import SupportingDocuments from './SupportingDocuments.jsx'
import CrRefusal from './CrRefusal.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/**
 * Stage 2 (spec §5): per joiner and leaver, the KYC tick and the supporting
 * documents; the signing capacity; and the route. e-Sign validates with CR
 * (free, no PIN); the manual route is "Mark as checked" and calls nobody.
 * e-Sign is offered only when every new director's consent can be signed from
 * a stored e-Registry account (answers 2 and 8) — otherwise the reasons say who.
 */
export default function StageDataVerification({ data, reload, can, goTo }) {
  const route = data.route || {}
  const [method, setMethod] = useState(data.signing_method || route.default || 'manual')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const approved = data.client_approved === true
  const validated = data.filing?.stage === 'validated' || data.filing?.stage === 'signed'
  const checked = Boolean(data.data_checked_at)
  const signatory = data.signatory || {}

  async function run(promise) {
    setError(null); setBusy(true)
    try { await reload(await promise) } catch (e) { setError(errorOf(e)) } finally { setBusy(false) }
  }

  async function choose(next) {
    setMethod(next)
    if (next !== data.signing_method) await run(officerChangeApi.patch(data.id, { signing_method: next }))
  }

  if (!approved) {
    return <div className="card"><div className="card-note">This stage opens once the client has confirmed the form.</div></div>
  }

  return (
    <>
      <div className="card">
        <div className="card-hdr"><div>
          <div className="card-title">Officers on this form</div>
          <div className="card-sub">Clear KYC for each new officer and attach the supporting documents.
            They are saved to each officer's profile when the form is filed.</div>
        </div></div>
        {(data.entries || []).map(entry => (
          <div key={entry.id} className="oc-pc" data-testid={`dv-${entry.id}`}>
            <div className="oc-pc-hd">
              <span className="oc-pc-name">{entry.party?.name}</span>
              <span className="td-muted">{entry.summary}</span>
            </div>
            {entry.kind === 'appointment' && (can.write ? (
              <label className="check-row">
                <input type="checkbox" checked={Boolean(entry.kyc_cleared)} disabled={busy}
                       onChange={e => run(officerChangeApi.setKyc(data.id, entry.id, e.target.checked))} />
                KYC cleared
              </label>
            ) : (
              // Without officer_changes (edit) the tick is a fact to read, not a control.
              <div className="f-hint">{entry.kyc_cleared ? 'KYC cleared.' : 'KYC not cleared yet.'}</div>
            ))}
            {entry.eservice && (
              <div className="f-hint">
                {entry.eservice.configured && entry.eservice.has_password
                  ? <>e-Registry account {entry.eservice.eservice_user_id} stored — their consent can be e-signed.</>
                  : <>No complete e-Registry account stored, so this ND2A can only be filed on the manual route.{' '}
                    {entry.party?.profile_path && <Link to={entry.party.profile_path}>Add it on the profile</Link>}</>}
              </div>
            )}
            {entry.kind !== 'change' && (
              <SupportingDocuments data={data} entry={entry} reload={reload} can={can} />
            )}
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">Signing</div>
        <div className="f-group" style={{ marginTop: 10, maxWidth: 520 }}>
          <label className="f-label" htmlFor="oc-capacity">
            {signatory.name ? `${signatory.name} signs as` : 'Signing capacity'}
          </label>
          {can.write ? (
            <select id="oc-capacity" className="f-select" disabled={busy}
                    value={signatory.selected_capacity || signatory.default_capacity || ''}
                    onChange={e => run(officerChangeApi.patch(data.id, { signatory_capacity: e.target.value }))}>
              {(signatory.capacities || []).map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          ) : (
            <div className="f-static" id="oc-capacity">
              {signatory.selected_capacity || signatory.default_capacity || 'Not chosen yet'}
            </div>
          )}
        </div>

        {can.write ? (
          <fieldset className="meth-group" style={{ border: 0, padding: 0, marginTop: 12 }}>
            <legend className="f-label">Route</legend>
            <label className="meth-opt">
              {/* Disabled for a DATA reason only — a new director with no stored
                  e-Registry account — and the reasons print just below. */}
              <input type="radio" name="oc-route" className="meth-radio" checked={method === 'esign'}
                     disabled={!route.esign_available}
                     onChange={() => choose('esign')} />
              <span className="meth-body"><span className="meth-lbl">e-Sign via CR</span>
                <span className="meth-sub">Validated with CR here, signed with stored e-Registry accounts, filed from the portal.</span>
              </span>
            </label>
            <label className="meth-opt">
              <input type="radio" name="oc-route" className="meth-radio" checked={method === 'manual'}
                     onChange={() => choose('manual')} />
              <span className="meth-body"><span className="meth-lbl">Manual (CR portal)</span>
                <span className="meth-sub">Prepared, signed and filed on CR's portal; the receipt is recorded here.</span>
              </span>
            </label>
          </fieldset>
        ) : (
          <div className="f-group" style={{ marginTop: 12 }}>
            <span className="f-label">Route</span>
            <div className="f-static">
              {data.signing_method === 'esign' ? 'e-Sign via CR'
                : data.signing_method === 'manual' ? 'Manual (CR portal)' : 'Not chosen yet'}
            </div>
          </div>
        )}
        {!route.esign_available && (route.reasons || []).length > 0 && (
          <div className="card-note" role="status">
            <b>e-Sign is not available:</b>
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {route.reasons.map(r => <li key={r}>{r}</li>)}
            </ul>
          </div>
        )}

        <div className="oc-send-row">
          {method === 'esign' && !validated && can.tpsiWrite && (
            <button className="btn btn-primary" disabled={busy}
                    onClick={() => run(officerChangeApi.validate(data.id))}>
              {busy ? 'Validating…' : 'Validate with CR Portal'}
            </button>
          )}
          {method === 'manual' && !checked && can.write && (
            <button className="btn btn-primary" disabled={busy}
                    onClick={() => run(officerChangeApi.markChecked(data.id))}>Mark as checked</button>
          )}
          {((method === 'esign' && validated) || (method === 'manual' && checked)) && (
            <>
              <span className="badge b-live">{method === 'esign' ? 'Validated by CR' : 'Checked'}</span>
              <button className="btn btn-primary" onClick={() => goTo(3)}>Continue to Signing →</button>
            </>
          )}
          {method === 'esign' && !validated && !can.tpsiWrite && (
            <span className="f-hint">Validating with CR needs Companies Registry filing (Edit).</span>
          )}
          {method === 'manual' && !checked && !can.write && (
            <span className="f-hint">Marking the form as checked needs Officer changes (Edit).</span>
          )}
        </div>
        <CrRefusal error={error} />
      </div>
    </>
  )
}
