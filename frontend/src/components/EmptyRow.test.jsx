import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'

import EmptyRow from './EmptyRow.jsx'

/**
 * The distinction this component exists to hold: an empty table and a broken
 * request are different facts, and only one of them is the operator's to act
 * on. Levi read "Failed to load cases: Failed to fetch" and reasonably took it
 * for the former.
 */
describe('EmptyRow', () => {
  it('states the fact in the words the operator asked for', () => {
    render(<EmptyRow filtered={false} onClear={() => {}} />)
    expect(screen.getByText('No records found')).toBeInTheDocument()
  })

  it('offers no way out when no filter is responsible', () => {
    // An unfiltered listing with nothing in it means the data is not there.
    // Offering "Clear all filters" would blame a filter that does not exist and
    // send the operator round a loop that changes nothing.
    render(<EmptyRow filtered={false} onClear={() => {}} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('offers exactly one action when a filter emptied the table', () => {
    render(<EmptyRow filtered onClear={() => {}} />)
    expect(screen.getByRole('button', { name: 'Clear all filters' })).toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(1)
  })

  it('says WHY it is empty, not only that it is', () => {
    // Two of these three screens filter themselves before anyone touches them.
    // "No records found" alone reads as "there is no data".
    render(<EmptyRow filtered onClear={() => {}} />)
    expect(screen.getByText(/Every row is filtered out/)).toBeInTheDocument()
  })

  it('clears on click', async () => {
    const onClear = vi.fn()
    const user = userEvent.setup()
    render(<EmptyRow filtered onClear={onClear} />)
    await user.click(screen.getByRole('button', { name: 'Clear all filters' }))
    expect(onClear).toHaveBeenCalledTimes(1)
  })
})
