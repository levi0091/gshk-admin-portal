import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DateInput, { displayToIso, isoToDisplay } from './DateInput.jsx'

function Harness({ initial = '', onValue = () => {}, ...props }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <label htmlFor="d">When</label>
      <DateInput id="d" value={value} {...props}
                 onChange={e => { setValue(e.target.value); onValue(e.target.value) }} />
      <output data-testid="iso">{value}</output>
    </>
  )
}

describe('DateInput — dd/mm/yyyy whatever the browser locale (UAT 2026-11-09)', () => {
  it('shows a stored ISO date day first', () => {
    render(<Harness initial="2026-11-08" />)
    expect(screen.getByLabelText('When')).toHaveValue('08/11/2026')
  })

  it('types digits into dd/mm/yyyy and reports ISO only when the day is whole', async () => {
    const user = userEvent.setup()
    const onValue = vi.fn()
    render(<Harness onValue={onValue} />)
    await user.type(screen.getByLabelText('When'), '0811202')
    expect(screen.getByLabelText('When')).toHaveValue('08/11/202')
    expect(screen.getByTestId('iso')).toHaveTextContent('')
    await user.type(screen.getByLabelText('When'), '6')
    expect(screen.getByLabelText('When')).toHaveValue('08/11/2026')
    expect(screen.getByTestId('iso')).toHaveTextContent('2026-11-08')
  })

  it('reads 08/11 as 8 November, never 11 August', () => {
    expect(displayToIso('08/11/2026')).toBe('2026-11-08')
    expect(isoToDisplay('2026-08-11')).toBe('11/08/2026')
  })

  it('refuses a day that does not exist and flags the box', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('When'), '31022026')
    expect(screen.getByLabelText('When')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByTestId('iso')).toHaveTextContent('')
  })

  it('accepts an ISO date typed or pasted, and shows it day first', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('When'), '2027-12-31')
    expect(screen.getByTestId('iso')).toHaveTextContent('2027-12-31')
    expect(screen.getByLabelText('When')).toHaveValue('31/12/2027')
    fireEvent.change(screen.getByLabelText('When'), { target: { value: '2026-01-02' } })
    expect(screen.getByLabelText('When')).toHaveValue('02/01/2026')
  })

  it('clears to an empty value', async () => {
    const user = userEvent.setup()
    render(<Harness initial="2026-11-08" />)
    await user.clear(screen.getByLabelText('When'))
    expect(screen.getByTestId('iso')).toHaveTextContent('')
  })

  it('follows a value set from outside', () => {
    const { rerender } = render(<DateInput aria-label="d" value="2026-01-02" onChange={() => {}} />)
    rerender(<DateInput aria-label="d" value="2026-03-04" onChange={() => {}} />)
    expect(screen.getByLabelText('d')).toHaveValue('04/03/2026')
  })

  it('keeps min and max on the box, so the calendar and the box agree', () => {
    render(<DateInput aria-label="d" value="" min="2026-01-01" max="2026-12-31" onChange={() => {}} />)
    expect(screen.getByLabelText('d')).toHaveAttribute('min', '2026-01-01')
    expect(screen.getByLabelText('d')).toHaveAttribute('max', '2026-12-31')
  })
})
