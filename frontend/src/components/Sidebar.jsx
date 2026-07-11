import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'


const NavItem = ({ to, icon, children }) => (
  <NavLink
    to={to}
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
    {children}
  </NavLink>
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
const SignOutIcon = () => (
  <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 16 16">
    <path d="M10 3h3a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-3"/>
    <polyline points="7 10 10 8 7 6"/>
    <line x1="10" y1="8" x2="2" y2="8"/>
  </svg>
)

export default function Sidebar({ isOpen, onClose }) {
  const { isSuperAdmin, hasPermission, signOut } = useAuth()
  const navigate = useNavigate()

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  return (
    <nav
      className={`app-sidebar${isOpen ? ' open' : ''}`}
      style={{
        width: 232, background: 'var(--bg-card)',
        borderRight: '1px solid var(--border)',
        flexShrink: 0, overflowY: 'auto', padding: '16px 0',
      }}
    >
      <div style={{ padding: '0 10px', marginBottom: 4 }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--t-muted)', padding: '10px 8px 4px' }}>
          Main
        </div>
        {hasPermission('companies', 'read') && (
          <>
            <NavItem to="/dashboard" icon={<DashIcon />}>Dashboard</NavItem>
            <NavItem to="/registry" icon={<RegistryIcon />}>Company Registry</NavItem>
          </>
        )}
        {hasPermission('persons', 'read') && (
          <NavItem to="/persons" icon={<PersonsIcon />}>Persons Registry</NavItem>
        )}

        {isSuperAdmin && (
          <>
            <div style={{ height: 1, background: 'var(--border)', margin: '8px 0' }} />
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--t-muted)', padding: '10px 8px 4px' }}>
              Admin
            </div>
            <NavItem to="/users" icon={<UsersIcon />}>User Management</NavItem>
            <NavItem to="/roles" icon={<RolesIcon />}>Roles</NavItem>
            {hasPermission('audit_trail', 'read') && (
              <NavItem to="/audit-log" icon={<AuditIcon />}>Audit Log</NavItem>
            )}
          </>
        )}

        <div style={{ height: 1, background: 'var(--border)', margin: '8px 0' }} />
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.12em', textTransform: 'uppercase', color: 'var(--t-muted)', padding: '10px 8px 4px' }}>
          System
        </div>
        <button
          onClick={handleSignOut}
          style={{
            display: 'flex', alignItems: 'center', gap: 9,
            padding: '8px 10px', borderRadius: 6, width: '100%',
            color: 'var(--t-muted)', fontSize: 13, fontWeight: 500,
            background: 'none', border: 'none', cursor: 'pointer', transition: '.15s',
          }}
        >
          <SignOutIcon /> Sign Out
        </button>
      </div>
    </nav>
  )
}
