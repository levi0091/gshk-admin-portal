import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import Sidebar from './Sidebar.jsx'

/**
 * Brian's B1: the two registries are renamed to NAR1's own vocabulary.
 *
 * The ROUTES do not move. `/registry` and `/persons` are in people's
 * bookmarks and browser history, and a rename is not a reason to break them.
 */
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

beforeEach(() => {
  auth = { isSuperAdmin: true, hasPermission: () => true, signOut: vi.fn() }
})

const renderSidebar = () =>
  render(<MemoryRouter><Sidebar /></MemoryRouter>)

describe('Sidebar', () => {
  it('names the company registry as CR does', () => {
    renderSidebar()

    const link = screen.getByRole('link', { name: /Body Corporate Registry/ })
    expect(link).toHaveAttribute('href', '/registry')
    expect(screen.queryByText('Company Registry')).not.toBeInTheDocument()
  })

  it('names the persons registry as CR does', () => {
    renderSidebar()

    const link = screen.getByRole('link', { name: /Natural Person Registry/ })
    expect(link).toHaveAttribute('href', '/persons')
    expect(screen.queryByText('Persons Registry')).not.toBeInTheDocument()
  })

  it('still hides each registry from a role that cannot read it', () => {
    auth = {
      isSuperAdmin: false,
      hasPermission: (m) => m === 'companies',
      signOut: vi.fn(),
    }
    renderSidebar()

    expect(screen.getByText('Body Corporate Registry')).toBeInTheDocument()
    expect(screen.queryByText('Natural Person Registry')).not.toBeInTheDocument()
  })
})

/**
 * The menu and the landing are drawn from ONE list now (lib/navigation.js).
 * They used to be separate opinions, and that is how they came to disagree:
 * this was gated and `/` was not.
 */
describe('Sidebar — what the tester role sees', () => {
  const holding = (...perms) => (module, permission) =>
    perms.includes(`${module}:${permission}`)

  it('shows both registries and no Post-incorporation', () => {
    auth = {
      isSuperAdmin: false, signOut: vi.fn(),
      hasPermission: holding('companies:read', 'persons:read', 'persons:write'),
    }
    renderSidebar()

    expect(screen.getByRole('link', { name: /Body Corporate Registry/ }))
      .toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Natural Person Registry/ }))
      .toBeInTheDocument()
    expect(screen.queryByText('Post-incorporation')).not.toBeInTheDocument()
  })

  it('shows the Audit Log to a non-super-admin who holds audit_trail:read', () => {
    // `all_access` is exactly this role. The link used to be nested inside the
    // `isSuperAdmin` block, which hid the one screen that role exists to read.
    auth = {
      isSuperAdmin: false, signOut: vi.fn(),
      hasPermission: holding('audit_trail:read'),
    }
    renderSidebar()

    expect(screen.getByRole('link', { name: /Audit Log/ })).toBeInTheDocument()
    // Still not an administrator, though.
    expect(screen.queryByText('User Management')).not.toBeInTheDocument()
    expect(screen.queryByText('Roles')).not.toBeInTheDocument()
  })

  it('says so when the menu is empty because the profile failed to load', () => {
    // AN EMPTY MENU IS AMBIGUOUS. "Your role has nothing" and "we could not
    // find out what your role has" look identical, and the second is what
    // actually happened: one failed /auth/me stripped every item silently.
    auth = {
      isSuperAdmin: false, signOut: vi.fn(),
      hasPermission: () => false,
      profileError: 'Invalid token',
    }
    renderSidebar()

    expect(screen.getByText(/Menu unavailable/)).toBeInTheDocument()
  })

  it('says nothing of the sort when the role is simply empty', () => {
    auth = { isSuperAdmin: false, signOut: vi.fn(), hasPermission: () => false }
    renderSidebar()

    expect(screen.queryByText(/Menu unavailable/)).not.toBeInTheDocument()
  })
})
