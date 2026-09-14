import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import VipBar, { VipChip } from './VipBar.jsx'

// The verdict as GET /persons/{id} serves it (routers/persons.vip_status).
const STANDARD = { is_vip: false, automatic: false, reasons: [], company_count: 2, threshold: 3 }
const BY_RULE = {
  is_vip: true, automatic: true, reasons: ['affiliated_agent', 'companies'],
  company_count: 5, threshold: 3,
}
const MARKED = { is_vip: true, automatic: false, reasons: ['marked'], company_count: 1, threshold: 3 }

const renderBar = (props = {}) => {
  const onSave = props.onSave || vi.fn().mockResolvedValue({})
  render(<VipBar vip={STANDARD} canWrite onSave={onSave} {...props} />)
  return onSave
}

describe('VipBar', () => {
  it('draws a standard client with the count and the rule that would upgrade it', () => {
    renderBar()
    expect(screen.getByText('Standard client')).toBeInTheDocument()
    expect(screen.getByText(/more than 3/)).toBeInTheDocument()
    expect(screen.getByText('2 companies')).toBeInTheDocument()
  })

  it('marks a standard client VIP', async () => {
    const onSave = renderBar()
    await userEvent.setup().click(screen.getByRole('button', { name: /Mark as VIP/ }))
    expect(onSave).toHaveBeenCalledWith({ is_vip_marked: true })
  })

  it('flags an affiliated agent — agents are VIP', async () => {
    const onSave = renderBar()
    await userEvent.setup().click(screen.getByRole('switch', { name: 'Affiliated agent' }))
    expect(onSave).toHaveBeenCalledWith({ is_affiliated_agent: true })
  })

  it('draws a VIP with the reasons it is one', () => {
    renderBar({ vip: BY_RULE, isAgent: true })
    expect(screen.getByText('VIP Client')).toBeInTheDocument()
    expect(screen.getByText('5 companies with us')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Affiliated agent' }))
      .toHaveAttribute('aria-checked', 'true')
  })

  it('locks the VIP switch when the status comes from the rule', () => {
    // Switching it off would only be undone by the rule on the next read.
    renderBar({ vip: BY_RULE, isAgent: true })
    expect(screen.getByRole('switch', { name: 'VIP status' })).toBeDisabled()
    expect(screen.getByText('Automatic')).toBeInTheDocument()
  })

  it('lets a manually marked VIP be unmarked', async () => {
    const onSave = renderBar({ vip: MARKED })
    expect(screen.getByText('Manual')).toBeInTheDocument()
    expect(screen.getByText('Marked VIP')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('switch', { name: 'VIP status' }))
    expect(onSave).toHaveBeenCalledWith({ is_vip_marked: false })
  })

  it('shows the status to a role that cannot edit the person, and no controls', () => {
    renderBar({ vip: MARKED, canWrite: false })
    expect(screen.getByText('VIP Client')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says so when the save fails, and leaves the bar standing', async () => {
    renderBar({ onSave: vi.fn().mockRejectedValue(new Error('nope')) })
    await userEvent.setup().click(screen.getByRole('button', { name: /Mark as VIP/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('nope'))
    expect(screen.getByText('Standard client')).toBeInTheDocument()
  })

  it('draws nothing when the profile carries no verdict', () => {
    const { container } = render(<VipBar vip={undefined} canWrite onSave={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('has a chip for beside the name', () => {
    render(<VipChip />)
    expect(screen.getByTestId('vip-chip')).toHaveTextContent('VIP')
  })
})
