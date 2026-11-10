import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import RecipientPicker, { isAddress } from './RecipientPicker.jsx'

const BOARD = [
  { person_id: 'p1', name: 'AH CHAN', email: 'chan@example.com',
    role: 'director', party_type: 'individual', reason: null },
  { person_id: 'p2', name: 'BO LEE', email: 'lee@example.com',
    role: 'director', party_type: 'individual', reason: null },
  { person_id: null, name: 'HOLDCO LIMITED', email: null, role: 'director',
    party_type: 'corporate',
    reason: 'a corporate director has no address on record' },
]

function renderPicker(over = {}) {
  const onChange = vi.fn()
  const props = {
    recipients: BOARD,
    to: ['chan@example.com', 'lee@example.com'],
    onChange, disabled: false, maxRecipients: 20, ...over,
  }
  const view = render(<RecipientPicker {...props} />)
  return { ...view, onChange, props }
}

describe('RecipientPicker', () => {
  it('names the director behind each address', () => {
    // The operator is deciding whether a PERSON should see the return. An
    // address alone does not tell them which director they are removing.
    renderPicker()
    expect(screen.getByText('AH CHAN')).toBeInTheDocument()
    expect(screen.getByText('chan@example.com')).toBeInTheDocument()
  })

  it('lists a director with no address instead of dropping them', () => {
    renderPicker()
    expect(screen.getByText(/HOLDCO LIMITED/)).toBeInTheDocument()
    expect(screen.getByText(/no address on record/)).toBeInTheDocument()
  })

  it('does not offer a remove button on a director it cannot write to', () => {
    // There is nothing to remove — they were never a recipient.
    renderPicker()
    expect(screen.queryByRole('button', { name: /Remove HOLDCO/ })).toBeNull()
  })

  it('removes an address without touching the rest', async () => {
    const user = userEvent.setup()
    const { onChange } = renderPicker()
    await user.click(screen.getByRole('button', { name: 'Remove chan@example.com' }))
    expect(onChange).toHaveBeenCalledWith(['lee@example.com'])
  })

  // ── suggestion pills (Levi 2026-10-29) ──────────────────────────────────

  it('offers each director with an address as a pill, and none without one', () => {
    renderPicker({ to: [] })
    const pills = within(screen.getByTestId('recipient-suggestions')).getAllByRole('button')
    expect(pills.map(b => b.getAttribute('aria-label'))).toEqual([
      'Add AH CHAN (chan@example.com)', 'Add BO LEE (lee@example.com)'])
    // The corporate director has no address: listed with its reason, never a pill.
    expect(screen.getByText(/HOLDCO LIMITED/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add HOLDCO/ })).toBeNull()
  })

  it('adds the pill\'s address when it is clicked', async () => {
    const user = userEvent.setup()
    const { onChange } = renderPicker({ to: [] })
    await user.click(screen.getByRole('button', { name: 'Add AH CHAN (chan@example.com)' }))
    expect(onChange).toHaveBeenCalledWith(['chan@example.com'])
  })

  it('drops a pill once its address is chosen, and brings it back when the chip goes', () => {
    const { rerender, props } = renderPicker({ to: ['lee@example.com'] })
    expect(screen.queryByRole('button', { name: /Add BO LEE/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Add AH CHAN (chan@example.com)' })).toBeInTheDocument()
    rerender(<RecipientPicker {...props} to={[]} />)
    expect(screen.getByRole('button', { name: 'Add BO LEE (lee@example.com)' })).toBeInTheDocument()
  })

  it('shows no suggestions when every address is already chosen', () => {
    renderPicker()
    expect(screen.queryByTestId('recipient-suggestions')).toBeNull()
  })

  it('does not say anyone is added automatically', () => {
    renderPicker({ to: [] })
    expect(screen.queryByText(/Every current director/)).toBeNull()
    expect(screen.getByText(/No one is added automatically/)).toBeInTheDocument()
  })

  it('points at suggestions only when there are some', () => {
    // Every address already chosen: nothing below to choose from.
    renderPicker()
    expect(screen.queryByText(/suggestions below/)).toBeNull()
    expect(screen.getByText(/Type the address it should go to/)).toBeInTheDocument()
  })

  it('gives a read-only reader no instructions to choose', () => {
    renderPicker({ to: [], readOnly: true })
    expect(screen.queryByText(/No one is added automatically/)).toBeNull()
  })

  it('disables the pills while a send is running', () => {
    renderPicker({ to: [], disabled: true })
    expect(screen.getByRole('button', { name: /Add AH CHAN/ })).toBeDisabled()
  })

  it('shows the board as plain text, with no pills and no warning, to a reader who cannot send', () => {
    renderPicker({ to: [], readOnly: true })
    const board = screen.getByTestId('recipient-board')
    expect(board).toHaveTextContent('chan@example.com')
    expect(within(board).queryByRole('button')).toBeNull()
    expect(screen.queryByTestId('recipient-suggestions')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('adds a typed address', async () => {
    const user = userEvent.setup()
    const { onChange } = renderPicker()
    await user.type(screen.getByLabelText('Add a recipient'), 'levi@zenexflow.com')
    await user.click(screen.getByRole('button', { name: 'Add recipient' }))
    expect(onChange).toHaveBeenCalledWith(
      ['chan@example.com', 'lee@example.com', 'levi@zenexflow.com'])
  })

  it('adds on Enter without submitting anything', async () => {
    // This input sits above a Send button. Enter must never reach it.
    const user = userEvent.setup()
    const { onChange } = renderPicker()
    await user.type(screen.getByLabelText('Add a recipient'),
                    'levi@zenexflow.com{Enter}')
    expect(onChange).toHaveBeenCalledWith(
      ['chan@example.com', 'lee@example.com', 'levi@zenexflow.com'])
  })

  it('refuses a value that is not an address', async () => {
    const user = userEvent.setup()
    const { onChange } = renderPicker()
    await user.type(screen.getByLabelText('Add a recipient'), 'nope')
    await user.click(screen.getByRole('button', { name: 'Add recipient' }))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByText(/is not an email address/)).toBeInTheDocument()
  })

  it('treats a duplicate as already done rather than as an error', async () => {
    // The address is there, which is what the operator was asking for.
    const user = userEvent.setup()
    const { onChange } = renderPicker()
    await user.type(screen.getByLabelText('Add a recipient'), 'CHAN@example.com')
    await user.click(screen.getByRole('button', { name: 'Add recipient' }))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.queryByText(/is not an email address/)).toBeNull()
  })

  it('stops at the recipient ceiling', async () => {
    const user = userEvent.setup()
    const { onChange } = renderPicker({ to: ['a@b.com', 'c@d.com'], maxRecipients: 2 })
    await user.type(screen.getByLabelText('Add a recipient'), 'e@f.com')
    await user.click(screen.getByRole('button', { name: 'Add recipient' }))
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByText(/at most 2 recipients/)).toBeInTheDocument()
  })

  it('warns rather than showing an empty box when every chip is gone', () => {
    renderPicker({ to: [] })
    expect(screen.getByRole('alert')).toHaveTextContent(/No recipients/)
  })

  it('cannot be edited by someone without write access', () => {
    renderPicker({ disabled: true })
    expect(screen.getByRole('button', { name: 'Remove chan@example.com' })).toBeDisabled()
    expect(screen.getByLabelText('Add a recipient')).toBeDisabled()
  })

  it('validates addresses the same way the server does', () => {
    expect(isAddress('a@b.co')).toBe(true)
    expect(isAddress('a@b')).toBe(false)
    expect(isAddress('a b@c.com')).toBe(false)
    expect(isAddress('')).toBe(false)
  })
})
