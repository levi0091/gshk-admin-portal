import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CaseWorkflowPage from './CaseWorkflowPage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ caseId: 'c1' }) }
})

// The audit tab fetches on its own and is covered by its own test file.
vi.mock('../components/AuditTrailTab.jsx', () => ({
  default: ({ caseId }) => <div data-testid="audit-trail">{caseId}</div>,
}))

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn() } }))
import { api } from '../lib/api.js'

const CASE = {
  id: 'c1', case_no: 'NAR-2026-0041', entity_id: 'e7',
  company_name: 'Harbour Tech Ltd.', br_number: '2100028', case_type: 'NAR1',
  case_status: 'live', workflow_status: 'signing',
  form_status: { code: 'validated', label: 'Validated by CR', failed: false, faults: [] },
  days_to_anniversary: -12, signing_method: 'esign',
  verification_sent_at: '2026-08-01T09:00:00Z', client_response_at: '2026-08-03',
  client_approved: true,
}

function renderPage() {
  return render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue(CASE)
})

describe('CaseWorkflowPage', () => {
  it('reads the composite case endpoint for the id in the route', async () => {
    renderPage()
    await screen.findByText('NAR-2026-0041')
    expect(api.get.mock.calls[0][0]).toBe('/cases/c1')
  })

  it('leads with the case number and names the company', async () => {
    renderPage()
    expect(await screen.findByText('NAR-2026-0041')).toBeInTheDocument()
    expect(screen.getByText(/Harbour Tech Ltd\./)).toBeInTheDocument()
    expect(screen.getByText(/2100028/)).toBeInTheDocument()
  })

  it('shows both statuses separately, never merged into one', async () => {
    renderPage()
    await screen.findByText('NAR-2026-0041')
    expect(screen.getByText('Signing')).toBeInTheDocument()          // workflow
    expect(screen.getByText('Validated by CR')).toBeInTheDocument()  // CR form
  })

  it('marks a passed anniversary as overdue', async () => {
    renderPage()
    expect(await screen.findByText('12 days ago')).toBeInTheDocument()
  })

  it('renders EVERY CR fault, not just the first', async () => {
    // CR deliberately returns all faults at once so one pass fixes them all.
    api.get.mockResolvedValue({
      ...CASE,
      form_status: {
        code: 'validation_failed', label: 'Rejected at validation', failed: true,
        faults: ['Partial HKID is required', 'Signatory date precedes appointment'],
      },
    })
    renderPage()
    await screen.findByText('The Companies Registry rejected this form')
    expect(screen.getByText('Partial HKID is required')).toBeInTheDocument()
    expect(screen.getByText('Signatory date precedes appointment')).toBeInTheDocument()
  })

  it('does not show a fault panel when CR has not refused anything', async () => {
    renderPage()
    await screen.findByText('NAR-2026-0041')
    expect(screen.queryByText('The Companies Registry rejected this form'))
      .not.toBeInTheDocument()
  })

  it('passes the ENTITY id to the audit trail, not the case id', async () => {
    // audit_log.case_id holds the entity id — see routers/audit.py and the
    // _audit_target() helper in routers/cases.py. Passing c1 here would render
    // an empty trail that looks like "nothing ever happened".
    renderPage()
    const tab = await screen.findByTestId('audit-trail')
    expect(tab).toHaveTextContent('e7')
    expect(tab).not.toHaveTextContent('c1')
  })

  it('offers a way back to the case list and to the company', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('NAR-2026-0041')

    await user.click(screen.getByRole('button', { name: 'Back to cases' }))
    expect(navigate).toHaveBeenCalledWith('/dashboard')

    await user.click(screen.getByRole('button', { name: 'Company profile' }))
    expect(navigate).toHaveBeenCalledWith('/companies/e7')
  })

  it('says the filing stages are not built rather than showing dead buttons', async () => {
    // These particular buttons spend money at the Companies Registry. A control
    // that looks live and does nothing is worse than an honest absence.
    renderPage()
    await screen.findByText('NAR-2026-0041')
    expect(screen.getByText(/five filing stages are not built yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Submit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Sign/i })).not.toBeInTheDocument()
  })

  it('shows a loading state, then an error state if the case will not load', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    const { unmount } = renderPage()
    expect(screen.getByText('Loading case…')).toBeInTheDocument()
    unmount()

    api.get.mockRejectedValue(new Error('nope'))
    renderPage()
    expect(await screen.findByText(/Failed to load this case: nope/)).toBeInTheDocument()
  })

  it('reads "Not chosen yet" rather than blank when no signing method is set', async () => {
    api.get.mockResolvedValue({ ...CASE, signing_method: null })
    renderPage()
    expect(await screen.findByText('Not chosen yet')).toBeInTheDocument()
  })

  it('distinguishes a declining client from one who never replied', async () => {
    api.get.mockResolvedValue({ ...CASE, client_approved: false })
    renderPage()
    await screen.findByText('NAR-2026-0041')
    expect(screen.getByText(/Declined/)).toBeInTheDocument()

    api.get.mockResolvedValue({ ...CASE, client_response_at: null, client_approved: null })
    const { container } = render(<MemoryRouter><CaseWorkflowPage /></MemoryRouter>)
    expect(await within(container).findByText('No response recorded')).toBeInTheDocument()
  })
})
