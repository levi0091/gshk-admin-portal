import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import AppShell from '../components/AppShell.jsx'
import DashboardPage from './DashboardPage.jsx'

/**
 * The real shell around the real page — the combination nothing else covers.
 *
 * Every other test renders a page on its own, so AppShell and Sidebar have
 * never been rendered by the suite at all. There is no ErrorBoundary in
 * main.jsx, so anything that throws during render unmounts the whole tree and
 * the browser shows a blank white page with no failed request to point at.
 * That is exactly the symptom reported on admin-dev.
 */

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const get = vi.fn()
vi.mock('../lib/api.js', () => ({ api: { get: (...a) => get(...a) } }))

// The shape GET /cases?scope=dashboard actually returns.
const PAYLOAD = {
  total: 1, page: 1, page_size: 50,
  counts: { all: 1, data_verification: 1, client_verification: 0, awaiting_client: 0,
            client_rejected: 0, signing: 0, submission: 0, completed: 0 },
  rows: [{
    id: 'c1', case_no: 'NAR-2026-0001', entity_id: 'e1',
    company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
    case_status: 'live', filing_stage: null,
    // The composite object nar1_case_status.badge_from_row() actually returns.
    workflow_status: { code: 'data_verification', label: 'Data Verification',
                       off_portal: false, overdue: false },
    days_to_anniversary: 34, created_at: '2024-05-02', updated_at: '2026-06-25',
  }],
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue(PAYLOAD)
  auth = {
    profile: { display_name: 'Levi', role_name: 'super_admin', permissions: [] },
    isSuperAdmin: true,
    hasPermission: () => true,
    profileLoading: false,
  }
})

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="dashboard" element={<DashboardPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('the app shell renders the dashboard without crashing', () => {
  it('renders header, sidebar and the case list together', async () => {
    renderShell()
    expect(await screen.findByText('NAR-2026-0001')).toBeInTheDocument()
    expect(screen.getByText('G-FlowDesk')).toBeInTheDocument()
    // The shell's nav link and something only the page draws — proof that both
    // halves rendered, which is the whole point of this test. The page's phase
    // toggle used to be the second half; it is gone (this screen only ever
    // listed post-incorporation cases), so the stat tile stands in for it.
    expect(screen.getByRole('link', { name: /Post-incorporation/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Action Required/ })).toBeInTheDocument()
  })

  it('renders for an ordinary user who holds nar1:read', async () => {
    auth = {
      profile: { display_name: 'Staff', role_name: 'case_manager',
                 permissions: ['nar1:read', 'companies:read'] },
      isSuperAdmin: false,
      hasPermission: (m, p) => ['nar1:read', 'companies:read'].includes(`${m}:${p}`),
      profileLoading: false,
    }
    renderShell()
    expect(await screen.findByText('NAR-2026-0001')).toBeInTheDocument()
  })

  it('renders for a user with NO permissions at all', async () => {
    // The sidebar renders nothing; the page still must not crash the tree.
    auth = {
      profile: { display_name: 'Nobody', role_name: 'viewer', permissions: [] },
      isSuperAdmin: false,
      hasPermission: () => false,
      profileLoading: false,
    }
    renderShell()
    await waitFor(() => expect(get).toHaveBeenCalled())
    expect(screen.getByText('G-FlowDesk')).toBeInTheDocument()
  })

  it('renders before the profile has loaded', async () => {
    // AuthContext yields profile: null while /auth/me is in flight.
    auth = {
      profile: null, isSuperAdmin: false, hasPermission: () => false,
      profileLoading: true,
    }
    renderShell()
    expect(screen.getByText('G-FlowDesk')).toBeInTheDocument()
  })
})
