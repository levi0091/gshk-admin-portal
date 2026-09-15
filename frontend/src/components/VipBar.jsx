import { useState } from 'react'

/**
 * A client's VIP status, at the very top of the person profile (wireframe v11,
 * screen s11; migration 041).
 *
 * GSHK's mock-up feedback, 16 July: "Add a bar at the very top so colleagues
 * can quickly identify whether the client is important. For example, VIP
 * clients are those who have more than three companies with us, and they may
 * also be our affiliated agents. (Agents are considered VIP clients.)" It sat
 * in the wireframe from v9 and was never built (Levi 2026-09-14).
 *
 * THE VERDICT IS THE BACKEND'S (`routers/persons.vip_status`), read off `vip`.
 * This component never recounts companies — the rule would then live twice and
 * the bar could disagree with the API that every other screen reads.
 *
 * Two things can be changed here, and only by a role that can edit the person
 * (a control you cannot use is not rendered): the AFFILIATED AGENT flag, and a
 * MANUAL mark. A client who is VIP by rule — an agent, or more than three
 * companies — shows the VIP switch LOCKED, because switching it off would only
 * be undone by the rule on the next read.
 */

const CROWN = (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff"
       strokeWidth="1.7" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 8l4.2 3 4.8-7 4.8 7 4.2-3-2 11H5L3 8z" />
    <path d="M5 20h14" strokeLinecap="round" />
  </svg>
)

const STAR = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#7C80A3"
       strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3.2l2.6 5.6 6.1.9-4.4 4.3 1 6.1L12 19.3 6.7 22.1l1-6.1L3.3 9.7l6.1-.9L12 3.2z" />
  </svg>
)

/** The small crown chip beside the person's name. */
export function VipChip() {
  return (
    <span className="vip-chip" data-testid="vip-chip">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M3 8l4.2 3 4.8-7 4.8 7 4.2-3-2 11H5L3 8z" />
      </svg>
      VIP
    </span>
  )
}

function Switch({ on, label, hint, locked = false, disabled = false, title, onToggle }) {
  return (
    <div className="vip-sw-row">
      <div className="vip-sw-txt">
        <span className="vip-sw-lbl">{label}</span>
        {hint && <span className="vip-sw-hint">{hint}</span>}
      </div>
      <button type="button" role="switch" aria-checked={on} aria-label={label}
              title={title}
              className={`vip-sw${on ? ' on' : ''}${locked ? ' vip-sw-lock' : ''}`}
              disabled={locked || disabled} onClick={onToggle}>
        <span className="vip-knob" />
      </button>
    </div>
  )
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

export default function VipBar({ vip, isAgent = false, canWrite = false, onSave }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  if (!vip) return null

  const on = vip.is_vip === true
  const automatic = vip.automatic === true
  const count = vip.company_count ?? 0
  const threshold = vip.threshold ?? 3
  const reasons = vip.reasons || []

  async function save(patch) {
    setBusy(true); setError(null)
    try {
      await onSave(patch)
    } catch (e) {
      setError(e?.message || 'Could not save the VIP status.')
    } finally {
      setBusy(false)
    }
  }

  const controls = canWrite && (
    <div className="vip-controls">
      <Switch on={isAgent} label="Affiliated agent"
              hint={isAgent ? 'Agents are VIP' : ''} disabled={busy}
              onToggle={() => save({ is_affiliated_agent: !isAgent })} />
      <div className="vip-div" />
      {on ? (
        <Switch on label="VIP status" hint={automatic ? 'Automatic' : 'Manual'}
                locked={automatic} disabled={busy}
                title={automatic
                  ? 'VIP is automatic for this client and cannot be switched off'
                  : 'Remove the VIP mark'}
                onToggle={() => save({ is_vip_marked: false })} />
      ) : (
        <button type="button" className="vip-mark-btn" disabled={busy}
                onClick={() => save({ is_vip_marked: true })}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 3.2l2.6 5.6 6.1.9-4.4 4.3 1 6.1L12 19.3 6.7 22.1l1-6.1L3.3 9.7l6.1-.9L12 3.2z" />
          </svg>
          Mark as VIP
        </button>
      )}
    </div>
  )

  return (
    <div className={`vip-bar ${on ? 'on' : 'off'}`} data-testid="vip-bar">
      <div className="vip-inner">
        <div className="vip-id">
          <div className="vip-medal">{on ? CROWN : STAR}</div>
          <div>
            {on ? (
              <>
                <div className="vip-eyebrow">Priority client</div>
                <div className="vip-title">VIP Client</div>
                <div className="vip-sub">
                  Flagged for every colleague — handle this client with priority.
                </div>
                <div className="vip-reasons">
                  {reasons.includes('affiliated_agent') && (
                    <span className="vip-reason">Affiliated agent</span>
                  )}
                  <span className="vip-reason">
                    {plural(count, 'company', 'companies')} with us
                  </span>
                  {!automatic && reasons.includes('marked') && (
                    <span className="vip-reason">Marked VIP</span>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="vip-eyebrow">Client tier</div>
                <div className="vip-title">Standard client</div>
                <div className="vip-sub">
                  Becomes <b>VIP</b> automatically at more than {threshold}{' '}
                  companies, or when flagged as an affiliated agent. Currently{' '}
                  <b>{plural(count, 'company', 'companies')}</b>.
                </div>
              </>
            )}
            {error && <div className="vip-error" role="alert">{error}</div>}
          </div>
        </div>
        {controls}
      </div>
    </div>
  )
}
