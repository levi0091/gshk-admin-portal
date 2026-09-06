import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import RequirePermission, { NoAccess, ReadOnlyNote } from './RequirePermission.jsx'

/**
 * The screen saying "you may not open this", instead of the API saying it.
 *
 * Every module route is reachable by typing its URL. Before this they all
 * rendered, asked for data the caller could not have, and printed whatever the
 * backend refused with — "Failed to load cases: Insufficient permissions" where
 * the table should have been. The API refusing is correct and unchanged; what
 * was missing was the screen refusing FIRST, in its own words.
 */
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const holding = (...perms) => (module, permission) =>
  perms.includes(`${module}:${permission}`)

beforeEach(() => {
  auth = {
    hasPermission: holding('companies:read', 'persons:read', 'persons:write'),
    profileLoading: false,
    profile: { display_name: 'Tester', role_name: 'tester' },
  }
})

const renderGuard = (module, permission) => render(
  <MemoryRouter>
    <RequirePermission module={module} permission={permission}>
      <div>THE SCREEN</div>
    </RequirePermission>
  </MemoryRouter>,
)

describe('RequirePermission', () => {
  it('renders the screen when the role holds the permission', () => {
    renderGuard('companies', 'read')
    expect(screen.getByText('THE SCREEN')).toBeInTheDocument()
  })

  it('refuses, and does NOT render the screen, when it does not', () => {
    // The screen must not mount at all — mounting it fires its data fetch,
    // which is the 403 this exists to pre-empt.
    renderGuard('nar1', 'read')
    expect(screen.queryByText('THE SCREEN')).not.toBeInTheDocument()
    expect(screen.getByText(/No access to this screen/)).toBeInTheDocument()
  })

  it('names the exact module and level to ask for', () => {
    // "Ask an administrator for access" makes the administrator guess too.
    renderGuard('nar1', 'read')
    expect(screen.getByText('nar1 (read)')).toBeInTheDocument()
  })

  it('offers the screens the role CAN open', () => {
    renderGuard('nar1', 'read')
    expect(screen.getByText('Body Corporate Registry')).toBeInTheDocument()
    expect(screen.getByText('Natural Person Registry')).toBeInTheDocument()
    expect(screen.queryByText('Post-incorporation')).not.toBeInTheDocument()
  })

  it('renders nothing while the profile is still loading', () => {
    // Deciding early would flash a refusal at every user on every reload —
    // `hasPermission` reads an empty list until /auth/me lands.
    auth = { ...auth, profileLoading: true }
    const { container } = renderGuard('companies', 'read')
    expect(container).toBeEmptyDOMElement()
  })

  it('names the role, so the reader knows which account they are in', () => {
    renderGuard('nar1', 'read')
    expect(screen.getByText(/\(tester\)/)).toBeInTheDocument()
  })
})

describe('NoAccess — the super-admin-only form', () => {
  it('says so without inventing a module name', () => {
    render(<MemoryRouter><NoAccess title="Super Admins only" /></MemoryRouter>)
    expect(screen.getByText('Super Admins only')).toBeInTheDocument()
    expect(screen.getByText(/restricted to Super Admins/)).toBeInTheDocument()
  })
})

describe('ReadOnlyNote', () => {
  it('says what is readable, and what the missing permission is called', () => {
    render(<ReadOnlyNote module="companies" what="this company's full profile" />)
    expect(screen.getByRole('note')).toHaveTextContent(/Read-only/)
    expect(screen.getByRole('note'))
      .toHaveTextContent("this company's full profile")
    expect(screen.getByText('companies (write)')).toBeInTheDocument()
  })
})
