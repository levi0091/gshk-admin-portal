import { act, render, screen, waitFor, within } from '@testing-library/react'
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

// UAT W-8: "If we toggle too fast on the dashboard there's a failure message."
//
// Every filter/tab/sort/page change fires a fresh GET. Nothing cancelled the
// previous one or checked whether it was still wanted, so a slow earlier
// response could land after a newer one and win — and a slow earlier FAILURE
// could paint the error banner over a view that had already loaded fine.
// That is the failure message Levi saw.
describe('DashboardPage — overlapping requests (UAT W-8)', () => {
  function deferred() {
    let resolve, reject
    const promise = new Promise((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
  }

  // Click a tab, having queued a controllable promise for each of the two
  // requests that produces: the initial load, then the tab change.
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
    const { first, second } = await toggleTo(/Pending AML/)

    first.reject(new Error('boom'))     // superseded request fails, late
    second.resolve(PAYLOAD)             // the one the user is waiting for

    await screen.findByText('Acme Ltd')
    expect(screen.queryByText(/Failed to load dashboard/)).not.toBeInTheDocument()
  })

  it('ignores a slow response that arrives after a newer one', async () => {
    const { first, second } = await toggleTo(/Pending AML/)

    second.resolve({
      ...PAYLOAD,
      companies: [{ ...PAYLOAD.companies[0], id: 'e9', company_name: 'Newer Co' }],
    })
    await screen.findByText('Newer Co')

    first.resolve(PAYLOAD)              // stale data lands last
    await waitFor(() => {
      expect(screen.getByText('Newer Co')).toBeInTheDocument()
    })
    expect(screen.queryByText('Acme Ltd')).not.toBeInTheDocument()
  })

  it('keeps showing Loading… when only the superseded request has resolved', async () => {
    const { first } = await toggleTo(/Pending AML/)

    first.resolve(PAYLOAD)              // stale; the current request is still out
    // Drain the microtask queue so the stale .then/.finally definitely runs.
    // waitFor would pass on its first tick, before those callbacks fire, and
    // assert nothing.
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    const { } = await toggleTo(/Pending AML/)

    const signal = api.get.mock.calls[0][1]?.signal
    expect(signal).toBeInstanceOf(AbortSignal)
    expect(signal.aborted).toBe(true)
    // The current request must NOT be aborted.
    expect(api.get.mock.calls[1][1].signal.aborted).toBe(false)
  })

  it('aborts the in-flight request when the page unmounts', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    const { unmount } = renderPage()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    const signal = api.get.mock.calls[0][1].signal
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})
