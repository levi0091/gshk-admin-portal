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

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
import { api } from '../lib/api.js'

// The dashboard gates "+ Open Case" on nar1:write, so it needs an identity.
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

/**
 * The workflow badge as the backend ACTUALLY sends it — a composite object,
 * not a code (nar1_case_status.badge_from_row).
 *
 * These fixtures used a bare string, which is how a render crash reached DEV
 * with 318 tests green: the mock encoded my assumption instead of the contract,
 * and React error #31 ("Objects are not valid as a React child") only fires on
 * the real shape. Keep this in step with badge_from_row/derive.
 */
const badge = (code, label, extra = {}) => ({
  code, label, off_portal: false, overdue: false, ...extra,
})

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
      case_status: 'live', filing_stage: 'draft',
      workflow_status: badge('data_verification', 'Data Verification'),
      days_to_anniversary: -12, created_at: '2023-08-01', updated_at: '2026-06-26',
      created_by: 'u1', created_by_name: 'Levi Z.',
    },
    {
      id: 'c2', case_no: 'NAR-2026-0028', entity_id: 'e1',
      company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
      case_status: 'live', filing_stage: null,
      workflow_status: badge('data_verification', 'Data Verification'),
      days_to_anniversary: 47, created_at: '2023-08-01', updated_at: '2026-06-26',
      created_by: 'u2', created_by_name: 'Brian Yiu',
    },
    {
      id: 'c3', case_no: 'NAR-2026-0031', entity_id: 'e2',
      company_name: 'Skyline Capital', br_number: '2100031', case_type: 'NAR1',
      case_status: 'live', filing_stage: 'validated',
      workflow_status: badge('awaiting_client', 'Awaiting Client'),
      days_to_anniversary: 34, created_at: '2024-05-02', updated_at: '2026-06-25',
      // Opened before migration 021 added the column.
      created_by: null, created_by_name: null,
    },
  ],
}

function renderPage() {
  return render(<MemoryRouter><DashboardPage /></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(PAYLOAD)
  // The dashboard opens on the signed-in user's own cases, so it needs an id
  // as well as permissions. `profileLoading: false` is the settled state.
  auth = {
    hasPermission: () => true, isSuperAdmin: true,
    profile: { id: 'u-1', display_name: 'Levi Z.' }, profileLoading: false,
  }
})

