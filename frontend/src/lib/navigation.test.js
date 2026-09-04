import { describe, it, expect } from 'vitest'
import { LANDINGS, landingsFor, homePathFor } from './navigation.js'

/**
 * The list the sidebar, `/` and every route guard read.
 *
 * They used to be three separate opinions, which is how the reported bug
 * happened: the sidebar was permission-gated and `/` was not, so a role without
 * `nar1:read` landed on Post-incorporation beside a menu that showed nothing.
 */
const holding = (...perms) => (module, permission) =>
  perms.includes(`${module}:${permission}`)

describe('navigation — what a role may land on', () => {
  it('offers a super-admin-equivalent role every landing, dashboard first', () => {
    expect(landingsFor(() => true).map(l => l.to))
      .toEqual(['/dashboard', '/registry', '/persons', '/audit-log'])
  })

  it('sends a full-access role to the dashboard, exactly as before', () => {
    // The fix must not cost anybody a click. A role that could already land on
    // Post-incorporation still does.
    expect(homePathFor(() => true)).toBe('/dashboard')
  })

  it('sends the tester role to the registry, not to Post-incorporation', () => {
    // The reported case: companies (read), persons (read), persons (write) —
    // and no nar1 at all.
    const tester = holding('companies:read', 'persons:read', 'persons:write')
    expect(homePathFor(tester)).toBe('/registry')
    expect(landingsFor(tester).map(l => l.to)).toEqual(['/registry', '/persons'])
  })

  it('sends a persons-only role to the persons registry', () => {
    expect(homePathFor(holding('persons:read'))).toBe('/persons')
  })

  it('sends an audit-only role to the audit log', () => {
    // `all_access` holds `audit_trail:read` and is not a super admin. It is the
    // only screen that role has, and it must be reachable.
    expect(homePathFor(holding('audit_trail:read'))).toBe('/audit-log')
  })

  it('answers null for a role with no module at all', () => {
    // A real answer, not a failure: a freshly created account is in exactly
    // this state, and sending it anywhere would be a guess.
    expect(homePathFor(holding())).toBeNull()
    expect(landingsFor(holding())).toEqual([])
  })

  it('answers null rather than throwing when there is no hasPermission yet', () => {
    // `useAuth()` outside a provider hands back a deny-everything default, but
    // nothing here may assume it was called correctly — this runs during the
    // first paint of every session.
    expect(homePathFor(undefined)).toBeNull()
    expect(landingsFor(null)).toEqual([])
  })

  it('narrows to one sidebar section on request', () => {
    expect(landingsFor(() => true, 'main').map(l => l.to))
      .toEqual(['/dashboard', '/registry', '/persons'])
    expect(landingsFor(() => true, 'admin').map(l => l.to)).toEqual(['/audit-log'])
  })

  it('gives every landing a module, a permission and a section', () => {
    // A landing missing one of these would be silently unreachable, or
    // silently reachable by everybody.
    for (const l of LANDINGS) {
      expect(l.module, l.to).toBeTruthy()
      expect(l.permission, l.to).toBeTruthy()
      expect(['main', 'admin'], l.to).toContain(l.section)
    }
  })

  it('never lands anybody on /settings', () => {
    // Settings needs no permission, so including it would mean nobody could
    // ever have "no landing" — and the empty case is the one worth saying out
    // loud rather than papering over.
    expect(LANDINGS.map(l => l.to)).not.toContain('/settings')
  })
})
