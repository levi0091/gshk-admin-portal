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
// "+ Add Person" is gated on `persons:write`. Reassigned by the read-only test
// at the bottom of this file.
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))
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
  auth = {
    hasPermission: () => true, isSuperAdmin: true, profileLoading: false,
    profile: { id: 'u-1', display_name: 'Levi Z.', role_name: 'super_admin' },
  }
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
    expect(await screen.findByText('No records found')).toBeInTheDocument()
    // Nothing to clear — this screen opens unfiltered, so offering the button
    // would blame a filter for an empty database.
    expect(screen.queryByRole('button', { name: 'Clear all filters' }))
      .not.toBeInTheDocument()

    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load persons: boom/)).toBeInTheDocument()
  })
})

// Same race as the dashboard (UAT W-8): a superseded request could clobber the
// current view, or paint its error banner over a view that had loaded fine.
describe('PersonsRegistryPage — overlapping requests (UAT W-8)', () => {
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
    const { first, second } = await toggleTo(/Directors/)
    first.reject(new Error('boom'))
    second.resolve(PAYLOAD)
    await screen.findByText('John Smith')
    expect(screen.queryByText(/Failed to load persons/)).not.toBeInTheDocument()
  })

  it('ignores a slow response that arrives after a newer one', async () => {
    const { first, second } = await toggleTo(/Directors/)
    second.resolve({
      ...PAYLOAD,
      persons: [{ ...PAYLOAD.persons[0], id: 'p9', full_name: 'Newer Person' }],
    })
    await screen.findByText('Newer Person')
    first.resolve(PAYLOAD)
    await waitFor(() => expect(screen.getByText('Newer Person')).toBeInTheDocument())
    expect(screen.queryByText('John Smith')).not.toBeInTheDocument()
  })

  it('aborts the superseded request rather than leaving it in flight', async () => {
    await toggleTo(/Directors/)
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

describe('PersonsRegistryPage — column filters', () => {
  const urls = () => api.get.mock.calls.map(c => decodeURIComponent(c[0]))

  it('offers a filter on every column', async () => {
    renderPage()
    await screen.findByText('John Smith')
    for (const label of ['Name', 'Identity', 'Nationality', 'Roles', 'Last Updated']) {
      expect(screen.getByRole('button', { name: new RegExp(`^Filter ${label}`) }))
        .toBeInTheDocument()
    }
  })

  it('filters a name server-side', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.click(screen.getByRole('button', { name: /^Filter Name/ }))
    await user.type(screen.getByLabelText('Name value'), 'chan')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=full_name:contains:chan'))).toBe(true)
    })
  })

  it('picks several identity types at once', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.click(screen.getByRole('button', { name: /^Filter Identity/ }))
    await user.click(screen.getByRole('checkbox', { name: 'HKID' }))
    await user.click(screen.getByRole('checkbox', { name: 'Passport' }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=primary_id_type:in:hkid,passport'))).toBe(true)
    })
  })

  it('finds the people with no nationality on record', async () => {
    // Nationality has no Viewpoint lookup and is free text, so blanks are
    // common — and finding them is the reason to filter the column at all.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.click(screen.getByRole('button', { name: /^Filter Nationality/ }))
    await user.selectOptions(screen.getByLabelText('Condition'), 'empty')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('filter=nationality:empty:'))).toBe(true)
    })
  })

  it('drives the SAME role filter the tabs do, through the Roles column', async () => {
    // Two ways in, one state. Two states over one role is how a tab and a
    // header start disagreeing about what the table is showing.
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.click(screen.getByRole('button', { name: /^Filter Roles/ }))
    await user.click(screen.getByRole('radio', { name: 'Directors' }))
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urls().some(u => u.includes('role=director'))).toBe(true)
    })
    expect(screen.getByRole('tab', { name: /Directors/ }))
      .toHaveAttribute('aria-selected', 'true')
  })

  it('sends a Last Updated range as two bounds', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('John Smith')
    await user.click(screen.getByRole('button', { name: /^Filter Last Updated/ }))
    await user.type(screen.getByLabelText('From date'), '2026-06-01')
    await user.type(screen.getByLabelText('To date'), '2026-06-30')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      const last = decodeURIComponent(api.get.mock.calls.at(-1)[0])
      expect(last).toContain('filter=updated_at:gte:2026-06-01')
      expect(last).toContain('filter=updated_at:lte:2026-06-30')
    })
  })
})

describe('PersonsRegistryPage — write access', () => {
  it('lets the tester role add a person', async () => {
    // The reported case holds persons (read) AND persons (write).
    auth.hasPermission = (m, p) =>
      ['companies:read', 'persons:read', 'persons:write'].includes(`${m}:${p}`)
    renderPage()
    await screen.findByText('John Smith')

    expect(screen.getByRole('button', { name: /Add Person/ })).toBeEnabled()
  })

  it('disables + Add Person for a persons:read-only role, with the reason', async () => {
    auth.hasPermission = (m, p) => `${m}:${p}` === 'persons:read'
    renderPage()
    await screen.findByText('John Smith')

    const add = screen.getByRole('button', { name: /Add Person/ })
    expect(add).toBeDisabled()
    expect(add).toHaveAttribute('title', expect.stringContaining('persons (write)'))
  })
})
