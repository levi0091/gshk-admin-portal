import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import PersonProfilePage from './PersonProfilePage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ personId: 'p1' }) }
})

vi.mock('../lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), upload: vi.fn() },
}))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'
import { _resetFormContract } from '../lib/formContract.js'
import { _resetDocumentSections } from '../lib/documentSections.js'

const PERSON = {
  id: 'p1', full_name: 'John Smith Junior', given_names: 'John Smith', surname: 'Smith',
  nationality: 'British (BNO)', date_of_birth: '1979-03-14', email: 'js@x.com',
  full_name_zh: '約翰史密夫',
  former_name: 'John Smyth', former_name_zh: '約翰史密',
  alias_en: 'Johnny', alias_zh: '阿John',
  marital_status: 'MA',
  residential_address: { line1: 'Flat 3B', city: 'Mid-Levels', country: 'HK' },
  identity_documents: [
    // A real, internally consistent HKID — the check digit is computed, so a
    // made-up one here would make every validation test meaningless.
    { id: 'i1', id_type: 'hkid', id_number: 'A123456(3)', is_primary: true,
      issuing_country: 'HK', place_of_issue: 'Hong Kong' },
    { id: 'i2', id_type: 'passport', id_number: '987654321', is_primary: false,
      issuing_country: 'UK', place_of_issue: 'London' },
  ],
  documents: [
    {
      id: 'd1', document_type_code: 'id_scan', current_version: 2,
      document_versions: [
        { id: 'v1', version_number: 1, file_name: 'hkid-front.pdf', created_at: '2024-05-02' },
        { id: 'v2', version_number: 2, file_name: 'hkid-both.pdf', created_at: '2026-06-04' },
      ],
    },
  ],
  role_rollup: [
    { relation: 'officer', entity_id: 'e1', company_name: 'Skyline Capital', role: 'director', is_current: true },
    { relation: 'officer', entity_id: 'e2', company_name: 'Harbour Tech', role: 'director', is_current: true },
    { relation: 'shareholder', entity_id: 'e1', company_name: 'Skyline Capital', is_current: true },
  ],
}

const renderPage = () => render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)

// The profile forms now read their dropdowns from /lookups, so api.get has to
// answer per-URL rather than returning the same payload for everything.
const LOOKUPS = {
  gender: [{ code: 'M', label: 'Male' }, { code: 'F', label: 'Female' }],
  nationality: [{ code: 'Dutch', label: 'Dutch' }, { code: 'British', label: 'British' }],
  marital_status: [{ code: 'SI', label: 'Single' }, { code: 'MA', label: 'Married' }],
  country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'ZA', label: 'South Africa' }],
}

// What CR requires of each person column, as GET /form-contract serves it.
const CONTRACT = {
  persons: {
    surname: { max_length: 50, mandatory: true, cr_fields: ['indvEngSname'] },
    given_names: { max_length: 110, mandatory: false, cr_fields: ['indvEngOname'] },
    full_name_zh: { max_length: 50, mandatory: false, cr_fields: ['indvChiName'] },
    former_name: { max_length: 150, mandatory: false, cr_fields: ['indvPrevEngName'] },
    alias_en: { max_length: 150, mandatory: false, cr_fields: ['indvAlsEngName'] },
    email: { max_length: 60, mandatory: false, cr_fields: ['indvEmailAddr'] },
  },
  addresses: {
    line1: { max_length: 60, mandatory: false, cr_fields: ['flatFlrBlk'] },
    country: { max_length: 3, mandatory: true, cr_fields: ['ctryRegion'] },
  },
}

