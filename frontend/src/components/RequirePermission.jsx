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
 * Every disabled control below it also carries its own reason as a `title`, but
 * a tooltip is only found by someone who already suspects. This is the sentence
 * that stops a reader concluding the page is broken.
 */
export function ReadOnlyNote({ module, permission = 'write', what }) {
  return (
    <div className="reveal-note" role="note"
         style={{ color: 'var(--indigo)', background: 'var(--indigo-10)' }}>
      <b>Read-only.</b> You can open and read {what}, but not change
      it. Editing needs{' '}
      <span className="role-tag role-dir">{module} ({permission})</span>, which
      your role does not have — every action below is disabled for that reason,
      and the API refuses them independently.
    </div>
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
