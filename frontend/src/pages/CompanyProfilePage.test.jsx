import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CompanyProfilePage from './CompanyProfilePage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ companyId: 'e1' }) }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'

const CLIENT = {
  id: 'e1', company_name: 'Skyline Capital', vp_source_key: 'SKYLINE01',
  br_number: '2100031', cr_number: '2100031', status: 'live',
  company_type: 'Private company limited by shares',
  incorporation_place: 'HK',
  incorporation_date: '2024-05-20', created_at: '2024-05-02',
  is_client: true, is_corporate_party: false,
  registered_address: { line1: 'Unit 12A', city: 'Central', country: 'HK' },
  contacts: [{ id: 'c1', contact_type: 'phone', contact_value: '+852 3500 1234' }],
  documents: [{
    id: 'd1', document_type_code: 'coi', current_version: 1,
    file_name: 'brand-guideline-v3.pdf',
    document_types: { code: 'coi', label: 'Certificate of Incorporation' },
  }],
  officers: [{
    id: 'o1', role: 'director', appointed_date: '2024-05-20', is_current: true,
    persons: { id: 'p1', full_name: 'John Smith', email: 'js@x.com' },
  }],
  shareholders: [], beneficial_owners: [], secretaries: [],
  cases: { nar1: [], nnc1: [] },
}

const CORP_ONLY = {
  ...CLIENT,
  id: 'e3', company_name: 'Asia BC Ltd.',
  is_client: false, is_corporate_party: true,
  tcsp_licence_no: 'TC000807', incorporation_place: 'Hong Kong',
  officers: [], cases: undefined,
}

const renderPage = () => render(<MemoryRouter><CompanyProfilePage /></MemoryRouter>)

// The profile forms now read their dropdowns from /lookups, so api.get has to
// answer per-URL rather than returning the same payload for everything.
const LOOKUPS = {
  gender: [{ code: 'M', label: 'Male' }, { code: 'F', label: 'Female' }],
  nationality: [{ code: 'Dutch', label: 'Dutch' }, { code: 'British', label: 'British' }],
  marital_status: [{ code: 'SI', label: 'Single' }, { code: 'MA', label: 'Married' }],
  country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'ZA', label: 'South Africa' }],
}
const mockGet = (data) =>
  api.get.mockImplementation(url =>
    Promise.resolve(url === '/lookups' ? LOOKUPS : data))

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  mockGet(CLIENT)
  api.patch.mockResolvedValue({})
})

describe('CompanyProfilePage', () => {
  it('shows a loading state first', () => {
    api.get.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('renders core company information', async () => {
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText('SKYLINE01')).toBeInTheDocument()
    expect(screen.getByText('+852 3500 1234')).toBeInTheDocument()
    expect(screen.getByText('Unit 12A, Central, HK')).toBeInTheDocument()
  })

  it('shows Country of Incorporation in read-only info even when not a corporate party', async () => {
    // Regression: incorporation_place is editable for every company but was only
    // displayed inside the corporate-party tile, so a plain client could save it
    // and never see it again.
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText('Country of Incorporation')).toBeInTheDocument()
    // 'HK' resolves to its country label via the /lookups vocabulary
    expect(screen.getByText('Hong Kong')).toBeInTheDocument()
    // and the corporate-party tile is hidden for a client (field not duplicated)
    expect(screen.queryByText('Corporate Party Details')).not.toBeInTheDocument()
  })

  it('shows client-only tiles and the Cases pane when is_client', async () => {
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText(/Director\(s\)/)).toBeInTheDocument()
    expect(screen.getByText(/Shareholder\(s\)/)).toBeInTheDocument()
    expect(screen.getByText('Cases')).toBeInTheDocument()
    expect(screen.getByText('John Smith')).toBeInTheDocument()
    // corporate-party tile hidden when the flag is off
    expect(screen.queryByText('Corporate Party Details')).not.toBeInTheDocument()
  })

  it('hides client tiles + Cases pane and reveals the corporate tile for a non-client', async () => {
    mockGet(CORP_ONLY)
    renderPage()
    await screen.findByText('Company Information')
    expect(screen.getByText('Corporate Party Details')).toBeInTheDocument()
    expect(screen.getByText('TC000807')).toBeInTheDocument()
    expect(screen.queryByText('Cases')).not.toBeInTheDocument()
    expect(screen.queryByText(/Director\(s\)/)).not.toBeInTheDocument()
  })

  it('shows an empty Cases pane when there are no cases', async () => {
    renderPage()
    await screen.findByText('Cases')
    expect(screen.getByText('No cases yet.')).toBeInTheDocument()
  })

  it('toggles a flag via PATCH /flags and refetches', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Company Information')
    await user.click(screen.getByRole('switch', { name: 'Is Corporate Party' }))
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/companies/e1/flags', { is_corporate_party: true })
    })
  })

  it('edits company info and PATCHes only the changed fields', async () => {
    const user = userEvent.setup()
    renderPage()
    // Party tiles carry their own Edit buttons — scope to the info card.
    const infoCard = (await screen.findByText('Company Information')).closest('.card')
    await user.click(within(infoCard).getByRole('button', { name: 'Edit' }))

    const nameInput = screen.getByLabelText('Company Name')
    await user.clear(nameInput)
    await user.type(nameInput, 'Skyline Capital Management')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(api.patch).toHaveBe