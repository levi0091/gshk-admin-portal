import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import SettingsPage from './SettingsPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

const signOut = vi.fn()
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const renderPage = () => render(<MemoryRouter><SettingsPage /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  auth = {
    profile: { display_name: 'Levi Z.', role_name: 'super_admin', permissions: [] },
    // /auth/me omits the email — it comes off the session
    session: { user: { email: 'levi@zenexflow.com' } },
    isSuperAdmin: true,
    hasPermission: () => true,
    signOut,
  }
})

describe('SettingsPage', () => {
  it('shows the signed-in account, taking the email from the session', () => {
    renderPage()
    expect(screen.getByText('Levi Z.')).toBeInTheDocument()
    expect(screen.getByText('levi@zenexflow.com')).toBeInTheDocument()
  })

  it('states that a super admin bypasses permission checks', () => {
    renderPage()
    expect(screen.getByText(/bypasses every module permission check/)).toBeInTheDocument()
  })

  it('lists the granted permissions for a non-super-admin', () => {
    auth = {
      profile: { display_name: 'Staff', email: 's@x.com', role_name: 'nar1_write',
                 permissions: ['nar1_data:read', 'nar1_data:write'] },
      isSuperAdmin: false,
      hasPermission: () => false,
      signOut,
    }
    renderPage()
    expect(screen.getByText('nar1_data:read')).toBeInTheDocument()
    expect(screen.getByText('nar1_data:write')).toBeInTheDocument()
    // no admin tools for a role without them
    expect(screen.queryByText('User Management')).not.toBeInTheDocument()
  })

  it('says so when a role has no permissions at all', () => {
    auth = {
      profile: { display_name: 'New', email: 'n@x.com', role_name: 'none', permissions: [] },
      isSuperAdmin: false, hasPermission: () => false, signOut,
    }
    renderPage()
    expect(screen.getByText(/No module permissions granted/)).toBeInTheDocument()
  })

  it('links to the admin tools and signs out', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getAllByRole('button', { name: 'Open →' })[0])
    expect(navigate).toHaveBeenCalledWith('/users')

    await user.click(screen.getByRole('button', { name: 'Log Out' }))
    expect(signOut).toHaveBeenCalled()
  })
})
