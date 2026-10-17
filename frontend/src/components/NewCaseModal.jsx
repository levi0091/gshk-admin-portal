import { useState, useEffect, useRef } from 'react'
import { api } from '../lib/api.js'
import { useAuth } from '../context/AuthContext.jsx'
import { officerChangeApi } from './officerChange/api.js'
import './officerChange/entryPoints.css'

/**
 * Open a case — from the Post-incorporation dashboard or a company profile.
 *
 * The dashboard lists CASES, so its primary action is opening one. It used to
 * be "+ Add Company", which is a different job on a different screen (the
 * Company Registry) and left no way at all to start the work the dashboard is
 * about.
 *
 * `entity` fixes the company (the profile page knows it already); without it
 * the operator searches for one. A company may hold more than one open case —
 * two outstanding returns is a normal state — so this never refuses on the
 * grounds that a case already exists. The backend decides that.
 *
 * THREE FORMS, EACH ON ITS OWN PERMISSION (migration 050). An annual return is
 * `nar1:write`; an ND2A or ND2B is `officer_changes:write`. A form the role may
 * not open is not drawn at all — the portal's rule for every permission-gated
 * control — so a role holding one of the two sees a picker of one, worded as a
 * fact rather than as a choice. `onCreated` receives the case with its
 * `form_code`, and the caller routes it (`casePath`).
 */
export const FORMS = [
  { code: 'Nar1', label: 'Annual Return (NAR1)', module: 'nar1',
    hint: 'The annual return is filed for this company.' },
  { code: 'Nd2a', label: 'Appointment / cessation of officers (ND2A)', module: 'officer_changes',
    hint: 'A director or secretary joins or leaves. Add who on the next screen.' },
  { code: 'Nd2b', label: "Change of an officer's particulars (ND2B)", module: 'officer_changes',
    hint: 'Particulars already edited on a profile. The next screen lists what changed.' },
]

export default function NewCaseModal({ entity, onClose, onCreated, initialForm }) {
  const { hasPermission } = useAuth()
  const forms = FORMS.filter(f => hasPermission?.(f.module, 'write'))
  const [form, setForm] = useState(
    forms.find(f => f.code === initialForm)?.code || forms[0]?.code || null)
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [picked, setPicked] = useState(entity || null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const searching = useRef(false)
  const chosen = forms.find(f => f.code === form)

  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    if (entity || query.length < 2) { setResults([]); return undefined }
    let cancelled = false
    searching.current = true
    api.get(`/companies?search=${encodeURIComponent(query)}&page_size=8`)
      .then(d => { if (!cancelled) setResults(d?.companies || []) })
      .catch(() => { if (!cancelled) setResults([]) })
      .finally(() => { searching.current = false })
    return () => { cancelled = true }
  }, [query, entity])

  async function create() {
    if (!picked || !chosen) return
    setError(null); setBusy(true)
    try {
      if (chosen.code === 'Nar1') {
        const created = await api.post('/cases', { entity_id: picked.id, form_code: 'Nar1' })
        onCreated(created)
      } else {
        const res = await officerChangeApi.create(picked.id, chosen.code)
        onCreated({ ...res.case, form_code: chosen.code })
      }
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-hdr">
          <div className="modal-title">Open a case</div>
          <div className="modal-close" onClick={onClose} role="button" aria-label="Close">×</div>
        </div>

        <div className="modal-body">
          {error && (
            <div className="alert al-danger" role="alert" style={{ marginBottom: 14 }}>
              <span className="al-icon">⚠</span>
              <div className="al-body">
                {error.message}
                {Array.isArray(error.problems) && (
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                    {error.problems.map((p, i) => <li key={i}>{String(p)}</li>)}
                  </ul>
                )}
              </div>
            </div>
          )}

          {entity ? (
            <div className="f-group">
              <label className="f-label">Company</label>
              <div className="f-input" style={{ display: 'flex', alignItems: 'center' }}>
                {entity.company_name}
              </div>
            </div>
          ) : (
            <>
              <div className="f-group">
                <label className="f-label" htmlFor="nc-search">Company</label>
                <input
                  id="nc-search" className="f-input" value={search} autoFocus
                  placeholder="Search by name or BRN"
                  onChange={e => { setSearch(e.target.value); setPicked(null) }}
                />
                <span className="f-hint">
                  Only a company already on the registry can hold a case.
                </span>
              </div>

              {picked ? (
                <div className="alert al-success" role="status">
                  <span className="al-icon">✓</span>
                  <div className="al-body">
                    <b>{picked.company_name}</b>
                    {picked.br_number ? ` · BRN ${picked.br_number}` : ''}
                  </div>
                </div>
              ) : results.length > 0 && (
                <div className="tbl-wrap" style={{ maxHeight: 220, overflowY: 'auto' }}>
                  <table>
                    <tbody>
                      {results.map(c => (
                        <tr key={c.id} className="clickable" onClick={() => setPicked(c)}>
                          <td><span className="td-primary">{c.company_name}</span></td>
                          <td><span className="td-muted">{c.br_number || '—'}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          <div className="f-group" style={{ marginTop: 14 }}>
            {forms.length > 1 ? (
              <fieldset className="nc-forms">
                <legend className="f-label">Case type</legend>
                {forms.map(f => (
                  <label key={f.code} className={`nc-form${form === f.code ? ' on' : ''}`}>
                    <input type="radio" name="nc-form" value={f.code}
                           checked={form === f.code} onChange={() => setForm(f.code)} />
                    <span>{f.label}</span>
                  </label>
                ))}
              </fieldset>
            ) : (
              <>
                <label className="f-label">Case type</label>
                <div className="f-input" style={{ display: 'flex', alignItems: 'center' }}>
                  {chosen?.label || '—'}
                </div>
              </>
            )}
            {chosen && <span className="f-hint">{chosen.hint}</span>}
            {/* NNC1 is not built. An enabled-looking choice that cannot be
                opened is worse than saying so. */}
            <span className="f-hint">
              NNC1 (incorporation) cases are not available yet.
            </span>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-action" onClick={create} disabled={!picked || !chosen || busy}>
            {busy ? 'Opening…' : 'Open case'}
          </button>
        </div>
      </div>
    </div>
  )
}
