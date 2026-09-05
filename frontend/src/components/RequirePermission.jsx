import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { landingsFor } from '../lib/navigation.js'

/**
 * "You cannot open this" — said once, on the screen, instead of by the API.
 *
 * Every module route is reachable by typing its URL, and until now they all
 * rendered and then showed whatever the backend refused with: "Failed to load
 * cases: Insufficient permissions" where the table should be, or worse, an
 * empty screen with a red line at the top. The API refusing is correct and
 * stays; what was missing was the screen saying so in its own words BEFORE
 * asking for data the caller cannot have.
 *
 * It names the permission, because "ask an administrator" without saying what
 * to ask for makes the administrator guess too.
 */
export function NoAccess({ module, permission, title = 'No access to this screen' }) {
  const navigate = useNavigate()
  const { hasPermission, profile } = useAuth()
  const elsewhere = landingsFor(hasPermission)

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">{title}</div>
          <div className="pg-sub">
            Your role{profile?.role_name ? ` (${profile.role_name})` : ''} does
            not include this module
          </div>
        </div>
      </div>

      <div className="detail-grid client-off">
        <div>
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">What is missing</div>
                <div className="card-sub">Name this when asking for access</div>
              </div>
            </div>
            <div className="empty-state" style={{ padding: '16px 0' }}>
              {module && permission ? (
                <>
                  This screen needs{' '}
                  <span className="role-tag role-dir">{module} ({permission})</span>
                  {' '}and your role does not have it. A Super Admin can add it
                  under Roles.
                </>
              ) : (
                <>This screen is restricted to Super Admins.</>
              )}
            </div>
          </div>

          {elsewhere.length > 0 && (
            <div className="card">
              <div className="card-hdr">
                <div>
                  <div className="card-title">What you can open</div>
                  <div className="card-sub">Screens your role does include</div>
                </div>
              </div>
              {elsewhere.map(l => (
                <div className="role-item" key={l.to}>
                  <div>
                    <div className="role-item-main">{l.label}</div>
                    <div className="role-item-sub">{l.description}</div>
                  </div>
                  <button className="role-open" onClick={() => navigate(l.to)}>
                    Open →
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

/**
 * The one banner a read-only screen carries, at the top, before anything else.
 *
 * THIS IS THE OTHER HALF OF HIDING THE CONTROLS, and it is not optional. The
 * buttons a role cannot press are not rendered at all (Levi 2026-09-04), which
 * is the right call — a disabled button is still an offer, and its reason hides
 * in a tooltip you only see by hovering the thing you have been refused. But
 * hidden controls with no explanation turn "you may not edit this" into "this
 * app cannot edit this", and the operator then asks the wrong person the wrong
 * question. So: nothing to click, and one sentence saying why.
 *
 * `permissions` takes several pairs for a screen that withholds more than one
 * thing — the case workflow needs `nar1 (write)` and `tpsi (submit)` named
 * separately, because a role can hold either without the other.
 */
export function ReadOnlyNote({ module, permission = 'write', permissions, what,
                               verb = 'Editing' }) {
  const needed = permissions?.length
    ? permissions
    : [{ module, permission }]

  return (
    <div className="ro-note" role="note">
      <b>Read-only.</b> You can open and read {what}, but not change
      it. {verb} needs{' '}
      {needed.map((p, i) => (
        <span key={`${p.module}:${p.permission}`}>
          {i > 0 && (i === needed.length - 1 ? ' and ' : ' ')}
          <span className="role-tag role-dir">{p.module} ({p.permission})</span>
        </span>
      ))}
      {/* AN EM DASH AFTER THE CHIP, not a comma. A chip is an inline-block
          carrying 8px of its own right padding, so a comma set against it
          renders adrift — "persons (write) , which your role…". A dash is
          meant to sit in space, so the same gap reads as deliberate. */}
      {' — your role does not have '}{needed.length > 1 ? 'them' : 'it'}
      , so those actions are not shown. The API refuses them independently.
    </div>
  )
}

/**
 * What stands in the slot where a stage's action button would have been.
 *
 * THE WORKFLOW NEEDS THIS AND THE PROFILES DO NOT. On a profile, a missing Edit
 * button leaves a screen that still makes sense — it reads. A workflow stage is
 * nothing BUT its next action: remove the button and the operator is looking at
 * a step with no way forward and no hint that the way forward exists for
 * somebody else. So the button goes and a sentence naming who can do it stays,
 * in the same place, with nothing to click.
 *
 * It reuses `.perm-tag`, which already sat beside these buttons naming the
 * requirement — this is that tag doing the whole job instead of half of it.
 */
export function ActionWithheld({ module, permission = 'write', action }) {
  return (
    <span className="perm-tag" role="note">
      Needs <b>{module}:{permission}</b> — {action} is not available to your role
    </span>
  )
}

/**
 * Guard one route on one (module, permission) pair.
 *
 * WAITS FOR `/auth/me`, exactly as `RequireSuperAdmin` does. Deciding before
 * the profile resolves would flash a refusal at every user on every reload,
 * and then keep it on screen — `hasPermission` reads an empty list while the
 * profile is loading, which is indistinguishable from a role with nothing in
 * it.
 */
export default function RequirePermission({ module, permission, children }) {
  const { hasPermission, profileLoading } = useAuth()
  if (profileLoading) return null
  if (!hasPermission(module, permission)) {
    return <NoAccess module={module} permission={permission} />
  }
  return children
}
