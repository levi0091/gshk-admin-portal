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
      {/* Header */}
      <header
        className="app-hdr-pad"
        style={{
          height: 60, background: 'var(--indigo)',
          display: 'flex', alignItems: 'center', padding: '0 20px', gap: 16,
          flexShrink: 0, borderBottom: '1px solid rgba(255,255,255,.08)',
        }}
      >
        {/* Hamburger — left side on mobile so it's next to the sidebar it controls */}
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

        {/* GSHK logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          <div style={{
            background: '#fff', borderRadius: 6, padding: 3,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 34, height: 34, flexShrink: 0,
          }}>
            <img src="/gshk-icon.png" style={{ width: 28, height: 28, objectFit: 'contain' }} alt="GSHK" />
          </div>
          <div style={{ lineHeight: 1 }}>
            <div style={{
              fontSize: 19, fontWeight: 900, letterSpacing: '-.01em',
              display: 'flex', alignItems: 'baseline',
            }}>
              <span style={{ color: 'var(--carrot)' }}>G</span>
              <span style={{ color: '#fff' }}>SHK</span>
            </div>
            <div style={{
              fontSize: 9, fontWeight: 600, letterSpacing: '.18em',
              color: 'rgba(243,108,50,.85)', textTransform: 'uppercase', marginTop: 2,
            }}>
              Get Started HK
            </div>
          </div>
        </div>

        <div style={{ width: 1, height: 28, background: 'rgba(255,255,255,.15)' }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,.8)', letterSpacing: '.04em' }}>
          G-FlowDesk
        </span>

        <div style={{ flex: 1 }} />

        {/* User chip — name hidden on mobile, avatar only */}
        <div className="hdr-chip" style={{
          display: 'flex', alignItems: 'center', gap: 8,
          background: 'rgba(255,255,255,.10)', borderRadius: 20,
          padding: '3px 12px 3px 3px', cursor: 'pointer',
        }}>
          <div style={{
            width: 26, height: 26, borderRadius: '50%',
            background: 'var(--carrot)', color: '#fff',
            fontWeight: 800, fontSize: 11,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            {initials(profile?.display_name)}
          </div>
          <span className="hdr-username" style={{ fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,.9)' }}>
            {profile?.display_name}
          </span>
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
