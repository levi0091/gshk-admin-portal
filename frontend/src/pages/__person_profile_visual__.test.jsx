/**
 * NOT a test — a visual harness for the whole Person Profile, so the page can
 * be judged as a page (Levi 2026-10-17: "make sure the profile page is not
 * bloated"). Skipped unless SHOOT=1.
 *
 *   SHOOT=1 SHOOT_OUT=/some/dir npx vitest run src/pages/__person_profile_visual__.test.jsx
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import PersonProfilePage from './PersonProfilePage.jsx'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => ({ personId: 'p1' }) }
})
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({
  hasPermission: () => true, isSuperAdmin: true, profileLoading: false,
  profile: { id: 'u-1', display_name: 'Levi Z.', role_name: 'super_admin' } }) }))

const PERSON = {
  id: 'p1', full_name: 'Amélie DURAND', given_names: 'Amélie', surname: 'DURAND',
  nationality: 'French', date_of_birth: '1984-06-02', email: 'amelie@durand.example',
  residential_address: { line1: 'Flat A, 10/F', line2: 'Harbour View', line3: "1 Queen's Road",
                         city: 'CENTRAL', country: 'HK' },
  identity_documents: [
    { id: 'd1', id_type: 'passport', id_number: '18FV22917', is_primary: true, issuing_country: 'FR' },
    { id: 'd2', id_type: 'passport', id_number: '567201934', is_primary: false, issuing_country: 'US' },
  ],
  documents: [],
  role_rollup: [
    { relation: 'officer', entity_id: 'e-kanenas', company_name: 'Kanenas Holding Limited', role: 'director', is_current: true },
    { relation: 'officer', entity_id: 'e-zenith', company_name: 'ZenithStream Limited', role: 'director', is_current: true },
    { relation: 'officer', entity_id: 'e-harbour', company_name: 'Harbour Lane Trading Limited', role: 'director', is_current: true },
  ],
}
const BOOK = {
  companies: [{ entity_id: 'e-kanenas', company_name: 'Kanenas Holding Limited', roles: ['director'] },
              { entity_id: 'e-zenith', company_name: 'ZenithStream Limited', roles: ['director', 'company_secretary'] },
              { entity_id: 'e-harbour', company_name: 'Harbour Lane Trading Limited', roles: ['director'] }],
  default_residential_address_id: 'a1',
  residential: [
    { address_id: 'a1', is_default: true, used_by: ['e-kanenas', 'e-harbour'],
      address: { line1: 'Flat A, 10/F', line2: 'Harbour View', line3: "1 Queen's Road", city: 'CENTRAL', country: 'HK' } },
    { address_id: 'a2', is_default: false, used_by: ['e-zenith'],
      address: { line1: '12 Rue de Rivoli', city: 'PARIS', postal_code: '75001', country: 'FR' } },
  ],
  correspondence: [{ address_id: 'a3', used_by: ['e-kanenas'],
    address: { line1: 'Room 1201', line2: 'Tower 2', line3: '8 Connaught Place', city: 'CENTRAL', country: 'HK' } }],
  correspondence_same_as_residential: ['e-zenith', 'e-harbour'],
  identity: [
    { document_id: 'd1', id_type: 'passport', id_number: '18FV22917', issuing_country: 'FR', is_primary: true,
      used_by: ['e-kanenas', 'e-harbour'] },
    { document_id: 'd2', id_type: 'passport', id_number: '567201934', issuing_country: 'US', is_primary: false,
      used_by: ['e-zenith'] },
  ],
}
const SECTIONS = { sections: [
  { key: 'identity', label: 'Identity Documents', is_identity: true, file_required: false,
    description: 'Passport, HKID and other identity documents',
    types: [{ code: 'id_passport', label: 'Passport', id_type: 'passport' }] },
  { key: 'address_proof', label: 'Proof of Address', is_identity: false, file_required: true,
    description: 'Evidence of the residential address on file',
    types: [{ code: 'addr_utility_bill', label: 'Utility Bill', id_type: null }] },
], identity_fields: { passport: { fields: ['id_number', 'issuing_country'], required: ['id_number'] } } }
const LOOKUPS = { cr_country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'FR', label: 'France' },
  { code: 'US', label: 'United States of America' }], nationality: [{ code: 'French', label: 'French' }] }

vi.mock('../lib/api.js', () => ({ api: {
  get: vi.fn(url => Promise.resolve(
    url === '/lookups' ? LOOKUPS
      : url.endsWith('/particulars-by-company') ? BOOK
        : url === '/form-contract' ? {}
          : url.startsWith('/documents/sections') ? SECTIONS
            : url.includes('eservice') ? { configured: false }
              : url.includes('particulars-changes') ? { changes: [] }
                : PERSON)),
  post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn() } }))

const SHOOT = process.env.SHOOT === '1'
const OUT = path.resolve(process.env.SHOOT_OUT || path.join(process.cwd(), '.visual'))

describe.skipIf(!SHOOT)('person profile — visual dump', () => {
  it('dumps the page', async () => {
    const { container } = render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)
    await screen.findByRole('region', { name: 'Residential addresses' })
    await new Promise(r => setTimeout(r, 50))
    fs.mkdirSync(OUT, { recursive: true })
    fs.writeFileSync(path.join(OUT, `${process.env.SHOOT_NAME || 'person-profile'}.html`), container.innerHTML)
  })
})
