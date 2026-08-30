import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'


const NavItem = ({ to, icon, children, title }) => (
  <NavLink
    to={to}
    className="nav-item"
    title={title}
    style={({ isActive }) => ({
      display: 'flex', alignItems: 'center', gap: 9,
      padding: '8px 10px', borderRadius: 6,
      color: isActive ? 'var(--indigo)' : 'var(--t-body)',
      fontWeight: isActive ? 600 : 500, fontSize: 13,
      background: isActive ? 'var(--indigo-10)' : 'transparent',
      textDecoration: 'none', transition: '.15s',
    })}
  >
    <span style={{ opacity: .65, flexShrink: 0 }}>{icon}</span>
    <span className="nav-label">{children}</span>
  </NavLink>
)

const SettingsIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 16 16">
    <circle cx="8" cy="8" r="2.2"/>
    <path d="M13 8a5 5 0 0 0-.1-1l1.3-1-1.5-2.6-1.6.6a5 5 0 0 0-1.7-1L9.1 1H6.1l-.3 1.7a5 5 0 0 0-1.7 1l-1.6-.6L1 5.7l1.3 1a5 5 0 0 0 0 2l-1.3 1 1.5 2.6 1.6-.6a5 5 0 0 0 1.7 1l.3 1.7h3l.3-1.7a5 5 0 0 0 1.7-1l1.6.6 1.5-2.6-1.3-1c.06-.3.1-.65.1-1z"/>
  </svg>
)

const DashIcon = () => (
  <svg width="15" height="15" fill="currentColor" viewBox="0 0 16 16">
    <rect x="1" y="1" width="6" height="6" rx="1.5"/>
    <rect x="9" y="1" width="6" height="6" rx="1.5"/>
    <rect x="1" y="9" width="6" height="6" rx="1.5"/>
    <rect x="9" y="9" width="6" height="6" rx="1.5"/>
  </svg>
)
const RegistryIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 16 16">
    <rect x="2" y="2" width="12" height="12" rx="1.5"/>
    <line x1="2" y1="6" x2="14" y2="6"/>
    <line x1="6" y1="6" x2="6" y2="14"/>
  </svg>
)
const PersonsIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 16 16">
    <circle cx="8" cy="5" r="2.6"/>
    <path d="M3 14c0-2.8 2.2-4.6 5-4.6s5 1.8 5 4.6"/>
  </svg>
)
const UsersIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 16 16">
    <circle cx="6" cy="5" r="2.5"/>
    <path d="M1 13c0-2.8 2.2-5 5-5s5 2.2 5 5"/>
    <path d="M11 7c1.4 0 2.5 1.1 2.5 2.5"/>
    <path d="M13.5 13c0-1.7-.9-3.1-2.5-3.5"/>
  </svg>
)
const RolesIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 16 16">
    <path d="M8 1.5L2 4v4c0 3.3 2.6 5.7 6 6.5 3.4-.8 6-3.2 6-6.5V4L8 1.5z"/>
    <path d="M5.5 8l1.8 1.8L10.5 6"/>
  </svg>
)
const AuditIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 16 16">
    <circle cx="8" cy="8" r="6.5"/>
    <polyline points="8 4.5 8 8 10.5 9.5"/>
  </svg>
)
const KeyIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 16 16">
    <rect x="3" y="7" width="10" height="7" rx="1.5"/>
    <path d="M5 7V5a3 3 0 0 1 6 0v2"/>
  </svg>
)
const SignOutIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 16 16">
    <path d="M10 3h3a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3"/>
    <polyline points="7 10 10 8 7 6"/>
    <line x1="10" y1="8" x2="2" y2="8"/>
  </svg>
)

export default function Sidebar({ isOpen, collapsed, onClose }) {
  const { isSuperAdmin, hasPermission, signOut } = useAuth()
  const navigate = useNavigate()

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  const sectionLbl = {
    fontSize: 9, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase',
    color: 'var(--t-muted)', padding: '10px 8px 4px',
  }

  return (
    <nav
      className={`app-sidebar${isOpen ? ' open' : ''}${collapsed ? ' collapsed' : ''}`}
      style={{
        width: 232, background: 'var(--bg-card)',
        borderRight: '1px solid var(--border)',
        flexShrink: 0, overflowY: 'auto', padding: '16px 0',
      }}
    >
      <div style={{ padding: '0 10px', marginBottom: 4 }}>
        <div className="nav-section-lbl" style={sectionLbl}>
          Main
        </div>
        {/* Two different modules on purpose. The dashboard is now the NAR1 CASE
            list (GET /cases, `nar1:read`); the registry is companies
            (`companies:read`). A role may hold one without the other, and
            showing a nav item that answers 403 is worse than not showing it. */}
        {hasPermission('nar1', 'read') && (
          <NavItem to="/dashboard" icon={<DashIcon />}>Post-incorporation</NavItem>
        )}
        {hasPermission('companies', 'read') && (
          <NavItem to="/registry" icon={<RegistryIcon />}>Company Registry</NavItem>
        )}
        {hasPermission('persons', 'read') && (
          <NavItem to="/persons" icon={<PersonsIcon />}>Persons Registry</NavItem>
        )}

        {isSuperAdmin && (
          <>
            <div className="nav-divider" />
            <div className="nav-section-lbl" style={sectionLbl}>
              Admin
            </div>
            <NavItem to="/users" icon={<UsersIcon />} title="User Management">User Management</NavItem>
            <NavItem to="/roles" icon={<RolesIcon />} title="Roles">Roles</NavItem>
            {hasPermission('audit_trail', 'read') && (
              <NavItem to="/audit-log" icon={<AuditIcon />} title="Audit Log">Audit Log</NavItem>
            )}
          </>
        )}

        <div className="nav-divider" />
        <div className="nav-section-lbl" style={sectionLbl}>
          System
        </div>
        <NavItem to="/settings" icon={<SettingsIcon />} title="Settings">Settings</NavItem>
        {/* tpsi:read is enough to VIEW the credential metadata; the page itself
            gates saving on tpsi:write. Hiding it from users with neither keeps
            the nav honest about what they can actually open. */}
        {hasPermission('tpsi', 'read') && (
          <NavItem to="/cr-credentials" icon={<KeyIcon />} title="CR Credentials">CR Credentials</NavItem>
        )}
        <button
          className="nav-item"
          onClick={handleSignOut}
          title="Log Out"
          style={{
            display: 'flex', alignItems: 'center', gap: 9,
            padding: '8px 10px', borderRadius: 6, width: '100%',
            color: 'var(--t-muted)', fontSize: 13, fontWeight: 500,
            background: 'none', border: 'none', cursor: 'pointer', transition: '.15s',
          }}
        >
          <SignOutIcon />
          <span className="nav-label">Log Out</span>
        </button>
      </div>
    </nav>
  )
}
