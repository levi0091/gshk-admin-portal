import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import PersonProfilePage from './PersonProfilePage.jsx'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate, useParams: () => ({ personId: 'p1' }) }
})

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), upload: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'

const PERSON = {
  id: 'p1', full_name: 'John Smith Junior', given_names: 'John Smith', surname: 'Smith',
  nationality: 'British (BNO)', date_of_birth: '1979-03-14', email: 'js@x.com',
  residential_address: { line1: 'Flat 3B', city: 'Mid-Levels', country: 'HK' },
  identity_documents: [
    { id: 'i1', id_type: 'hkid', id_number: 'A1234567(8)', is_primary: true, issuing_country: 'HK' },
    { id: 'i2', id_type: 'passport', id_number: '987654321', is_primary: false, issuing_country: 'UK' },
  ],
  documents: [
    {
      id: 'd1', document_type_code: 'id_scan', current_version: 2,
      document_versions: [
        { id: 'v1', version_number: 1, file_name: 'hkid-front.pdf', created_at: '2024-05-02' },
        { id: 'v2', version_number: 2, file_name: 'hkid-both.pdf', created_at: '2026-06-04' },
      ],
    },
  ],
  role_rollup: [
    { relation: 'officer', entity_id: 'e1', company_name: 'Skyline Capital', role: 'director', is_current: true },
    { relation: 'officer', entity_id: 'e2', company_name: 'Harbour Tech', role: 'director', is_current: true },
    { relation: 'shareholder', entity_id: 'e1', company_name: 'Skyline Capital', is_current: true },
  ],
}

const renderPage = () => render(<MemoryRouter><PersonProfilePage /></MemoryRouter>)

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
  mockGet(PERSON)
  api.patch.mockResolvedValue({})
})

describe('PersonProfilePage', () => {
  it('renders personal information and residential address', async () => {
    renderPage()
    await screen.findByText('Personal Information')
    expect(screen.getByText('British (BNO)')).toBeInTheDocument()
    // The residential address renders as the separate lines CR receives — this
    // is the address a NAR1 files for the director, and a joined string hides
    // whether any single line is over CR's 60-character limit.
    expect(screen.getByText('Flat 3B')).toBeInTheDocument()
    expect(screen.getByText('Mid-Levels')).toBeInTheDocument()
  })

  it('shows role pills counted per relation in the header', async () => {
    renderPage()
    await screen.findByText('Personal Information')
    // two director appointments, one shareholding
    expect(screen.getByText('Director ×2')).toBeInTheDocument()
    expect(screen.getByText('Shareholder ×1')).toBeInTheDocument()
  })

  it('lists identity documents with the primary flagged', async () => {
    renderPage()
    await screen.findByText('Personal Information')
    expect(screen.getByText('A1234567(8)')).toBeInTheDocument()
    expect(screen.getByText('987654321')).toBeInTheDocument()
    expect(screen.getByText('PRIMARY')).toBeInTheDocument()
  })

  it('groups document history by type with current + superseded versions', async () => {
    renderPage()
    await screen.findByText('Document History')
    expect(screen.getByText('2 versions')).toBeInTheDocument()
    // newest version is CURRENT, older preserved as SUPERSEDED
    expect(screen.getByText('CURRENT')).toBeInTheDocument()
    expect(screen.getByText('SUPERSEDED')).toBeInTheDocument()
    expect(screen.getByText(/v2 · hkid-both\.pdf/)).toBeInTheDocument()
    expect(screen.getByText(/v1 · hkid-front\.pdf/)).toBeInTheDocument()
  })

  it('shows the role roll-up read-only and links out to each company', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Appointments & Roles')
    expect(screen.getByText(/Read-only here/)).toBeInTheDocument()
    expect(screen.getByText('Director — Skyline Capital')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Open →' })[1])
    expect(navigate).toHaveBeenCalledWith('/companies/e2')
  })

  it('edits a person field and PATCHes only what changed', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('Personal Information')
    await user.click(screen.getByRole('button', { name: 'Edit' }))

    const occupation = screen.getByLabelText('Occupation')
    await user.type(occupation, 'Company Director')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/persons/p1', { occupation: 'Company Director' })
    })
  })

  it('renders an error state when the fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    renderPage()
    expect(await screen.findByText(/Failed to load person: boom/)).toBeInTheDocument()
  })
})
