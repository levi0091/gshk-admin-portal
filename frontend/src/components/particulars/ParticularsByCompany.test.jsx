// Identification and addresses by company (Levi 2026-10-05, Jacqueline's ND2B
// question 2): each entry lists the companies using it; New adds one;
// Companies… chooses who uses it.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import ParticularsByCompany from './ParticularsByCompany.jsx'

const get = vi.fn(); const post = vi.fn(); const put = vi.fn(); const del = vi.fn()
vi.mock('../../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: (...a) => post(...a), put: (...a) => put(...a),
         del: (...a) => del(...a) },
}))

const HOME = { line1: 'Flat A, 10/F', line2: 'Harbour View', line3: "1 Queen's Road",
  city: 'CENTRAL', country: 'HK' }
const PARIS = { line1: '12 Rue de Rivoli', line2: '', line3: '', city: 'PARIS',
  postal_code: '75001', country: 'FR' }
const BOOK = {
  companies: [{ entity_id: 'e1', company_name: 'Kanenas Holding Limited', roles: ['director'] },
              { entity_id: 'e2', company_name: 'Second Limited', roles: ['director', 'company_secretary'] }],
  default_residential_address_id: 'a1',
  residential: [
    { address_id: 'a1', address: HOME, is_default: true, used_by: ['e1'] },
    { address_id: 'a2', address: PARIS, is_default: false, used_by: ['e2'] },
    { address_id: 'a4', address: { line1: 'Old Flat', city: 'CENTRAL', country: 'HK' },
      is_default: false, used_by: [] },
  ],
  correspondence: [{ address_id: 'a3', address: { line1: 'Room 1201', city: 'CENTRAL', country: 'HK' },
    used_by: ['e1'] }],
  correspondence_same_as_residential: ['e2'],
  identity: [
    { document_id: 'd1', id_type: 'passport', id_number: 'F1111111', issuing_country: 'FR',
      is_primary: true, used_by: ['e1'] },
    { document_id: 'd2', id_type: 'passport', id_number: 'K7654321', issuing_country: 'US',
      is_primary: false, used_by: ['e2'] },
  ],
}
const LOOKUPS = { cr_country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'FR', label: 'France' },
  { code: 'US', label: 'United States' }] }

function renderCards(props = {}) {
  const onChanged = vi.fn()
  render(<ParticularsByCompany personId="p1" canEdit lookups={LOOKUPS} onChanged={onChanged}
                               {...props} />)
  return { onChanged }
}

const card = name => screen.getByRole('region', { name })

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(BOOK)
  post.mockResolvedValue(BOOK); put.mockResolvedValue(BOOK); del.mockResolvedValue(BOOK)
})

