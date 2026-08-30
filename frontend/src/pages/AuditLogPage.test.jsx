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

// Same race as the dashboard (UAT W-8). This page pages through 226k rows, so
// a slow response landing after a newer one is more likely here, not less.
describe('AuditLogPage — overlapping requests (UAT W-8)', () => {
  function deferred() {
    let resolve, reject
    const promise = new Promise((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
  }

  async function toggleTo(tabName) {
    const user = userEvent.setup()
    const first = deferred()
    const second = deferred()
    api.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    renderPage()
    await user.click(screen.getByRole('tab', { name: tabName }))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    return { first, second }
  }

  it('does not report a failure from a request the user has already moved past', async () => {
    const { first, second } = await toggleTo(/G-FlowDesk/)
    first.reject(new Error('boom'))
    second.resolve(PAYLOAD)
    await waitFor(() => expect(screen.queryByText('Loading…')).not.toBeInTheDocument())
    expect(screen.queryByText(/Failed to load audit log/)).not.toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    await toggleTo(/G-FlowDesk/)
    const signal = api.get.mock.calls[0][1]?.signal
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(signal.aborted).toBe(true)
    expect(api.get.mock.calls[1][1].signal.aborted).toBe(false)
  })

  it('aborts the in-flight request when the page unmounts', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    const { unmount } = renderPage()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    const { signal } = api.get.mock.calls[0][1]
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})
