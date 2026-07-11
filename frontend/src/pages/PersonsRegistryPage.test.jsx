import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import PersonsRegistryPage from './PersonsRegistryPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
import { api } from '../lib/api.js'

const PAYLOAD = {
  total: 2, page: 1, page_size: 50,
  role_counts: { all: 6850, director: 6259, shareholder: 6447, secretary: 13, beneficial_owner: 3 },
  persons: [
    {
      id: 'p1', full_name: 'John Smith', nationality: 'British (BNO)',
      primary_id_type: 'hkid', primary_id_number: 'A1234567(8)',
      is_director: true, is_shareholder: true, is_secretary: false, is_beneficial_owner: false,
      updated_at: '2026-06-04',
    },
    {
      id: 'p2', full_name: 'Mei Chan', nationality: 'Singaporean',
      primary_id_type: 'passport', primary_id_number: 'EA1122334',
      is_director: false, is_shareholder: true, is_secretary: false, is_beneficial_owner: true,
      updated_at: '2026-05-22',
    },
  ],
}

const renderPage = () => render(<MemoryRouter><PersonsRegistryPage /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(PAYLOAD)
})

describe('PersonsRegistryPage', () => {
  it('shows a loading state first', () => {
    api.get.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('lists persons with identity, nationality and role tags', async () => {
    renderPage()
    await screen.findByText('John Smith')
    const table = within(screen.getByRole('table'))
    expect(table.getByText('HKID · A1234567(8)')).toBeInTheDocument()
    expect(table.getByText('British (BNO)')).toBeInTheDocument()

    const row = screen.getByText('John Smith').closest('tr')
    expect(within(row).getByText('Director')).toBeInTheDocument()
    expect(within(row).getByText('Shareholder')).toBeInTheDocument()
    expect(within(row).queryByText('Secretary')).not.toBeInTheDocument()
  })

  it('shows distinct-person role counts on the tabs', async () => {
    renderPage()
    await screen.findByText('John Smith')
    expect(screen.getByRole('tab', { name: /All/ })).toHaveTextContent('6850')
    expect(screen.getByRole('tab', { name: /Directors/ })).toHaveTextContent('6259')
    expect(screen.getByRole('tab', { name: /Secretaries/ })).toHaveTextContent('13')
  })

  it('filters by role when a tab is clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.click(screen.getByRole('tab', { name: /Directors/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('role=director'))).toBe(true)
    })
  })

  it('debounces search to the server', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.type(screen.getByLabelText('Search name, email or ID number'), 'chan')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('search=chan'))).toBe(true)
    }, { timeout: 2000 })
  })

  it('navigates to the person profile on row click', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('Mei Chan'))
    expect(navigate).toHaveBeenCalledWith('/persons/p2')
  })

  it('renders empty and error states', async () => {
    api.get.mockResolvedValue({ ...PAYLOAD, persons: [], total: 0 })
    renderPage()
    expect(await screen.findByText('No persons match this view.')).toBeInTheDocument()

    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load persons: boom/)).toBeInTheDocument()
  })
})
