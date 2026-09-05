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
import { _resetDocumentSections } from '../lib/documentSections.js'

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
    id: 'd1', document_type_code: 'coi', current_version: 1, status: 'active',
    file_name: 'brand-guideline-v3.pdf', updated_at: '2026-06-04T09:30:00Z',
    document_types: { code: 'coi', label: 'Certificate of Incorporation',
                      category: 'certificate' },
    document_versions: [{ id: 'v1', version_number: 1,
                          file_name: 'brand-guideline-v3.pdf',
                          created_at: '2026-06-04T09:30:00Z' }],
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
  // `record_locations` is still returned by the API and deliberately not
  // rendered — see the note where the Statutory Records tests used to be.
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
  share_class_name: [{ code: 'Ordinary', label: 'Ordinary' },
                     { code: 'Ordinary A', label: 'Ordinary A' },
                     { code: 'Preference', label: 'Preference' }],
  bo_owner_type: [{ code: 'ubo', label: 'Ultimate Beneficial Owner' },
                  { code: 'significant_controller', label: 'Significant Controller' }],
  bo_nature_of_control: [
    { code: 'over_25_percent',
      label: 'Holds more than 25% of the issued shares of the company' },
    { code: 'significant_influence',
      label: 'Has the right to exercise, or actually exercises, significant '
           + 'influence or control over the company' }],
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

// A company's documents are filed under sections exactly as a person's are
// (migration 036). `certificate` is the one the fixture document lands in.
const SECTIONS = {
  sections: [
    { key: 'certificate', label: 'Certificates', is_identity: false,
      description: 'Certificates issued for this company', file_required: true,
      types: [{ code: 'coi', label: 'Certificate of Incorporation', id_type: null }] },
    { key: 'address_proof', label: 'Proof of Address', is_identity: false,
      description: 'Evidence of the registered address on file', file_required: true,
      types: [{ code: 'addr_utility_bill', label: 'Utility Bill', id_type: null }] },
  ],
  identity_fields: {},
}

const mockGet = (data) =>
  api.get.mockImplementation(url => {
    if (url === '/lookups') return Promise.resolve(LOOKUPS)
    if (url === '/form-contract') return Promise.resolve(CONTRACT)
    if (url.startsWith('/documents/sections')) return Promise.resolve(SECTIONS)
    if (url.startsWith('/documents/types')) {
      const category = new URL(url, 'http://x').searchParams.get('category')
      return Promise.resolve(
        SECTIONS.sections.find(s => s.key === category)?.types || [])
    }
    return Promise.resolve(data)
  })

