import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Link } from 'react-router-dom'
import CessationDrawer from './CessationDrawer.jsx'
import AppointmentDrawer from './AppointmentDrawer.jsx'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'

/**
 * How a new director's consent to act is given (Jacqueline A5, Levi
 * 2026-10-05): GSHK PIN-signs it from the e-Registry account stored on their
 * profile, or the whole form is filed on CR's portal (the manual route). CR's
 * consent signature IS the consent, so there is no third, in-portal way.
 */
function consentLine(entry) {
  if (entry.kind !== 'appointment' || entry.capacity !== 'director' || !entry.consent_mode) return null
  return entry.consent_mode === 'esign'
    ? 'Consent: e-Sign — PIN-signed from the e-Registry account on file'
    : 'Consent: manual route — given on the CR portal'
}

function OfficerRow({ entry, editable, onEdit, onRemove }) {
  const missing = entry.party?.missing || []
  const consent = consentLine(entry)
  return (
    <div className="oc-officer" data-testid={`entry-${entry.id}`}>
      <div className="oc-officer-name">{entry.party?.name}</div>
      <div className="oc-officer-meta">{entry.summary}</div>
      {consent && <div className="oc-officer-meta">{consent}</div>}
      {editable && (
        <div className="oc-officer-acts">
          <button className="btn btn-ghost btn-sm" onClick={() => onEdit(entry)}>Edit</button>
          <button className="btn btn-ghost btn-sm" onClick={() => onRemove(entry)}>Remove</button>
        </div>
      )}
      {missing.length > 0 && (
        <div className="oc-officer-warn">
          Missing on the profile: {missing.join(', ')}.{' '}
          {entry.party?.profile_path && <Link to={entry.party.profile_path}>Open profile</Link>}
        </div>
      )}
    </div>
  )
}

/**
 * The ND2A change list as a board: who leaves, who joins, and — underneath, as
 * the ledger total — what the board looks like once both have happened. That
 * last line is the one the company rules are about, so it sits where the eye
 * lands after reading the two lanes.
 */
export default function ChangesCard({ data, reload, can }) {
  const entries = data.entries || []
  const leaving = entries.filter(e => e.kind === 'cessation')
  const joining = entries.filter(e => e.kind === 'appointment')
  const editable = data.editable && can.write
  // Cease on an officer's row of the company profile lands here with
  // `?cease=<officerRef>`, and the drawer opens on that officer.
  const [params, setParams] = useSearchParams()
  const [drawer, setDrawer] = useState(() => (editable && params.get('cease')
    ? { kind: 'cessation', preselect: params.get('cease') } : null))
  const [removing, setRemoving] = useState(null)
  const [error, setError] = useState(null)

  async function remove() {
    setError(null)
    try {
      await reload(await officerChangeApi.removeEntry(data.id, removing.id))
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setRemoving(null)
    }
  }

  function closeDrawer() {
    setDrawer(null)
    // Once handled, the request is spent: a reload must not reopen it.
    if (params.has('cease')) {
      const rest = new URLSearchParams(params)
      rest.delete('cease')
      setParams(rest, { replace: true })
    }
  }

  function saved(next) { closeDrawer(); reload(next) }

  return (
    <div className="card">
      <div className="card-hdr">
        <div>
          <div className="card-title">Changes on this form</div>
          <div className="card-sub">
            {data.editable ? 'Add every officer leaving and joining. One ND2A reports them all.'
              : 'Sent to the client — restart verification to change the list.'}
          </div>
        </div>
        {editable && (
          <div className="row gap-8">
            <button className="btn btn-outline" onClick={() => setDrawer({ kind: 'cessation' })}>
              + Add cessation
            </button>
            <button className="btn btn-primary" onClick={() => setDrawer({ kind: 'appointment' })}>
              + Add appointment
            </button>
          </div>
        )}
      </div>

      <div className="oc-board">
        <section className="oc-lane" aria-label="Leaving">
          <div className="oc-lane-hd">
            <span className="oc-lane-mark" aria-hidden="true">−</span> Leaving
            <span className="oc-lane-count">{leaving.length}</span>
          </div>
          {leaving.length === 0 && <div className="oc-lane-empty">Nobody ceases on this form.</div>}
          {leaving.map(e => (
            <OfficerRow key={e.id} entry={e} editable={editable}
                        onEdit={x => setDrawer({ kind: 'cessation', entry: x })}
                        onRemove={setRemoving} />
          ))}
        </section>
        <div className="oc-arrow" aria-hidden="true">→</div>
        <section className="oc-lane oc-lane-join" aria-label="Joining">
          <div className="oc-lane-hd">
            <span className="oc-lane-mark" aria-hidden="true">+</span> Joining
            <span className="oc-lane-count">{joining.length}</span>
          </div>
          {joining.length === 0 && <div className="oc-lane-empty">Nobody is appointed on this form.</div>}
          {joining.map(e => (
            <OfficerRow key={e.id} entry={e} editable={editable}
                        onEdit={x => setDrawer({ kind: 'appointment', entry: x })}
                        onRemove={setRemoving} />
          ))}
        </section>
      </div>

      {data.rules?.summary && (
        <div className="oc-after"><b>Afterwards</b><span>{data.rules.summary.replace(/^After these changes /, '')}</span></div>
      )}
      {error && <div className="alert al-danger" role="alert" style={{ marginTop: 12 }}>
        <div className="al-body">{error}</div></div>}

      {drawer?.kind === 'cessation' && (
        <CessationDrawer data={data} entry={drawer.entry} preselect={drawer.preselect}
                         onClose={closeDrawer} onSaved={saved} />
      )}
      {drawer?.kind === 'appointment' && (
        <AppointmentDrawer data={data} entry={drawer.entry} onClose={() => setDrawer(null)} onSaved={saved} />
      )}
      {removing && (
        <div className="modal-confirm" role="alertdialog" aria-label="Remove from the form">
          <div className="modal-confirm-card">
            <div className="modal-confirm-title">Remove {removing.party?.name} from this form?</div>
            <div className="modal-confirm-text">
              The {removing.kind === 'cessation' ? 'cessation' : 'appointment'} is taken off the
              ND2A and any supporting documents uploaded for it are deleted. Their profile is not
              changed.
            </div>
            <div className="modal-confirm-actions">
              <button className="btn btn-outline" onClick={() => setRemoving(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={remove}>Remove</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
