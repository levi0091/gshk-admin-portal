import { Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import Sidebar from './Sidebar.jsx'

function initials(name) {
  return name?.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?'
}

export default function AppShell() {
  const { profile } = useAuth()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Header */}
      <header style={{
        height: 60, background: 'var(--indigo)',
        display: 'flex', alignItems: 'center', padding: '0 20px', gap: 16,
        flexShrink: 0, borderBottom: '1px solid rgba(255,255,255,.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <svg width="34" height="34" viewBox="0 0 44 44" xmlns="http://www.w3.org/2000/svg">
            <path d="M38 11 A20 20 0 1 0 38 33" fill="none" stroke="white" strokeWidth="7" strokeLinecap="round"/>
            <rect x="31" y="19" width="14" height="7" rx="3.5" fill="white"/>
            <circle cx="40" cy="22.5" r="2.5" fill="#242C66"/>
          </svg>
          <div>
            <div style={{ fontSize: 19, fontWeight: 900, display: 'flex', alignItems: 'baseline', lineHeight: 1 }}>
              <span style={{ color: 'var(--carrot)' }}>G</span>
              <span style={{ color: '#fff' }}>SHK</span>
            </div>
            <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: '.18em', color: 'rgba(243,108,50,.85)', textTransform: 'uppercase', marginTop: 2 }}>
              Get Started HK
            </div>
          </div>
        </div>
        <div style={{ width: 1, height: 28, background: 'rgba(255,255,255,.15)' }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,.8)', letterSpacing: '.04em' }}>G-FlowDesk</span>
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(255,255,255,.10)', borderRadius: 20, padding: '3px 12px 3px 3px', cursor: 'pointer' }}>
          <div style={{ width: 26, height: 26, borderRadius: '50%', background: 'var(--carrot)', color: '#fff', fontWeight: 800, fontSize: 11, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {initials(profile?.display_name)}
          </div>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,.9)' }}>
            {profile?.display_name}
          </span>
        </div>
      </header>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar />
        <main style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-page)', padding: 28 }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
