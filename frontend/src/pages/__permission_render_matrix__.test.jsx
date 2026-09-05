import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * THE SCREENS, RENDERED FOR EVERY ROLE, asserting what is on them.
 *
 * `screenCapabilities.test.js` proves the RULES are right across all 8192
 * permission combinations. This proves the SCREENS obey them — that a
 * capability being false actually removes a button from the DOM rather than
 * merely disabling it, which is the whole of Levi's 2026-09-04 correction:
 * "we should not even show the edit, add or remove button. do not just make it
 * disabled you should not even render it if it cannot be clicked."
 *
 * Every expectation below is therefore about PRESENCE, and the negative case
 * asserts `not.toBeInTheDocument()` — never `toBeDisabled()`, which is exactly
 * what this replaced.
 */
const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigate,
    useParams: () => ({ companyId: 'e1', personId: 'p1' }),
  }
})

vi.mock('../lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn(),
         upload: vi.fn() },
}))

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'
import { _resetFormContract } from '../lib/formContract.js'
import { _resetDocumentSections } from '../lib/documentSections.js'
import CompanyProfilePage from './CompanyProfilePage.jsx'
import PersonProfilePage from './PersonProfilePage.jsx'
import CompanyRegistryPage from './CompanyRegistryPage.jsx'
import PersonsRegistryPage from './PersonsRegistryPage.jsx'

// ---------------------------------------------------------------------------
// Fixtures — the smallest shape each screen needs to draw all of its controls.

const COMPANY = {
  id: 'e1', company_name: 'Skyline Capital', br_number: '2100031',
  status: 'live', is_client: true, is_corporate_party: true,
  incorporation_place: 'HK', company_type: 'P',
  registered_address: { line1: 'Unit 12A', city: 'Central', country: 'HK' },
  contacts: [],
  filing_problems: [],
  documents: [{
    id: 'd1', document_type_code: 'coi', current_version: 1, status: 'active',
    file_name: 'coi.pdf', updated_at: '2026-06-04T09:30:00Z',
    document_types: { code: 'coi', label: 'Certificate of Incorporation',
                      category: 'certificate' },
    document_versions: [{ id: 'v1', version_number: 1, file_name: 'coi.pdf',
                          created_at: '2026-06-04T09:30:00Z' }],
  }],
  officers: [{
    id: 'o1', role: 'director', appointed_date: '2024-05-20', is_current: true,
    persons: { id: 'p1', full_name: 'John Smith' },
  }],
  shareholders: [], beneficial_owners: [], secretaries: [],
  share_classes: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
                    total_issued: 10000, issued_amount: 10000, total_paid: 10000 }],
  business_names: [],
  cases: { nar1: [], nnc1: [] },
}

const PERSON = {
  id: 'p1', full_name: 'John Smith', given_names: 'John', surname: 'Smith',
  residential_address: { line1: 'Flat 3B', city: 'Central', country: 'HK' },
  identity_documents: [{
    id: 'i1', id_type: 'hkid', id_number: 'A123456(3)', is_primary: true,
    scan_document_id: 'd9',
  }, {
    id: 'i2', id_type: 'passport', id_number: 'P998877', is_primary: false,
  }],
  documents: [{
    id: 'd2', document_type_code: 'addr_utility_bill', current_version: 1,
    status: 'active', file_name: 'bill.pdf', updated_at: '2026-06-04T09:30:00Z',
    document_types: { code: 'addr_utility_bill', label: 'Utility Bill',
                      category: 'address_proof' },
    document_versions: [{ id: 'v2', version_number: 1, file_name: 'bill.pdf',
                          created_at: '2026-06-04T09:30:00Z' }],
  }],
  roles: [],
}

const LOOKUPS = {
  cr_country: [{ code: 'HK', label: 'Hong Kong' }],
  cr_company_type: [{ code: 'P', label: 'Private' }],
  cr_business_nature: [], cr_currency: [{ code: 'HKD', label: 'HKD' }],
  share_class_name: [], country: [], gender: [], nationality: [],
  bo_owner_type: [], bo_nature_of_control: [], marital_status: [],
}

