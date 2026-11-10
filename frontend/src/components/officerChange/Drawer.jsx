import { useEffect, useRef } from 'react'

/**
 * A right-hand sheet for adding or editing one entry. Every add/edit in this
 * app is a dialog with a right-aligned footer; this is that, taller, because a
 * party picker and its read-only particulars do not fit a 520px modal.
 *
 * It closes from its footer's Cancel and nowhere else — no outside click and no
 * Escape (Levi 2026-10-30), so a stray press cannot lose what has been keyed.
 */
export default function Drawer({ title, sub, footer, children }) {
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus() }, [])
  return (
    <div className="oc-drawer-wrap">
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
