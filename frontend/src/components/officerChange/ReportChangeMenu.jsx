import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { officerChangeApi } from './api.js'
import { errorOf } from './workflow.js'
import './entryPoints.css'

/**
 * Open (or reuse) an officer-change case for a company and go to it.
 *
 * The backend reuses the company's unsent case of the same form, so pressing
 * Cease on two directors one after the other builds ONE ND2A, as CR's form
 * expects, rather than two.
 *
 * `entry` is added to the case on the way (Change particulars: the items come
 * from the profile, so there is nothing more to ask). An officer already on
 * that case is not an error — the operator lands on the case that holds them.
 * `cease` is an officer ref; the case page opens the cessation drawer on it,
 * because a cessation needs a date and a reason that only the operator knows.
 */
export function useStartOfficerChange(entityId) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // `company` overrides the hook's company, for a screen listing several (the
  // particulars alert on a person names every company they serve).
  async function start(formCode, { entry, cease, company } = {}) {
    setBusy(true); setError(null)
    try {
      const res = await officerChangeApi.create(company || entityId, formCode)
      const id = res?.case?.id
      if (entry) {
        try {
          await officerChangeApi.addEntry(id, entry)
        } catch (e) {
          if (!/already on this form/i.test(errorOf(e).message)) throw e
        }
      }
      navigate(`/officer-changes/${id}${cease ? `?cease=${encodeURIComponent(cease)}` : ''}`)
    } catch (e) {
      setError(errorOf(e).message)
    } finally {
      setBusy(false)
    }
  }

  return { start, busy, error, clearError: () => setError(null) }
}

const ITEMS = [
  { form: 'Nd2a', label: 'Appoint or cease an officer', code: 'ND2A' },
  { form: 'Nd2b', label: "Change an officer's particulars", code: 'ND2B' },
]

/**
 * The company profile's way into ND2A / ND2B. A menu rather than two buttons:
 * both are "tell CR about our officers", and the header already carries the
 * profile's own actions. Rendered only for `officer_changes:write`.
 */
export default function ReportChangeMenu({ entityId }) {
  const [open, setOpen] = useState(false)
  const { start, busy, error, clearError } = useStartOfficerChange(entityId)
  const wrap = useRef(null)
  const firstItem = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    firstItem.current?.focus()
    const onDown = e => { if (!wrap.current?.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="ep-menu" ref={wrap}>
      <button type="button" className="btn btn-outline" aria-haspopup="menu" aria-expanded={open}
              disabled={busy} onClick={() => { clearError(); setOpen(o => !o) }}>
        {busy ? 'Opening…' : 'Report a change'}
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" className="ep-caret">
          <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.5"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="ep-menu-list" role="menu" aria-label="Report a change">
          {ITEMS.map((item, i) => (
            <button key={item.form} type="button" role="menuitem" className="ep-menu-item"
                    ref={i === 0 ? firstItem : undefined}
                    onClick={() => { setOpen(false); start(item.form) }}>
              <span className="ep-menu-code">{item.code}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
      {error && <div className="ep-error" role="alert">{error}</div>}
    </div>
  )
}
