/**
 * NOT a test — a visual harness for the three listing screens.
 *
 * Renders each page with the real components and dumps the markup so it can be
 * screenshotted against the real stylesheet (see scripts/shoot-stages.mjs).
 * Reading JSX tells you what you wrote; a picture tells you what an operator
 * sees — which is how the column-filter work found a funnel sitting on the
 * table's own hairline and a chip row that read as a toolbar.
 *
 * The popover portals to document.body, so the "open" shots dump `body`
 * rather than the render container — otherwise the one thing worth looking at
 * is the one thing missing from the picture.
 *
 * Skipped unless SHOOT=1, so it never runs in CI.
 *
 *   SHOOT=1 npx vitest run src/pages/__tables_visual__.test.jsx
 *   node scripts/shoot-stages.mjs
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import DashboardPage from './DashboardPage.jsx'
import CompanyRegistryPage from './CompanyRegistryPage.jsx'
import PersonsRegistryPage from './PersonsRegistryPage.jsx'

const get = vi.fn()
vi.mock('../lib/api.js', () => ({ api: { get: (...a) => get(...a), post: vi.fn() } }))
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    hasPermission: () => true, isSuperAdmin: true, profileLoading: false,
    profile: { id: 'u-1', display_name: 'Levi Z.' },
  }),
}))

const OUT = path.resolve(process.cwd(), '.visual')
const SHOOT = process.env.SHOOT === '1'

const badge = (code, label, extra = {}) => ({
  code, label, off_portal: false, overdue: false, ...extra,
})

const CASES = {
  total: 30, page: 1, page_size: 50,
  counts: {
    all: 30, data_verification: 11, client_verification: 7, awaiting_client: 3,
    client_rejected: 0, signing: 2, submission: 0, completed: 7,
  },
  rows: [
    { id: 'c1', case_no: 'NAR-2026-0065', entity_id: '4a20786b-7b50-4f35-8e4d-c3e342766db9',
      company_name: 'CGAHCHBAABBG TEST COMPANY LIMITED', br_number: 'T0001137',
      case_type: 'NAR1', case_status: 'draft',
      workflow_status: badge('completed', 'Completed'),
      days_to_anniversary: 120, created_at: '2026-08-31', updated_at: '2026-08-31',
      created_by: 'u-1', created_by_name: 'Levi Z.' },
    { id: 'c2', case_no: 'NAR-2026-0064', entity_id: '4a20786b-7b50-4f35-8e4d-c3e342766db9',
      company_name: 'CGAHCHBAABBG TEST COMPANY LIMITED', br_number: 'T0001137',
      case_type: 'NAR1', case_status: 'draft',
      workflow_status: badge('awaiting_client', 'Awaiting Client'),
      days_to_anniversary: 120, created_at: '2026-08-31', updated_at: '2026-09-02',
      created_by: 'u-1', created_by_name: 'Levi Z.' },
    { id: 'c3', case_no: 'NAR-2026-0063', entity_id: 'ada56dfc-21c7-4045-a91e-27a1ba1447d4',
      company_name: 'CGAHCHBAABBG DIRECTOR COMPANY LIMITED', br_number: 'T0001138',
      case_type: 'NAR1', case_status: 'draft',
      workflow_status: badge('data_verification', 'Data Verification'),
      days_to_anniversary: -12, created_at: '2026-08-31', updated_at: '2026-09-02',
      created_by: 'u-1', created_by_name: 'Levi Z.' },
  ],
}

const COMPANIES = {
  total: 5998, page: 1, page_size: 50,
  flag_counts: { all: 5998, client: 5930, corporate_party: 279, non_client: 68 },
  companies: [
    { id: 'e1', company_name: 'CLICKBYTE MEDIA LIMITED', company_name_zh: null,
      br_number: '69664946 - 000', cr_number: '2724972', status: 'live',
      is_client: true, is_corporate_party: false, days_to_anniversary: -42 },
    { id: 'e2', company_name: 'Nurie AI Hong Kong Limited', company_name_zh: null,
      br_number: null, cr_number: '76845880', status: 'live',
      is_client: true, is_corporate_party: false, days_to_anniversary: -42 },
    { id: 'e3', company_name: 'IZY AIR INTERNATIONAL LIMITED', company_name_zh: '易飛國際有限公司',
      br_number: '72074859 - 000', cr_number: '2962507', status: 'live',
      is_client: true, is_corporate_party: true, days_to_anniversary: 17 },
    // Past the old -42 floor (migration 033). Here to check that the row reads
    // as a plain date fact and does NOT pick up the carrot "act on me" weight —
    // 2,262 of DEV's companies live in this band and highlighting them all
    // would be an alarm about 38% of the register.
    { id: 'e4', company_name: 'WINDOW SHUT HOLDINGS LIMITED', company_name_zh: null,
      br_number: '61200341 - 000', cr_number: '2119887', status: 'ceased',
      is_client: true, is_corporate_party: false, days_to_anniversary: -120 },
  ],
}

const PERSONS = {
  total: 6850, page: 1, page_size: 50,
  role_counts: { all: 6850, director: 6259, shareholder: 6447, secretary: 13, beneficial_owner: 3 },
  persons: [
    { id: 'p1', full_name: 'John Smith', nationality: 'British (BNO)',
      primary_id_type: 'hkid', primary_id_number: 'A1234567(8)',
      is_director: true, is_shareholder: true, updated_at: '2026-06-04' },
    { id: 'p2', full_name: 'Mei Chan', nationality: 'Singaporean',
      primary_id_type: 'passport', primary_id_number: 'EA1122334',
      is_shareholder: true, is_beneficial_owner: true, updated_at: '2026-05-22' },
    { id: 'p3', full_name: 'Priya Raghunathan', nationality: null,
      primary_id_type: null, primary_id_number: null,
      is_director: true, updated_at: '2026-04-11' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockImplementation(url => Promise.resolve(
    url.startsWith('/cases') ? CASES
      : url.startsWith('/companies') ? COMPANIES
        : PERSONS))
})

async function dump(name, ui, { open, whole } = {}) {
  const { container } = render(<MemoryRouter>{ui}</MemoryRouter>)
  await waitFor(() => expect(container.querySelector('tbody tr td')).toBeTruthy())
  if (open) {
    await userEvent.setup().click(
      screen.getByRole('button', { name: new RegExp(`^Filter ${open}`) }))
    await screen.findByRole('dialog')
  }
  fs.mkdirSync(OUT, { recursive: true })
  // The popover portals to body, so an "open" shot has to dump body to include it.
  fs.writeFileSync(path.join(OUT, `${name}.html`),
    (open || whole ? document.body : container).innerHTML, 'utf8')
}

describe.runIf(SHOOT)('tables visual harness', () => {
  it('post-incorporation dashboard', async () => {
    await dump('t1-dashboard', <DashboardPage />)
  })

  it('dashboard · workflow filter open', async () => {
    await dump('t2-dashboard-workflow-open', <DashboardPage />, { open: 'Workflow' })
  })

  it('dashboard · created-by filter open', async () => {
    await dump('t3-dashboard-owner-open', <DashboardPage />, { open: 'Created By' })
  })

  it('body corporate registry', async () => {
    await dump('t4-registry', <CompanyRegistryPage />)
  })

  it('registry · anniversary range open', async () => {
    await dump('t5-registry-anniv-open', <CompanyRegistryPage />,
      { open: 'Days to anniversary' })
  })

  it('registry · status list open', async () => {
    await dump('t6-registry-status-open', <CompanyRegistryPage />, { open: 'Status' })
  })

  it('natural person registry', async () => {
    await dump('t7-persons', <PersonsRegistryPage />)
  })

  it('persons · identity filter open', async () => {
    await dump('t8-persons-identity-open', <PersonsRegistryPage />, { open: 'Identity' })
  })

  // The two shots the 2026-09-04 round of fixes is actually about.
  it('registry · status list, company statuses only', async () => {
    await dump('t9-registry-status-narrowed', <CompanyRegistryPage />, { open: 'Status' })
  })

  it('dashboard · nothing matches', async () => {
    get.mockImplementation(url => Promise.resolve(
      url.startsWith('/cases') ? { ...CASES, rows: [], total: 0 } : COMPANIES))
    const { container } = render(<MemoryRouter><DashboardPage /></MemoryRouter>)
    await screen.findByText('No records found')
    fs.mkdirSync(OUT, { recursive: true })
    fs.writeFileSync(path.join(OUT, 't10-dashboard-empty.html'),
      container.innerHTML, 'utf8')
  })
})
