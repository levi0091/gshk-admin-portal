import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Look at the read-only screens, rather than at the JSX that made them.
 *
 * Removing a control changes LAYOUT, and no assertion catches an empty action
 * slot in a card header, a flag panel that reads as broken, or a document row
 * whose buttons have gone leaving the metadata floating. The unit tests here
 * can only say the buttons are absent; this is how somebody checks that what
 * is left still looks like a finished screen.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/pages/__readonly_visual__.test.jsx
 *   node scripts/shoot-stages.mjs
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

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

const COMPANY = {
  id: 'e1', company_name: 'Nexura Marketing Limited', br_number: '77061251',
  cr_number: '77061251', vp_source_key: 'NEXURA', status: 'live',
  is_client: true, is_corporate_party: false,
  company_type: 'P', incorporation_place: 'HK',
  incorporation_date: '2024-09-12', mortgages_total: 'Nil',
  registered_address: { line1: 'Unit 12A', line2: 'Harbour Centre',
                        city: 'Wan Chai', country: 'HK' },
  contacts: [{ id: 'c1', contact_type: 'phone', contact_value: '+852 3500 1234' }],
  filing_problems: [],
  business_names: [{ id: 'bn1', business_name: 'Nexura Marketing Limited' }],
  documents: [{
    id: 'd1', document_type_code: 'coi', current_version: 2, status: 'active',
    file_name: 'certificate-of-incorporation.pdf',
    updated_at: '2026-06-04T09:30:00Z',
    document_types: { code: 'coi', label: 'Certificate of Incorporation',
                      category: 'certificate' },
    document_versions: [
      { id: 'v2', version_number: 2, file_name: 'certificate-of-incorporation.pdf',
        created_at: '2026-06-04T09:30:00Z' },
      { id: 'v1', version_number: 1, file_name: 'coi-original.pdf',
        created_at: '2025-02-11T02:15:00Z' },
    ],
  }],
  officers: [{
    id: 'o1', role: 'director', appointed_date: '2024-09-20', is_current: true,
    persons: { id: 'p1', full_name: 'Chan Tai Man', email: 'chan@example.com',
               residential_address: { line1: 'Flat 3B', city: 'Central', country: 'HK' } },
  }],
  shareholders: [], beneficial_owners: [], secretaries: [],
  share_classes: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
                    total_issued: 10000, issued_amount: 10000, total_paid: 10000 }],
  cases: { nar1: [], nnc1: [] },
}

const PERSON = {
  id: 'p1', full_name: 'Chan Tai Man', surname: 'Chan', given_names: 'Tai Man',
  email: 'chan@example.com', date_of_birth: '1979-03-14',
  residential_address: { line1: 'Flat 3B', line2: 'Sunrise Court',
                         city: 'Central', country: 'HK' },
  identity_documents: [
    { id: 'i1', id_type: 'hkid', id_number: 'A123456(3)', is_primary: true,
      scan_document_id: 'd9' },
    { id: 'i2', id_type: 'passport', id_number: 'P998877', is_primary: false },
  ],
  documents: [{
    id: 'd2', document_type_code: 'addr_utility_bill', current_version: 1,
    status: 'active', file_name: 'utility-bill.pdf',
    updated_at: '2026-06-04T09:30:00Z',
    document_types: { code: 'addr_utility_bill', label: 'Utility Bill',
                      category: 'address_proof' },
    document_versions: [{ id: 'v3', version_number: 1, file_name: 'utility-bill.pdf',
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
  sections: [{ key: 'certificate', label: 'Certificates', is_identity: false,
               description: 'Certificates issued for this company',
               file_required: true,
               types: [{ code: 'coi', label: 'Certificate of Incorporation', id_type: null }] }],
  identity_fields: {},
}

const PERSON_SECTIONS = {
  sections: [
    { key: 'identity', label: 'Identity Documents', is_identity: true,
      description: 'Identity records held for this person', file_required: false,
      types: [{ code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
              { code: 'id_passport', label: 'Passport', id_type: 'passport' }] },
    { key: 'address_proof', label: 'Proof of Address', is_identity: false,
      description: 'Evidence of the address on file', file_required: true,
      types: [{ code: 'addr_utility_bill', label: 'Utility Bill', id_type: null }] },
  ],
  identity_fields: {
    hkid: { fields: [{ key: 'id_number', label: 'HKID number' }], required: ['id_number'] },
    passport: { fields: [{ key: 'id_number', label: 'Passport number' }], required: ['id_number'] },
  },
}

function mockApi(entity, sections) {
  api.get.mockImplementation(url => {
    const u = String(url)
    if (u === '/lookups') return Promise.resolve(LOOKUPS)
    if (u === '/form-contract') return Promise.resolve(CONTRACT)
    if (u.startsWith('/documents/sections')) return Promise.resolve(sections)
    if (u.startsWith('/documents/types')) {
      const category = new URL(u, 'http://x').searchParams.get('category')
      return Promise.resolve(sections.sections.find(s => s.key === category)?.types || [])
    }
    return Promise.resolve(entity)
  })
}

const authFor = perms => ({
  isSuperAdmin: false,
  hasPermission: (m, p) => perms.includes(`${m}:${p}`),
  profile: { display_name: 'Tester', role_name: 'tester' },
  profileLoading: false,
})

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups(); _resetFormContract(); _resetDocumentSections()
})

/**
 * The page header, the read-only banner, and the cards.
 *
 * `.ro-note` only — NOT every `.reveal-note` on the page. The party tiles carry
 * their own notes inside the grid, so collecting all of them printed the
 * shareholder guidance twice: once floating under the header and again in its
 * own tile, which looked like a rendering bug in the page rather than in this
 * harness.
 */
function dump(name, container) {
  fs.mkdirSync(OUT, { recursive: true })
  const header = container.querySelector('.pg-hdr')?.outerHTML || ''
  const note = [...container.querySelectorAll(':scope > .ro-note')]
    .map(n => n.outerHTML).join('')
  const grid = container.querySelector('.detail-grid')?.outerHTML || ''
  fs.writeFileSync(path.join(OUT, `${name}.html`),
                   `${header}${note}${grid}`, 'utf8')
}

describe.runIf(SHOOT)('read-only screens visual harness', () => {
  it('company profile — companies:read only', async () => {
    auth = authFor(['companies:read'])
    mockApi(COMPANY, COMPANY_SECTIONS)
    const { container } = render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)
    await screen.findByText('Document History')
    await waitFor(() => screen.getByText('Director(s)'))
    dump('r1-company-readonly', container)
  })

  it('company profile — full write, for comparison', async () => {
    auth = authFor(['companies:read', 'companies:write', 'documents:read',
                    'documents:write', 'documents:delete', 'nar1:write'])
    mockApi(COMPANY, COMPANY_SECTIONS)
    const { container } = render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)
    await screen.findByText('Document History')
    await waitFor(() => screen.getByText('Director(s)'))
    dump('r2-company-writable', container)
  })

  it('person profile — persons:read only', async () => {
    auth = authFor(['persons:read'])
    mockApi(PERSON, PERSON_SECTIONS)
    const { container } = render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)
    await screen.findByText('Document History')
    dump('r3-person-readonly', container)
  })

  it('person profile — the tester role (persons read+write, no documents)', async () => {
    auth = authFor(['persons:read', 'persons:write'])
    mockApi(PERSON, PERSON_SECTIONS)
    const { container } = render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)
    await screen.findByText('Document History')
    dump('r4-person-tester', container)
  })
})