// The sections a person's documents are filed under, and the fields each
// identity type carries — as GET /documents/sections serves them (migration
// 036). WHICH FIELDS AN IDENTITY DOCUMENT SHOWS IS THIS PAYLOAD'S ANSWER, not
// the screen's: CR has no country box beside <hkid> and a Hong Kong identity
// card does not expire, so an HKID takes a number and nothing else.
const SECTIONS = {
  sections: [
    {
      key: 'identity', label: 'Identity Documents', is_identity: true,
      description: 'Passport, HKID and other identity documents',
      file_required: false,
      types: [
        { code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
        { code: 'id_passport', label: 'Passport', id_type: 'passport' },
        { code: 'id_china_id', label: 'Mainland China Identity Card', id_type: 'china_id' },
        { code: 'id_other', label: 'Other Identity Document', id_type: 'other' },
      ],
    },
    {
      key: 'address_proof', label: 'Proof of Address', is_identity: false,
      description: 'Evidence of the residential address on file',
      file_required: true,
      types: [
        { code: 'addr_utility_bill', label: 'Utility Bill', id_type: null },
        { code: 'addr_bank_statement', label: 'Bank Statement', id_type: null },
      ],
    },
    {
      key: 'internal', label: 'Other Documents', is_identity: false,
      description: 'Anything that does not belong to a section above',
      file_required: true,
      types: [{ code: 'other', label: 'Other', id_type: null }],
    },
  ],
  identity_fields: {
    hkid: { fields: ['id_number'], required: ['id_number'] },
    passport: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number', 'issuing_country'],
    },
    china_id: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number'],
    },
    other: {
      fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
      required: ['id_number'],
    },
  },
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

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetFormContract()
  _resetDocumentSections()
  mockGet(PERSON)
  api.patch.mockResolvedValue({})
  api.upload.mockResolvedValue({ id: 'i9' })
})

describe('PersonProfilePage', () => {
  it('renders personal information and residential address', async () => {
    renderPage()
    await screen.findByText('Personal Information')
    expect(screen.getByText('British (BNO)')).toBeInTheDocument()
    // The residential address renders as the separate lines CR receives — this
    // is the address a NAR1 files for the director, and a joined string hides
    // whether any single line is over CR's 60-character limit.
    expect(screen.getByText('Flat 3B')).toBeInTheDocument()
    expect(screen.getByText('Mid-Levels')).toBeInTheDocument()
  })

  it('shows role pills counted per relation in the header', async () => {
    renderPage()
    await screen.findByText('Personal Information')
    // two director appointments, one shareholding
    expect(screen.getByText('Director ×2')).toBeInTheDocument()
    expect(screen.getByText('Shareholder ×1')).toBeInTheDocument()
  })

  it('lists identity documents with the primary flagged', async () => {
    renderPage()
    await screen.findByText('Personal Information')
    expect(screen.getByText('A123456(3)')).toBeInTheDocument()
    expect(screen.getByText('987654321')).toBeInTheDocument()
    expect(screen.getByText('PRIMARY')).toBeInTheDocument()
  })

  it('groups document history by type with current + superseded versions', async () => {
    renderPage()
    await screen.findByText('Document History')
    expect(screen.getByText('2 versions')).toBeInTheDocument()
    // newest version is CURRENT, older preserved as SUPERSEDED
    expect(screen.getByText('CURRENT')).toBeInTheDocument()
    expect(screen.getByText('SUPERSEDED')).toBeInTheDocument()
    expect(screen.getByText(/v2 · hkid-both\.pdf/)).toBeInTheDocument()
    expect(screen.getByText(/v1 · hkid-front\.pdf/)).toBeInTheDocument()
  })

  it('shows the role roll-up read-only and links out to each company', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Appointments & Roles')
    expect(screen.getByText(/Read-only here/)).toBeInTheDocument()
    expect(screen.getByText('Director — Skyline Capital')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Open →' })[1])
    expect(navigate).toHaveBeenCalledWith('/companies/e2')
  })

  it('edits a person field and PATCHes only what changed', async () => {
    const user = userEvent.setup()
    renderPage()
    // Identity documents carry their own Edit buttons now — scope to the card.
    const card = (await screen.findByText('Personal Information')).closest('.card')
    await user.click(within(card).getByRole('button', { name: 'Edit' }))

    const occupation = screen.getByLabelText('Occupation')
    await user.type(occupation, 'Company Director')
    await user.click(within(card).getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/persons/p1', { occupation: 'Company Director' })
    })
  })

  it('renders an error state when the fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load person: boom/)).toBeInTheDocument()
  })
})

