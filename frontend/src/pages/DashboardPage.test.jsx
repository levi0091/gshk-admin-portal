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

// The shape GET /cases?scope=dashboard returns (nar1_cases.list_dashboard).
// Harbour Tech appears TWICE on purpose — one company, two outstanding returns.
// That is the whole reason this screen lists cases rather than companies.
const PAYLOAD = {
  total: 3,
  page: 1,
  page_size: 50,
  counts: {
    all: 3, data_verification: 2, client_verification: 0, awaiting_client: 1,
    client_rejected: 0, signing: 0, submission: 0, completed: 0,
  },
  rows: [
    {
      id: 'c1', case_no: 'NAR-2025-0028', entity_id: 'e1',
      company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
      case_status: 'live', filing_stage: 'draft', workflow_status: 'data_verification',
      days_to_anniversary: -12, created_at: '2023-08-01', updated_at: '2026-06-26',
    },
    {
      id: 'c2', case_no: 'NAR-2026-0028', entity_id: 'e1',
      company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
      case_status: 'live', filing_stage: null, workflow_status: 'data_verification',
      days_to_anniversary: 47, created_at: '2023-08-01', updated_at: '2026-06-26',
    },
    {
      id: 'c3', case_no: 'NAR-2026-0031', entity_id: 'e2',
      company_name: 'Skyline Capital', br_number: '2100031', case_type: 'NAR1',
      case_status: 'live', filing_stage: 'validated', workflow_status: 'awaiting_client',
      days_to_anniversary: 34, created_at: '2024-05-02', updated_at: '2026-06-25',
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

describe('DashboardPage — the NAR1 case dashboard (v11 s2)', () => {
  it('shows a loading state before data arrives', () => {
    api.get.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('reads cases, not companies', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(api.get.mock.calls[0][0]).toMatch(/^\/cases\?/)
  })

  it('requests the dashboard scope with pagination', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    const url = api.get.mock.calls[0][0]
    expect(url).toContain('scope=dashboard')
    expect(url).toContain('page=1')
    expect(url).toContain('page_size=50')
  })

  it('lists one row per case, so a company with two returns appears twice', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    const table = within(screen.getByRole('table'))
    expect(table.getAllByText('Harbour Tech Ltd.')).toHaveLength(2)
    expect(table.getByText('NAR-2025-0028')).toBeInTheDocument()
    expect(table.getByText('NAR-2026-0028')).toBeInTheDocument()
  })

  it('opens the CASE, not the company profile, when a row is clicked', async () => {
    // The behaviour Levi asked for by name (2026-08-15): "clicking on the record
    // should bring me directly to the case management screen and not the
    // company profile page."
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByText('NAR-2025-0028'))
    expect(navigate).toHaveBeenCalledWith('/cases/c1')
  })

  it('shows the workflow status and the CR form status as SEPARATE badges', async () => {
    // D-6: two vocabularies answering different questions. A case can be at
    // "Data Verification" with us while CR holds nothing at all — merging them
    // would lose that, in both directions.
    renderPage()
    await screen.findByText('NAR-2025-0028')
    const table = within(screen.getByRole('table'))
    expect(table.getAllByText('Data Verification').length).toBeGreaterThan(0)
    expect(table.getByText('Not yet sent to CR')).toBeInTheDocument()
    expect(table.getByText('Validated by CR')).toBeInTheDocument()
  })

  it('reads an em dash for a case with no filing yet, never a fake draft', async () => {
    renderPage()
    await screen.findByText('NAR-2026-0028')
    // c2 has filing_stage: null. "Not yet sent to CR" belongs to c1's real
    // draft filing and must not be borrowed for a case with no filing at all.
    expect(within(screen.getByRole('table')).getAllByText('Not yet sent to CR'))
      .toHaveLength(1)
  })

  it('counts the two stat tiles from the per-status counts', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    // Action Required = the five statuses whose next move is ours (2 here).
    expect(screen.getByText('Action Required').parentElement).toHaveTextContent('2')
    // Pending = awaiting_client (1).
    expect(screen.getByText('Pending').parentElement).toHaveTextContent('1')
  })

  it('filters by workflow status when a filter tab is clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('tab', { name: /Awaiting Client/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('workflow_status=awaiting_client')))
        .toBe(true)
    })
  })

  it('debounces search and sends it to the server', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.type(screen.getByLabelText('Search Company or BRN'), 'harbour')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('search=harbour'))).toBe(true)
    }, { timeout: 2000 })
  })

  it('renders a passed anniversary as overdue and a future one plainly', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    const table = within(screen.getByRole('table'))
    expect(table.getByText('12 days ago')).toBeInTheDocument()
    expect(table.getByText('in 47 days')).toBeInTheDocument()
  })

  it('warns about cases past the anniversary and can narrow to them', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(screen.getByText(/passed the NAR1 anniversary/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Review overdue' }))
    await waitFor(() => {
      // Both parameters or neither — the backend 422s on a half-supplied pair.
      const hit = api.get.mock.calls.find(c => c[0].includes('anniv_op=lte'))
      expect(hit).toBeTruthy()
      expect(hit[0]).toContain('anniv_days=0')
    })
  })

  it('does not warn when nothing has passed its anniversary', async () => {
    api.get.mockResolvedValue({
      ...PAYLOAD,
      rows: [{ ...PAYLOAD.rows[2] }],   // days_to_anniversary: 34
    })
    renderPage()
    await screen.findByText('NAR-2026-0031')
    expect(screen.queryByText(/passed the NAR1 anniversary/)).not.toBeInTheDocument()
  })

  it('sorts server-side on a whitelisted column and toggles direction', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')

    await user.click(screen.getByRole('columnheader', { name: /Days to anniversary/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=days_to_anniversary&dir=asc')))
        .toBe(true)
    })
    await user.click(screen.getByRole('columnheader', { name: /Days to anniversary/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=days_to_anniversary&dir=desc')))
        .toBe(true)
    })
  })

  it('does not offer a sort the server would reject', async () => {
    // nar1_cases._SORTABLE has no entity_id / case_type. Offering the header
    // would produce a control that 422s — a broken control, not a feature.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('columnheader', { name: 'Entity ID' }))
    await user.click(screen.getByRole('columnheader', { name: 'Case Type' }))
    expect(api.get.mock.calls.some(c => /sort=(entity_id|case_type)/.test(c[0]))).toBe(false)
  })

  it('says plainly that pre-incorporation is not built rather than showing an empty table', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('tab', { name: 'Pre-incorporation' }))
    expect(screen.getByText(/Pre-incorporation cases \(NNC1\) are not built yet/))
      .toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders an empty state when no cases match', async () => {
    api.get.mockResolvedValue({ ...PAYLOAD, rows: [], total: 0 })
    renderPage()
    expect(await screen.findByText('No cases match this view.')).toBeInTheDocument()
  })

  it('renders an error state when the request fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load cases: boom/)).toBeInTheDocument()
  })

  it('pages forward and disables Previous on page 1', async () => {
    const user = userEvent.setup()
    api.get.mockResolvedValue({ ...PAYLOAD, total: 120 })
    renderPage()
    await screen.findByText('NAR-2025-0028')
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
// That is the failure message Levi saw. Carried over from the company dashboard
// this screen replaced: the hazard belongs to the pattern, not the payload.
describe('DashboardPage — overlapping requests (UAT W-8)', () => {
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
    const { first, second } = await toggleTo(/Awaiting Client/)

    first.reject(new Error('boom'))     // superseded request fails, late
    second.resolve(PAYLOAD)             // the one the user is waiting for

    await screen.findByText('NAR-2025-0028')
    expect(screen.queryByText(/Failed to load cases/)).not.toBeInTheDocument()
  })

  it('ignores a slow response that arrives after a newer one', async () => {
    const { first, second } = await toggleTo(/Awaiting Client/)

    second.resolve({
      ...PAYLOAD,
      rows: [{ ...PAYLOAD.rows[0], id: 'c9', case_no: 'NAR-2026-9999' }],
    })
    await screen.findByText('NAR-2026-9999')

    first.resolve(PAYLOAD)              // stale data lands last
    await waitFor(() => {
      expect(screen.getByText('NAR-2026-9999')).toBeInTheDocument()
    })
    expect(screen.queryByText('NAR-2025-0028')).not.toBeInTheDocument()
  })

  it('keeps showing Loading… when only the superseded request has resolved', async () => {
    const { first } = await toggleTo(/Awaiting Client/)

    first.resolve(PAYLOAD)              // stale; the current request is still out
    // Drain the microtask queue so the stale .then/.finally definitely runs.
    // waitFor would pass on its first tick, before those callbacks fire, and
    // assert nothing.
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    await toggleTo(/Awaiting Client/)

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
