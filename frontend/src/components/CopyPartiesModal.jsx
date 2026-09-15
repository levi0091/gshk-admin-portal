import { useMemo, useState } from 'react'
import { api } from '../lib/api.js'
import { useLookups, optionsFor } from '../lib/lookups.js'

/**
 * Add beneficial owners by copying the parties already on the company.
 *
 * WHY THIS EXISTS. A significant controller is almost never a new party — it is
 * one of the members, occasionally a director. The only route in was `+ Add`,
 * which searches the whole Natural Person Registry by name for somebody already
 * listed twelve inches up the same screen, and then asks for the party again
 * for the next one. Levi 2026-09-07: "most of the cases would be the
 * shareholder".
 *
 * IT COPIES THE PARTY, NOT THE ROW. A beneficial owner is a different fact from
 * a shareholding — s.653D asks *how* control is held, not how many shares are
 * held — so nothing is carried across but the identity of the person or body
 * corporate. Owner type and nature of control are chosen here, once, for
 * everything being copied.
 *
 * WHAT IT WILL NOT DO IS GUESS THE 25%. The default nature for a shareholder is
 * `over_25_percent`, and a default that is wrong on a statutory register is
 * worse than no default, so the list shows each member's computed share of the
 * issued capital and pre-ticks ONLY those actually over 25%. Where the share
 * cannot be computed — no `total_issued` on the class, which is true of some
 * ETL'd companies — nothing is pre-ticked and the percentage column says so.
 */

/** How the two sources are labelled and what they start the form at. */
const SOURCES = {
  officers: {
    label: 'Directors',
    empty: 'This company has no directors recorded.',
    // A director's control is held through office, not shareholding — s.653D
    // condition (b). Offering condition (a) here by default would say they hold
    // more than 25% of the shares, which the directors tile does not know.
    nature: 'significant_influence',
  },
  shareholders: {
    label: 'Shareholders',
    empty: 'This company has no shareholders recorded.',
    nature: 'over_25_percent',
  },
}

/** The party on a link row, as the API wants it back. */
function partyRef(row) {
  return row.person_id
    ? { person_id: row.person_id }
    : { corporate_entity_id: row.corporate_entity_id }
}

/** Identity for comparing a link to another link — the party, not the row. */
function partyKey(row) {
  return row.person_id ? `p:${row.person_id}` : `c:${row.corporate_entity_id}`
}

function partyName(row) {
  return row.persons?.full_name
    || row.corporate_entity?.company_name
    || row.corporate_name
    || '—'
}

/**
 * Each member's holding as a percentage of the company's issued shares.
 *
 * ACROSS ALL CLASSES, because s.653D is about the issued shares of the company
 * and a member holding 30% of a minority class does not control it. Returns
 * null for everybody when the total cannot be established, rather than a number
 * computed from a partial denominator — a percentage that is quietly out of a
 * smaller total is the kind of wrong that looks right.
 */
export function holdingPercents(shareholders, shareClasses) {
  const totals = (shareClasses || []).map(c => Number(c.total_issued))
  if (!totals.length || totals.some(t => !Number.isFinite(t) || t <= 0)) return null
  const issued = totals.reduce((a, b) => a + b, 0)

  const held = new Map()
  for (const s of shareholders || []) {
    // A former member holds nothing. `is_current` false is how a transfer out
    // is recorded, and counting them would push the register over 100%.
    if (s.is_current === false) continue
    const n = Number(s.shares_held)
    if (!Number.isFinite(n)) continue
    held.set(partyKey(s), (held.get(partyKey(s)) || 0) + n)
  }
  return new Map([...held].map(([k, n]) => [k, (n / issued) * 100]))
}

