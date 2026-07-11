import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AuditLogPage from './AuditLogPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn() } }))
import { api } from '../lib/api.js'

const PAYLOAD = {
  total: 226351,
  page: 1,
  page_size: 100,
  entries: [
    {
      // imported Viewpoint row — action_type is a useless placeholder
      id: 'l1', created_at: '2026-06-18T12:07:00Z',
      action_type: 'LEGACY_VP_EVENT', source: 'viewpoint_import',
      event_code: 'OFA', created_by: 'JAC', user_display_name: 'JAC', case_id: 'e1',
      // denormalized by migration 012 — generic action + company name
      action_label: 'Statutory Officer (Director/Secretary) Appointment',
      company_name: 'iTutors Limited',
      new_value: 'Get Started HK Limited (company_secretary)',
      metadata: { description: 'Get Started HK Limited Appointed as Secretary' },
    },
    {
      // imported STATUS row — no description, but carries descr + new_value
      id: 'l2', created_at: '2026-06-18T12:07:00Z',
      action_type: 'LEGACY_VP_EVENT', source: 'viewpoint_import',
      event_code: 'STATUS', created_by: 'LEEANN', user_display_name: 'LEEANN',
      source_keycode: '1450PO', action_label: 'Status Changed',
      old_value: '', new_value: 'NC',
      metadata: { descr: 'Not Yet Classified' },
    },
    {
      // native G-FlowDesk field edit
      id: 'n1', created_at: '2026-07-11T09:00:00Z',
      action_type: 'CASE_FIELD_UPDATED', source: 'g_flowdesk',
      event_code: 'ADC', action_label: 'Change Master File Details',
      user_display_name: 'Levi Z.', case_id: 'e2',
      company_name: 'Harbour Tech',
      before_state: { field: 'company_name', old: 'Old Co' },
      after_state: { field: 'company_name', new: 'New Co' },
      metadata: null,
    },
  ],
}

const renderPage = () => render(<MemoryRouter><AuditLogPage /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(PAYLOAD)
})

describe('AuditLogPage', () => {
  it('shows the GENERIC action, never the placeholder or the per-record description', async () => {
    renderPage()
    await screen.findByText('Statutory Officer (Director/Secretary) Appointment')
    expect(screen.queryByText('LEGACY_VP_EVENT')).not.toBeInTheDocument()
    // the per-record description must NOT be the action — it can't be grouped
    expect(screen.queryByText('Get Started HK Limited Appointed as Secretary')).not.toBeInTheDocument()
    expect(screen.getByText('OFA')).toBeInTheDocument()
  })

  it('sorts server-side from the column headers', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    await user.click(screen.getByRole('columnheader', { name: /Company \/ Case/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=company_name'))).toBe(true)
    })
  })

  it('resolves the case to a company name and links to it', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('iTutors Limited'))
    expect(navigate).toHaveBeenCalledWith('/companies/e1')
  })

  it('falls back to the Viewpoint key when no company resolves', async () => {
    renderPage()
    await screen.findByText('1450PO')
    expect(screen.getByText('1450PO')).toBeInTheDocument()
  })

  it('shows what changed for a native field edit', async () => {
    renderPage()
    await screen.findByText('Change Master File Details')
    const row = screen.getByText('Harbour Tech').closest('tr')
    expect(within(row).getByText('Old Co')).toBeInTheDocument()
    expect(within(row).getByText('New Co')).toBeInTheDocument()
  })

  it('renders a STATUS row change', async () => {
    renderPage()
    await screen.findByText('Status Changed')
    const row = screen.getByText('1450PO').closest('tr')
    expect(within(row).getByText('NC')).toBeInTheDocument()
  })

  it('shows the acting user, falling back to the Viewpoint actor', async () => {
    renderPage()
    await screen.findByText('iTutors Limited')
    expect(screen.getByText('Levi Z.')).toBeInTheDocument()
    expect(screen.getByText('JAC')).toBeInTheDocument()
  })

  it('filters to native G-FlowDesk events', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    await user.click(screen.getByRole('tab', { name: 'G-FlowDesk' }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('source=g_flowdesk'))).toBe(true)
    })
  })

  it('debounces search to the server', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('iTutors Limited')
    await user.type(screen.getByLabelText('Search company, action, event code or user'), 'secretary')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('search=secretary'))).toBe(true)
    }, { timeout: 2000 })
  })

  it('renders an error state', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load audit log: boom/)).toBeInTheDocument()
  })
})