const CONTRACT = { entities: {}, addresses: {}, share_classes: {}, persons: {} }

const COMPANY_SECTIONS = {
  sections: [
    { key: 'certificate', label: 'Certificates', is_identity: false,
      description: 'Certificates issued for this company', file_required: true,
      types: [{ code: 'coi', label: 'Certificate of Incorporation', id_type: null }] },
  ],
  identity_fields: {},
}

const PERSON_SECTIONS = {
  sections: [
    { key: 'identity', label: 'Identity Documents', is_identity: true,
      description: 'Identity records', file_required: false,
      types: [{ code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
              { code: 'id_passport', label: 'Passport', id_type: 'passport' }] },
    { key: 'address_proof', label: 'Proof of Address', is_identity: false,
      description: 'Evidence of address', file_required: true,
      types: [{ code: 'addr_utility_bill', label: 'Utility Bill', id_type: null }] },
  ],
  identity_fields: {
    hkid: { fields: [{ key: 'id_number', label: 'HKID number' }], required: ['id_number'] },
    passport: { fields: [{ key: 'id_number', label: 'Passport number' }], required: ['id_number'] },
  },
}

const COMPANY_LIST = {
  total: 1, page: 1, page_size: 50,
  flag_counts: { all: 1, client: 1, corporate_party: 0, non_client: 0 },
  companies: [{ id: 'e1', company_name: 'Skyline Capital', br_number: '2100031',
                is_client: true, is_corporate_party: false, status: 'live',
                incorporation_date: '2023-08-12' }],
}

const PERSON_LIST = {
  total: 1, page: 1, page_size: 50,
  persons: [{ id: 'p1', full_name: 'John Smith', roles: [] }],
}

function mockApi(entity, sections, list) {
  api.get.mockImplementation(url => {
    const u = String(url)
    if (u === '/lookups') return Promise.resolve(LOOKUPS)
    if (u === '/form-contract') return Promise.resolve(CONTRACT)
    if (u.startsWith('/documents/sections')) return Promise.resolve(sections)
    if (u.startsWith('/documents/types')) {
      const category = new URL(u, 'http://x').searchParams.get('category')
      return Promise.resolve(
        sections.sections.find(s => s.key === category)?.types || [])
    }
    if (u.startsWith('/companies?') || u.startsWith('/persons?')) {
      return Promise.resolve(list)
    }
    return Promise.resolve(entity)
  })
}

// ---------------------------------------------------------------------------
// The roles. Every one is a real shape a Super Admin could create in Roles.

const ROLES = {
  'no permissions at all': [],
  'companies:read only': ['companies:read'],
  'companies read+write': ['companies:read', 'companies:write'],
  'persons:read only': ['persons:read'],
  'persons read+write': ['persons:read', 'persons:write'],
  'the tester role': ['companies:read', 'persons:read', 'persons:write'],
  'documents reader': ['companies:read', 'persons:read', 'documents:read'],
  'documents manager': ['companies:read', 'persons:read', 'documents:read',
                        'documents:write'],
  'documents manager who may delete': ['companies:read', 'persons:read',
                                       'documents:read', 'documents:write',
                                       'documents:delete'],
  'case worker': ['companies:read', 'nar1:read', 'nar1:write'],
  'everything': ['companies:read', 'companies:write', 'persons:read',
                 'persons:write', 'documents:read', 'documents:write',
                 'documents:delete', 'nar1:read', 'nar1:write', 'tpsi:read',
                 'tpsi:write', 'tpsi:submit', 'audit_trail:read'],
}

const authFor = perms => ({
  isSuperAdmin: false,
  hasPermission: (m, p) => perms.includes(`${m}:${p}`),
  profile: { display_name: 'Role Under Test', role_name: 'under-test' },
  profileLoading: false,
})

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetFormContract()
  _resetDocumentSections()
})

