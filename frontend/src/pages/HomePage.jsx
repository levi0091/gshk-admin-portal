import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { homePathFor, landingsFor } from '../lib/navigation.js'

/**
 * What `/` does, which used to be `<Navigate to="/dashboard">` for everybody.
 *
 * THAT WAS THE BUG. Post-incorporation needs `nar1:read`; a role holding only
 * `companies` and `persons` signed in, was dropped on it anyway, and got
 * "Failed to load cases" on a screen it was never allowed to open — while the
 * sidebar, which IS permission-gated, showed nothing under Main. The portal
 * looked broken rather than restricted.
 *
 * A user with any module at all is sent to the FIRST one their sidebar offers,
 * so their landing and their menu agree and nobody gains an extra click:
 * a super admin still lands on Post-incorporation exactly as before.
 *
 * A user with NO module gets the screen below rather than a redirect. There is
 * nowhere honest to send them, and bouncing them to Settings would answer
 * "where am I supposed to be?" with a page about session and permissions —
 * technically their only option, and completely silent about why.
 */
export default function HomePage() {
  const { hasPermission, profile, profileLoading, profileError } = useAuth()
  const navigate = useNavigate()

  // Deciding before /auth/me resolves would send every user to the no-access
  // screen for a frame — `hasPermission` reads an empty list while loading,
  // which is indistinguishable from a role that holds nothing.
  if (profileLoading) return null

  // A FAILED PROFILE IS NOT AN EMPTY ONE. Redirecting on a permission list we
  // could not load would land the user on the no-access screen and tell them
  // their role is empty, which is a guess presented as a fact.
  if (!profileError) {
    const home = homePathFor(hasPermission)
    if (home) return <Navigate to={home} replace />
  }

  const landings = landingsFor(hasPermission)

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">
            Welcome{profile?.display_name ? `, ${profile.display_name}` : ''}
          </div>
          <div className="pg-sub">G-FlowDesk — Get Started HK</div>
        </div>
      </div>

      <div className="detail-grid client-off">
        <div>
          {profileError ? (
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Your permissions could not be loaded</div>
                  <div className="card-sub">
                    This is not the same as having none
                  </div>
                </div>
              </div>
              <div className="reveal-note" style={{ color: '#B91C1C', background: '#FEE2E2' }}>
                {profileError} — the menu is empty because the portal does not
                know what you may open, not because your role is empty. Reload
                the page; if it keeps happening the API may be down.
              </div>
            </div>
          ) : (
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">
                    Your role has no modules yet
                  </div>
                  <div className="card-sub">
                    {profile?.role_name
                      ? `Signed in as ${profile.role_name}`
                      : 'Signed in'}
                  </div>
                </div>
              </div>
              <div className="empty-state" style={{ padding: '16px 0' }}>
                Your account works — it just has not been given access to any
                module. A Super Admin adds these under Roles. Until then there
                is nothing here to open.
              </div>
            </div>
          )}

          {landings.length > 0 && (
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Go to</div>
                  <div className="card-sub">Screens your role can open</div>
                </div>
              </div>
              {landings.map(l => (
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

          <div className="card">
            <div className="card-hdr">
              <div>
                <div className="card-title">Account</div>
                <div className="card-sub">Your details and the access in force</div>
              </div>
              <button className="btn btn-outline btn-sm"
                      onClick={() => navigate('/settings')}>
                Open Settings
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
