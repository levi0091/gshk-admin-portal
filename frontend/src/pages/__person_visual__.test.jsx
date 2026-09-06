/**
 * NOT a test — a visual harness for the Person Profile's document sections.
 *
 * The identity cards carry four actions now (Make primary / Download scan /
 * Edit / Remove) and the sections carry two, and a row of buttons that wraps or
 * collides is exactly the class of defect that ships green. Renders the real
 * page against mocked data and dumps it for `scripts/shoot-modals.mjs`.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/pages/__person_visual__.test.jsx
 *   node scripts/shoot-modals.mjs
 */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import PersonProfilePage from './PersonProfilePage.jsx'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => () => {}, useParams: () => ({ personId: 'p1' }) }
})

const get = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(),
         del: vi.fn(), upload: vi.fn() },
}))
// The screen shot is of a user who may edit — the read-only variant is a
// different picture, covered by the unit tests rather than by a screenshot.
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    hasPermission: () => true, isSuperAdmin: true, profileLoading: false,
    profile: { id: 'u-1', display_name: 'Levi Z.', role_name: 'super_admin' },
  }),
}))
import { _resetLookups } from '../lib/lookups.js'
import { _resetFormContract } from '../lib/formContract.js'
import { _resetDocumentSections } from '../lib/documentSections.js'

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

const LOOKUPS = {
  gender: [{ code: 'M', label: 'Male' }],
  nationality: [{ code: 'British', label: 'British' }],
  cr_country: [
    { code: 'HK', label: 'Hong Kong' },
    { code: 'GB', label: 'United Kingdom of Great Britain and Northern Ireland' },
  ],
}

const CONTRACT = {
  persons: { surname: { max_length: 50, mandatory: true, cr_fields: ['indvEngSname'] } },
  addresses: { country: { max_length: 3, mandatory: true, cr_fields: ['ctryRegion'] } },
}

const SECTIONS = {
  sections: [
    { key: 'identity', label: 'Identity Documents', is_identity: true,
      description: 'Passport, HKID and other identity documents — the numbers filed with CR',
      file_required: false,
      types: [{ code: 'id_hkid', label: 'Hong Kong Identity Card', id_type: 'hkid' },
              { code: 'id_passport', label: 'Passport', id_type: 'passport' }] },
    { key: 'address_proof', label: 'Proof of Address', is_identity: false,
      description: 'Evidence of the residential or registered address on file',
      file_required: true,
      types: [{ code: 'addr_utility_bill', label: 'Utility Bill', id_type: null }] },
    { key: 'internal', label: 'Other Documents', is_identity: false,
      description: 'Anything that does not belong to a section above',
      file_required: true, types: [{ code: 'other', label: 'Other', id_type: null }] },
  ],
  identity_fields: {
    hkid: { fields: ['id_number'], required: ['id_number'] },
    passport: { fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
                required: ['id_number', 'issuing_country'] },
    china_id: { fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
                required: ['id_number'] },
    other: { fields: ['id_number', 'issuing_country', 'issue_date', 'expiry_date'],
             required: ['id_number'] },
  },
}

// Two identity documents, so the primary picker has something to choose
// between; one uploaded proof of address; one REMOVED document, which must
// appear in the history and nowhere else.
const PERSON = {
  id: 'p1', full_name: 'Chan Tai Man', surname: 'Chan', given_names: 'Tai Man',
  nationality: 'British', date_of_birth: '1979-03-14', email: 'ctm@example.com',
  residential_address: { line1: 'Flat 3B, Ventris Court', city: 'Happy Valley', country: 'HK' },
  identity_documents: [
    { id: 'i1', id_type: 'hkid', id_number: 'A123456(3)', is_primary: true,
      created_at: '2024-01-02', scan_document_id: 'd9' },
    { id: 'i2', id_type: 'passport', id_number: 'K1234567', is_primary: false,
      issuing_country: 'GB', issue_date: '2021-01-28', expiry_date: '2031-01-27',
      created_at: '2024-06-02' },
  ],
  documents: [
    { id: 'd9', document_type_code: 'id_hkid', current_version: 2, status: 'active',
      file_name: 'hkid-both-sides.pdf', updated_at: '2026-06-04T09:30:00Z',
      document_types: { code: 'id_hkid', label: 'Hong Kong Identity Card', category: 'identity' },
      document_versions: [
        { id: 'v1', version_number: 1, file_name: 'hkid-front.pdf', created_at: '2024-05-02T02:10:00Z' },
        { id: 'v2', version_number: 2, file_name: 'hkid-both-sides.pdf', created_at: '2026-06-04T09:30:00Z' },
      ] },
    { id: 'd10', document_type_code: 'addr_utility_bill', current_version: 1, status: 'active',
      title: 'CLP June', file_name: 'clp-june.pdf', updated_at: '2026-08-11T01:05:00Z',
      document_types: { code: 'addr_utility_bill', label: 'Utility Bill', category: 'address_proof' },
      document_versions: [
        { id: 'v3', version_number: 1, file_name: 'clp-june.pdf', created_at: '2026-08-11T01:05:00Z' },
      ] },
    { id: 'd11', document_type_code: 'other', current_version: 1, status: 'deleted',
      file_name: 'wrong-client.pdf', updated_at: '2026-08-12T03:00:00Z',
      document_types: { code: 'other', label: 'Other', category: 'internal' },
      document_versions: [
        { id: 'v4', version_number: 1, file_name: 'wrong-client.pdf', created_at: '2026-08-12T03:00:00Z' },
      ] },
  ],
  role_rollup: [
    { relation: 'officer', entity_id: 'e1', company_name: 'Skyline Capital Limited',
      role: 'director', is_current: true, appointed_date: '2021-04-01' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetFormContract()
  _resetDocumentSections()
  get.mockImplementation(url => {
    const u = String(url)
    if (u === '/lookups') return Promise.resolve(LOOKUPS)
    if (u === '/form-contract') return Promise.resolve(CONTRACT)
    if (u.startsWith('/documents/sections')) return Promise.resolve(SECTIONS)
    return Promise.resolve(PERSON)
  })
})

describe.runIf(SHOOT)('person profile visual harness', () => {
  it('document sections', async () => {
    const { container } = render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)
    // "Identity Documents" appears twice once history renders — as the section
    // heading and as the history group's section tag — which is itself the
    // thing being looked at.
    // Each heading appears twice once history renders — as the section title
    // and as a history group's section tag — which is itself the thing being
    // looked at, so wait on the count rather than on uniqueness.
    await waitFor(() => {
      if (screen.getAllByText('Proof of Address').length < 2) throw new Error('not yet')
    })
    fs.mkdirSync(OUT, { recursive: true })
    // Just the document area — the personal-details card above it is unchanged
    // and would only make the shot taller.
    const cards = [...container.querySelectorAll('.card')].slice(1)
    fs.writeFileSync(
      path.join(OUT, 's1-person-documents.html'),
      `<div class="detail-grid client-off"><div>${cards.map(c => c.outerHTML).join('')}</div></div>`,
      'utf8')
  })
})