export default function CopyPartiesModal({ companyId, officers, shareholders,
                                           shareClasses, existing,
                                           onClose, onSaved }) {
  const lookups = useLookups()
  const [source, setSource] = useState('shareholders')
  const [ownerType, setOwnerType] = useState('significant_controller')
  const [nature, setNature] = useState(SOURCES.shareholders.nature)
  const [picked, setPicked] = useState(null)   // null = "not touched yet"
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // Who is already a beneficial owner. Copying somebody twice would put two
  // rows for one controller on the register, and the tile gives no hint that
  // the second is a duplicate rather than a second kind of control.
  const already = useMemo(
    () => new Set((existing || []).map(partyKey)), [existing])

  const percents = useMemo(
    () => holdingPercents(shareholders, shareClasses), [shareholders, shareClasses])

  /** One row per DISTINCT party — a member with two classes is one controller. */
  const candidates = useMemo(() => {
    const rows = source === 'officers' ? (officers || []) : (shareholders || [])
    const seen = new Map()
    for (const r of rows) {
      if (r.is_current === false) continue
      const key = partyKey(r)
      if (!key || key === 'c:undefined' || key === 'p:undefined') continue
      if (!seen.has(key)) {
        seen.set(key, {
          key,
          name: partyName(r),
          corporate: Boolean(r.corporate_entity_id),
          ref: partyRef(r),
          percent: percents?.get(key) ?? null,
          linked: already.has(key),
        })
      }
    }
    return [...seen.values()]
  }, [source, officers, shareholders, percents, already])

  /**
   * The default tick. Shareholders over 25% only — see the note at the top on
   * why this does not simply select everybody. Directors are never pre-ticked:
   * being a director is not by itself significant control, and a screen that
   * arrived with all of them ticked would be inviting exactly that claim.
   */
  const defaultPicked = useMemo(() => {
    if (source !== 'shareholders' || !percents) return new Set()
    return new Set(candidates.filter(c => !c.linked && c.percent > 25).map(c => c.key))
  }, [source, percents, candidates])

  const selected = picked ?? defaultPicked

  function toggle(key) {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setPicked(next)
  }

  function switchSource(next) {
    setSource(next)
    setNature(SOURCES[next].nature)
    setPicked(null)      // back to that source's own default
    setError('')
  }

  async function handleCopy() {
    setError('')
    const rows = candidates.filter(c => selected.has(c.key) && !c.linked)
    if (!rows.length) return setError('Select at least one party to copy.')

    setSaving(true)
    // Sequential, and every failure named. These are separate inserts with no
    // transaction around them, so a copy of six can genuinely half-succeed —
    // reporting "failed" for the batch would send the operator back to redo
    // the four that worked, and reporting success would hide the two that
    // did not. Same rule the verification mail follows for `failed_to`.
    const failed = []
    let added = 0
    for (const row of rows) {
      try {
        await api.post(`/companies/${companyId}/beneficial-owners`, {
          ...row.ref,
          owner_type: ownerType || undefined,
          nature_of_control: nature || undefined,
          is_current: true,
        })
        added += 1
      } catch (err) {
        failed.push(`${row.name} (${err.message})`)
      }
    }
    setSaving(false)

    if (failed.length) {
      setPicked(new Set(rows.filter(r => failed.some(f => f.startsWith(r.name)))
        .map(r => r.key)))
      setError(added
        ? `Copied ${added}. These were not copied: ${failed.join('; ')}`
        : `Nothing was copied: ${failed.join('; ')}`)
      // Still refresh — the ones that worked are on the register now, and
      // leaving the tile stale would show the operator a screen that
      // contradicts the message they are reading.
      onSaved({ close: false })
      return
    }
    onSaved({ close: true })
  }

  const ownerTypes = optionsFor(lookups?.bo_owner_type, ownerType || null)
  const natures = optionsFor(lookups?.bo_nature_of_control, nature || null)
  const selectable = candidates.filter(c => !c.linked)

  return (
    <div className="overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal" role="dialog" aria-label="Copy beneficial owners">
        <div className="modal-hdr">
          <div className="modal-title">Copy Beneficial Owners</div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          {error && (
            <div style={{ marginBottom: 14, padding: 10, background: '#FEE2E2',
                          borderRadius: 6, color: '#B91C1C', fontSize: 12 }}>
              {error}
            </div>
          )}

          <div className="filter-tabs" role="tablist" style={{ marginBottom: 12 }}>
            {Object.entries(SOURCES).map(([key, s]) => (
              <button key={key} role="tab" aria-selected={source === key}
                      className={`filter-tab ${source === key ? 'active' : ''}`}
                      onClick={() => switchSource(key)}>
                {s.label}
              </button>
            ))}
          </div>

          {candidates.length === 0 ? (
            <div className="empty-state" style={{ padding: '16px 0' }}>
              {SOURCES[source].empty}
            </div>
          ) : (
            <>
              <div className="tbl-wrap" style={{ marginBottom: 14, maxHeight: 240,
                                                 overflowY: 'auto' }}>
                {candidates.map(c => (
                  <label key={c.key} className="doc-item copy-party"
                         style={{ padding: '8px 12px',
                                  cursor: c.linked ? 'default' : 'pointer' }}>
                    <input type="checkbox" checked={selected.has(c.key) && !c.linked}
                           disabled={c.linked || saving}
                           onChange={() => toggle(c.key)} />
                    <span className="doc-name">{c.name}</span>
                    {c.corporate && <span className="member-role-tag">Body Corporate</span>}
                    {/* The unit is stated ONCE, in the hint above the list —
                        "% of issued shares" on every row wrapped to two lines
                        in a 520px dialog and pushed the names into three. */}
                    <span className="copy-party-note">
                      {c.linked
                        ? 'Already a beneficial owner'
                        : source === 'shareholders'
                          ? (c.percent == null ? '—' : `${c.percent.toFixed(2)}%`)
                          : ''}
                    </span>
                  </label>
                ))}
              </div>

              {source === 'shareholders' && selectable.length > 0 && (
                <div className="f-hint" style={{ marginBottom: 12 }}>
                  {percents == null
                    ? 'Every class of shares needs a Total Number before a '
                      + 'member’s share of the company can be worked out, so '
                      + 'nothing is pre-selected — check the 25% test yourself '
                      + 'before copying.'
                    : 'Share of the company’s total issued shares, across every '
                      + 'class. Members over 25% are selected already.'}
                </div>
              )}

              <div className="form-grid">
                <div className="f-group">
                  <label className="f-label" htmlFor="copy_owner_type">Owner Type</label>
                  <select id="copy_owner_type" className="f-select" value={ownerType}
                          onChange={e => setOwnerType(e.target.value)}>
                    <option value="">Select…</option>
                    {ownerTypes.map(o => (
                      <option key={o.code} value={o.code}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div className="f-group full">
                  <label className="f-label" htmlFor="copy_nature">
                    Nature of Control over the Company
                  </label>
                  <select id="copy_nature" className="f-select" value={nature}
                          onChange={e => setNature(e.target.value)}>
                    <option value="">Select…</option>
                    {natures.map(o => (
                      <option key={o.code} value={o.code}>{o.label}</option>
                    ))}
                  </select>
                  {/* One value for the whole batch. Said out loud, because a
                      form that applies a control to six people silently is a
                      form that gets one of the six wrong. */}
                  <span className="f-hint">
                    Applied to everyone copied. Copy them in groups, or edit a
                    row afterwards, where the answer differs.
                  </span>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleCopy}
                  disabled={saving || selectable.length === 0}>
            {saving ? 'Copying…' : `Copy ${selected.size || ''}`.trim()}
          </button>
        </div>
      </div>
    </div>
  )
}
