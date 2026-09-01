import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

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
      id: 'e1', company_name: 'Harbour Tech Ltd.', company_name_zh: '海港科技有限公司',
      br_number: '2100028',
      cr_number: '2100028', is_client: true, is_corporate_party: false, status: 'live',
      incorporation_date: '2023-08-12',   // 3 days past anniversary — inside the window
    },
    {
      id: 'e2', company_name: 'Get Started HK Limited', br_number: '63912808',
      cr_number: '2882908', is_client: true, is_corporate_party: true, status: 'live',
      incorporation_date: '2018-09-18',   // 34 days ahead
    },
    {
      id: 'e3', company_name: 'Asia BC Ltd.', company_name_zh: null, br_number: null,
      cr_number: null, is_client: false, is_corporate_party: true, status: 'live',
      incorporation_date: null,           // Viewpoint row with no incorporation date
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
  it('shows the Chinese name as its own column', async () => {
    // Brian's B2 — "where do we show the Chinese Name?". It was already on the
    // profile; what was missing was any way to find a company by it in a list.
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')

    expect(screen.getByRole('columnheader', { name: /Chinese Name/ })).toBeInTheDocument()
    expect(screen.getByText('海港科技有限公司')).toBeInTheDocument()
  })

  it('leaves the Chinese name blank rather than repeating the English one', async () => {
    // 'Asia BC Ltd.' has none, and 5,930 Viewpoint companies are in the same
    // state. An em dash says "not recorded"; the English name would be a lie.
    renderPage()
    const row = (await screen.findByText('Asia BC Ltd.')).closest('tr')
    const cell = row.querySelector('[data-label="Chinese Name"]')

    expect(cell).toHaveTextContent('—')
    expect(cell).not.toHaveTextContent('Asia BC')
  })

  it('names the page as CR does', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')

    expect(screen.getByText('Body Corporate Registry')).toBeInTheDocument()
  })

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

describe('CompanyRegistryPage — days to anniversary (UAT F-6)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-15T09:00:00'))
  })
  afterEach(() => vi.useRealTimers())

  it('adds a Days to anniversary column', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    expect(screen.getByRole('columnheader', { name: /Days to anniversary/ })).toBeInTheDocument()
  })

  it('counts down to an anniversary that is still ahead', async () => {
    renderPage()
    const row = (await screen.findByText('Get Started HK Limited')).closest('tr')
    expect(within(row).getByText('in 34 days')).toBeInTheDocument()
  })

  it('highlights a company inside the 42-day filing window', async () => {
    renderPage()
    const row = (await screen.findByText('Harbour Tech Ltd.')).closest('tr')
    const cell = within(row).getByText('3 days ago')
    expect(cell).toBeInTheDocument()
    expect(cell).toHaveClass('td-anniv-due')
  })

  it('does not highlight a company whose anniversary is still ahead', async () => {
    renderPage()
    const row = (await screen.findByText('Get Started HK Limited')).closest('tr')
    expect(within(row).getByText('in 34 days')).not.toHaveClass('td-anniv-due')
  })

  it('shows an em dash for a company with no incorporation date', async () => {
    renderPage()
    const row = (await screen.findByText('Asia BC Ltd.')).closest('tr')
    expect(within(row).getByLabelText('Days to anniversary')).toHaveTextContent('—')
  })

  // The server now computes the same signed number (migration 019). Rendering
  // the server's value is what keeps the text and the sort order in agreement.
  it('prefers the day count the server computed', async () => {
    api.get.mockResolvedValue({
      ...PAYLOAD,
      companies: [{ ...PAYLOAD.companies[0], incorporation_date: '2023-08-12',
                    days_to_anniversary: -3 }],
    })
    renderPage()
    const row = (await screen.findByText('Harbour Tech Ltd.')).closest('tr')
    expect(within(row).getByText('3 days ago')).toBeInTheDocument()
  })

  it('falls back to computing locally when the server omits it', async () => {
    renderPage()   // PAYLOAD carries no days_to_anniversary
    const row = (await screen.findByText('Get Started HK Limited')).closest('tr')
    expect(within(row).getByText('in 34 days')).toBeInTheDocument()
  })

  it('renders an em dash when the server says null', async () => {
    api.get.mockResolvedValue({
      ...PAYLOAD,
      companies: [{ ...PAYLOAD.companies[0], days_to_anniversary: null }],
    })
    renderPage()
    const row = (await screen.findByText('Harbour Tech Ltd.')).closest('tr')
    expect(within(row).getByLabelText('Days to anniversary')).toHaveTextContent('—')
  })
})

