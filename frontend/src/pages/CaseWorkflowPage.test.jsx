import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CaseWorkflowPage from './CaseWorkflowPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ caseId: 'c1' }) }
})

vi.mock('../components/AuditTrailTab.jsx', () => ({
  default: ({ caseId }) => <div data-testid="audit-trail">{caseId}</div>,
}))

let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn()
const blob = vi.fn(); const upload = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    blob: (...a) => blob(...a), upload: (...a) => upload(...a), put: vi.fn(),
  },
}))

// A case that has cleared every gate except filing — opens on Submission.
const CASE = {
  id: 'c1', case_no: 'NAR-2026-0041', entity_id: 'e7',
  company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
  case_status: 'live', workflow_status: 'submission',
  form_status: { code: 'signed', label: 'Signed', failed: false, faults: [] },
  filing_id: 'f1', days_to_anniversary: -12, signing_method: 'esign',
  verification_sent_at: '2026-08-01T09:00:00Z', client_response_at: '2026-08-03',
  client_approved: true, created_at: '2026-01-01', updated_at: '2026-08-03T10:00:00Z',
}

function caseAt(over) { return { ...CASE, ...over } }

function routeGet(caseRow = CASE, extra = {}) {
  get.mockImplementation(path => {
    if (path.startsWith('/cases/')) return Promise.resolve(caseRow)
    if (path.includes('/preview')) {
      return Promise.resolve(extra.preview ?? { fee: 105, balance: 12480, sufficient: true })
    }
    if (path.includes('/doc-status')) return Promise.resolve(extra.docStatus ?? [])
    return Promise.resolve({})
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { hasPermission: () => true, isSuperAdmin: true }
  routeGet()
  blob.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
  post.mockResolvedValue({}); patch.mockResolvedValue({}); upload.mockResolvedValue({})
  // jsdom has no object-URL implementation.
  global.URL.createObjectURL = vi.fn(() => 'blob:preview')
  global.URL.revokeObjectURL = vi.fn()
})

const renderPage = async () => {
  render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
  await screen.findByText('NAR-2026-0041')
}

describe('CaseWorkflowPage — shell', () => {
  it('reads the composite case endpoint for the id in the route', async () => {
    await renderPage()
    expect(get.mock.calls[0][0]).toBe('/cases/c1')
  })

  it('shows both statuses separately, never merged', async () => {
    await renderPage()
    // Scoped to their own rows: "Submission" is also a stepper label, and the
    // point here is that the two badges are two distinct facts side by side.
    const workflow = screen.getByText('Workflow status').closest('.kv-row')
    const form = screen.getByText('CR form status').closest('.kv-row')
    expect(within(workflow).getByText('Submission')).toBeInTheDocument()
    expect(within(form).getByText('Signed')).toBeInTheDocument()
  })

  it('opens on the furthest stage the case has actually reached', async () => {
    await renderPage()
    const submission = screen.getByRole('tab', { name: /Submission/ })
    expect(submission).toHaveAttribute('aria-selected', 'true')
  })

  it('passes the ENTITY id to the audit trail, not the case id', async () => {
    // audit_log.case_id holds the entity id — see routers/audit.py.
    await renderPage()
    expect(await screen.findByTestId('audit-trail')).toHaveTextContent('e7')
  })

  it('offers a way back to the case list and to the company', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('button', { name: 'Back to cases' }))
    expect(navigate).toHaveBeenCalledWith('/dashboard')
    await user.click(screen.getByRole('button', { name: 'Company profile' }))
    expect(navigate).toHaveBeenCalledWith('/companies/e7')
  })

  it('renders an error state when the case will not load', async () => {
    get.mockRejectedValue(new Error('nope'))
    render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    expect(await screen.findByText(/Failed to load this case: nope/)).toBeInTheDocument()
  })
})

describe('CaseWorkflowPage — the stage gate is enforced, not just drawn', () => {
  it('locks stages the case has not reached', async () => {
    routeGet(caseAt({ form_status: null, filing_id: null, verification_sent_at: null,
                      client_approved: null, signing_method: null }))
    await renderPage()
    expect(screen.getByRole('tab', { name: /Signing/ })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('tab', { name: /Confirmation/ })).toHaveAttribute('aria-disabled', 'true')
  })

  it('refuses to open a locked stage and says what would unlock it', async () => {
    const user = userEvent.setup()
    routeGet(caseAt({ form_status: null, filing_id: null, verification_sent_at: null,
                      client_approved: null, signing_method: null }))
    await renderPage()
    await user.click(screen.getByRole('tab', { name: /Submission/ }))
    // Still on stage 1, and told why.
    expect(screen.getByRole('tab', { name: /Data Verification/ }))
      .toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText(/Complete "Data Verification" to unlock/))
      .toBeInTheDocument()
  })

  it('lets the operator move back to a stage already passed', async () => {
    const user = userEvent.setup()
    await renderPage()
    await user.click(screen.getByRole('tab', { name: /Data Verification/ }))
    expect(screen.getByRole('tab', { name: /Data Verification/ }))
      .toHaveAttribute('aria-selected', 'true')
  })

  it('clears the locked-stage note once the operator moves somewhere', async () => {
    // Left up, it would explain a refusal that has already been moved past.
    const user = userEvent.setup()
    routeGet(caseAt({ form_status: { code: 'validated' }, verification_sent_at: null,
                      client_approved: null }))
    await renderPage()
    await user.click(screen.getByRole('tab', { name: /Signing/ }))
    expect(await screen.findByText(/to unlock/)).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /Data Verification/ }))
    expect(screen.queryByText(/to unlock/)).not.toBeInTheDocument()
  })
})

describe('CaseWorkflowPage — permissions gate the consequential controls', () => {
  it('hides filing from someone without tpsi:submit', async () => {
    auth = {
      isSuperAdmin: false,
      hasPermission: (m, p) => !(m === 'tpsi' && p === 'submit'),
    }
    await renderPage()
    expect(await screen.findByText(/Filing requires the/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /File the return/ })).not.toBeInTheDocument()
  })

  it('offers filing to someone who holds tpsi:submit', async () => {
    await renderPage()
    expect(await screen.findByRole('button', { name: /File the return/ })).toBeInTheDocument()
  })
})
