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

// The Cases pane gates "+ New case" on nar1:write, so this needs an identity.
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))
import { _resetLookups } from '../lib/lookups.js'
import { _resetFormContract } from '../lib/formContract.js'

const CLIENT = {
  id: 'e1', company_name: 'Skyline Capital', vp_source_key: 'SKYLINE01',
  br_number: '2100031', cr_number: '2100031', status: 'live',
  company_type: 'Private company limited by shares',
  incorporation_place: 'HK',
  incorporation_date: '2024-05-20', created_at: '2024-05-02',
  is_client: true, is_corporate_party: false,
  registered_address: { line1: 'Unit 12A', city: 'Central', country: 'HK' },
  contacts: [{ id: 'c1', contact_type: 'phone', contact_value: '+852 3500 1234' }],
  documents: [{
    id: 'd1', document_type_code: 'coi', current_version: 1,
    file_name: 'brand-guideline-v3.pdf',
    document_types: { code: 'coi', label: 'Certificate of Incorporation' },
  }],
  officers: [{
    id: 'o1', role: 'director', appointed_date: '2024-05-20', is_current: true,
    correspondence_address: { line1: 'Care of GSHK', city: 'WANCHAI', country: 'HK' },
    persons: {
      id: 'p1', full_name: 'John Smith', email: 'js@x.com',
      residential_address: { line1: 'Flat 3B', city: 'CENTRAL', country: 'HK' },
    },
  }],
  shareholders: [], beneficial_owners: [], secretaries: [],
  cases: { nar1: [], nnc1: [] },
  // Block 5 additions — all of it data that already existed and never reached
  // a screen.
  business_nature_code: '070',
  business_nature_desc: 'Activities of head offices',
  mortgages_total: 'Nil',
  business_names: [{ id: 'bn1', business_name: 'Skyline Advisory',
                     business_name_zh: '天際顧問' }],
  share_classes: [{
    id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
    total_issued: 10000, issued_amount: 10000, total_paid: 10000,
  }],
  record_locations: [
    { record_type: 'SM', label: 'Register of Members',
      address: { line1: 'Unit 12A', city: 'CENTRAL', country: 'HK' },
      address_id: 'addr-ro' },
    { record_type: 'SC', label: 'Register of Charges', address: null,
      address_id: null },
  ],
  filing_problems: [],
}

const CORP_ONLY = {
  ...CLIENT,
  id: 'e3', company_name: 'Asia BC Ltd.',
  is_client: false, is_corporate_party: true,
  tcsp_licence_no: 'TC000807', incorporation_place: 'Hong Kong',
  officers: [], cases: undefined,
}

const renderPage = () => render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)

// The profile forms now read their dropdowns from /lookups, so api.get has to
// answer per-URL rather than returning the same payload for everything.
const LOOKUPS = {
  gender: [{ code: 'M', label: 'Male' }, { code: 'F', label: 'Female' }],
  nationality: [{ code: 'Dutch', label: 'Dutch' }, { code: 'British', label: 'British' }],
  marital_status: [{ code: 'SI', label: 'Single' }, { code: 'MA', label: 'Married' }],
  // Viewpoint's list, deliberately carrying a value CR cannot resolve — the
  // screens must not read it for any field CR validates.
  country: [{ code: 'HK-CH', label: '香港' }],
  cr_country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'ZA', label: 'South Africa' }],
  cr_company_type: [{ code: 'P', label: 'Private' }, { code: 'N', label: 'Public' },
                    { code: 'G', label: 'Limited by Guarantee' }],
  cr_business_nature: [{ code: '070', label: 'Activities of head offices' },
                       { code: '001', label: 'Crop and animal production' }],
  cr_currency: [{ code: 'HKD', label: 'HKD - Hong Kong Dollar' },
                { code: 'RMB', label: 'RMB - Ren Min Bi' }],
}

// What CR requires of each profile column, as GET /form-contract serves it.
const CONTRACT = {
  entities: {
    company_name: { max_length: 100, mandatory: true, cr_fields: ['coyEngName'] },
    company_type: { max_length: 1, mandatory: true, cr_fields: ['coyType'] },
    business_nature_code: { max_length: 5, mandatory: false, cr_fields: ['nature'] },
    mortgages_total: { max_length: 120, mandatory: false,
                       cr_fields: ['totalAmountMortCharge'] },
  },
  addresses: {
    line1: { max_length: 60, mandatory: false, cr_fields: ['flatFlrBlk'] },
    country: { max_length: 3, mandatory: true, cr_fields: ['ctryRegion'] },
  },
  share_classes: {
    class_name: { max_length: 60, mandatory: true, cr_fields: ['clsOfShares'] },
    currency: { max_length: 3, mandatory: true, cr_fields: ['currency'] },
    total_issued: { max_length: 16, mandatory: true,
                    cr_fields: ['noOfShareIssuedOnThisCls'] },
    issued_amount: { max_length: 16, mandatory: true, cr_fields: ['issuedCapital'] },
    total_paid: { max_length: 16, mandatory: true, cr_fields: ['paidUpCapital'] },
  },
}

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