describe('CompanyRegistryPage — anniversary sort & filter (R3)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-15T09:00:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('opens on the actionable set — 60 days or fewer', async () => {
    renderPage()
    await waitFor(() => {
      expect(api.get.mock.calls[0][0]).toContain('anniv_op=lte')
      expect(api.get.mock.calls[0][0]).toContain('anniv_days=60')
    })
  })

  it('asks the server to sort, never the visible page', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    // SortableTh renders a clickable <th>, not a <button>.
    await user.click(screen.getByRole('columnheader', { name: /Days to anniversary/ }))
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('sort=days_to_anniversary'))).toBe(true)
    })
  })

  it('marks the column as sorted for assistive tech', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    const th = screen.getByRole('columnheader', { name: /Days to anniversary/ })
    expect(th).toHaveAttribute('aria-sort', 'none')
    await user.click(th)
    await waitFor(() => expect(
      screen.getByRole('columnheader', { name: /Days to anniversary/ })
    ).toHaveAttribute('aria-sort', 'ascending'))
  })

  it('sends the chosen comparison and day count', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.selectOptions(screen.getByLabelText('Comparison'), 'gte')
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('anniv_op=gte'))).toBe(true)
    })
  })

  it('clearing the filter drops both parameters', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => {
      const last = api.get.mock.calls[api.get.mock.calls.length - 1][0]
      expect(last).not.toContain('anniv_op')
      expect(last).not.toContain('anniv_days')
    })
  })

  it('never sends one half of the pair', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.clear(screen.getByLabelText('Day count'))
    await waitFor(() => {
      const last = api.get.mock.calls[api.get.mock.calls.length - 1][0]
      expect(last.includes('anniv_op')).toBe(last.includes('anniv_days'))
    })
  })

  it('explains that a passed anniversary counts negative', async () => {
    renderPage()
    expect(screen.getByText(/negative/i)).toBeInTheDocument()
  })
})

// Same race as the dashboard (UAT W-8). Not reported here, but this page has
// MORE ways to fire overlapping requests than the dashboard does — four flag
// tabs, six sortable columns, a search box and the anniversary comparison and
// day-count inputs. Fixing one and not the other would just move the bug.
describe('CompanyRegistryPage — overlapping requests (UAT W-8)', () => {
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
    const { first, second } = await toggleTo(/Corporate Parties/)

    first.reject(new Error('boom'))
    second.resolve(PAYLOAD)

    await screen.findByText('Harbour Tech Ltd.')
    expect(screen.queryByText(/Failed to load company registry/)).not.toBeInTheDocument()
  })

  it('ignores a slow response that arrives after a newer one', async () => {
    const { first, second } = await toggleTo(/Corporate Parties/)

    second.resolve({
      ...PAYLOAD,
      companies: [{ ...PAYLOAD.companies[0], id: 'e9', company_name: 'Newer Co' }],
    })
    await screen.findByText('Newer Co')

    first.resolve(PAYLOAD)
    await waitFor(() => expect(screen.getByText('Newer Co')).toBeInTheDocument())
    expect(screen.queryByText('Harbour Tech Ltd.')).not.toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    await toggleTo(/Corporate Parties/)

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