/** The query string as it reads before URL-encoding, for legible assertions. */
const urls = () => api.get.mock.calls.map(c => decodeURIComponent(c[0]))

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

  it('shows ONLY the workflow status in the Workflow column', async () => {
    // Levi 2026-08-30. The CR form status used to stack under the workflow
    // status in this cell; it now lives on the case detail only. The fixtures
    // still carry filing_stage 'draft' and 'validated', so if FormBadge ever
    // comes back to this table these assertions fail rather than pass quietly.
    renderPage()
    await screen.findByText('NAR-2025-0028')
    const table = within(screen.getByRole('table'))
    expect(table.getAllByText('Data Verification').length).toBeGreaterThan(0)
    expect(table.queryByText('Not yet sent to CR')).not.toBeInTheDocument()
    expect(table.queryByText('Validated by CR')).not.toBeInTheDocument()
  })

  it('counts the two stat tiles from the per-status counts', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    // Action Required = the five statuses whose next move is ours (2 here).
    expect(screen.getByText('Action Required').parentElement).toHaveTextContent('2')
    // Pending = awaiting_client (1).
    expect(screen.getByText('Pending').parentElement).toHaveTextContent('1')
  })

  it('opens on the signed-in user\'s own cases', async () => {
    // A dashboard of 30 cases, most of them somebody else's, is not a to-do
    // list. Server-side, because the page holds 50 rows of a longer set.
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(urls()[0]).toContain('filter=created_by:eq:u-1')
  })

  it('says so, in a chip that drops the default in one click', async () => {
    // A default that hides rows without naming itself cannot be told apart
    // from a table that is simply missing data.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('button', { name: 'Remove the Created By filter' }))
    await waitFor(() => {
      expect(urls().some(u => !u.includes('created_by'))).toBe(true)
    })
  })

  it('shows everyone\'s cases rather than hanging when there is no identity', async () => {
    // /auth/me can fail. An unfiltered dashboard is a worse default but a
    // working screen; waiting forever for an id that is not coming is not.
    auth = { ...auth, profile: null }
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(urls()[0]).not.toContain('created_by')
  })

  it('has no workflow-status tab row — those badges are one form\'s process', async () => {
    // This dashboard is meant to hold every post-incorporation form. A
    // permanent row of NAR1's seven statuses stops being true the moment a
    // second form arrives, so they live on the Workflow column instead.
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(screen.queryByRole('tab', { name: /Data Verification/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Awaiting Client/ })).not.toBeInTheDocument()
  })

  it('filters by workflow status through the Workflow column', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('button', { name: /^Filter Workflow/ }))
    await user.click(screen.getByRole('checkbox', { name: /Awaiting Client/ }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('workflow_status=awaiting_client'))).toBe(true)
    })
  })

  it('keeps the per-badge counts the removed tab row used to carry', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('button', { name: /^Filter Workflow/ }))
    const panel = within(screen.getByRole('dialog', { name: 'Filter Workflow' }))
    expect(panel.getByText('Data Verification').parentElement).toHaveTextContent('2')
    expect(panel.getByText('Awaiting Client').parentElement).toHaveTextContent('1')
  })

  it('filters to the work that is ours when Action Required is clicked', async () => {
    // The tile IS the filter for its own set, so the number on it and the rows
    // beneath it can never disagree.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('button', { name: /Action Required/ }))
    await waitFor(() => {
      expect(urls().some(u => u.includes(
        'workflow_status=data_verification,client_verification,client_rejected,signing,submission'
      ))).toBe(true)
    })
  })

  it('filters to the client\'s move when Pending is clicked, and clears on a second click', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    const tile = screen.getByRole('button', { name: /Pending/ })
    await user.click(tile)
    await waitFor(() => {
      expect(urls().some(u => u.includes('workflow_status=awaiting_client'))).toBe(true)
    })
    expect(tile).toHaveAttribute('aria-pressed', 'true')
    await user.click(tile)
    await waitFor(() => expect(tile).toHaveAttribute('aria-pressed', 'false'))
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
      // Writes the same Days-to-anniversary filter the column header does, so
      // it shows up as a chip and lights that column's funnel.
      expect(urls().some(u => u.includes('filter=days_to_anniversary:lte:0'))).toBe(true)
    })
    expect(screen.getByRole('button', { name: 'Remove the Days to anniversary filter' }))
      .toBeInTheDocument()
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

  it('shows who opened each case', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(screen.getByText('Levi Z.')).toBeInTheDocument()
    expect(screen.getByText('Brian Yiu')).toBeInTheDocument()
  })

  it('shows an em dash, not the reader, for a case with no recorded author', async () => {
    // Cases opened before migration 021 added the column carry no author.
    // Falling back to the current user would be a lie about who opened it.
    renderPage()
    const row = (await screen.findByText('NAR-2026-0031')).closest('tr')
    expect(within(row).getByText('—')).toBeInTheDocument()
  })

  it('sorts by the author\'s name, not by their uuid', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('columnheader', { name: /Created By/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=created_by_name')))
        .toBe(true)
    })
    expect(api.get.mock.calls.some(c => /sort=created_by(&|$)/.test(c[0]))).toBe(false)
  })

  it('does not offer a phase toggle on a screen that only lists one phase', async () => {
    // "All cases / Post-incorporation / Pre-incorporation" sat above a table
    // that has only ever held post-incorporation cases; picking either of the
    // other two selected an empty table with an apology in it.
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(screen.queryByRole('tab', { name: 'Pre-incorporation' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'All cases' })).not.toBeInTheDocument()
  })

  it('filters a column the header offers, server-side', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2025-0028')
    await user.click(screen.getByRole('button', { name: /^Filter Company Name/ }))
    await user.type(screen.getByLabelText('Company Name value'), 'harbour')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=company_name:contains:harbour'))).toBe(true)
    })
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

  /** Fire a second request over the first — now through the Pending tile,
   *  which is what the removed "Awaiting Client" tab used to do. */
  async function toggleTo() {
    const user = userEvent.setup()
    const first = deferred()
    const second = deferred()
    api.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    renderPage()
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))
    await user.click(screen.getByRole('button', { name: /Pending/ }))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    return { first, second }
  }

  it('does not report a failure from a request the user has already moved past', async () => {
    const { first, second } = await toggleTo()

    first.reject(new Error('boom'))     // superseded request fails, late
    second.resolve(PAYLOAD)             // the one the user is waiting for

    await screen.findByText('NAR-2025-0028')
    expect(screen.queryByText(/Failed to load cases/)).not.toBeInTheDocument()
  })

  it('ignores a slow response that arrives after a newer one', async () => {
    const { first, second } = await toggleTo()

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
    const { first } = await toggleTo()

    first.resolve(PAYLOAD)              // stale; the current request is still out
    // Drain the microtask queue so the stale .then/.finally definitely runs.
    // waitFor would pass on its first tick, before those callbacks fire, and
    // assert nothing.
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    await toggleTo()

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

// The dashboard lists CASES, so its primary action opens one. "+ Add Company"
// belonged to the Company Registry and left no way to start the work this
// screen exists for.
describe('DashboardPage — the primary action opens a case', () => {
  it('offers "Open Case", not "Add Company"', async () => {
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(screen.getByRole('button', { name: /Open Case/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add Company/ })).not.toBeInTheDocument()
  })

  it('hides it from a role that may only READ nar1 cases', async () => {
    // read shows the cases; write is what opens and drives one.
    auth = { isSuperAdmin: false, hasPermission: (m, p) => `${m}:${p}` === 'nar1:read' }
    renderPage()
    await screen.findByText('NAR-2025-0028')
    expect(screen.queryByRole('button', { name: /Open Case/ })).not.toBeInTheDocument()
  })
})