describe('CompanyProfilePage', () => {
  it('shows a loading state first', () => {
    api.get.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('renders core company information', async () => {
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText('SKYLINE01')).toBeInTheDocument()
    expect(screen.getByText('+852 3500 1234')).toBeInTheDocument()
    // The registered office renders as the separate lines CR receives, not as
    // one comma-joined string: a filable address and an unfilable one look
    // identical once joined, and the joined form is what hid 874 bad rows.
    expect(screen.getByText('Unit 12A')).toBeInTheDocument()
    expect(screen.getByText('Central')).toBeInTheDocument()
  })

  it('shows Country of Incorporation in read-only info even when not a corporate party', async () => {
    // Regression: incorporation_place is editable for every company but was only
    // displayed inside the corporate-party tile, so a plain client could save it
    // and never see it again.
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText('Country of Incorporation')).toBeInTheDocument()
    // 'HK' resolves to its country label via the /lookups vocabulary
    expect(screen.getByText('Hong Kong')).toBeInTheDocument()
    // and the corporate-party tile is hidden for a client (field not duplicated)
    expect(screen.queryByText('Corporate Party Details')).not.toBeInTheDocument()
  })

  it('shows client-only tiles and the Cases pane when is_client', async () => {
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText(/Director\(s\)/)).toBeInTheDocument()
    expect(screen.getByText(/Shareholder\(s\)/)).toBeInTheDocument()
    expect(screen.getByText('Cases')).toBeInTheDocument()
    expect(screen.getByText('John Smith')).toBeInTheDocument()
    // corporate-party tile hidden when the flag is off
    expect(screen.queryByText('Corporate Party Details')).not.toBeInTheDocument()
  })

  it('hides client tiles + Cases pane and reveals the corporate tile for a non-client', async () => {
    mockGet(CORP_ONLY)
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText('Corporate Party Details')).toBeInTheDocument()
    expect(screen.getByText('TC000807')).toBeInTheDocument()
    expect(screen.queryByText('Cases')).not.toBeInTheDocument()
    expect(screen.queryByText(/Director\(s\)/)).not.toBeInTheDocument()
  })

  it('shows an empty Cases pane when there are no cases', async () => {
    renderPage()
    await screen.findByText('Cases')
    expect(screen.getByText('No cases yet.')).toBeInTheDocument()
  })

  it('toggles a flag via PATCH /flags and refetches', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Company Information')
    await user.click(screen.getByRole('switch', { name: 'Is Corporate Party' }))
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/companies/e1/flags', { is_corporate_party: true })
    })
  })

  it('edits company info and PATCHes only the changed fields', async () => {
    const user = userEvent.setup()
    renderPage()
    // Party tiles carry their own Edit buttons — scope to the info card.
    const infoCard = (await screen.findByText('Company Information')).closest('.card')
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))

    const nameInput = screen.getByLabelText('Company Name')
    await user.clear(nameInput)
    await user.type(nameInput, 'Skyline Capital Management')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/companies/e1',
        { company_name: 'Skyline Capital Management' })
    })
  })

  it('names the document TYPE, not just the uploaded file name', async () => {
    renderPage()
    // the file name alone ("brand-guideline-v3.pdf") does not say what the
    // document IS — the type must be shown
    await screen.findByText('Certificate of Incorporation')
    expect(screen.getByText(/brand-guideline-v3\.pdf/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument()
  })

  // -- Editing under a live case (wireframe_v11 "Edit conflicts with a live
  // case"). Validation freezes a snapshot; an edit after it changes the
  // profile ONLY, and the two then disagree silently.

  const withLiveCase = (code = 'signing') => ({
    ...CLIENT,
    cases: {
      nar1: [{ id: 'c1', case_no: 'NAR-2026-0041',
               workflow_status: { code, label: 'Signing' } }],
      nnc1: [],
    },
  })

  const editName = async (user, value = 'Skyline Capital Management') => {
    const infoCard = (await screen.findByText('Company Information')).closest('.card')
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))
    const nameInput = screen.getByLabelText('Company Name')
    await user.clear(nameInput)
    await user.type(nameInput, value)
    await user.click(screen.getByRole('button', { name: 'Save' }))
  }

  it('warns before saving an edit that a live case would stop matching', async () => {
    const user = userEvent.setup()
    mockGet(withLiveCase())
    renderPage()
    await editName(user)

    expect(screen.getByRole('alertdialog',
      { name: 'Edit conflicts with a live case' })).toBeInTheDocument()
    expect(screen.getByText(/NAR-2026-0041/)).toBeInTheDocument()
    // and NOTHING has been written yet
    expect(api.patch).not.toHaveBeenCalled()
  })

  it('cancelling the warning leaves the record untouched', async () => {
    const user = userEvent.setup()
    mockGet(withLiveCase())
    renderPage()
    await editName(user)
    await user.click(screen.getByRole('button', { name: 'Cancel edit' }))

    expect(api.patch).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('saves anyway when the operator overrides — the edit is allowed', async () => {
    const user = userEvent.setup()
    mockGet(withLiveCase())
    renderPage()
    await editName(user)
    await user.click(screen.getByRole('button', { name: 'Save anyway' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/companies/e1',
      { company_name: 'Skyline Capital Management' }))
  })

  it('does NOT warn when the only case is still at Data Verification', async () => {
    // Nothing is frozen yet, so there is nothing to disagree with. Warning
    // here would fire on every edit and stop being read.
    const user = userEvent.setup()
    mockGet(withLiveCase('data_verification'))
    renderPage()
    await editName(user)

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
  })

  it('the Save button does not smuggle the click event in as an override', async () => {
    // `onClick={saveEdit}` hands React's event object to the first parameter.
    // With `saveEdit(force = false)` that event is truthy, so the guard would
    // be bypassed on every save and never fire once.
    const user = userEvent.setup()
    mockGet(withLiveCase())
    renderPage()
    await editName(user)
    expect(api.patch).not.toHaveBeenCalled()
  })

  it('renders an error state when the fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load company: boom/)).toBeInTheDocument()
  })
})

