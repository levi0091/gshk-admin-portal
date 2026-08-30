import { useState, useEffect, useRef } from 'react'
import { api } from '../lib/api.js'

/**
 * Open a NAR1 case — from the Post-incorporation dashboard or a company profile.
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
 */
export default function NewCaseModal({ entity, onClose, onCreated }) {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [picked, setPicked] = useState(entity || null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const searching = useRef(false)

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
    if (!picked) return
    setError(null); setBusy(true)
    try {
      const created = await api.post('/cases', {
        entity_id: picked.id,
        form_code: 'Nar1',
      })
      onCreated(created)
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
          <div className="modal-title">Open a NAR1 case</div>
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
              <span className="f-hint">
                The annual return is filed for this company.
              </span>
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
            <label className="f-label">Case type</label>
            <div className="f-input" style={{ display: 'flex', alignItems: 'center' }}>
              NAR1 — Annual Return
            </div>
            {/* NNC1 is not built. An enabled-looking picker with one option
                that cannot change is worse than saying so. */}
            <span className="f-hint">
              NNC1 (incorporation) cases are not available yet.
            </span>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-action" onClick={create} disabled={!picked || busy}>
            {busy ? 'Opening…' : 'Open case'}
          </button>
        </div>
      </div>
    </div>
  )
}
