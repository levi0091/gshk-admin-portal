import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Sidebar from './Sidebar.jsx'

function initials(name) {
  return name?.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?'
}

export default function AppShell() {
  const { profile } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Header — white, full-colour GSHK logo (wireframe_v7). The logo is the
          PNG asset, never reconstructed in markup, and is NOT inverted. */}
      <header className="app-hdr app-hdr-pad">
        <button
          className="hamburger"
          onClick={() => setSidebarOpen(o => !o)}
          aria-label="Menu"
        >
          <svg width="18" height="14" viewBox="0 0 18 14" fill="none">
            <rect y="0" width="18" height="2" rx="1" fill="currentColor"/>
            <rect y="6" width="18" height="2" rx="1" fill="currentColor"/>
            <rect y="12" width="18" height="2" rx="1" fill="currentColor"/>
          </svg>
        </button>

        <div className="hdr-logo">
          <img src="/gshk-logo.png" alt="Get Started HK"
               style={{ height: 30, width: 'auto', objectFit: 'contain' }} />
        </div>

        <div className="hdr-vdiv" />
        <span className="hdr-app-name">G-FlowDesk</span>

        <div className="hdr-spacer" />

        {/* User chip — name hidden on mobile, avatar only */}
        <div className="user-chip hdr-chip">
          <div className="user-avatar">{initials(profile?.display_name)}</div>
          <span className="user-name hdr-username">{profile?.display_name}</span>
        </div>
      </header>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Sidebar overlay — shown on mobile when sidebar is open */}
        <div
          className={`sidebar-overlay${sidebarOpen ? ' open' : ''}`}
          onClick={() => setSidebarOpen(false)}
        />

        <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

        <main
          className="app-main"
          style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-page)', padding: 28 }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}