/**
 * Block 5 — the fields Brian asked for, and the ones CR needs beside them.
 *
 * Every one of these is data that already existed somewhere and never reached
 * a screen. The tests name Brian's item numbers because the point is the
 * comment being answered, not the div being added.
 */
describe('CompanyProfilePage — the CR form fields', () => {
  const findInfoCard = async () =>
    (await screen.findByText('Company Information')).closest('.card')

  it('shows the business name (B9)', async () => {
    // 5,026 rows have sat in `business_names` since the ETL and no screen has
    // ever read one.
    renderPage()
    await findInfoCard()

    expect(screen.getByText('Business Name')).toBeInTheDocument()
    expect(screen.getByText(/Skyline Advisory/)).toBeInTheDocument()
  })

  it('shows business nature as its code AND the description it drives (B5)', async () => {
    renderPage()
    await findInfoCard()

    expect(screen.getByText('Business Nature')).toBeInTheDocument()
    expect(screen.getByText(/070/)).toBeInTheDocument()
    expect(screen.getByText(/Activities of head offices/)).toBeInTheDocument()
  })

  it('shows mortgages and charges (B6)', async () => {
    renderPage()
    await findInfoCard()

    expect(screen.getByText('Mortgages and Charges')).toBeInTheDocument()
    expect(screen.getByText('Nil')).toBeInTheDocument()
  })

  it('offers business nature as a closed dropdown, never free text', async () => {
    // CR's list is closed; an invented code fails the filing. Viewpoint holds
    // no business nature at all, so this dropdown is the only thing standing
    // between an operator and a made-up value.
    const user = userEvent.setup()
    renderPage()
    const infoCard = await findInfoCard()
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))

    const select = screen.getByLabelText(/Business Nature Code/)
    expect(select.tagName).toBe('SELECT')
    expect(within(select).getByRole('option', { name: /Activities of head offices/ }))
      .toBeInTheDocument()
  })

  it('does not let the description be typed — the code fills it in', async () => {
    // CR derives natureDesc from nature after web-form validation. A typed
    // description could disagree with the code it is supposed to describe.
    const user = userEvent.setup()
    renderPage()
    const infoCard = await findInfoCard()
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))

    expect(screen.queryByLabelText(/Business Nature Description/)).not.toBeInTheDocument()
  })

  it('offers company type as CRs three codes (§7.4)', async () => {
    const user = userEvent.setup()
    renderPage()
    const infoCard = await findInfoCard()
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))

    const select = screen.getByLabelText('Company Type')
    expect(select.tagName).toBe('SELECT')
    expect(within(select).getByRole('option', { name: 'Limited by Guarantee' }))
      .toBeInTheDocument()
  })

  it('keeps a legacy free-text company type visible rather than blanking it', async () => {
    // `entities.company_type` held Viewpoint's own descriptions. Dropping the
    // stored value from the dropdown would silently blank it on the next save.
    const user = userEvent.setup()
    mockGet({ ...CLIENT, company_type: 'Private company limited by shares' })
    renderPage()
    const infoCard = await findInfoCard()
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))

    expect(screen.getByLabelText('Company Type'))
      .toHaveValue('Private company limited by shares')
  })

  // -- Share capital (B7) --------------------------------------------------

  it('shows share capital under CRs own headings (B7)', async () => {
    // Total Number is a COUNT of shares; Total Amount is money. The schema
    // could not tell them apart until migration 028, and neither could the
    // screen — which is exactly what Brian spotted.
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')

    expect(within(tile).getByText('Class of Shares')).toBeInTheDocument()
    expect(within(tile).getByText('Total Number')).toBeInTheDocument()
    expect(within(tile).getByText('Total Amount')).toBeInTheDocument()
    expect(within(tile).getByText(/Total Amount Paid up/)).toBeInTheDocument()
    expect(within(tile).getByText('Ordinary')).toBeInTheDocument()
  })

  it('can edit a share class — the card shipped with no way to fix it', async () => {
    // THE DEFECT. The card showed "1 to fix" beside a blank Total Amount and
    // offered no control that could fix it. A badge you cannot act on is
    // worse than no badge.
    const user = userEvent.setup()
    mockGet({
      ...CLIENT,
      share_classes: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
                        total_issued: 100, issued_amount: null, total_paid: 100 }],
    })
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')

    await user.click(within(tile).getByRole('button', { name: 'Edit' }))
    await user.type(screen.getByLabelText('Total Amount'), '100')
    await user.click(within(tile).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1/share-classes/sc1',
      expect.objectContaining({ issued_amount: '100' })))
  })

  it('offers currency from CRs list, which is not ISO', async () => {
    const user = userEvent.setup()
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')
    await user.click(within(tile).getByRole('button', { name: 'Edit' }))

    const select = screen.getByLabelText('Currency')
    const codes = [...select.querySelectorAll('option')].map(o => o.value)

    expect(codes).toContain('RMB')      // CR's renminbi
    expect(codes).not.toContain('CNY')  // ISO's, which CR refuses
  })

  it('a company with no share capital can be given some', async () => {
    // 219 client companies are in this state, and it is what stops them
    // filing. Editing alone would never unblock one.
    const user = userEvent.setup()
    mockGet({ ...CLIENT, share_classes: [] })
    api.post.mockResolvedValue({ id: 'sc9' })
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')

    await user.click(within(tile).getByRole('button', { name: /Add a class/ }))
    await user.type(screen.getByLabelText('Class of Shares'), 'Ordinary')
    await user.selectOptions(screen.getByLabelText('Currency'), 'HKD')
    await user.type(screen.getByLabelText('Total Number'), '100')
    await user.type(screen.getByLabelText('Total Amount'), '100')
    await user.type(screen.getByLabelText(/Total Amount Paid up/), '100')
    await user.click(within(tile).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/companies/e1/share-classes',
      expect.objectContaining({ class_name: 'Ordinary', currency: 'HKD' })))
  })

  it('says so plainly when a company has no share capital at all', async () => {
    // 219 client companies are in this state and cannot produce a return.
    mockGet({ ...CLIENT, share_classes: [] })
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')

    expect(within(tile).getByText(/No share capital recorded/)).toBeInTheDocument()
  })

  // -- Statutory records (OQ-3) --------------------------------------------

  it('lists every register NAR1 s16 asks about, answered or not', async () => {
    renderPage()
    const tile = (await screen.findByText(/Statutory Records/)).closest('.card')

    expect(within(tile).getByText('Register of Members')).toBeInTheDocument()
    // A register with nowhere recorded is the answer s16 needs to SHOW.
    expect(within(tile).getByText('Register of Charges')).toBeInTheDocument()
  })

  it('repoints a register and refetches', async () => {
    const user = userEvent.setup()
    renderPage()
    const tile = (await screen.findByText(/Statutory Records/)).closest('.card')

    const select = within(tile).getByLabelText('Register of Charges')
    await user.selectOptions(select, 'addr-ro')

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      '/companies/e1/record-locations/SC', { address_id: 'addr-ro' }))
  })

  it('can record that a register is kept nowhere', async () => {
    const user = userEvent.setup()
    renderPage()
    const tile = (await screen.findByText(/Statutory Records/)).closest('.card')

    await user.selectOptions(within(tile).getByLabelText('Register of Members'), '')

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      '/companies/e1/record-locations/SM', { address_id: null }))
  })

  // -- Party tiles (B3, B4, B10) -------------------------------------------

  it('shows a director\'s email and correspondence address (B3)', async () => {
    // "Appointing director" vs "director" was the question; the substantive
    // half of it was that a director's contact details were not shown at all.
    renderPage()
    const tile = (await screen.findByText(/Director\(s\)/)).closest('.card')

    expect(within(tile).getByText('js@x.com')).toBeInTheDocument()
    expect(within(tile).getByText(/Care of GSHK/)).toBeInTheDocument()
    expect(within(tile).getByText(/Flat 3B/)).toBeInTheDocument()
  })

  it('shows an address for a body-corporate shareholder (B4)', async () => {
    mockGet({
      ...CLIENT,
      shareholders: [{
        id: 's1', shares_held: 100, amount_paid: 100,
        corporate_entity_id: 'e9',
        corporate_entity: {
          id: 'e9', company_name: 'Asia BC Ltd',
          registered_address: { line1: 'Suite 900', city: 'CENTRAL', country: 'HK' },
        },
        share_classes: { class_name: 'Ordinary', currency: 'HKD' },
      }],
    })
    renderPage()
    const tile = (await screen.findByText(/Shareholder\(s\)/)).closest('.card')

    expect(within(tile).getByText(/Suite 900/)).toBeInTheDocument()
    // CR's shareCapitalList wants the class and currency beside the holding.
    expect(within(tile).getByText('Ordinary')).toBeInTheDocument()
    expect(within(tile).getByText('HKD')).toBeInTheDocument()
  })

  it('calls a corporate party a Body Corporate (B10)', async () => {
    mockGet({
      ...CLIENT,
      shareholders: [{
        id: 's1', shares_held: 100, corporate_entity_id: 'e9',
        corporate_entity: { id: 'e9', company_name: 'Asia BC Ltd' },
      }],
    })
    renderPage()
    const tile = (await screen.findByText(/Shareholder\(s\)/)).closest('.card')

    expect(within(tile).getByText('Body Corporate')).toBeInTheDocument()
    expect(within(tile).queryByText('Corporate')).not.toBeInTheDocument()
  })

  // -- Highlighting and gating (§5.3, OQ-2) --------------------------------

  it('marks a mandatory field CR requires and nobody filled in', async () => {
    mockGet({ ...CLIENT, registered_address: { line1: 'Unit 12A', country: '' } })
    renderPage()
    await findInfoCard()

    expect(await screen.findByText(/requires this on the return/)).toBeInTheDocument()
  })

  it('marks a value longer than CR accepts', async () => {
    mockGet({
      ...CLIENT,
      registered_address: { line1: 'x'.repeat(75), country: 'HK' },
    })
    renderPage()
    await findInfoCard()

    expect(await screen.findByText(/75 characters/)).toBeInTheDocument()
  })

  it('never highlights a field CR does not require', async () => {
    mockGet({ ...CLIENT, business_nature_code: null, business_nature_desc: null })
    renderPage()
    await findInfoCard()

    expect(screen.queryByText(/requires this on the return/)).not.toBeInTheDocument()
  })

  it('refuses to open a case for a company that cannot produce a return', async () => {
    mockGet({
      ...CLIENT,
      filing_problems: [{ field: 'share_classes',
                          message: 'No share capital is recorded.' }],
    })
    renderPage()
    await screen.findByText('Cases')

    expect(screen.getByRole('button', { name: /New case/ })).toBeDisabled()
  })

  it('says WHY it is refusing, beside the button that is refusing', async () => {
    // A disabled control with no explanation is the failure this exists to
    // avoid — and a page-level banner is a screen and a half away from the
    // button someone just pressed.
    mockGet({
      ...CLIENT,
      filing_problems: [{ field: 'share_classes',
                          message: 'No share capital is recorded.' }],
    })
    renderPage()
    const pane = (await screen.findByText('Cases')).closest('.card')

    expect(within(pane).getByText(/No share capital is recorded/)).toBeInTheDocument()
  })

  it('opens a case normally when the company is filable', async () => {
    renderPage()
    await screen.findByText('Cases')

    expect(screen.getByRole('button', { name: /New case/ })).toBeEnabled()
  })
})
