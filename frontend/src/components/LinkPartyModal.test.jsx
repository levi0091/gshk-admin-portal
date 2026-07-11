import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import LinkPartyModal from './LinkPartyModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }))
import { api } from '../lib/api.js'

const onClose = vi.fn()
const onSaved = vi.fn()

const renderModal = (props = {}) => render(
  <LinkPartyModal companyId="e1" relation="officers"
                  onClose={onClose} onSaved={onSaved} {...props} />
)

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue({ persons: [{ id: 'p1', full_name: 'John Smith' }] })
  api.post.mockResolvedValue({ id: 'lnk1' })
  api.patch.mockResolvedValue({})
})

describe('LinkPartyModal', () => {
  it('links an existing person with person_id only (never both party ids)', async () => {
    const user = userEvent.setup()
    renderModal()

    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.selectOptions(screen.getByLabelText('Role'), 'director')
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const [path, body] = api.post.mock.calls[0]
    expect(path).toBe('/companies/e1/officers')
    expect(body.person_id).toBe('p1')
    expect(body).not.toHaveProperty('corporate_entity_id')
    expect(body.role).toBe('director')
  })

  it('searches the corporate-party registry and links corporate_entity_id only', async () => {
    const user = userEvent.setup()
    api.get.mockResolvedValue({ companies: [{ id: 'c9', company_name: 'Asia BC Ltd.' }] })
    renderModal()

    await user.click(screen.getByRole('tab', { name: 'Corporate Party' }))
    await user.type(screen.getByLabelText('Search parties'), 'asia')
    // corporate search is scoped to is_corporate_party
    await waitFor(() => {
      expect(api.get.mock.calls.some(c => c[0].includes('flag=corporate_party'))).toBe(true)
    })
    await user.click(await screen.findByText('Asia BC Ltd.'))
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    const body = api.post.mock.calls[0][1]
    expect(body.corporate_entity_id).toBe('c9')
    expect(body).not.toHaveProperty('person_id')
  })

  it('blocks linking when no party is selected', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.click(screen.getByRole('button', { name: 'Link Party' }))
    expect(await screen.findByText('Select a party to link')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('edits link attributes via PATCH and does not offer a party picker (OQ-1)', async () => {
    const user = userEvent.setup()
    const link = { id: 'lnk1', role: 'director', position: 'Chair',
                   persons: { full_name: 'John Smith' } }
    renderModal({ link })

    // party is immutable on edit — no search box
    expect(screen.queryByLabelText('Search parties')).not.toBeInTheDocument()
    expect(screen.getByText(/remove this link and add a new one/)).toBeInTheDocument()

    const position = screen.getByLabelText('Position')
    await user.clear(position)
    await user.type(position, 'Managing Director')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith('/companies/e1/officers/lnk1',
        expect.objectContaining({ position: 'Managing Director' }))
    })
    expect(api.post).not.toHaveBeenCalled()
  })

  it('renders relation-specific attribute fields for beneficial owners', () => {
    renderModal({ relation: 'beneficial-owners' })
    expect(screen.getByLabelText('Interest %')).toBeInTheDocument()
    expect(screen.getByLabelText('Voting %')).toBeInTheDocument()
    expect(screen.queryByLabelText('Role')).not.toBeInTheDocument()
  })

  it('surfaces a server error (e.g. the exactly-one-party 422)', async () => {
    const user = userEvent.setup()
    api.post.mockRejectedValue(new Error('Provide exactly one of person_id or corporate_entity_id'))
    renderModal()
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.click(screen.getByRole('button', { name: 'Link Party' }))
    expect(await screen.findByText(/exactly one of person_id/)).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })
})
