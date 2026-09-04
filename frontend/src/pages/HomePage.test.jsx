import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import HomePage from './HomePage.jsx'

/**
 * What `/` does.
 *
 * It used to be `<Navigate to="/dashboard" replace />` for every signed-in
 * user. Post-incorporation needs `nar1:read`, so the tester role — companies
 * (read), persons (read), persons (write) — was dropped onto a screen it could
 * not open, got "Failed to load cases" where the table should be, and saw
 * nothing at all under Main in the sidebar. The portal read as broken rather
 * than as restricted.
 */
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const holding = (...perms) => (module, permission) =>
  perms.includes(`${module}:${permission}`)

beforeEach(() => {
  auth = {
    hasPermission: () => true, profileLoading: false, profileError: null,
    profile: { display_name: 'Levi Z.', role_name: 'super_admin' },
  }
})

/** Renders `/` alongside stand-ins for every screen it might redirect to. */
function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/dashboard" element={<div>POST-INCORPORATION SCREEN</div>} />
        <Route path="/registry" element={<div>BODY CORPORATE SCREEN</div>} />
        <Route path="/persons" element={<div>NATURAL PERSON SCREEN</div>} />
        <Route path="/audit-log" element={<div>AUDIT LOG SCREEN</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HomePage — where a signed-in user lands', () => {
  it('still sends a full-access user to Post-incorporation', async () => {
    // The fix must not cost the people it was already working for a click.
    renderHome()
    expect(await screen.findByText('POST-INCORPORATION SCREEN')).toBeInTheDocument()
  })

  it('sends the tester role to the Body Corporate Registry instead', async () => {
    auth.hasPermission = holding('companies:read', 'persons:read', 'persons:write')
    renderHome()

    expect(await screen.findByText('BODY CORPORATE SCREEN')).toBeInTheDocument()
    expect(screen.queryByText('POST-INCORPORATION SCREEN')).not.toBeInTheDocument()
  })

  it('sends a persons-only role to the Natural Person Registry', async () => {
    auth.hasPermission = holding('persons:read')
    renderHome()
    expect(await screen.findByText('NATURAL PERSON SCREEN')).toBeInTheDocument()
  })

  it('sends an audit-only role to the Audit Log', async () => {
    auth.hasPermission = holding('audit_trail:read')
    renderHome()
    expect(await screen.findByText('AUDIT LOG SCREEN')).toBeInTheDocument()
  })

  it('renders nothing at all while the profile is still loading', () => {
    // Deciding early would redirect on an empty permission list, which reads
    // identically to a role that holds nothing.
    auth = { ...auth, profileLoading: true, hasPermission: () => false }
    const { container } = renderHome()
    expect(container).toBeEmptyDOMElement()
  })
})

describe('HomePage — a role with no modules', () => {
  beforeEach(() => {
    auth = {
      hasPermission: holding(), profileLoading: false, profileError: null,
      profile: { display_name: 'New Starter', role_name: 'tester' },
    }
  })

  it('shows a home screen rather than redirecting anywhere', () => {
    renderHome()
    expect(screen.getByText(/Welcome, New Starter/)).toBeInTheDocument()
    expect(screen.queryByText('POST-INCORPORATION SCREEN')).not.toBeInTheDocument()
  })

  it('says the account works and names who can fix it', () => {
    // "Nothing here" without a reason reads as a broken portal.
    renderHome()
    expect(screen.getByText(/Your role has no modules yet/)).toBeInTheDocument()
    expect(screen.getByText(/A Super Admin adds these under Roles/)).toBeInTheDocument()
  })

  it('offers Settings, the one screen every account may open', () => {
    renderHome()
    expect(screen.getByRole('button', { name: /Open Settings/ })).toBeInTheDocument()
  })
})

describe('HomePage — when the permissions could not be loaded', () => {
  beforeEach(() => {
    auth = {
      hasPermission: holding(), profileLoading: false,
      profileError: 'Invalid token',
      profile: null,
    }
  })

  it('does not redirect on a permission list it never got', () => {
    // A FAILED PROFILE IS NOT AN EMPTY ONE, and redirecting on one would land
    // the user somewhere chosen by a guess.
    renderHome()
    expect(screen.queryByText('POST-INCORPORATION SCREEN')).not.toBeInTheDocument()
  })

  it('distinguishes "could not load" from "you have none"', () => {
    renderHome()
    expect(screen.getByText(/could not be loaded/)).toBeInTheDocument()
    expect(screen.getByText(/Invalid token/)).toBeInTheDocument()
    expect(screen.queryByText(/Your role has no modules yet/)).not.toBeInTheDocument()
  })
})
