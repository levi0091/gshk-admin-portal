/**
 * The 2026-09-04 body-corporate profile pass (Levi's 13 items).
 *
 * Its own file rather than more cases in CompanyProfilePage.test.jsx: these are
 * one review of one screen, and each test's reason for existing is that review.
 * Kept next to the page it covers, per the co-location rule in CLAUDE.md.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CompanyProfilePage from './CompanyProfilePage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ companyId: 'e1' }) }
})

vi.mock('../lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() },
}))
import { api } from '../lib/api.js'

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))
import { _resetLookups } from '../lib/lookups.js'
import { _resetFormContract } from '../lib/formContract.js'

const CLIENT = {
  id: 'e1', company_name: 'ABC Testing Limited', vp_source_key: 'ABC01',
  br_number: '98578122', status: 'pre_incorporation', company_type: 'P',
  incorporation_place: 'HK', incorporation_date: '2025-09-01',
  created_at: '2026-08-03', is_client: true, is_corporate_party: false,
  registered_address: { line1: '19/F, World Trust Tower', city: 'CENTRAL', country: 'HK' },
  contacts: [{ id: 'c1', contact_type: 'phone', contact_value: '+852 64317125',
               is_preferred: true }],
  documents: [], business_names: [],
  officers: [{
    id: 'o1', role: 'director', appointed_date: '2025-09-01', is_current: true,
    persons: { id: 'p1', full_name: 'John Smith', email: 'js@x.com' },
  }],
  shareholders: [], beneficial_owners: [], secretaries: [],
  share_classes: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
                    total_issued: 10000, issued_amount: 10000, total_paid: 10000 }],
  cases: { nar1: [], nnc1: [] },
  filing_problems: [],
}

const CORP_ONLY = {
  ...CLIENT, id: 'e3', company_name: 'Asia BC Ltd.',
  is_client: false, is_corporate_party: true,
  tcsp_licence_no: 'TC000807', officers: [], cases: undefined,
}

const LOOKUPS = {
  cr_country: [{ code: 'HK', label: 'Hong Kong' }],
  cr_company_type: [{ code: 'P', label: 'Private' }],
  cr_business_nature: [{ code: '001', label: 'Crop and animal production' }],
  cr_currency: [{ code: 'HKD', label: 'HKD - Hong Kong Dollar' }],
  share_class_name: [{ code: 'Ordinary', label: 'Ordinary' }],
  bo_owner_type: [{ code: 'ubo', label: 'Ultimate Beneficial Owner' },
                  { code: 'significant_controller', label: 'Significant Controller' }],
  bo_nature_of_control: [
    { code: 'over_25_percent',
      label: 'Holds more than 25% of the issued shares of the company' },
    { code: 'significant_influence',
      label: 'Has the right to exercise, or actually exercises, significant '
           + 'influence or control over the company' }],
}

const CONTRACT = { entities: {}, addresses: {}, share_classes: {} }

const renderPage = () => render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)

const mockGet = (data) =>
  api.get.mockImplementation(url => {
    if (url === '/lookups') return Promise.resolve(LOOKUPS)
    if (url === '/form-contract') return Promise.resolve(CONTRACT)
    return Promise.resolve(data)
  })

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetFormContract()
  mockGet(CLIENT)
  api.patch.mockResolvedValue({})
  api.put.mockResolvedValue({})
  auth = { hasPermission: () => true, isSuperAdmin: true }
})

describe('CompanyProfilePage — the 2026-09-04 pass', () => {
  it('shows a director’s Position and Resignation Reason (item 5)', async () => {
    // Both were editable in the modal and printed nowhere, so typing one and
    // saving it looked identical to not typing it.
    mockGet({
      ...CLIENT,
      officers: [{
        id: 'o1', role: 'authorised_rep', position: 'Chair',
        appointed_date: '2026-09-10', resigned_date: '2026-09-23',
        resignation_reason: 'Retired', is_current: false,
        persons: { id: 'p1', full_name: 'Abo Ahmad' },
      }],
    })
    renderPage()
    const tile = (await screen.findByText(/Director\(s\)/)).closest('.card')

    expect(within(tile).getByText('Position')).toBeInTheDocument()
    expect(within(tile).getByText('Chair')).toBeInTheDocument()
    expect(within(tile).getByText('Resignation Reason')).toBeInTheDocument()
    expect(within(tile).getByText('Retired')).toBeInTheDocument()
    // The enum's underscores are not a label.
    expect(within(tile).getByText('authorised rep')).toBeInTheDocument()
  })

  it('leaves out a director’s Position when there is none', async () => {
    // A conditional row, not an em dash: a director with no position is not a
    // director whose position is missing.
    renderPage()
    const tile = (await screen.findByText(/Director\(s\)/)).closest('.card')
    expect(within(tile).queryByText('Position')).not.toBeInTheDocument()
  })

  it('reads a company secretary’s TCSP licence off the PERSON too (item 10)', async () => {
    // It used to read `corporate_entity` alone, so a secretary who is a
    // licensed individual rendered an em dash — and nothing in the portal
    // could fill it in.
    mockGet({
      ...CLIENT,
      secretaries: [{
        id: 'sec1', position: 'Secretary', appointed_date: '2026-09-10',
        resignation_reason: 'Replaced', is_current: true,
        persons: { id: 'p9', full_name: 'Abo Ahmad', tcsp_licence_no: 'TC000807' },
      }],
    })
    renderPage()
    const tile = (await screen.findByText(/Company Secretary/)).closest('.card')

    expect(within(tile).getByText('TC000807')).toBeInTheDocument()
    // The same gap the director tile had.
    expect(within(tile).getByText('Replaced')).toBeInTheDocument()
  })

  it('states a beneficial owner’s nature of control, not two percentages (item 12)', async () => {
    mockGet({
      ...CLIENT,
      beneficial_owners: [{
        id: 'bo1', owner_type: 'significant_controller',
        nature_of_control: 'significant_influence',
        percent_interest: 0, percent_vote: 0,
        persons: { id: 'p2', full_name: 'Bryan Ng' },
      }],
    })
    renderPage()
    const tile = (await screen.findByText(/Beneficial Owner/)).closest('.card')

    // The stored code rendered as its sentence — the tile used to print
    // "significant_controller".
    expect(within(tile).getByText('Significant Controller')).toBeInTheDocument()
    expect(within(tile).getByText(/significant influence or control/))
      .toBeInTheDocument()
    // Removed: 0/0 reads as "not a controller", which is exactly wrong for
    // someone whose control is a veto rather than a shareholding.
    expect(within(tile).queryByText('Interest %')).not.toBeInTheDocument()
    expect(within(tile).queryByText('Voting %')).not.toBeInTheDocument()
  })

  it('tells the operator how to record a share transfer (item 9)', async () => {
    // The two buttons on offer are Edit and Remove, and Remove is the one that
    // reads like "this person no longer holds shares" — while being the one
    // that destroys the record that they ever did.
    renderPage()
    const tile = (await screen.findByText(/Shareholder\(s\)/)).closest('.card')
    expect(within(tile).getByText(/set Status to Former/)).toBeInTheDocument()
  })

  it('does not label one member’s holding with CR’s class-total heading', async () => {
    // "Total Number" is CR's heading for the number of shares in issue for the
    // whole class. Using it for one member's holding put the same words on two
    // different figures on the same screen.
    mockGet({
      ...CLIENT,
      shareholders: [{
        id: 'sh1', shares_held: 100, amount_paid: 100,
        share_classes: { class_name: 'Ordinary', currency: 'HKD' },
        persons: { id: 'p3', full_name: 'El Haddar' },
      }],
    })
    renderPage()
    const tile = (await screen.findByText(/Shareholder\(s\)/)).closest('.card')

    expect(within(tile).getByText('Shares Held')).toBeInTheDocument()
    expect(within(tile).queryByText('Total Number')).not.toBeInTheDocument()
  })

  it('shows Case Notes, which were editable and displayed nowhere', async () => {
    mockGet({ ...CLIENT, case_notes: 'Client prefers email contact' })
    renderPage()
    await screen.findByText('Case Notes')
    expect(screen.getByText('Client prefers email contact')).toBeInTheDocument()
  })

  it('lets the company phone be corrected after creation', async () => {
    // `company_phone` was accepted at creation, written to `contacts`, printed
    // here — and then unreachable. CR's NAR1 maps `telNo` straight off it.
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText('Company Information')).closest('.card')
    await user.click(within(card).getByRole('button', { name: 'Edit' }))

    const phone = screen.getByLabelText('Company Phone')
    await user.clear(phone)
    await user.type(phone, '+852 9000 1111')
    await user.click(within(card).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      '/companies/e1/company-phone', { company_phone: '+852 9000 1111' }))
  })

  it('sends an emptied field so it can actually be cleared', async () => {
    // Deleting a value and pressing Save used to do nothing at all, and looked
    // exactly like a save that worked — the old value came back on reload.
    const user = userEvent.setup()
    mockGet({ ...CLIENT, cr_number: '2100031' })
    renderPage()
    const card = (await screen.findByText('Company Information')).closest('.card')
    await user.click(within(card).getByRole('button', { name: 'Edit' }))

    await user.clear(screen.getByLabelText('CR No.'))
    await user.click(within(card).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1', expect.objectContaining({ cr_number: '' })))
  })

  it('does not send fields that were already empty', async () => {
    // The other half of the rule: "" reaching the API for a column that was
    // already null would write an audit row saying nothing changed.
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText('Company Information')).closest('.card')
    await user.click(within(card).getByRole('button', { name: 'Edit' }))
    await user.type(screen.getByLabelText('BRN'), '9')
    await user.click(within(card).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalled())
    const body = api.patch.mock.calls.at(-1)[1]
    expect(body).not.toHaveProperty('case_notes')
    expect(body).not.toHaveProperty('company_name_zh')
  })

  it('lets a corporate party’s TCSP licence be edited (item 10)', async () => {
    // The tile was read-only, and this is the one thing it is for.
    const user = userEvent.setup()
    mockGet(CORP_ONLY)
    renderPage()
    const tile = (await screen.findByText('Corporate Party Details')).closest('.card')

    await user.click(within(tile).getByRole('button', { name: 'Edit' }))
    const licence = within(tile).getByLabelText('TCSP Licence No.')
    await user.clear(licence)
    await user.type(licence, 'TC000999')
    await user.click(within(tile).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1', expect.objectContaining({ tcsp_licence_no: 'TC000999' })))
  })

  it('names the party in the remove confirmation, and says what is lost', async () => {
    // "Remove this party from the company?" named nobody — with eight
    // directors on screen there was no way to tell which row it belonged to.
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()
    const tile = (await screen.findByText(/Director\(s\)/)).closest('.card')

    await user.click(within(tile).getByRole('button', { name: 'Remove' }))
    expect(confirm.mock.calls[0][0]).toContain('John Smith')
    expect(confirm.mock.calls[0][0]).toContain('Status to Former')
    expect(api.del).not.toHaveBeenCalled()
    confirm.mockRestore()
  })
})