/** Is there a clickable control with this accessible name anywhere on screen? */
const has = name => screen.queryAllByRole('button', { name }).length > 0

// ---------------------------------------------------------------------------

describe('Company profile — controls present per role', () => {
  const cases = [
    // role,                            edit,  parties, shares, upload, download, remove, newCase
    ['no permissions at all',           false, false,   false,  false,  false,    false,  false],
    ['companies:read only',             false, false,   false,  false,  false,    false,  false],
    ['companies read+write',            true,  true,    true,   false,  false,    false,  false],
    ['the tester role',                 false, false,   false,  false,  false,    false,  false],
    ['documents reader',                false, false,   false,  false,  true,     false,  false],
    ['documents manager',               false, false,   false,  true,   true,     false,  false],
    ['documents manager who may delete', false, false,  false,  true,   true,     true,   false],
    ['case worker',                     false, false,   false,  false,  false,    false,  true],
    ['everything',                      true,  true,    true,   true,   true,     true,   true],
  ]

  it.each(cases)('%s', async (role, edit, parties, shares, upload, download,
                              remove, newCase) => {
    auth = authFor(ROLES[role])
    mockApi(COMPANY, COMPANY_SECTIONS, COMPANY_LIST)
    render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)
    await screen.findByText('Document History')

    // `Edit` appears on Company Information AND Corporate Party Details AND
    // each share class, so counting them apart is not the point — whether ANY
    // exists is.
    expect(has(/^Edit$/), 'Edit').toBe(edit || shares || parties)
    expect(has(/^\+ Add$/), '+ Add (party)').toBe(parties)
    expect(has(/Add a class/), 'Add a class').toBe(shares)
    expect(has(/Upload Document/), 'Upload Document').toBe(upload)
    expect(has(/^Download$/), 'Download').toBe(download)
    expect(has(/^Remove$/), 'Remove').toBe(remove || parties)
    expect(has(/New case/), 'New case').toBe(newCase)
  })

  it('shows the read-only banner exactly when the company cannot be edited', async () => {
    for (const [role, perms] of Object.entries(ROLES)) {
      auth = authFor(perms)
      mockApi(COMPANY, COMPANY_SECTIONS, COMPANY_LIST)
      const { unmount } = render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)
      await screen.findByText('Document History')

      const banner = screen.queryAllByRole('note')
        .some(n => /Read-only/.test(n.textContent))
      expect(banner, role).toBe(!perms.includes('companies:write'))
      unmount()
      _resetLookups(); _resetFormContract(); _resetDocumentSections()
    }
  })
})

describe('Person profile — controls present per role', () => {
  const cases = [
    // role,                             editPerson, addId, upload, download, remove
    ['no permissions at all',            false,      false, false,  false,    false],
    ['persons:read only',                false,      false, false,  false,    false],
    ['persons read+write',               true,       true,  false,  false,    false],
    ['the tester role',                  true,       true,  false,  false,    false],
    ['documents reader',                 false,      false, false,  true,     false],
    ['documents manager',                false,      false, true,   true,     false],
    ['documents manager who may delete', false,      false, true,   true,     true],
    ['everything',                       true,       true,  true,   true,     true],
  ]

  it.each(cases)('%s', async (role, editPerson, addId, upload, download, remove) => {
    auth = authFor(ROLES[role])
    mockApi(PERSON, PERSON_SECTIONS, PERSON_LIST)
    render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)
    await screen.findByText('Document History')

    expect(has(/^Edit$/), 'Edit').toBe(editPerson)
    expect(has(/Add Identity Document/), 'Add Identity Document').toBe(addId)
    expect(has(/Upload Document/), 'Upload Document').toBe(upload)
    expect(has(/^Download$/), 'Download (filed document)').toBe(download)
    expect(has(/Download scan/), 'Download scan').toBe(download)
    // `Remove` is on identity records (persons:write) and on filed documents
    // (documents:delete) — either one puts a Remove on the screen.
    expect(has(/^Remove$/), 'Remove').toBe(remove || editPerson)
    // "Make primary" only exists where there is a second document to promote.
    expect(has(/Make primary/), 'Make primary').toBe(editPerson)
  })

  it('shows the read-only banner exactly when the person cannot be edited', async () => {
    for (const [role, perms] of Object.entries(ROLES)) {
      auth = authFor(perms)
      mockApi(PERSON, PERSON_SECTIONS, PERSON_LIST)
      const { unmount } = render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)
      await screen.findByText('Document History')

      const banner = screen.queryAllByRole('note')
        .some(n => /Read-only/.test(n.textContent) && /persons \(write\)/.test(n.textContent))
      expect(banner, role).toBe(!perms.includes('persons:write'))
      unmount()
      _resetLookups(); _resetFormContract(); _resetDocumentSections()
    }
  })
})

