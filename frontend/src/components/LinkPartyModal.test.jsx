import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import LinkPartyModal from './LinkPartyModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'

const onClose = vi.fn()
const onSaved = vi.fn()

// The beneficial-owner dropdowns are served from /lookups, so the modal's own
// party search and the vocabularies come through the same mocked api.get.
const LOOKUPS = {
  bo_owner_type: [{ code: 'ubo', label: 'Ultimate Beneficial Owner' },
                  { code: 'significant_controller', label: 'Significant Controller' }],
  bo_nature_of_control: [
    { code: 'over_25_percent',
      label: 'Holds more than 25% of the issued shares of the company' },
    { code: 'significant_influence',
      label: 'Has the right to exercise, or actually exercises, significant '
           + 'influence or control over the company' }],
}

const renderModal = (props = {}) => render(
  <LinkPartyModal companyId="e1" relation="officers"
                  onClose={onClose} onSaved={onSaved} {...props} />
)

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  api.get.mockImplementation(url => (url === '/lookups'
    ? Promise.resolve(LOOKUPS)
    : Promise.resolve({ persons: [{ id: 'p1', full_name: 'John Smith' }] })))
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

  it('renders relation-specific attribute fields for beneficial owners', async () => {
    renderModal({ relation: 'beneficial-owners' })
    expect(await screen.findByLabelText('Owner Type')).toBeInTheDocument()
    expect(screen.getByLabelText('Nature of Control over the Company')).toBeInTheDocument()
    expect(screen.queryByLabelText('Role')).not.toBeInTheDocument()
    // REPLACED by Nature of Control (Levi 2026-09-04). Two numeric columns
    // could not express "has the right to exercise significant influence or
    // control" at all — a controller with no shares and a veto rendered as
    // 0/0, which reads as "not a controller".
    expect(screen.queryByLabelText('Interest %')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Voting %')).not.toBeInTheDocument()
  })

  it('offers the two Companies Ordinance conditions and nothing typed by hand', async () => {
    renderModal({ relation: 'beneficial-owners' })

    const nature = await screen.findByLabelText('Nature of Control over the Company')
    await waitFor(() => {
      expect([...nature.querySelectorAll('option')].map(o => o.value))
        .toEqual(['', 'over_25_percent', 'significant_influence'])
    })
    const kind = screen.getByLabelText('Owner Type')
    expect([...kind.querySelectorAll('option')].map(o => o.textContent))
      .toEqual(['Select…', 'Ultimate Beneficial Owner', 'Significant Controller'])
  })

  it('offers the company own classes of shares, never a free-text id', async () => {
    // THE BUG (Levi 2026-09-04). This was a text box labelled "Share Class ID"
    // over a `uuid NOT NULL REFERENCES share_classes(id)` column. Typing "1"
    // produced a database error that reached the browser without CORS headers,
    // so the screen reported the API as unreachable for a request the API had
    // understood and correctly rejected.
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })

    const picker = await screen.findByLabelText(/Class of Shares/)
    expect(picker.tagName).toBe('SELECT')
    expect([...picker.querySelectorAll('option')].map(o => o.value))
      .toEqual(['', 'sc1'])
    // The currency is part of a class's identity: a company can hold an HKD
    // and a USD Ordinary, and CR's section 11 states both.
    expect(within(picker).getByText('Ordinary · HKD')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.selectOptions(picker, 'sc1')
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/companies/e1/shareholders',
      expect.objectContaining({ share_class_id: 'sc1' })))
  })

  it('says what to do when the company has no share capital yet', async () => {
    // An empty dropdown with no explanation is the same dead end the free-text
    // box was — it just fails earlier.
    renderModal({ relation: 'shareholders', shareClasses: [] })
    expect(await screen.findByText(/no share capital recorded yet/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Class of Shares/)).toBeDisabled()
  })

  it('sends is_current as a real boolean, which is how a transfer is recorded', async () => {
    // `is_current: "false"` is a non-empty string, which Python reads as true —
    // the register would then show a transferred-out member as still holding
    // the shares.
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      link: { id: 'sh1', share_class_id: 'sc1', shares_held: 100, is_current: true,
              persons: { full_name: 'John Smith' } },
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })

    await user.selectOptions(await screen.findByLabelText('Status'), 'false')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1/shareholders/sh1',
      expect.objectContaining({ is_current: false })))
  })

  it('refuses to link a shareholder with no class of shares chosen', async () => {
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    expect(await screen.findByText('Class of Shares is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
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
