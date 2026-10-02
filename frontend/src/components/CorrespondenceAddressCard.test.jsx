import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CorrespondenceAddressCard from './CorrespondenceAddressCard.jsx'

const get = vi.fn(); const put = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), put: (...a) => put(...a) },
}))
vi.mock('../lib/lookups.js', () => ({
  optionsFor: (values) => values || [],
}))

const LOOKUPS = { cr_country: [{ code: 'HK', label: 'Hong Kong' }], cr_district: [{ code: 'CENTRAL', label: 'Central' }] }
const ROWS = [
  { officer_id: 'o1', entity_id: 'e1', role: 'director', company_name: 'Sample Trading Limited',
    address: null },
  { officer_id: 'o2', entity_id: 'e2', role: 'company_secretary', company_name: 'Harbourview Holdings',
    address: { line1: 'Unit 1203, 12/F', line2: 'Tower 1', line3: '9 Model Road',
               city: 'CENTRAL', country: 'HK' } },
]

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ correspondence_addresses: ROWS })
})

describe('CorrespondenceAddressCard', () => {
  it('lists each appointment: same as residential, or its own address in CR lines (Jacqueline B4)', async () => {
    render(<CorrespondenceAddressCard personId="p1" canEdit lookups={LOOKUPS} />)
    expect(await screen.findByText('Sample Trading Limited')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/persons/p1/correspondence-addresses')
    expect(screen.getByText('Same as residential address')).toBeInTheDocument()
    expect(screen.getByText('Unit 1203, 12/F')).toBeInTheDocument()
    expect(screen.getAllByText('Country/Region').length).toBeGreaterThan(0)
    expect(screen.getByText('Hong Kong')).toBeInTheDocument()
  })

  it('edits one appointment and saves its own address', async () => {
    put.mockResolvedValue({ correspondence_addresses: ROWS })
    const user = userEvent.setup()
    render(<CorrespondenceAddressCard personId="p1" canEdit lookups={LOOKUPS} />)
    await screen.findByText('Sample Trading Limited')
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const dialog = screen.getByRole('dialog', { name: /Correspondence address/ })
    await user.click(within(dialog).getByLabelText('Same as residential address'))
    await user.type(within(dialog).getByLabelText('Flat/Floor/Block etc.'), 'Room 5')
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    const [path, body] = put.mock.calls[0]
    expect(path).toBe('/persons/p1/appointments/o1/correspondence-address')
    expect(body.line1).toBe('Room 5')
    expect(body.same_as_residential).toBeUndefined()
  })

  it('sends same_as_residential when that box stays ticked', async () => {
    put.mockResolvedValue({ correspondence_addresses: ROWS })
    const user = userEvent.setup()
    render(<CorrespondenceAddressCard personId="p1" canEdit lookups={LOOKUPS} />)
    await screen.findByText('Harbourview Holdings')
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[1])
    const dialog = screen.getByRole('dialog', { name: /Correspondence address/ })
    await user.click(within(dialog).getByLabelText('Same as residential address'))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith(
      '/persons/p1/appointments/o2/correspondence-address', { same_as_residential: true }))
  })

  it('draws no Edit without persons:write', async () => {
    render(<CorrespondenceAddressCard personId="p1" canEdit={false} lookups={LOOKUPS} />)
    await screen.findByText('Sample Trading Limited')
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('renders nothing for a person with no current appointment', async () => {
    get.mockResolvedValue({ correspondence_addresses: [] })
    const { container } = render(<CorrespondenceAddressCard personId="p1" canEdit lookups={LOOKUPS} />)
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