describe('ParticularsByCompany', () => {
  it('lists each address and document with the companies using it', async () => {
    renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    const home = within(res).getByText('Flat A, 10/F').closest('[data-entry]')
    expect(within(home).getByText('Default')).toBeInTheDocument()
    expect(within(home).getByText('Kanenas Holding Limited')).toBeInTheDocument()
    const paris = within(res).getByText('12 Rue de Rivoli').closest('[data-entry]')
    expect(within(paris).getByText('Second Limited')).toBeInTheDocument()
    expect(within(paris).getByText('France')).toBeInTheDocument()
    const old = within(res).getByText('Old Flat').closest('[data-entry]')
    expect(within(old).getByText('No company uses this address.')).toBeInTheDocument()

    const corr = card('Correspondence addresses')
    expect(within(corr).getByText('Room 1201')).toBeInTheDocument()
    const same = within(corr).getByText('Same as residential address').closest('[data-entry]')
    expect(within(same).getByText('Second Limited')).toBeInTheDocument()

    const ids = card('Identification by company')
    const fr = within(ids).getByText('F1111111').closest('[data-entry]')
    expect(within(fr).getByText('Primary')).toBeInTheDocument()
    expect(within(fr).getByText('Kanenas Holding Limited')).toBeInTheDocument()
    expect(within(within(ids).getByText('K7654321').closest('[data-entry]'))
      .getByText('Second Limited')).toBeInTheDocument()
  })

  it('gives a company the same colour on every card', async () => {
    renderCards()
    await screen.findByRole('region', { name: 'Residential addresses' })
    const chips = screen.getAllByText('Second Limited').map(el => el.closest('.co-chip').className)
    expect(chips.length).toBe(3)
    expect(new Set(chips).size).toBe(1)
  })

  it('adds a residential address for chosen companies, as the default', async () => {
    const user = userEvent.setup()
    const { onChanged } = renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    await user.click(within(res).getByRole('button', { name: 'New' }))
    const dialog = screen.getByRole('dialog', { name: 'New residential address' })
    await user.type(within(dialog).getByLabelText('Flat/Floor/Block etc.'), 'Flat 20A')
    await user.click(within(dialog).getByLabelText(/Second Limited/))
    await user.click(within(dialog).getByLabelText('Make this the default residential address'))
    await user.click(within(dialog).getByRole('button', { name: 'Add address' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const [path, body] = post.mock.calls[0]
    expect(path).toBe('/persons/p1/addresses')
    expect(body).toMatchObject({ kind: 'residential', line1: 'Flat 20A', entity_ids: ['e2'],
      make_default: true })
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('a correspondence address cannot be made the default', async () => {
    const user = userEvent.setup()
    renderCards()
    const corr = await screen.findByRole('region', { name: 'Correspondence addresses' })
    await user.click(within(corr).getByRole('button', { name: 'New' }))
    const dialog = screen.getByRole('dialog', { name: 'New correspondence address' })
    expect(within(dialog).queryByLabelText(/default/)).not.toBeInTheDocument()
  })

  it('chooses which companies use an address', async () => {
    const user = userEvent.setup()
    renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    const paris = within(res).getByText('12 Rue de Rivoli').closest('[data-entry]')
    await user.click(within(paris).getByRole('button', { name: 'Companies…' }))
    const dialog = screen.getByRole('dialog', { name: /Companies using this address/ })
    await user.click(within(dialog).getByLabelText(/Kanenas Holding Limited/))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/persons/p1/addresses/a2/companies',
      { kind: 'residential', entity_ids: ['e2', 'e1'] }))
  })

  it('on the default address, a company using it cannot be unticked there', async () => {
    const user = userEvent.setup()
    renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    const home = within(res).getByText('Flat A, 10/F').closest('[data-entry]')
    await user.click(within(home).getByRole('button', { name: 'Companies…' }))
    const dialog = screen.getByRole('dialog', { name: /Companies using this address/ })
    expect(within(dialog).getByLabelText(/Kanenas Holding Limited/)).toBeDisabled()
    expect(within(dialog).getByText(/choose another address for it/)).toBeInTheDocument()
  })

  it('corrects an address in place', async () => {
    const user = userEvent.setup()
    renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    const home = within(res).getByText('Flat A, 10/F').closest('[data-entry]')
    await user.click(within(home).getByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog', { name: 'Correct this address' })
    expect(within(dialog).getByText(/Kanenas Holding Limited/)).toBeInTheDocument()
    const line = within(dialog).getByLabelText('Flat/Floor/Block etc.')
    await user.clear(line); await user.type(line, 'Flat B, 10/F')
    await user.click(within(dialog).getByRole('button', { name: 'Save correction' }))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][0]).toBe('/persons/p1/addresses/a1')
    expect(put.mock.calls[0][1].line1).toBe('Flat B, 10/F')
  })

  it('makes another address the default, and removes only an unused one', async () => {
    const user = userEvent.setup()
    renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    const home = within(res).getByText('Flat A, 10/F').closest('[data-entry]')
    expect(within(home).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    const paris = within(res).getByText('12 Rue de Rivoli').closest('[data-entry]')
    expect(within(paris).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    await user.click(within(paris).getByRole('button', { name: 'Make default' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/persons/p1/addresses/a2/default', {}))
    const old = within(res).getByText('Old Flat').closest('[data-entry]')
    await user.click(within(old).getByRole('button', { name: 'Remove' }))
    await user.click(within(screen.getByRole('alertdialog', { name: 'Remove address' }))
      .getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/persons/p1/addresses/a4?kind=residential'))
  })

  it('links a passport to the chosen companies', async () => {
    const user = userEvent.setup()
    renderCards()
    const ids = await screen.findByRole('region', { name: 'Identification by company' })
    const us = within(ids).getByText('K7654321').closest('[data-entry]')
    await user.click(within(us).getByRole('button', { name: 'Companies…' }))
    const dialog = screen.getByRole('dialog', { name: /Companies filing this document/ })
    await user.click(within(dialog).getByLabelText(/Kanenas Holding Limited/))
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith(
      '/persons/p1/identity-documents/d2/companies', { entity_ids: ['e2', 'e1'] }))
  })

  it('shows the refusal the API gives', async () => {
    put.mockRejectedValueOnce({ detail: { message: 'A company still uses this address.' } })
    const user = userEvent.setup()
    renderCards()
    const res = await screen.findByRole('region', { name: 'Residential addresses' })
    const paris = within(res).getByText('12 Rue de Rivoli').closest('[data-entry]')
    await user.click(within(paris).getByRole('button', { name: 'Companies…' }))
    await user.click(within(screen.getByRole('dialog', { name: /Companies using/ }))
      .getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('A company still uses this address.')).toBeInTheDocument()
  })

  it('draws no control without persons (edit)', async () => {
    renderCards({ canEdit: false })
    await screen.findByRole('region', { name: 'Residential addresses' })
    for (const name of ['New', 'Companies…', 'Edit', 'Make default', 'Remove']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })

  it('renders nothing it cannot read rather than an empty card', async () => {
    get.mockRejectedValueOnce(new Error('down'))
    renderCards()
    expect(await screen.findByText(/could not be loaded/)).toBeInTheDocument()
  })
})
