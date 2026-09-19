/**
 * NOT a test — a visual harness for soft delete (migration 049).
 *
 * Renders the REAL components against mocked data and dumps their markup for
 * `scripts/shoot-modals.mjs`, which screenshots it with `src/index.css`:
 * the profile header's Delete button, the dialog blocked and ready, a deleted
 * profile's banner, a registry's Deleted tab and the "not available" panel.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/pages/__soft_delete_visual__.test.jsx
 *   node scripts/shoot-modals.mjs
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import CompanyProfilePage from './CompanyProfilePage.jsx'
import CompanyRegistryPage from './CompanyRegistryPage.jsx'
import { DeleteRecordModal, RecordGone } from '../components/SoftDelete.jsx'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => () => {}, useParams: () => ({ companyId: 'e1' }) }
})

const get = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: { get: (...a) => get(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(),
         del: vi.fn(), upload: vi.fn() },
}))
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

const COMPANY = {
  id: 'e1', company_name: 'Payward Limited', br_number: '74159213',
  cr_number: '3308741', status: 'live', incorporation_date: '2023-06-14',
  created_at: '2026-09-19T05:11:00Z', is_client: true, is_corporate_party: false,
  registered_address: { line1: 'Suite C, Level 7', city: 'Central', country: 'HK' },
  contacts: [], documents: [], officers: [], shareholders: [], secretaries: [],
  beneficial_owners: [], share_classes: [], business_names: [],
  cases: { nar1: [], nnc1: [] }, filing_problems: [],
}

const DELETED = {
  ...COMPANY, deleted_at: '2026-09-20T02:14:00Z', deleted_by_name: 'Levi Z.',
  deleted_reason: 'Duplicate of the profile imported from Viewpoint (BRN 74159213).',
}

const BLOCKED = {
  can_delete: false, links_total: 5603,
  links: [
    { company_id: 'c1', company_name: '21 Consult Limited', br_number: '71234567',
      roles: ['Company secretary'] },
    { company_id: 'c2', company_name: 'AFULLSPACE COMPANY LIMITED', br_number: '69876543',
      roles: ['Company secretary'] },
    { company_id: 'c3', company_name: 'Alex International Consulting Limited',
      br_number: '70011223', roles: ['Company secretary', 'Shareholder'] },
  ],
  cases: [{ case_id: 'k1', case_no: 'NAR-2026-0075', workflow_status: 'client_verification' }],
}

function dump(name, html) {
  fs.mkdirSync(OUT, { recursive: true })
  fs.writeFileSync(path.join(OUT, `${name}.html`), html, 'utf8')
}

function route(company) {
  get.mockImplementation(url => {
    const u = String(url)
    if (u === '/lookups') return Promise.resolve({})
    if (u === '/form-contract') return Promise.resolve({})
    if (u.startsWith('/documents/sections')) return Promise.resolve({ sections: [], identity_fields: {} })
    if (u.startsWith('/companies/deleted')) {
      return Promise.resolve({ total: 2, companies: [
        { ...DELETED, id: 'e1' },
        { id: 'e7', company_name: 'Test Holdings (Old) Limited', br_number: null,
          deleted_at: '2026-09-18T09:02:00Z', deleted_by_name: 'Vanis',
          deleted_reason: 'Test record created during UAT.' },
      ] })
    }
    if (u.startsWith('/companies?')) {
      return Promise.resolve({ total: 0, companies: [],
                               flag_counts: { all: 5930, client: 5864, corporate_party: 279, non_client: 66 } })
    }
    return Promise.resolve(company)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  _resetFormContract()
  _resetDocumentSections()
})

describe.runIf(SHOOT)('soft delete visual harness', () => {
  it('s91 — a live profile header carries Delete', async () => {
    route(COMPANY)
    const { container } = render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)
    await screen.findByRole('button', { name: 'Delete company' })
    dump('s91-sd-header', container.querySelector('.pg-hdr').outerHTML)
  })

  it('s92 — a deleted profile: the banner, nothing to edit', async () => {
    route(DELETED)
    const { container } = render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)
    await screen.findByText('This company has been deleted.')
    // Header, banner and the grid of cards -- everything the page renders.
    dump('s92-sd-deleted-profile', container.innerHTML)
  })

  it('m91 — the dialog, blocked', async () => {
    get.mockResolvedValue(BLOCKED)
    const { container } = render(
      <MemoryRouter>
        <DeleteRecordModal kind="company" basePath="/companies/gshk"
                           name="Get Started HK Limited"
                           identifiers={['BRN 63912808', 'CR No. 2882908', 'Created 12 Jul 2024']}
                           onClose={() => {}} onDeleted={() => {}} />
      </MemoryRouter>)
    await screen.findByText(/cannot be deleted yet/)
    dump('m91-sd-dialog-blocked', container.innerHTML)
  })

  it('m92 — the dialog, ready, with a reason typed', async () => {
    get.mockResolvedValue({ can_delete: true, links: [], links_total: 0, cases: [] })
    const user = userEvent.setup()
    const { container } = render(
      <MemoryRouter>
        <DeleteRecordModal kind="company" basePath="/companies/e1"
                           name="Payward Limited"
                           identifiers={['BRN 74159213', 'CR No. 3308741', 'Created 19 Sep 2026']}
                           onClose={() => {}} onDeleted={() => {}} />
      </MemoryRouter>)
    await user.type(await screen.findByLabelText(/Why is this company/),
                    'Duplicate of the profile imported from Viewpoint.')
    dump('m92-sd-dialog-ready', container.innerHTML)
  })

  it('s93 — the registry Deleted tab', async () => {
    route(COMPANY)
    const user = userEvent.setup()
    const { container } = render(<MemoryRouter><CompanyRegistryPage /></MemoryRouter>)
    await user.click(await screen.findByRole('tab', { name: 'Deleted' }))
    await screen.findByText('Test Holdings (Old) Limited')
    await waitFor(() => {})
    dump('s93-sd-registry-deleted', container.innerHTML)
  })

  it('s94 — a 404 profile', () => {
    const { container } = render(
      <MemoryRouter>
        <RecordGone kind="company" backTo="/registry" backLabel="Back to Company Registry" />
      </MemoryRouter>)
    dump('s94-sd-not-available', container.innerHTML)
  })
})