/**
 * Block 6 — the Natural Person Registry, in NAR1's own words.
 *
 * The labels are not cosmetic. "Given Names" and CR's "Other Names" are the
 * same field, and an operator reading the form and the screen side by side
 * had no way to know that.
 */
describe('PersonProfilePage — the CR form fields', () => {
  const openEdit = async (user) => {
    await screen.findByText('Personal Information')
    const card = screen.getByText('Personal Information').closest('.card')
    await user.click(within(card).getByRole('button', { name: 'Edit' }))
    return card
  }

  // -- Removals (D3) -------------------------------------------------------

  it('no longer shows Marital Status anywhere (B11)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Personal Information')

    expect(screen.queryByText('Marital Status')).not.toBeInTheDocument()
    await openEdit(user)
    expect(screen.queryByLabelText('Marital Status')).not.toBeInTheDocument()
  })

  it('no longer shows Place of Issue (B15)', async () => {
    renderPage()
    await screen.findByText('Personal Information')

    expect(screen.queryByText('Place of Issue')).not.toBeInTheDocument()
    expect(screen.queryByText('Hong Kong')).not.toBeInTheDocument()
  })

  // -- Labels (B12, B13, §10.5) --------------------------------------------

  it('names the fields as NAR1 names them', async () => {
    renderPage()
    await screen.findByText('Personal Information')

    expect(screen.getByText('Name in English (Other Names)')).toBeInTheDocument()
    expect(screen.getByText('Name in English (Surname)')).toBeInTheDocument()
    expect(screen.getByText('Name in Chinese')).toBeInTheDocument()
    expect(screen.getByText('Email Address')).toBeInTheDocument()
    // and the Viewpoint wording is gone
    expect(screen.queryByText('Given Names')).not.toBeInTheDocument()
    expect(screen.queryByText('Former Name')).not.toBeInTheDocument()
  })

  it('shows previous names in both scripts (B12)', async () => {
    renderPage()
    await screen.findByText('Personal Information')

    expect(screen.getByText('Previous Names (English)')).toBeInTheDocument()
    expect(screen.getByText('Previous Names (Chinese)')).toBeInTheDocument()
    expect(screen.getByText('約翰史密')).toBeInTheDocument()
  })

  it('shows alias in both scripts (B12)', async () => {
    // A previous name and an alias are DIFFERENT facts. The ETL used to write
    // `former_name = FormerName or Aliases`, which filed a person's current
    // alias as a name they had abandoned.
    renderPage()
    await screen.findByText('Personal Information')

    expect(screen.getByText('Alias (English)')).toBeInTheDocument()
    expect(screen.getByText('Alias (Chinese)')).toBeInTheDocument()
    expect(screen.getByText('Johnny')).toBeInTheDocument()
    expect(screen.getByText('阿John')).toBeInTheDocument()
  })

  it('saves the new name fields', async () => {
    const user = userEvent.setup()
    renderPage()
    await openEdit(user)

    await user.clear(screen.getByLabelText('Alias (English)'))
    await user.type(screen.getByLabelText('Alias (English)'), 'JD')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith('/persons/p1', { alias_en: 'JD' }))
  })

  // -- Identity documents (B14) --------------------------------------------

  it('lets an identity document be edited', async () => {
    // Brian annotated the Edit button on this card. Until Block 4 there was
    // no write endpoint at all, so the checksum had nowhere to apply.
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[0])
    await user.clear(screen.getByLabelText(/^ID Number/))
    await user.type(screen.getByLabelText(/^ID Number/), 'AB987654(3)')
    await user.click(within(card).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/persons/p1/identity-documents/i1',
      expect.objectContaining({ id_number: 'AB987654(3)' })))
  })

  it('refuses to save an HKID whose check digit is wrong', async () => {
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')
    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[0])

    await user.clear(screen.getByLabelText(/^ID Number/))
    await user.type(screen.getByLabelText(/^ID Number/), 'Z351007(9)')

    expect(within(card).getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByText(/check digit does not match/)).toBeInTheDocument()
    expect(api.patch).not.toHaveBeenCalled()
  })

  it('points a mistyped Mainland ID at the document type, not the number', async () => {
    // 29 of the 30 unparseable rows are 18-digit Mainland China IDs filed as
    // HKID. Telling someone to fix the number would have them retype a
    // correct value until they gave up.
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')
    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[0])

    await user.clear(screen.getByLabelText(/^ID Number/))
    await user.type(screen.getByLabelText(/^ID Number/), '440782198611028063')

    expect(screen.getByText(/change the document type/)).toBeInTheDocument()
  })

  it('does not checksum a passport, because there is nothing to checksum', async () => {
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[1])
    await user.clear(screen.getByLabelText(/^ID Number/))
    await user.type(screen.getByLabelText(/^ID Number/), 'Z351007')

    expect(within(card).getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('does not offer Place of Issue in the identity document editor', async () => {
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[0])

    expect(screen.queryByLabelText('Place of Issue')).not.toBeInTheDocument()
  })

  it('flags a stored HKID that would fail, without freezing the record', async () => {
    // D4 grandfathering: 31 real rows are in this state. They are shown so
    // somebody fixes them, and every other field on the record stays editable.
    mockGet({
      ...PERSON,
      identity_documents: [{ id: 'i1', id_type: 'hkid',
                             id_number: '440782198611028063', is_primary: true }],
    })
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    expect(within(card).getByText(/change the document type/)).toBeInTheDocument()
    expect(within(card).getAllByRole('button', { name: 'Edit' })[0]).toBeEnabled()
  })

  // -- Highlighting (§5.3) --------------------------------------------------

  it('marks a person field longer than CR accepts', async () => {
    mockGet({ ...PERSON, surname: 'S'.repeat(60) })
    renderPage()
    await screen.findByText('Personal Information')

    expect(await screen.findByText(/60 characters/)).toBeInTheDocument()
  })

  it('marks a mandatory field CR requires and nobody filled in', async () => {
    mockGet({ ...PERSON, surname: '' })
    renderPage()
    await screen.findByText('Personal Information')

    expect(await screen.findByText(/requires this on the return/)).toBeInTheDocument()
  })

  it('says nothing about an empty field CR does not require', async () => {
    mockGet({ ...PERSON, alias_en: null, alias_zh: null })
    renderPage()
    await screen.findByText('Personal Information')

    expect(screen.queryByText(/requires this on the return/)).not.toBeInTheDocument()
  })
})

