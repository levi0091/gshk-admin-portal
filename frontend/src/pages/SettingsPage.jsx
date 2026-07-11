import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

/**
 * The wireframe carries a Settings nav item but no Settings screen ("screen not
 * yet wireframed"). Rather than invent a workflow, this shows the signed-in
 * account and the permissions actually in force, and links to the admin tools
 * the user is allowed to open. Everything here is real state, not a stub.
 */
function Kv({ label, children }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{label}</span>
      <span className="kv-val">{children || <span className="td-muted">—</span>}</span>
    </div>
  )
}

export default function SettingsPage() {
  const { profile, session, isSuperAdmin, hasPermission, signOut } = useAuth()
  const navigate = useNavigate()

  const permissions = profile?.permissions || []
  // /auth/me doesn't return the email; the authenticated session carries it.
  const email = profile?.email || session?.user?.email

  const adminLinks = [
    { to: '/users', label: 'User Management', show: isSuperAdmin },
    { to: '/roles', label: 'Roles', show: isSuperAdmin },
    { to: '/audit-log', label: 'Audit Log', show: hasPermission('audit_trail', 'read') },
  ].filter(l => l.show)

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  return (
    <>
      <div className="pg-hdr">
        <div>
          <div className="pg-title">Settings</div>
          <div className="pg-sub">Your account and the access currently granted to it</div>
        </div>
      </div>

      <div className="detail-grid client-off">
        <div>
          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">Account</div>
                <div className="card-sub">Signed-in user</div>
              </div>
            </div>
            <div className="kv-list">
              <Kv label="Name"><span className="font-semibold">{profile?.display_name}</span></Kv>
              <Kv label="Email">{email}</Kv>
              <Kv label="Role">
                {profile?.role_name}
                {isSuperAdmin && <span className="reg-badge reg-badge-corp" style={{ marginLeft: 8 }}>Super Admin</span>}
              </Kv>
            </div>
          </div>

          <div className="card mb-16">
            <div className="card-hdr">
              <div>
                <div className="card-title">
                  Permissions <span className="count-pill">{isSuperAdmin ? '∗' : permissions.length}</span>
                </div>
                <div className="card-sub">What this role may do</div>
              </div>
            </div>
            {isSuperAdmin ? (
              <div className="reveal-note" style={{ color: 'var(--indigo)', background: 'var(--indigo-10)' }}>
                Super Admin — bypasses every module permission check.
              </div>
            ) : permissions.length === 0 ? (
              <div className="empty-state" style={{ padding: '16px 0' }}>
                No module permissions granted. Contact a Super Admin.
              </div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {permissions.map(p => (
                  <span key={p} className="role-tag role-dir">{p}</span>
                ))}
              </div>
            )}
          </div>

          {adminLinks.length > 0 && (
            <div className="card mb-16">
              <div className="card-hdr">
                <div>
                  <div className="card-title">Administration</div>
                  <div className="card-sub">Tools available to you</div>
                </div>
              </div>
              {adminLinks.map(l => (
                <div className="role-item" key={l.to}>
                  <div className="role-item-main">{l.label}</div>
                  <button className="role-open" onClick={() => navigate(l.to)}>Open →</button>
                </div>
              ))}
            </div>
          )}

          <div className="card">
            <div className="card-hdr">
              <div>
                <div className="card-title">Session</div>
                <div className="card-sub">Sign out of G-FlowDesk on this device</div>
              </div>
              <button className="btn btn-outline btn-sm" onClick={handleSignOut}>Log Out</button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
