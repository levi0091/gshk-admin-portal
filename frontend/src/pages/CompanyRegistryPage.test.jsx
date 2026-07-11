import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CompanyRegistryPage from './CompanyRegistryPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn() } }))
import { api } from '../lib/api.js'

const PAYLOAD = {
  total: 3,
  page: 1,
  page_size: 50,
  flag_counts: { all: 5982, client: 5914, corporate_party: 279, non_client: 68 },
  companies: [
    {
      id: 'e1', company_name: 'Harbour Tech Ltd.', br_number: '2100028',
      cr_number: '2100028', is_client: true, is_corporate_party: false, status: 'live',
    },
    {
      id: 'e2', company_name: 'Get Started HK Limited', br_number: '63912808',
      cr_number: '2882908', is_client: true, is_corporate_party: true, status: 'live',
    },
    {
      id: 'e3', company_name: 'Asia BC Ltd.', br_number: null,
      cr_number: null, is_client: false, is_corporate_party: true, status: 'live',
    },
  ],
}

function renderPage() {
  return render(<MemoryRouter><CompanyRegistryPage /></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(PAYLOAD)
})

describe('CompanyRegistryPage', () => {
  it('shows a loading state before data arrives', () => {
    api.get.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('lists all companies with BRN and CR number', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    const table = within(screen.getByRole('table'))
    expect(table.getByText('63912808')).toBeInTheDocument()
    expect(table.getByText('2882908')).toBeInTheDocument()
    // corporate-party-only row has no BRN/CR
    expect(table.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })

  it('renders Is Client / Is Corporate Party badges, including both on one row', async () => {
    renderPage()
    const bothRow = (await screen.findByText('Get Started HK Limited')).closest('tr')
    expect(within(bothRow).getByText('Client')).toBeInTheDocument()
    expect(within(bothRow).getByText('Corporate Party')).toBeInTheDocument()

    const corpOnly = screen.getByText('Asia BC Ltd.').closest('tr')
    expect(within(corpOnly).getByText('Corporate Party')).toBeInTheDocument()
    expect(within(corpOnly).queryByText('Client')).not.toBeInTheDocument()
  })

  it('shows flag counts on the filter tabs', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    expect(screen.getByRole('tab', { name: /All/ })).toHaveTextContent('5982')
    expect(screen.getByRole('tab', { name: /Corporate Parties/ })).toHaveTextContent('279')
    expect(screen.getByRole('tab', { name: /Non-client/ })).toHaveTextContent('68')
  })

  it('filters by flag when a tab is clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('tab', { name: /Corporate Parties/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('flag=corporate_party'))).toBe(true)
    })
  })

  it('does not request the dashboard scope (registry shows all companies)', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    expect(api.get.mock.calls[0][0]).not.toContain('scope=dashboard')
  })

  it('debounces search and sends it to the server', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.type(screen.getByLabelText('Search company, BRN or CR number'), 'asia')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('search=asia'))).toBe(true)
    }, { timeout: 2000 })
  })

  it('navigates to the company profile when a row is clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('Asia BC Ltd.'))
    expect(navigate).toHaveBeenCalledWith('/companies/e3')
  })

  it('renders an empty state when nothing matches', async () => {
    api.get.mockResolvedValue({ ...PAYLOAD, companies: [], total: 0 })
    renderPage()
    expect(await screen.findByText('No companies match this view.')).toBeInTheDocument()
  })

  it('renders an error state when the request fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load company registry: boom/)).toBeInTheDocument()
  })
})
