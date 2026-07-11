import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import DashboardPage from './DashboardPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn() } }))
import { api } from '../lib/api.js'

const PAYLOAD = {
  total: 2,
  page: 1,
  page_size: 50,
  tiles: { action_required: 3, pending: 1 },
  status_counts: { all: 2, pending_aml: 3, to_verify: 0, client_rejected: 0, pending_client: 1, submitted_to_cr: 0, cr_approved: 0 },
  companies: [
    {
      id: 'e1', vp_source_key: 'ACME01', company_name: 'Acme Ltd', br_number: '77712345',
      status: 'pending_aml', active_workflow: 'nar1', has_pending_case: true,
      created_at: '2023-08-01', updated_at: '2026-06-26', incorporation_date: '2023-08-12',
    },
    {
      id: 'e2', vp_source_key: 'HARB02', company_name: 'Harbour Tech', br_number: null,
      status: 'live', active_workflow: null, has_pending_case: false,
      created_at: '2024-05-02', updated_at: '2026-06-25', incorporation_date: null,
    },
  ],
}

function renderPage() {
  return render(<MemoryRouter><DashboardPage /></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(PAYLOAD)
})

describe('DashboardPage', () => {
  it('shows a loading state before data arrives', () => {
    api.get.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('renders the two counter tiles from the API', async () => {
    renderPage()
    await screen.findByText('Acme Ltd')
    expect(screen.getByText('Action Required').parentElement).toHaveTextContent('3')
    expect(screen.getByText('Pending').parentElement).toHaveTextContent('1')
  })

  it('renders company rows with entity id, status badge and workflow tag', async () => {
    renderPage()
    await screen.findByText('Acme Ltd')
    // Scope to the table — "Pending AML" also appears as a filter tab label.
    const table = within(screen.getByRole('table'))
    expect(table.getByText('ACME01')).toBeInTheDocument()
    expect(table.getByText('77712345')).toBeInTheDocument()
    expect(table.getByText('Pending AML')).toBeInTheDocument()
    expect(table.getByText('NAR1')).toBeInTheDocument()
    expect(table.getByText('Live')).toBeInTheDocument()
  })

  it('requests the dashboard scope with pagination', async () => {
    renderPage()
    await screen.findByText('Acme Ltd')
    const url = api.get.mock.calls[0][0]
    expect(url).toContain('scope=dashboard')
    expect(url).toContain('page=1')
    expect(url).toContain('page_size=50')
  })

  it('filters by status when a filter tab is clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Acme Ltd')
    await user.click(screen.getByRole('tab', { name: /Pending AML/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('status=pending_aml'))).toBe(true)
    })
  })

  it('debounces search and sends it to the server', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Acme Ltd')
    await user.type(screen.getByLabelText('Search Company or BRN'), 'harbour')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('search=harbour'))).toBe(true)
    }, { timeout: 2000 })
  })

  it('navigates to the company profile when a row is clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('Acme Ltd'))
    expect(navigate).toHaveBeenCalledWith('/companies/e1')
  })

  it('sorts server-side when a column header is clicked, and toggles direction', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Acme Ltd')

    await user.click(screen.getByRole('columnheader', { name: /Create Date/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=created_at&dir=asc'))).toBe(true)
    })

    // clicking the same column again flips to descending
    await user.click(screen.getByRole('columnheader', { name: /Create Date/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=created_at&dir=desc'))).toBe(true)
    })
  })

  it('renders an empty state when no companies match', async () => {
    api.get.mockResolvedValue({ ...PAYLOAD, companies: [], total: 0 })
    renderPage()
    expect(await screen.findByText('No companies match this view.')).toBeInTheDocument()
  })

  it('renders an error state when the request fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load dashboard: boom/)).toBeInTheDocument()
  })

  it('pages forward and disables Previous on page 1', async () => {
    const user = userEvent.setup()
    api.get.mockResolvedValue({ ...PAYLOAD, total: 120 })
    renderPage()
    await screen.findByText('Acme Ltd')
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('page=2'))).toBe(true)
    })
  })
})
