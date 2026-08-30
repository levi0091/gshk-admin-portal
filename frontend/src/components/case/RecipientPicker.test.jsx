import { render, screen } from '@testing-library/react'
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

  it('says which director was taken off, so the removal is undoable by name', async () => {
    const user = userEvent.setup()
    renderPicker({ to: ['lee@example.com'] })
    expect(screen.getByText(/Removed from this send: AH CHAN/)).toBeInTheDocument()
    // And an unrelated extra address does not get named as a removed director.
    await user.click(screen.getByRole('button', { name: 'Remove lee@example.com' }))
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
