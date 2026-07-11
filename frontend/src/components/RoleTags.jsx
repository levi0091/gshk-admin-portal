/** Role pills for a person. Roles come from the four link tables (read-only). */
export const ROLE_META = [
  { key: 'director', flag: 'is_director', label: 'Director', cls: 'role-dir' },
  { key: 'shareholder', flag: 'is_shareholder', label: 'Shareholder', cls: 'role-shr' },
  { key: 'secretary', flag: 'is_secretary', label: 'Secretary', cls: 'role-sec' },
  { key: 'beneficial_owner', flag: 'is_beneficial_owner', label: 'Beneficial Owner', cls: 'role-bo' },
]

export function initials(name) {
  if (!name) return '?'
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase()
}

/** `person` carries the is_* flags from the person_registry view. */
export default function RoleTags({ person, counts }) {
  const active = ROLE_META.filter(r => person[r.flag])
  if (active.length === 0) return <span className="td-muted">—</span>
  return (
    <>
      {active.map(r => (
        <span key={r.key} className={`role-tag ${r.cls}`}>
          {r.label}{counts?.[r.key] ? ` ×${counts[r.key]}` : ''}
        </span>
      ))}
    </>
  )
}
