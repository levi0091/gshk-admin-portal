import { useEffect, useRef } from 'react'

/**
 * A right-hand sheet for adding or editing one entry. Every add/edit in this
 * app is a dialog with a right-aligned footer; this is that, taller, because a
 * party picker and its read-only particulars do not fit a 520px modal.
 */
export default function Drawer({ title, sub, onClose, footer, children }) {
  const ref = useRef(null)
  useEffect(() => {
    ref.current?.focus()
    const onKey = e => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="oc-drawer-wrap" onMouseDown={e => { if (e.target === e.currentTarget) onClose?.() }}>
      <aside className="oc-drawer" role="dialog" aria-modal="true" aria-label={title}
             tabIndex={-1} ref={ref}>
        <div className="oc-drawer-hd">
          <div className="oc-drawer-title">{title}</div>
          {sub && <div className="oc-drawer-sub">{sub}</div>}
        </div>
        <div className="oc-drawer-body">{children}</div>
        <div className="oc-drawer-ft">{footer}</div>
      </aside>
    </div>
  )
}
