/**
 * Which screens a role may open, in the order they are offered.
 *
 * ONE LIST, READ BY THREE PLACES: the sidebar draws it, `/` redirects into it,
 * and every module route is guarded by the same (module, permission) pair. They
 * used to disagree — the sidebar was permission-gated but `/` redirected
 * everybody to `/dashboard` regardless, so a role without `nar1:read` signed in
 * and was dropped straight onto Post-incorporation, which then answered 403 and
 * printed the raw refusal where the case list should have been. The landing and
 * the menu have to be derived from the same fact or they will drift again.
 *
 * The ORDER is the order of the sidebar's Main section, so the screen a user
 * lands on is the first one they can see in the menu — not an arbitrary
 * favourite. `/settings` is deliberately NOT here: it needs no permission, so
 * including it would mean nobody could ever have "no landing", and the empty
 * case is exactly the one worth saying out loud.
 */
export const LANDINGS = [
  {
    to: '/dashboard',
    label: 'Post-incorporation',
    description: 'Open NAR1 cases — data verification through to submission',
    module: 'nar1',
    permission: 'read',
    section: 'main',
  },
  {
    to: '/registry',
    label: 'Body Corporate Registry',
    description: 'Every company on file, with its officers, shares and documents',
    module: 'companies',
    permission: 'read',
    section: 'main',
  },
  {
    to: '/persons',
    label: 'Natural Person Registry',
    description: 'Directors, shareholders and secretaries held as individuals',
    module: 'persons',
    permission: 'read',
    section: 'main',
  },
  {
    // Sits under Admin in the sidebar, but it is a landing like any other: the
    // `all_access` role holds `audit_trail:read` and is NOT a super admin, and
    // for such a role this is the only screen there is.
    to: '/audit-log',
    label: 'Audit Log',
    description: 'Every recorded change, across all modules',
    module: 'audit_trail',
    permission: 'read',
    section: 'admin',
  },
]

/** The landings this role may open, optionally narrowed to one sidebar section. */
export function landingsFor(hasPermission, section = null) {
  if (typeof hasPermission !== 'function') return []
  return LANDINGS.filter(l =>
    (section == null || l.section === section) && hasPermission(l.module, l.permission))
}

/**
 * Where `/` should send this role, or `null` when it holds no module at all.
 *
 * `null` is a real answer, not a failure: a freshly created account whose role
 * has not been given anything yet is in exactly that state, and sending it to a
 * screen it cannot read is how the reported bug looked from the user's chair.
 */
export function homePathFor(hasPermission) {
  return landingsFor(hasPermission)[0]?.to ?? null
}