describe('Registries — the Add button per role', () => {
  it.each([
    ['no permissions at all', false],
    ['companies:read only', false],
    ['companies read+write', true],
    ['the tester role', false],
    ['everything', true],
  ])('company registry, %s', async (role, expected) => {
    auth = authFor(ROLES[role])
    mockApi(COMPANY, COMPANY_SECTIONS, COMPANY_LIST)
    render(<MemoryRouter><CompanyRegistryPage /></MemoryRouter>)
    await screen.findByText('Skyline Capital')

    expect(has(/Add Company/)).toBe(expected)
    // The absence is always accounted for.
    expect(screen.queryAllByRole('note')
      .some(n => /Read-only/.test(n.textContent))).toBe(!expected)
  })

  it.each([
    ['no permissions at all', false],
    ['persons:read only', false],
    ['persons read+write', true],
    ['the tester role', true],
    ['everything', true],
  ])('persons registry, %s', async (role, expected) => {
    auth = authFor(ROLES[role])
    mockApi(PERSON, PERSON_SECTIONS, PERSON_LIST)
    render(<MemoryRouter><PersonsRegistryPage /></MemoryRouter>)
    await screen.findByText('John Smith')

    expect(has(/Add Person/)).toBe(expected)
    expect(screen.queryAllByRole('note')
      .some(n => /Read-only/.test(n.textContent))).toBe(!expected)
  })
})

describe('nothing anywhere is merely disabled by a permission', () => {
  // THE REGRESSION GUARD for the whole change. A control withheld for a
  // PERMISSION must be absent from the DOM; `disabled` stays legitimate for a
  // DATA or transient state — a save in flight, a company whose record cannot
  // produce a filing, a pager already on the last page. Those come back on
  // their own and are explained where they sit; a permission never does.
  //
  // So: render each screen for a role holding nothing at all, and assert that
  // the only disabled buttons left are the data-driven ones named here. Adding
  // a name to this list is a deliberate act — if a permission-gated control
  // ever turns up in it, this test is the thing that says so.
  const DATA_DRIVEN = [/^Previous$/, /^Next$/]

  const screens = [
    ['company profile', CompanyProfilePage, COMPANY, COMPANY_SECTIONS, 'Document History'],
    ['person profile', PersonProfilePage, PERSON, PERSON_SECTIONS, 'Document History'],
    ['company registry', CompanyRegistryPage, COMPANY, COMPANY_SECTIONS, 'Skyline Capital'],
    ['persons registry', PersonsRegistryPage, PERSON, PERSON_SECTIONS, 'John Smith'],
  ]

  it.each(screens)('%s', async (_name, Page, entity, sections, marker) => {
    auth = authFor([])
    mockApi(entity, sections, _name.includes('company') ? COMPANY_LIST : PERSON_LIST)
    render(<MemoryRouter><Page /></MemoryRouter>)
    await screen.findByText(marker)

    const disabled = screen.queryAllByRole('button')
      .filter(b => b.hasAttribute('disabled'))
      .map(b => b.textContent.trim())
      .filter(label => !DATA_DRIVEN.some(ok => ok.test(label)))
    expect(disabled).toEqual([])
  })
})