/**
 * Document sections (Levi 2026-09-04, migration 036).
 *
 * "The upload document button on the top right is not prominent. You should
 * have it inside the identity documents section... if there are other big
 * category documents such as proof of address then it should warrant its own
 * section... If there are no documents the section should still be there but
 * empty, and there should still be a button to add document to that section."
 */
describe('PersonProfilePage — document sections', () => {
  it('renders a section per category, empty ones included', async () => {
    renderPage()
    await screen.findByText(/Identity Documents/)

    expect(screen.getByText('Proof of Address')).toBeInTheDocument()
    expect(screen.getByText('Other Documents')).toBeInTheDocument()
    // Nothing has been uploaded as proof of address, and the section is still
    // there — an empty section with a button is how the first one gets added.
    const proof = screen.getByText('Proof of Address').closest('.card')
    expect(within(proof).getByText('Nothing uploaded yet.')).toBeInTheDocument()
    expect(within(proof).getByRole('button', { name: 'Upload Document' })).toBeInTheDocument()
  })

  it('drops the page-header Upload button in favour of per-section ones', async () => {
    // One button in the header offered every document type at once from a place
    // that named no section — which is how a passport got filed as an
    // "Identity Document Scan".
    renderPage()
    await screen.findByText(/Identity Documents/)

    const header = document.querySelector('.pg-hdr')
    expect(within(header).queryByRole('button', { name: 'Upload Document' })).toBeNull()
  })

  it('names the identity section button for what it actually does', async () => {
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')
    expect(within(card).getByRole('button', { name: 'Add Identity Document' }))
      .toBeInTheDocument()
  })

  it('opens the identity dialog scoped to the identity types', async () => {
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    await user.click(within(card).getByRole('button', { name: 'Add Identity Document' }))
    const dialog = await screen.findByRole('dialog', { name: 'Identity Document' })
    expect(within(dialog).getByRole('option', { name: 'Passport' })).toBeInTheDocument()
    // A Utility Bill is not an identity document and is not offered here.
    expect(within(dialog).queryByRole('option', { name: 'Utility Bill' })).toBeNull()
  })

  it('opens a section upload scoped to that section only', async () => {
    const user = userEvent.setup()
    renderPage()
    const proof = (await screen.findByText('Proof of Address')).closest('.card')

    await user.click(within(proof).getByRole('button', { name: 'Upload Document' }))
    await screen.findByRole('dialog', { name: 'Upload Document' })
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/documents/types?owner_type=person&category=address_proof'))
  })

  it('says "unavailable", not "none", when the sections cannot be loaded', async () => {
    // An empty list is indistinguishable from a failed fetch, and a screen that
    // treats them the same renders a director as holding no identity documents
    // because a lookup call timed out.
    api.get.mockImplementation(url => {
      if (url === '/lookups') return Promise.resolve(LOOKUPS)
      if (url === '/form-contract') return Promise.resolve(CONTRACT)
      if (url.startsWith('/documents/sections')) return Promise.reject(new Error('gateway'))
      return Promise.resolve(PERSON)
    })
    renderPage()
    await screen.findByText('Personal Information')

    expect(await screen.findByText(/not because there\s+are none/)).toBeInTheDocument()
    expect(screen.queryByText(/No identity documents on file/)).toBeNull()
  })
})

