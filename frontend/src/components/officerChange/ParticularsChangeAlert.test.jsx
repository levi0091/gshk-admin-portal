import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import ParticularsChangeAlert from './ParticularsChangeAlert.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})
const get = vi.fn(); const post = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a) },
}))

const ALL = { view: true, dismiss: true, start: true, open: true }
const ROWS = [
  { entity_id: 'e1', company_name: 'Kanenas Holding Limited', capacity: 'director',
    officer_id: 'o1', open_case: null,
    items: [{ key: 'email', cr_item: 'f', label: 'Email address',
      old_text: 'old@example.com', new_text: 'new@example.com' }] },
  { entity_id: 'e2', company_name: 'Skyline Capital', capacity: 'company_secretary',
    officer_id: null, secretary_id: 's7', open_case: { id: 'k5', case_no: 'ND2B-2026-0005' },
    items: [{ key: 'surname', cr_item: 'a', label: 'Name', old_text: 'HO', new_text: 'HO-LEE' }] },
]
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ changes: ROWS })
})

describe('ParticularsChangeAlert', () => {
  it('lists each company with what changed, old to new', async () => {
    wrap(<ParticularsChangeAlert kind="person" id="p1" caps={ALL} />)
    expect(await screen.findByText('Kanenas Holding Limited')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/persons/p1/particulars-changes')
    expect(screen.getByText('old@example.com')).toBeInTheDocument()
    expect(screen.getByText('new@example.com')).toBeInTheDocument()
    expect(screen.getByText(/2 appointments are/)).toBeInTheDocument()
  })

  it('re-reads when the profile is saved, so an edit raises or clears it at once', async () => {
    get.mockResolvedValueOnce({ changes: [] }).mockResolvedValueOnce({ changes: ROWS })
    const { rerender } = wrap(<ParticularsChangeAlert kind="person" id="p1" caps={ALL}
                                                      refreshKey={{ v: 1 }} />)
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('Kanenas Holding Limited')).not.toBeInTheDocument()
    rerender(<MemoryRouter><ParticularsChangeAlert kind="person" id="p1" caps={ALL}
                                                   refreshKey={{ v: 2 }} /></MemoryRouter>)
    expect(await screen.findByText('Kanenas Holding Limited')).toBeInTheDocument()
  })

  it('renders nothing when CR has been told everything', async () => {
    get.mockResolvedValue({ changes: [] })
    const { container } = wrap(<ParticularsChangeAlert kind="person" id="p1" caps={ALL} />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('does not even ask without read access', () => {
    wrap(<ParticularsChangeAlert kind="person" id="p1" caps={{ ...ALL, view: false }} />)
    expect(get).not.toHaveBeenCalled()
  })

  it('starts an ND2B on the company, by register id for a register-only secretaryship', async () => {
    post.mockResolvedValueOnce({ case: { id: 'k9' }, reused: false }).mockResolvedValueOnce({})
    const user = userEvent.setup()
    wrap(<ParticularsChangeAlert kind="person" id="p1" caps={ALL} />)
    await user.click(await screen.findByRole('button', { name: 'Start ND2B' }))
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/officer-changes/k9'))
    expect(post).toHaveBeenNthCalledWith(1, '/officer-changes', { entity_id: 'e1', form_code: 'Nd2b' })
    expect(post).toHaveBeenNthCalledWith(2, '/officer-changes/k9/entries',
      { kind: 'change', officer_id: 'o1' })
  })

  it('opens the ND2B already carrying the officer rather than starting another', async () => {
    wrap(<ParticularsChangeAlert kind="person" id="p1" caps={ALL} />)
    const open = await screen.findByRole('link', { name: 'Open ND2B-2026-0005' })
    expect(open).toHaveAttribute('href', '/officer-changes/k5')
    expect(screen.getAllByRole('button', { name: 'Start ND2B' })).toHaveLength(1)
  })

  it('draws no Start, Open or Dismiss for a role that may do none of them', async () => {
    wrap(<ParticularsChangeAlert kind="person" id="p1" caps={{ view: true }} />)
    await screen.findByText('Kanenas Holding Limited')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('confirms a dismiss, explains it is for loaded data and cannot be undone, then goes', async () => {
    post.mockResolvedValue({ dismissed: 2 })
    const user = userEvent.setup()
    wrap(<ParticularsChangeAlert kind="company" id="c1" caps={ALL} />)
    await user.click(await screen.findByRole('button', { name: 'Dismiss' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent(/data loaded from the previous system/)
    expect(dialog).toHaveTextContent(/cannot be undone/)
    expect(post).not.toHaveBeenCalled()
    await user.click(screen.getAllByRole('button', { name: 'Dismiss' }).at(-1))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/companies/c1/particulars-changes/dismiss', {}))
    await waitFor(() => expect(screen.queryByText('Kanenas Holding Limited')).not.toBeInTheDocument())
  })
})

describe('ParticularsChangeAlert — one company at a time (Jacqueline BQ2)', () => {
  it('dismisses for one company only, after confirming', async () => {
    post.mockResolvedValue({ dismissed: 1 })
    const user = userEvent.setup()
    wrap(<ParticularsChangeAlert kind="person" id="p1" caps={ALL} />)
    await screen.findByText('Kanenas Holding Limited')
    await user.click(screen.getAllByRole('button', { name: 'Not for this company' })[0])
    await user.click(screen.getByRole('button', { name: 'Dismiss for this company' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/persons/p1/particulars-changes/dismiss', { entity_id: 'e1' }))
    expect(screen.queryByText('Kanenas Holding Limited')).not.toBeInTheDocument()
    expect(screen.getByText('Skyline Capital')).toBeInTheDocument()
  })
})