// Document History tags each group with its SECTION, so a heading appears
// twice on the page. The section card is the one whose match is a `.card-title`.
const sectionCard = label =>
  screen.getAllByText(label)
    .filter(el => el.classList.contains('card-title') || el.closest('.card-title'))[0]
    .closest('.card')

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetFormContract()
  _resetDocumentSections()
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
    await screen.findByText('Document History')
    const certs = sectionCard('Certificates')
    expect(within(certs).getByText('Certificate of Incorporation')).toBeInTheDocument()
    expect(within(certs).getByText(/brand-guideline-v3\.pdf/)).toBeInTheDocument()
    expect(within(certs).getByRole('button', { name: 'Download' })).toBeInTheDocument()
  })

  // Levi 2026-09-04: "this is the same for the body corporation upload document
  // features" — download and remove from the section, not only the history.
  it('files company documents into sections, empty ones included', async () => {
    renderPage()
    await screen.findByText('Document History')

    expect(sectionCard('Certificates')).toBeInTheDocument()
    const proof = sectionCard('Proof of Address')
    expect(within(proof).getByText('Nothing uploaded yet.')).toBeInTheDocument()
    expect(within(proof).getByRole('button', { name: 'Upload Document' })).toBeInTheDocument()

    // The page-header button offered every type at once and is gone.
    const header = document.querySelector('.pg-hdr')
    expect(within(header).queryByRole('button', { name: 'Upload Document' })).toBeNull()
  })

  it('soft-deletes a company document from its section', async () => {
    const user = userEvent.setup()
    api.del.mockResolvedValue({})
    renderPage()
    await screen.findByText('Document History')

    await user.click(within(sectionCard('Certificates')).getByRole('button', { name: 'Remove' }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Remove document' })
    expect(within(dialog).getByText(/stays in Document History/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(api.del).toHaveBeenCalledWith('/documents/d1'))
  })

  it('downloads the VERSION that was clicked, not always the current one', async () => {
    // Every Download button in the history used to sign the CURRENT version's
    // path, so v1 and v2 both handed back v2 under two different file names.
    // The older bytes have always been in `document_versions.storage_path`;
    // nothing read them.
    const user = userEvent.setup()
    mockGet({
      ...CLIENT,
      documents: [{
        id: 'd1', document_type_code: 'coi', current_version: 2, status: 'active',
        file_name: 'coi-v2.pdf', updated_at: '2026-06-04T09:30:00Z',
        document_types: { code: 'coi', label: 'Certificate of Incorporation',
                          category: 'certificate' },
        document_versions: [
          { id: 'v1', version_number: 1, file_name: 'coi-v1.pdf',
            created_at: '2026-01-05T09:30:00Z' },
          { id: 'v2', version_number: 2, file_name: 'coi-v2.pdf',
            created_at: '2026-06-04T09:30:00Z' },
        ],
      }],
    })
    renderPage()
    await screen.findByText('Document History')

    const superseded = (await screen.findByText('SUPERSEDED')).closest('.doc-ver')
    await user.click(within(superseded).getByRole('button', { name: 'Download' }))

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/documents/d1/versions/1/download'))
  })

  it('sets the document TYPE in its own colour, in both places (item 13)', async () => {
    // Levi 2026-09-04: "make it clearer maybe in bigger font or color to make
    // it more prominent the type of document it is. maybe a different document
    // type a different colour". The colour is keyed to the type CODE, so the
    // same type reads the same in its section and in the history.
    renderPage()
    await screen.findByText('Document History')

    const chips = document.querySelectorAll('.doc-type-chip')
    expect(chips.length).toBeGreaterThanOrEqual(2)
    const classes = [...chips].map(
      c => [...c.classList].find(n => n.startsWith('doc-type-c')))
    expect(new Set(classes).size).toBe(1)
    expect(chips[0].textContent).toBe('Certificate of Incorporation')
  })

  it('scopes the upload picker to the section it was opened from', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Document History')

    await user.click(
      within(sectionCard('Proof of Address')).getByRole('button', { name: 'Upload Document' }))
    await screen.findByRole('dialog', { name: 'Upload Document' })
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/documents/types?owner_type=company&category=address_proof'))
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
    // Twice on purpose: the class NAME now heads its own block as well as
    // appearing under CR's "Class of Shares" heading. With several classes,
    // omitting the heading made every block start with an empty title bar
    // carrying nothing but an Edit button.
    expect(within(tile).getAllByText('Ordinary').length).toBeGreaterThan(0)
    expect(within(tile).getAllByText('HKD').length).toBeGreaterThan(0)
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
    const dialog = await screen.findByRole('dialog', { name: 'Edit Class of Shares' })
    await user.type(within(dialog).getByLabelText('Total Amount'), '100')
    await user.click(within(dialog).getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1/share-classes/sc1',
      expect.objectContaining({ issued_amount: '100' })))
  })

  it('edits a share class in a DIALOG, not inline under the row', async () => {
    // The inline editor put Cancel and Save in a `.f-group.full` — a column
    // flex box — so they stacked vertically and centred, the only pair of
    // buttons in the app that did not sit side by side at the bottom right.
    const user = userEvent.setup()
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')
    await user.click(within(tile).getByRole('button', { name: 'Edit' }))

    const dialog = await screen.findByRole('dialog', { name: 'Edit Class of Shares' })
    const footer = dialog.querySelector('.modal-footer')
    expect(within(footer).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(within(footer).getByRole('button', { name: 'Save Changes' })).toBeInTheDocument()
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

  it('offers Class of Shares as a list, with a free-text escape', async () => {
    // `share_classes` has a UNIQUE (entity_id, class_name), so "Ordinary" and
    // "ORDINARY" typed on two different days become two classes of one class
    // and Schedule 1 files the same members twice under both. CR validates
    // nothing here — `clsOfShares` is free text — so the list cannot be closed.
    const user = userEvent.setup()
    mockGet({ ...CLIENT, share_classes: [] })
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')
    await user.click(within(tile).getByRole('button', { name: /Add a class/ }))

    const picker = screen.getByLabelText('Class of Shares')
    const names = [...picker.querySelectorAll('option')].map(o => o.value)
    expect(names).toEqual(expect.arrayContaining(
      ['Ordinary', 'Ordinary A', 'Preference']))

    // "Other…" reveals a text box rather than refusing an unusual class.
    await user.selectOptions(picker, '__other__')
    const free = screen.getByLabelText('Class of Shares (other)')
    await user.type(free, 'Redeemable Preference')
    expect(free).toHaveValue('Redeemable Preference')
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
    const dialog = await screen.findByRole('dialog', { name: 'Add Class of Shares' })
    await user.selectOptions(within(dialog).getByLabelText('Class of Shares'), 'Ordinary')
    await user.selectOptions(within(dialog).getByLabelText('Currency'), 'HKD')
    await user.type(within(dialog).getByLabelText('Total Number'), '100')
    await user.type(within(dialog).getByLabelText('Total Amount'), '100')
    await user.type(within(dialog).getByLabelText(/Total Amount Paid up/), '100')
    await user.click(within(dialog).getByRole('button', { name: 'Add Class' }))

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

  // -- Statutory records: REMOVED 2026-09-02 -------------------------------
  //
  // The tile listed 13 registers under "Section 16 — where each register is
  // kept". CR's NAR1 asks nothing of the sort:
  //
  //   * the question is at s15, not s16 — s16 is the private-company
  //     STATEMENT (`field_map.py`: "statement_private": "cb_4_P.8");
  //   * it is ONE description and ONE address (`records_description`,
  //     `records_address`), not thirteen — CR's XML schema carries exactly two
  //     fields, `companyRecord` and `address`;
  //   * and it is asked ONLY when the records are NOT kept at the registered
  //     office. Every GSHK client keeps them at GSHK, which IS their
  //     registered office, so the honest answer for this book is to leave it
  //     blank.
  //
  // Levi 2026-09-02: "i dont think the statutory records are required." The
  // `entity_record_locations` table and its endpoints are LEFT IN PLACE — the
  // s15 concept is real for the minority of companies whose records sit
  // elsewhere, and dropping an applied migration to tidy a screen would cost
  // more than it saves.

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

/**
 * A role that may READ a company but not change it.
 *
 * THE RULE IS "DO NOT RENDER IT" (Levi 2026-09-04, reversing the disabled form
 * shipped hours earlier): "we should not even show the edit, add or remove
 * button. do not just make it disabled you should not even render it if it
 * cannot be clicked." So every assertion here is an ABSENCE — and the one
 * assertion that is not is the banner, which is what stops the absence reading
 * as a missing feature.
 */
describe('CompanyProfilePage — a read-only role', () => {
  const holding = (...perms) => (module, permission) =>
    perms.includes(`${module}:${permission}`)

  beforeEach(() => {
    // The tester role exactly: companies (read), persons (read+write), and no
    // `documents` or `nar1` at all.
    auth = {
      isSuperAdmin: false,
      hasPermission: holding('companies:read', 'persons:read', 'persons:write'),
      profile: { display_name: 'Tester', role_name: 'tester' },
    }
  })

  it('says once, at the top, that the screen is read-only', async () => {
    renderPage()
    await screen.findByText('Company Information')

    const note = screen.getAllByRole('note')
      .find(n => /Read-only/.test(n.textContent))
    expect(note).toBeTruthy()
    expect(note).toHaveTextContent('companies (write)')
  })

  it('still shows the company — reading is the whole point', async () => {
    renderPage()
    await screen.findByText('Company Information')
    // The name is in the header and in the breadcrumb; one of each is enough.
    expect(screen.getAllByText('Skyline Capital').length).toBeGreaterThan(0)
    expect(screen.getByText('Director(s)')).toBeInTheDocument()
  })

  it('renders NO Edit button on Company Information at all', async () => {
    renderPage()
    const card = (await screen.findByText('Company Information')).closest('.card')

    expect(within(card).queryByRole('button', { name: /^Edit$/ }))
      .not.toBeInTheDocument()
  })

  it('renders no clickable switch for Is Client / Is Corporate Party', async () => {
    renderPage()
    await screen.findByText('Company Information')

    expect(screen.queryByRole('switch', { name: 'Is Client' })).not.toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: 'Is Corporate Party' }))
      .not.toBeInTheDocument()
  })

  it('still SHOWS which flags are set — they decide what the page contains', async () => {
    // The one exception to hiding, and it is not a control: which flags are on
    // is why the client tiles and the Cases pane are there at all, so a reader
    // who cannot see them cannot tell a client from a corporate party.
    renderPage()
    await screen.findByText('Company Information')

    const flag = screen.getByTestId('flag-Is Client')
    expect(flag).toHaveTextContent('Is Client')
    expect(flag).toHaveTextContent('Yes')
    expect(screen.getByTestId('flag-Is Corporate Party')).toHaveTextContent('No')
  })

  it('renders no Add, Edit or Remove on any party tile', async () => {
    renderPage()
    const tile = (await screen.findByText('Director(s)')).closest('.card')

    expect(within(tile).queryByRole('button', { name: /\+ Add/ })).not.toBeInTheDocument()
    expect(within(tile).queryByRole('button', { name: /^Edit$/ })).not.toBeInTheDocument()
    expect(within(tile).queryByRole('button', { name: /^Remove$/ })).not.toBeInTheDocument()
    // The party itself is still listed — that is the reading half.
    expect(within(tile).getByText('John Smith')).toBeInTheDocument()
  })

  it('renders no Add or Edit on share capital, but still lists the classes', async () => {
    renderPage()
    const tile = (await screen.findByText(/Share Capital/)).closest('.card')

    expect(within(tile).queryByRole('button', { name: /Add a class/ }))
      .not.toBeInTheDocument()
    expect(within(tile).queryByRole('button', { name: /^Edit$/ })).not.toBeInTheDocument()
    // "Ordinary" is both the block heading and the Class of Shares row.
    expect(within(tile).getAllByText('Ordinary').length).toBeGreaterThan(0)
  })

  it('renders no + New case, which is a different module again', async () => {
    // `nar1:write`, not `companies:write` — a role that may edit a company
    // profile is not thereby entitled to drive a statutory filing.
    renderPage()
    await screen.findByText('Cases')

    expect(screen.queryByRole('button', { name: /New case/ })).not.toBeInTheDocument()
  })

  it('renders no upload button — a THIRD module, asked separately', async () => {
    // `documents:write`. A role can hold `companies:write` and still not be
    // allowed to file documents, and vice versa.
    renderPage()
    await screen.findByText('Document History')
    const card = sectionCard('Certificates')

    expect(within(card).queryByRole('button', { name: /Upload Document/ }))
      .not.toBeInTheDocument()
    // The SECTION still renders: what is on file is a fact worth reading.
    expect(card).toBeInTheDocument()
  })

  it('renders no Download or Remove beside a filed document', async () => {
    // Three separate grants: `documents:read` downloads, `documents:delete`
    // removes. This role holds neither.
    renderPage()
    await screen.findByText('Document History')
    const card = sectionCard('Certificates')

    expect(within(card).queryByRole('button', { name: 'Download' }))
      .not.toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: 'Remove' }))
      .not.toBeInTheDocument()
    // ...and the document is still named.
    expect(within(card).getByText('Certificate of Incorporation')).toBeInTheDocument()
  })

  it('lets a role that holds documents:write upload, on a company it cannot edit', async () => {
    // The permissions really are independent — this is the proof that the
    // screen asks each of them rather than gating everything on one.
    auth.hasPermission = holding('companies:read', 'documents:read',
                                 'documents:write')
    renderPage()
    await screen.findByText('Document History')
    const card = sectionCard('Certificates')

    expect(within(card).getByRole('button', { name: /Upload Document/ }))
      .toBeEnabled()
    // Download comes with documents:read; Remove needs documents:delete, which
    // this role does not hold.
    expect(within(card).getByRole('button', { name: 'Download' })).toBeEnabled()
    expect(within(card).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    // ...and still no company Edit.
    expect(within(screen.getByText('Company Information').closest('.card'))
      .queryByRole('button', { name: /^Edit$/ })).not.toBeInTheDocument()
  })
})