/** Levi 2026-09-04, points 3 and 5. */
describe('PersonProfilePage — the identity card and the history', () => {
  it('no longer shows a Renewal Reminder (nobody asked for it)', async () => {
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    expect(screen.queryByText('Renewal Reminder')).not.toBeInTheDocument()
    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[0])
    expect(screen.queryByLabelText(/Renewal Reminder/)).not.toBeInTheDocument()
  })

  it('names the identity document by type rather than shouting the code', async () => {
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    expect(within(card).getByText('Hong Kong Identity Card')).toBeInTheDocument()
    expect(within(card).getByText('Passport')).toBeInTheDocument()
  })

  it('offers an HKID no expiry date, because a Hong Kong ID card has none', async () => {
    const user = userEvent.setup()
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')

    await user.click(within(card).getAllByRole('button', { name: 'Edit' })[0])
    expect(screen.queryByLabelText('Expiry Date')).not.toBeInTheDocument()
  })

  it('still shows a stored value the type does not carry, rather than hiding it', async () => {
    // Viewpoint HKID rows carry an issuing country CR has no box for. Dropping
    // it from the screen would be quietly discarding data the operator can
    // still see in the source system.
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')
    expect(within(card).getAllByText('Issuing Country/Region').length).toBe(2)
  })

  it('links straight to the scan attached to an identity document', async () => {
    mockGet({
      ...PERSON,
      identity_documents: [{ id: 'i1', id_type: 'passport', id_number: '987654321',
                             issuing_country: 'GB', scan_document_id: 'doc-9' }],
    })
    renderPage()
    const card = (await screen.findByText(/Identity Documents/)).closest('.card')
    expect(within(card).getByRole('button', { name: 'Scan' })).toBeInTheDocument()
  })

  it('names the section and the exact upload time in Document History', async () => {
    mockGet({
      ...PERSON,
      documents: [{
        id: 'd1', document_type_code: 'id_passport', current_version: 1,
        document_types: { code: 'id_passport', label: 'Passport', category: 'identity' },
        document_versions: [{ id: 'v1', version_number: 1, file_name: 'p.pdf',
                              created_at: '2026-06-04T09:30:00Z' }],
      }],
    })
    renderPage()
    await screen.findByText('Document History')

    const history = screen.getByText('Document History').closest('.card')
    // "Passport" alone does not say whether it was filed as identity or as
    // proof of address, and the two now live in different sections.
    expect(within(history).getByText('Identity Documents')).toBeInTheDocument()
    expect(within(history).getByText(/v1 · p\.pdf/)).toBeInTheDocument()
    // Hong Kong wall-clock: 09:30 UTC is 17:30 the same day in HK.
    expect(within(history).getByText(/17:30/)).toBeInTheDocument()
  })
})
