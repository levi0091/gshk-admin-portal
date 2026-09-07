import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import CopyPartiesModal, { holdingPercents } from './CopyPartiesModal.jsx'

vi.mock('../lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
import { api } from '../lib/api.js'
import { _resetLookups } from '../lib/lookups.js'

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

// One class of 1,000 shares: Alice 300 (30%), Bob 100 (10%), Acme Holdings 600
// … which would be 100%, so the numbers below are the ones that matter, not
// the tidiness of the cap table.
const SHARE_CLASSES = [{ id: 'sc1', class_name: 'Ordinary', currency: 'HKD',
                         total_issued: 1000 }]
const SHAREHOLDERS = [
  { id: 'sh1', person_id: 'p1', shares_held: 300, is_current: true,
    persons: { full_name: 'Alice Wong' } },
  { id: 'sh2', person_id: 'p2', shares_held: 100, is_current: true,
    persons: { full_name: 'Bob Chan' } },
  { id: 'sh3', corporate_entity_id: 'c1', shares_held: 600, is_current: true,
    corporate_entity: { company_name: 'Acme Holdings Ltd.' } },
]
const OFFICERS = [
  { id: 'o1', person_id: 'p1', role: 'director', is_current: true,
    persons: { full_name: 'Alice Wong' } },
  { id: 'o2', person_id: 'p9', role: 'director', is_current: true,
    persons: { full_name: 'Dora Lam' } },
]

const onClose = vi.fn()
const onSaved = vi.fn()

const renderModal = (props = {}) => render(
  <CopyPartiesModal companyId="e1" officers={OFFICERS} shareholders={SHAREHOLDERS}
                    shareClasses={SHARE_CLASSES} existing={[]}
                    onClose={onClose} onSaved={onSaved} {...props} />
)

beforeEach(() => {
  vi.clearAllMocks()
  _resetLookups()
  api.get.mockResolvedValue(LOOKUPS)
  api.post.mockResolvedValue({ id: 'bo1' })
})

describe('holdingPercents', () => {
  it('measures a holding against the WHOLE issued capital, not one class', () => {
    // s.653D asks about the issued shares of the company. A member holding
    // 30% of a minority class does not control the company, and dividing by
    // that class alone would say they do.
    const classes = [{ total_issued: 100 }, { total_issued: 900 }]
    const holders = [{ person_id: 'p1', shares_held: 30, is_current: true }]
    expect(holdingPercents(holders, classes).get('p:p1')).toBeCloseTo(3)
  })

  it('adds up a member holding more than one class', () => {
    const holders = [
      { person_id: 'p1', shares_held: 200, is_current: true },
      { person_id: 'p1', shares_held: 300, is_current: true },
    ]
    expect(holdingPercents(holders, SHARE_CLASSES).get('p:p1')).toBeCloseTo(50)
  })

  it('ignores a former member, who holds nothing', () => {
    // Counting a transferred-out holder alongside the person they sold to
    // would push the register over 100%.
    const holders = [
      { person_id: 'p1', shares_held: 300, is_current: false },
      { person_id: 'p2', shares_held: 300, is_current: true },
    ]
    const pct = holdingPercents(holders, SHARE_CLASSES)
    expect(pct.has('p:p1')).toBe(false)
    expect(pct.get('p:p2')).toBeCloseTo(30)
  })

  it('returns null rather than a percentage out of a partial total', () => {
    // A number quietly computed from a smaller denominator is the kind of
    // wrong that looks right.
    expect(holdingPercents(SHAREHOLDERS, [{ total_issued: 1000 },
                                          { total_issued: null }])).toBeNull()
    expect(holdingPercents(SHAREHOLDERS, [])).toBeNull()
  })
})

describe('CopyPartiesModal', () => {
  it('opens on Shareholders, which is the case it exists for', async () => {
    renderModal()
    expect(await screen.findByRole('tab', { name: 'Shareholders' }))
      .toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Directors' }))
      .toHaveAttribute('aria-selected', 'false')
  })

  it('pre-ticks only the members actually over 25%', async () => {
    // The default nature of control is "holds more than 25% of the issued
    // shares". Pre-ticking a 10% holder would put that claim on a statutory
    // register on the operator's behalf.
    renderModal()
    await screen.findByText('Alice Wong')
    expect(screen.getByRole('checkbox', { name: /Alice Wong/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Acme Holdings/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Bob Chan/ })).not.toBeChecked()
  })

  it('shows each member’s share so the 25% test can be checked', async () => {
    renderModal()
    expect(await screen.findByText('30.00%')).toBeInTheDocument()
    expect(screen.getByText('10.00%')).toBeInTheDocument()
    // The unit is stated once, above the list — "% of issued shares" on every
    // row wrapped to two lines in a 520px dialog and took the names to three.
    expect(screen.getByText(/Share of the company’s total issued shares/))
      .toBeInTheDocument()
  })

  it('ticks nothing, and says why, when the share cannot be computed', async () => {
    // Some ETL'd companies carry a class with no Total Number. Guessing there
    // would be guessing at the one thing this default asserts.
    renderModal({ shareClasses: [{ id: 'sc1', class_name: 'Ordinary' }] })
    await screen.findByText('Alice Wong')
    expect(screen.getByRole('checkbox', { name: /Alice Wong/ })).not.toBeChecked()
    expect(screen.getByText(/needs a Total Number/)).toBeInTheDocument()
  })

  it('copies the party only — never the shareholding', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByText('Alice Wong')
    await user.click(screen.getByRole('checkbox', { name: /Acme Holdings/ }))  // untick
    await user.click(screen.getByRole('button', { name: /^Copy/ }))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    const [path, body] = api.post.mock.calls[0]
    expect(path).toBe('/companies/e1/beneficial-owners')
    expect(body).toEqual({
      person_id: 'p1',
      owner_type: 'significant_controller',
      nature_of_control: 'over_25_percent',
      is_current: true,
    })
    // A beneficial owner is a different fact from a shareholding: s.653D asks
    // HOW control is held, not how many shares.
    expect(body).not.toHaveProperty('shares_held')
    expect(body).not.toHaveProperty('share_class_id')
  })

  it('sends corporate_entity_id for a body corporate, never person_id', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByText('Acme Holdings Ltd.')
    await user.click(screen.getByRole('checkbox', { name: /Alice Wong/ }))  // untick
    await user.click(screen.getByRole('button', { name: /^Copy/ }))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    const [, body] = api.post.mock.calls[0]
    expect(body.corporate_entity_id).toBe('c1')
    expect(body).not.toHaveProperty('person_id')
  })

  it('switches to the directors, and defaults their control to influence', async () => {
    // A director's control is held through office — s.653D condition (b).
    // Offering condition (a) would say they hold over 25% of the shares, which
    // the directors tile does not know.
    const user = userEvent.setup()
    renderModal()
    await user.click(await screen.findByRole('tab', { name: 'Directors' }))

    expect(await screen.findByText('Dora Lam')).toBeInTheDocument()
    expect(screen.getByLabelText(/Nature of Control/)).toHaveValue('significant_influence')
    // And nothing is pre-ticked: being a director is not by itself significant
    // control, and a screen arriving with all of them ticked invites the claim.
    expect(screen.getByRole('checkbox', { name: /Dora Lam/ })).not.toBeChecked()
  })

  it('will not add somebody who is already a beneficial owner', async () => {
    renderModal({ existing: [{ id: 'bo1', person_id: 'p1' }] })
    await screen.findByText('Alice Wong')
    const row = screen.getByRole('checkbox', { name: /Alice Wong/ })
    expect(row).toBeDisabled()
    expect(row).not.toBeChecked()
    expect(screen.getByText('Already a beneficial owner')).toBeInTheDocument()
  })

  it('lists one row per party, not one per holding', async () => {
    // A member holding two classes is one controller, and two rows would be
    // two copies of the same person on the register.
    renderModal({
      shareholders: [
        { id: 'a', person_id: 'p1', shares_held: 200, is_current: true,
          persons: { full_name: 'Alice Wong' } },
        { id: 'b', person_id: 'p1', shares_held: 300, is_current: true,
          persons: { full_name: 'Alice Wong' } },
      ],
    })
    await screen.findByText('Alice Wong')
    expect(screen.getAllByRole('checkbox', { name: /Alice Wong/ })).toHaveLength(1)
    expect(screen.getByText('50.00%')).toBeInTheDocument()
  })

  it('refuses an empty selection rather than posting nothing', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByText('Alice Wong')
    await user.click(screen.getByRole('checkbox', { name: /Alice Wong/ }))
    await user.click(screen.getByRole('checkbox', { name: /Acme Holdings/ }))
    await user.click(screen.getByRole('button', { name: /^Copy/ }))

    expect(await screen.findByText('Select at least one party to copy.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('names exactly which parties failed, and keeps the ones that worked', async () => {
    // Separate inserts with no transaction around them, so a copy of three can
    // genuinely half-succeed. Reporting the batch as failed would send the
    // operator back to redo the two that worked.
    const user = userEvent.setup()
    api.post
      .mockResolvedValueOnce({ id: 'bo1' })
      .mockRejectedValueOnce(new Error('duplicate key'))
    renderModal()
    await screen.findByText('Alice Wong')
    await user.click(screen.getByRole('button', { name: /^Copy/ }))

    expect(await screen.findByText(/Copied 1\./)).toBeInTheDocument()
    expect(screen.getByText(/duplicate key/)).toBeInTheDocument()
    // Refreshed, because the one that worked is on the register now — but the
    // dialog stays open, over the message that says so.
    expect(onSaved).toHaveBeenCalledWith({ close: false })
  })

  it('closes only when every copy succeeded', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByText('Alice Wong')
    await user.click(screen.getByRole('button', { name: /^Copy/ }))

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ close: true }))
  })

  it('applies one nature of control to everything copied', async () => {
    const user = userEvent.setup()
    renderModal()
    await screen.findByText('Alice Wong')
    await user.selectOptions(screen.getByLabelText(/Nature of Control/),
                             'significant_influence')
    await user.click(screen.getByRole('button', { name: /^Copy/ }))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
    for (const [, body] of api.post.mock.calls) {
      expect(body.nature_of_control).toBe('significant_influence')
    }
    // Said out loud on the form, because applying one control to several
    // people silently is how one of them ends up wrong.
    expect(screen.getByText(/Applied to everyone copied/)).toBeInTheDocument()
  })

  it('says so when there is nothing on the tab to copy', async () => {
    renderModal({ shareholders: [] })
    expect(await screen.findByText('This company has no shareholders recorded.'))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Copy/ })).toBeDisabled()
  })

  it('leaves out a former member — they hold nothing to be significant about', async () => {
    renderModal({
      shareholders: [
        ...SHAREHOLDERS,
        { id: 'sh4', person_id: 'p8', shares_held: 400, is_current: false,
          persons: { full_name: 'Gone Away' } },
      ],
    })
    await screen.findByText('Alice Wong')
    expect(screen.queryByText('Gone Away')).not.toBeInTheDocument()
  })
})
