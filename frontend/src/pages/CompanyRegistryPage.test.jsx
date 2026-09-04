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
// "+ Add Company" is gated on `companies:write`. Reassigned by the read-only
// test at the bottom of this file.
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))
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
  auth = {
    hasPermission: () => true, isSuperAdmin: true, profileLoading: false,
    profile: { id: 'u-1', display_name: 'Levi Z.', role_name: 'super_admin' },
  }
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
    expect(await screen.findByText('No records found')).toBeInTheDocument()
  })

  it('offers a way out when the emptiness is the default filter’s doing', async () => {
    // This screen filters itself on first paint (−42..60 days). "No records
    // found" on its own would read as "there is no data" rather than "you are
    // looking through a filter you did not set".
    const user = userEvent.setup()
    api.get.mockResolvedValue({ ...PAYLOAD, companies: [], total: 0 })
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Clear all filters' }))
    await waitFor(() => {
      const last = decodeURIComponent(api.get.mock.calls.at(-1)[0])
      expect(last).not.toContain('days_to_anniversary')
    })
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

  it('shows a company whose filing window has shut, past the old −42 floor', async () => {
    // Migration 033. Under 019 this company reported +322 and was indexed among
    // the ones with a year in hand, so clearing the filter's lower bound found
    // nothing — the number below −42 did not exist to be found.
    api.get.mockResolvedValue({
      ...PAYLOAD,
      companies: [{ ...PAYLOAD.companies[0], days_to_anniversary: -120 }],
    })
    renderPage()
    const row = (await screen.findByText('Harbour Tech Ltd.')).closest('tr')
    expect(within(row).getByText('120 days ago')).toBeInTheDocument()
  })

  it('highlights the 42-day window, and only that', async () => {
    // 2,262 of DEV's client companies sit between −43 and −182. Painting all of
    // them carrot would be an alarm about 38% of the register, for a fact that
    // is not a deadline: inside the window the return can still be filed today,
    // outside it the cell is stating a date relationship.
    api.get.mockResolvedValue({
      ...PAYLOAD,
      companies: [
        { ...PAYLOAD.companies[0], id: 'in', company_name: 'Inside Window Ltd.',
          days_to_anniversary: -42 },
        { ...PAYLOAD.companies[0], id: 'out', company_name: 'Window Shut Ltd.',
          days_to_anniversary: -43 },
      ],
    })
    renderPage()
    const inside = (await screen.findByText('Inside Window Ltd.')).closest('tr')
    const outside = screen.getByText('Window Shut Ltd.').closest('tr')
    expect(within(inside).getByText('42 days ago')).toHaveClass('td-anniv-due')
    expect(within(outside).getByText('43 days ago')).not.toHaveClass('td-anniv-due')
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

  it('opens on the actionable set — the filing window through the next 60 days', async () => {
    // Two bounds, not one comparison. A passed anniversary counts NEGATIVE
    // while the return is still inside the 42-day statutory window, so -42 is
    // the far edge of "overdue but still filable" and 60 reaches what is
    // coming up.
    renderPage()
    await waitFor(() => {
      const url = decodeURIComponent(api.get.mock.calls[0][0])
      expect(url).toContain('filter=days_to_anniversary:gte:-42')
      expect(url).toContain('filter=days_to_anniversary:lte:60')
    })
  })

  it('names the default in a chip instead of a badge nobody can act on', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    expect(screen.getByRole('button', { name: 'Remove the Days to anniversary filter' }))
      .toBeInTheDocument()
    expect(screen.getByText('-42 to 60 days')).toBeInTheDocument()
  })

  it('takes a new upper and lower bound from the column header', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Days to anniversary/ }))
    const lower = screen.getByLabelText('Days to anniversary lower bound')
    const upper = screen.getByLabelText('Days to anniversary upper bound')
    await user.clear(lower)
    await user.type(lower, '0')
    await user.clear(upper)
    await user.type(upper, '30')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      const last = decodeURIComponent(api.get.mock.calls.at(-1)[0])
      expect(last).toContain('filter=days_to_anniversary:gte:0')
      expect(last).toContain('filter=days_to_anniversary:lte:30')
    })
  })

  it('drops the default entirely, showing every company', async () => {
    // "This is a starting view, not a lock." One click, from the chip.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: 'Remove the Days to anniversary filter' }))
    await waitFor(() => {
      expect(api.get.mock.calls.at(-1)[0]).not.toContain('days_to_anniversary')
    })
  })

  it('keeps one bound when the other is cleared', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Days to anniversary/ }))
    await user.clear(screen.getByLabelText('Days to anniversary lower bound'))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      const last = decodeURIComponent(api.get.mock.calls.at(-1)[0])
      expect(last).toContain('filter=days_to_anniversary:lte:60')
      expect(last).not.toContain('days_to_anniversary:gte')
    })
  })

  it('asks the server to sort, never the visible page', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    // FilterableTh renders a clickable <th>, not a <button> — the funnel inside
    // it is the button, and it stops the click before it becomes a sort.
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

  it('no longer keeps a filter bar of its own above the table', async () => {
    // One control per column, in the column. The standalone bar was a second
    // place to look for something the header can say.
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    expect(screen.queryByLabelText('Comparison')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Day count')).not.toBeInTheDocument()
  })

  it('explains that a passed anniversary counts negative, where the bounds are typed', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Days to anniversary/ }))
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

