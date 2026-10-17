import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/api.js'
import { formatDateTime } from '../../lib/format.js'
import { errorOf } from './workflow.js'
import './entryPoints.css'

/**
 * The person's own e-Registry account (answers 1, 2, 8; spec B-9).
 *
 * GSHK sets up and holds a new director's e-Registry account, and the portal
 * uses it for ONE thing: applying that person's own consent signature on an
 * ND2A filed through the portal. Without it, their appointment can only go by
 * the wet-ink route, which is why the case screen names whoever is missing one.
 *
 * THE PASSWORD IS WRITE-ONLY. Unlike the staff signing credential on CR
 * Credentials, nothing of it comes back — not a masked tail, not a length —
 * only whether one is stored. A blank password field on Save keeps the stored
 * one, so correcting the user ID never forces re-typing a secret.
 *
 * `canEdit` is `persons:write`; without it the card is read-only and draws no
 * Edit or Remove at all.
 */
export default function EServiceCredentialCard({ personId, canEdit }) {
  const [meta, setMeta] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ user: '', name: '', password: '', idType: '', idNumber: '' })
  const [saving, setSaving] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(null)

  const load = useCallback(() => {
    api.get(`/persons/${personId}/eservice-credential`)
      .then(d => setMeta(d && typeof d.configured === 'boolean' ? d : { configured: false }))
      .catch(() => setMeta({ configured: false, unavailable: true }))
  }, [personId])

  useEffect(() => { load() }, [load])

  function edit() {
    setDraft({ user: meta?.eservice_user_id || '', name: meta?.eservice_person_name || '',
               password: '', idType: meta?.registered_id_type || '',
               idNumber: meta?.registered_id_number || '' })
    setError(null); setSaved(null); setEditing(true)
  }

  async function save() {
    setSaving(true); setError(null)
    try {
      const body = { eservice_user_id: draft.user.trim(), eservice_person_name: draft.name.trim() }
      if (draft.password) body.password = draft.password
      // Sent only when there is something to say: a document now, or one to clear.
      if (draft.idType || meta?.registered_id_type) {
        body.registered_id_type = draft.idType || null
        body.registered_id_number = draft.idType ? draft.idNumber.trim() : null
      }
      const next = await api.put(`/persons/${personId}/eservice-credential`, body)
      setMeta(next)
      setEditing(false)
      setSaved(draft.password ? 'Saved, with the new password.' : 'Saved.')
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setSaving(false)
      setDraft(d => ({ ...d, password: '' }))
    }
  }

  async function remove() {
    setSaving(true); setError(null)
    try {
      const next = await api.del(`/persons/${personId}/eservice-credential`)
      setMeta(next && typeof next.configured === 'boolean' ? next : { configured: false })
      setConfirmRemove(false)
      setSaved('Removed.')
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setSaving(false)
    }
  }

  const configured = Boolean(meta?.configured)
  const needsPassword = !meta?.has_password
  const ready = draft.user.trim() && draft.name.trim() && (!needsPassword || draft.password)

  return (
    <div className="card mb-16">
      <div className="card-hdr">
        <div>
          <div className="card-title">e-Registry account</div>
          <div className="card-sub">
            The e-Registry username and password entered here are what G-FlowDesk uses to
            PIN-sign this person&apos;s consent to act on an ND2A. NAR1 is PIN-signed the same
            way, with GSHK&apos;s own account. Without one here, their appointment is filed on
            the CR portal instead.
          </div>
        </div>
        {canEdit && !editing && meta && !meta.unavailable && (
          <div className="tile-actions">
            {configured && (
              <button className="btn-edit" onClick={() => setConfirmRemove(true)}>Remove</button>
            )}
            <button className="btn-edit" onClick={edit}>{configured ? 'Edit' : 'Add account'}</button>
          </div>
        )}
      </div>

      {meta === null ? (
        <div className="empty-state" style={{ padding: '12px 0' }}>Loading…</div>
      ) : editing ? (
        <div className="ep-cred-form">
          <div className="f-group">
            <label className="f-label" htmlFor="es-user">e-Registry user ID <span className="f-req">*</span></label>
            <input id="es-user" className="f-input" autoComplete="off" value={draft.user}
                   onChange={e => setDraft(d => ({ ...d, user: e.target.value }))} />
          </div>
          <div className="f-group">
            <label className="f-label" htmlFor="es-name">Name on the account <span className="f-req">*</span></label>
            <input id="es-name" className="f-input" autoComplete="off" value={draft.name}
                   onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} />
            <span className="f-hint">As the Companies Registry holds it — CR checks it at signing.</span>
          </div>
          <div className="f-group">
            <label className="f-label" htmlFor="es-pass">
              Password {needsPassword && <span className="f-req">*</span>}
            </label>
            <input id="es-pass" className="f-input" type="password" autoComplete="new-password"
                   value={draft.password}
                   placeholder={needsPassword ? '' : 'Leave blank to keep the stored password'}
                   onChange={e => setDraft(d => ({ ...d, password: e.target.value }))} />
            <span className="f-hint">Stored encrypted. It is never shown again, here or anywhere.</span>
          </div>
          {/* Jacqueline, note 1 (2026-10-01): e-Reg keeps the document an
              account was opened with and CR's register does not update it, so
              a renewed passport makes CR refuse the consent later. Recorded
              here so the portal can say so before signing. */}
          <div className="f-group">
            <label className="f-label" htmlFor="es-idtype">Opened with</label>
            <select id="es-idtype" className="f-select" value={draft.idType}
                    onChange={e => setDraft(d => ({ ...d, idType: e.target.value }))}>
              <option value="">Not recorded</option>
              <option value="hkid">HKID</option>
              <option value="passport">Passport</option>
            </select>
          </div>
          {draft.idType && (
            <div className="f-group">
              <label className="f-label" htmlFor="es-idnum">Document number</label>
              <input id="es-idnum" className="f-input" autoComplete="off" value={draft.idNumber}
                     onChange={e => setDraft(d => ({ ...d, idNumber: e.target.value }))} />
              <span className="f-hint">The identity document used to register this e-Registry account.</span>
            </div>
          )}
          <div className="ep-cred-actions">
            <button className="btn btn-outline" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
            <button className="btn btn-action" onClick={save} disabled={!ready || saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : meta.unavailable ? (
        <div className="empty-state" style={{ padding: '12px 0' }}>
          The account could not be read just now. Reload the page to try again.
        </div>
      ) : configured ? (
        <div className="kv-list">
          <div className="kv-row"><span className="kv-key">User ID</span>
            <span className="kv-val">{meta.eservice_user_id}</span></div>
          <div className="kv-row"><span className="kv-key">Name on the account</span>
            <span className="kv-val">{meta.eservice_person_name || '—'}</span></div>
          <div className="kv-row"><span className="kv-key">Password</span>
            <span className="kv-val">
              <span className={`ep-state ${meta.has_password ? 'on' : 'off'}`}>
                {meta.has_password ? 'Password stored' : 'No password stored'}
              </span>
            </span></div>
          <div className="kv-row"><span className="kv-key">Opened with</span>
            <span className="kv-val">
              {meta.registered_id_type
                ? `${meta.registered_id_type === 'hkid' ? 'HKID' : 'Passport'} ${meta.registered_id_number || ''}`
                : <span className="td-muted">Not recorded</span>}
            </span></div>
          {meta.updated_at && (
            <div className="kv-row"><span className="kv-key">Last changed</span>
              <span className="kv-val">{formatDateTime(meta.updated_at)}</span></div>
          )}
          {meta.registered_id_mismatch && (
            <div className="alert al-warn" role="alert" style={{ marginTop: 10 }}>
              <div className="al-body">{meta.registered_id_mismatch}</div>
            </div>
          )}
        </div>
      ) : (
        <div className="empty-state" style={{ padding: '12px 0' }}>
          No e-Registry account stored{canEdit ? '.' : ' — ask someone who may edit this person to add one.'}
        </div>
      )}

      {saved && !editing && <div className="ep-saved" role="status">{saved}</div>}
      {error && <div className="ep-error" role="alert">{error}</div>}

      {confirmRemove && (
        <div className="overlay" onClick={e => { if (e.target === e.currentTarget) setConfirmRemove(false) }}>
          <div className="modal modal-sm" role="alertdialog" aria-label="Remove the e-Registry account">
            <div className="modal-hdr">
              <div className="modal-title">Remove the e-Registry account?</div>
              <button className="modal-close" onClick={() => setConfirmRemove(false)} aria-label="Close">×</button>
            </div>
            <div className="modal-body confirm-body">
              The user ID and the stored password for {meta?.eservice_user_id || 'this account'} are
              deleted. Until another is added, an ND2A appointing this person can only be filed by wet ink.
            </div>
            <div className="modal-footer">
              <button className="btn btn-outline" onClick={() => setConfirmRemove(false)} disabled={saving}>Cancel</button>
              <button className="btn btn-danger" onClick={remove} disabled={saving}>
                {saving ? 'Removing…' : 'Remove'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
