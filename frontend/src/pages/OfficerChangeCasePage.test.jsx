import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import OfficerChangeCasePage from './OfficerChangeCasePage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ caseId: 'k1' }) }
})
let auth
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => auth }))
vi.mock('../components/case/PdfPreview.jsx', () => ({
  default: () => <div data-testid="pdf" />, usePdfBlob: () => ({ url: 'blob:x', error: null }),
}))
vi.mock('../components/case/VerificationDeliveryModal.jsx', () => ({
  default: () => <div data-testid="delivery" />,
}))

const get = vi.fn(); const post = vi.fn(); const patch = vi.fn(); const del = vi.fn()
vi.mock('../lib/api.js', () => ({
  api: {
    get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a),
    del: (...a) => del(...a), upload: vi.fn(), blob: vi.fn(), put: vi.fn(),
  },
}))

export const ND2A = {
  id: 'k1', case_no: 'ND2A-2026-0001', form_code: 'Nd2a', case_type: 'ND2A',
  entity_id: 'e1', company_name: 'Kanenas Holding Limited', br_number: '69123456',
  workflow_status: { code: 'client_verification', label: 'Client Verification', overdue: false },
  form_status: null, cr_status: { code: 'cr_not_checked', label: 'Not checked' },
  editable: true, verification_sent_at: null, client_approved: null,
  deadline: { date: '2026-10-13', days: 11, overdue: false, basis: '' },
  reply_by_default: '2026-10-08', problems: [],
  rules: { blocking: false, summary: 'After these changes the company will have 2 directors (2 natural persons) and 1 secretary.',
    checks: [{ code: 'has_secretary', ok: true, level: 'rule', text: 'The company keeps a company secretary.' }] },
  route: { esign_available: true, reasons: [], consents: [], default: 'esign', selected: null },
  officers: [{ officer_id: 'o1', role: 'director', party_type: 'individual', name: 'CHAN Tai Man', pending: true }],
  documents: [], profile_changes: [], filing: null, signatory: { name: 'GSHK', capacities: ['Director'] },
  entries: [
    { id: 'n1', kind: 'cessation', capacity: 'director', party_type: 'individual', officer_id: 'o1',
      party: { name: 'CHAN Tai Man', missing: [] }, summary: 'Director · ceases 28 Sep 2026 · Resignation / Others',
      documents: [] },
    { id: 'n2', kind: 'appointment', capacity: 'director', party_type: 'individual', person_id: 'p9',
      party: { name: 'HO New', missing: ['email address'], profile_path: '/persons/p9' },
      summary: 'Director · appointed 29 Sep 2026', documents: [],
      eservice: { configured: false, has_password: false } },
  ],
  created_at: '2026-09-30', updated_at: '2026-10-01T00:00:00Z',
}

function renderPage(data) {
  get.mockImplementation(path => {
    if (path.includes('/verification/recipients')) {
      return Promise.resolve({ recipients: [{ email: 'a@example.com', name: 'A' }],
        default_to: ['a@example.com'], reply_by_default: '2026-10-08' })
    }
    return Promise.resolve(data)
  })
  return render(<MemoryRouter><OfficerChangeCasePage /></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  auth = { isSuperAdmin: true, hasPermission: () => true }
})

describe('OfficerChangeCasePage', () => {
  it('opens on Client Verification with the six stages and the deadline', async () => {
    renderPage(ND2A)
    expect(await screen.findByRole('tab', { name: /Client Verification/ })).toHaveAttribute('aria-selected', 'true')
    expect(within(screen.getByRole('tablist', { name: 'Case stages' })).getAllByRole('tab')).toHaveLength(6)
    expect(screen.getByText(/Due in 11 days/)).toBeInTheDocument()
    expect(screen.getAllByText(/ND2A-2026-0001/).length).toBeGreaterThan(0)
  })

  it('shows the Leaving / Joining board with the missing-particulars warning', async () => {
    renderPage(ND2A)
    const leaving = await screen.findByRole('region', { name: 'Leaving' })
    const joining = screen.getByRole('region', { name: 'Joining' })
    expect(within(leaving).getByText('CHAN Tai Man')).toBeInTheDocument()
    expect(within(joining).getByText('HO New')).toBeInTheDocument()
    expect(within(joining).getByText(/Missing on the profile: email address/)).toBeInTheDocument()
    // Stated twice on purpose: as the board's total and as the rules' summary.
    expect(screen.getAllByText(/2 directors \(2 natural persons\) and 1 secretary/).length).toBeGreaterThan(0)
  })

  it('disables Send while a rule is breached and says why beside the button', async () => {
    renderPage({ ...ND2A, rules: { blocking: true, summary: '', checks: [
      { code: 'has_secretary', ok: false, level: 'rule', text: 'The company would be left without a company secretary.' }] } })
    const send = await screen.findByRole('button', { name: 'Send to client' })
    expect(send).toBeDisabled()
    expect(screen.getByText(/A company rule is breached/)).toBeInTheDocument()
    expect(screen.getByText(/left without a company secretary/)).toBeInTheDocument()
  })

  it('sends with the chosen reply-by date', async () => {
    post.mockResolvedValue({ deliveries: [], failed: [] })
    renderPage(ND2A)
    const send = await screen.findByRole('button', { name: 'Send to client' })
    await waitFor(() => expect(send).toBeEnabled())
    await userEvent.click(send)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/officer-changes/k1/verification/send',
      { emails: ['a@example.com'], respond_by: '2026-10-08' }))
  })

  it('is read-only once sent, and records a relayed answer', async () => {
    post.mockResolvedValue({ ...ND2A, client_approved: true })
    renderPage({ ...ND2A, editable: false, verification_sent_at: '2026-10-01T00:00:00Z' })
    expect(await screen.findByText(/restart verification to change the list/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Add cessation' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Client approved' }))
    expect(post).toHaveBeenCalledWith('/officer-changes/k1/verification/response', { approved: true })
  })

  it('renders an ND2B with the read-only particulars card', async () => {
    renderPage({ ...ND2A, form_code: 'Nd2b', case_type: 'ND2B', entries: [
      { id: 'n3', kind: 'change', capacity: 'director', officer_id: 'o1',
        party: { name: 'CHAN Tai Man' }, documents: [],
        items: [{ key: 'email', cr_item: 'f', label: 'Email address', old_text: 'a@x.com',
          new_text: 'b@x.com', effective_date: null, omitted: false }] }] })
    expect(await screen.findByText('b@x.com')).toBeInTheDocument()
    expect(screen.getByText('a@x.com')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Leaving' })).not.toBeInTheDocument()
  })

  it('opens on Signing for an approved, checked manual case', async () => {
    renderPage({ ...ND2A, client_approved: true, verification_sent_at: 'x', editable: false,
      signing_method: 'manual', data_checked_at: '2026-10-01T00:00:00Z' })
    expect(await screen.findByRole('tab', { name: /Signing/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows the closed panel instead of the stages', async () => {
    renderPage({ ...ND2A, closed_at: '2026-10-01T00:00:00Z', closed_reason: 'Client not proceeding' })
    expect(await screen.findByText(/This case was closed/)).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  })
})
