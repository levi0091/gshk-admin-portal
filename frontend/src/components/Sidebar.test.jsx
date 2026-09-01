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
