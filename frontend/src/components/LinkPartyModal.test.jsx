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
    // Every box on this form is required now, so the happy path has to fill
    // them. Status is not typed: it arrives pre-set to Current.
    await user.type(screen.getByLabelText(/Shares Held/), '100')
    await user.type(screen.getByLabelText(/Amount Paid/), '100')
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

    // Regex, not the exact string: Status carries a required `*` on this form.
    await user.selectOptions(await screen.findByLabelText(/Status/), 'false')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1/shareholders/sh1',
      expect.objectContaining({ is_current: false })))
  })

  it('names EVERY required box a shareholder is missing, not just the first', async () => {
    // Levi 2026-09-07: every field on this form is mandatory. Reporting them
    // one press at a time is four round trips through a save that was never
    // going to succeed, and never shows how much is left to do.
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    expect(await screen.findByText(
      'These are required: Class of Shares, Shares Held, Amount Paid.'))
      .toBeInTheDocument()
    // Named in the banner AND marked on the boxes, so the operator does not
    // have to hold the list in their head while scrolling back to them.
    expect(screen.getByLabelText(/Class of Shares/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText(/Shares Held/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText(/Amount Paid/)).toHaveAttribute('aria-invalid', 'true')
    // Status is required too, and is NOT listed — it opens pre-set to Current.
    expect(screen.getByLabelText(/Status/)).not.toHaveAttribute('aria-invalid')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('names one missing box in the singular', async () => {
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.selectOptions(await screen.findByLabelText(/Class of Shares/), 'sc1')
    await user.type(screen.getByLabelText(/Shares Held/), '100')
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    expect(await screen.findByText('Amount Paid is required.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('stops flagging a box the moment it has a value', async () => {
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    const held = await screen.findByLabelText(/Shares Held/)
    expect(held).toHaveAttribute('aria-invalid', 'true')
    await user.type(held, '100')
    expect(held).not.toHaveAttribute('aria-invalid')
  })

  it('accepts a nil-paid holding — 0 is an answer, not an empty box', async () => {
    // `!attrs[key]` would have rejected this, which would have made a holding
    // paid up to nothing unrecordable the day Amount Paid became required.
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.selectOptions(await screen.findByLabelText(/Class of Shares/), 'sc1')
    await user.type(screen.getByLabelText(/Shares Held/), '100')
    await user.type(screen.getByLabelText(/Amount Paid/), '0')
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/companies/e1/shareholders',
      expect.objectContaining({ amount_paid: '0', is_current: true })))
  })

  it('lets an ETL row keep a blank it arrived with, but not be cleared', async () => {
    // Creation is stricter than editing, the rule `company_type` and the HKID
    // check digit already follow. Viewpoint left plenty of holdings with no
    // amount paid; enforcing that on edit would mean correcting a misspelled
    // class required inventing a paid-up figure first.
    const user = userEvent.setup()
    renderModal({
      relation: 'shareholders',
      link: { id: 'sh1', share_class_id: 'sc1', shares_held: 100,
              amount_paid: null, is_current: true,
              persons: { full_name: 'John Smith' } },
      shareClasses: [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD' }],
    })

    await user.clear(await screen.findByLabelText(/Shares Held/))
    await user.type(screen.getByLabelText(/Shares Held/), '250')
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/companies/e1/shareholders/sh1',
      expect.objectContaining({ shares_held: '250' })))

    // Clearing one that WAS filled is this edit's doing, and is refused.
    api.patch.mockClear()
    await user.clear(screen.getByLabelText(/Shares Held/))
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
    expect(await screen.findByText('Shares Held is required.')).toBeInTheDocument()
    expect(api.patch).not.toHaveBeenCalled()
  })

  it('opens the Company Secretary form with the Position already filled', async () => {
    // Levi 2026-09-07. This tile writes entity_officers with role fixed to
    // company_secretary server-side, so the position is "Company Secretary" on
    // all but a handful of rows and typing it every time was pure friction.
    const user = userEvent.setup()
    renderModal({ relation: 'secretaries' })

    expect(await screen.findByLabelText(/Position/)).toHaveValue('Company Secretary')
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.type(screen.getByLabelText(/Appointed/), '2025-01-09')
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/companies/e1/secretaries',
      expect.objectContaining({ position: 'Company Secretary',
                                appointed_date: '2025-01-09' })))
  })

  it('will not add a secretary with no appointment date', async () => {
    // NOT defaulted to today, unlike Position: a wrong date here is worse than
    // an empty one, because it looks filled in.
    const user = userEvent.setup()
    renderModal({ relation: 'secretaries' })
    await user.type(screen.getByLabelText('Search parties'), 'john')
    await user.click(await screen.findByText('John Smith'))
    await user.click(screen.getByRole('button', { name: 'Link Party' }))

    expect(await screen.findByText('Appointed is required.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('does not pre-fill Position when EDITING a secretary that has none', async () => {
    // A default that overwrote a stored blank would be a silent edit nobody
    // asked for — the operator opened the row to change something else.
    renderModal({
      relation: 'secretaries',
      link: { id: 'sec1', position: null, appointed_date: '2020-01-01',
              corporate_entity: { company_name: 'Get Started HK Limited' } },
    })
    expect(await screen.findByLabelText(/Position/)).toHaveValue('')
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