describe('CompanyRegistryPage — column filters', () => {
  const urls = () => api.get.mock.calls.map(c => decodeURIComponent(c[0]))

  it('offers a filter on every column', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    for (const label of ['Company Name', 'Chinese Name', 'BRN', 'CR No.',
                         'Type', 'Status', 'Days to anniversary']) {
      expect(screen.getByRole('button', { name: new RegExp(`^Filter ${label}`) }))
        .toBeInTheDocument()
    }
  })

  it('filters a company name server-side, never the visible page', async () => {
    // 5,930 rows served 50 at a time. Narrowing what arrived would look right
    // and answer a different question.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Company Name/ }))
    await user.type(screen.getByLabelText('Company Name value'), 'harbour')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=company_name:contains:harbour'))).toBe(true)
    })
  })

  it('finds the companies with no Chinese name', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Chinese Name/ }))
    await user.selectOptions(screen.getByLabelText('Condition'), 'empty')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=company_name_zh:empty:'))).toBe(true)
    })
  })

  it('offers the statuses a COMPANY can be, not the whole enum', async () => {
    // Levi 2026-09-04: "this is company status so some of these values dont
    // make sense". `entity_status` is one column doing two jobs — three values
    // describe a company, eight describe an incorporation in flight. On DEV:
    // 5,985 live, 12 ceased, 1 pre-incorporation, none of the other eight.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Status/ }))

    const boxes = screen.getAllByRole('checkbox').map(b => b.getAttribute('aria-label')
      ?? b.closest('label')?.textContent?.trim())
    expect(boxes).toEqual(['Live', 'Pre-Incorporation', 'Ceased'])
    for (const gone of ['Pending AML', 'To Verify', 'Submitted to CR', 'CR Approved']) {
      expect(screen.queryByRole('checkbox', { name: gone })).not.toBeInTheDocument()
    }
  })

  it('still filters by the status it does offer', async () => {
    // `live` and `ceased` are all 5,930 of the real rows. A filter that could
    // not name them would be a filter over nothing.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Status/ }))
    await user.click(screen.getByRole('checkbox', { name: 'Live' }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=status:in:live'))).toBe(true)
    })
  })

  it('drives the SAME flag filter the tabs do, through the Type column', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    await user.click(screen.getByRole('button', { name: /^Filter Type/ }))
    await user.click(screen.getByRole('radio', { name: 'Corporate Parties' }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('flag=corporate_party'))).toBe(true)
    })
    expect(screen.getByRole('tab', { name: /Corporate Parties/ }))
      .toHaveAttribute('aria-selected', 'true')
  })

  it('lights the funnel and the header of a column that is narrowing the table', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    // The default anniversary range is applied from first paint.
    expect(screen.getByRole('button', { name: 'Filter Days to anniversary (filtered)' }))
      .toHaveClass('is-on')
    expect(screen.getByRole('columnheader', { name: /Days to anniversary/ }))
      .toHaveClass('th-filtered')
    expect(screen.getByRole('button', { name: 'Filter Company Name' }))
      .not.toHaveClass('is-on')
  })
})

describe('CompanyRegistryPage — a read-only role', () => {
  it('still lists every company', async () => {
    // `companies:read` is exactly what this list is for.
    auth.hasPermission = (m, p) => `${m}:${p}` === 'companies:read'
    renderPage()
    expect(await screen.findByText('Harbour Tech Ltd.')).toBeInTheDocument()
  })

  it('disables + Add Company, and says which permission is missing', async () => {
    auth.hasPermission = (m, p) => `${m}:${p}` === 'companies:read'
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')

    const add = screen.getByRole('button', { name: /Add Company/ })
    expect(add).toBeDisabled()
    expect(add).toHaveAttribute('title', expect.stringContaining('companies (write)'))
  })

  it('leaves it enabled for a role that holds companies:write', async () => {
    renderPage()
    await screen.findByText('Harbour Tech Ltd.')
    expect(screen.getByRole('button', { name: /Add Company/ })).toBeEnabled()
  })
})
