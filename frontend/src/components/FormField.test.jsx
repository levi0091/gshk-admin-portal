import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import FormField, { displayValue } from './FormField.jsx'
import { optionsFor } from '../lib/lookups.js'

const LOOKUPS = {
  gender: [{ code: 'M', label: 'Male' }, { code: 'F', label: 'Female' }],
}

describe('FormField', () => {
  it('renders a dropdown when the field names a lookup', () => {
    render(<FormField field={{ key: 'gender', label: 'Gender', lookup: 'gender' }}
                      value="" lookups={LOOKUPS} onChange={() => {}} />)
    const select = screen.getByLabelText('Gender')
    expect(select.tagName).toBe('SELECT')
    expect(screen.getByRole('option', { name: 'Male' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Female' })).toBeInTheDocument()
  })

  it('renders a plain input when the field has no lookup', () => {
    render(<FormField field={{ key: 'occupation', label: 'Occupation' }}
                      value="" lookups={LOOKUPS} onChange={() => {}} />)
    expect(screen.getByLabelText('Occupation').tagName).toBe('INPUT')
  })

  it('reports the selected code, not the label', async () => {
    const onChange = vi.fn()
    render(<FormField field={{ key: 'gender', label: 'Gender', lookup: 'gender' }}
                      value="" lookups={LOOKUPS} onChange={onChange} />)
    await userEvent.selectOptions(screen.getByLabelText('Gender'), 'F')
    expect(onChange).toHaveBeenCalledWith('gender', 'F')
  })

  it('still shows a stored value that is not in the list', () => {
    // Legacy Viewpoint data holds a few values the seeded list does not.
    // Dropping them would silently blank the record on the next save.
    render(<FormField field={{ key: 'gender', label: 'Gender', lookup: 'gender' }}
                      value="X" lookups={LOOKUPS} onChange={() => {}} />)
    expect(screen.getByLabelText('Gender')).toHaveValue('X')
    expect(screen.getByRole('option', { name: /X \(not in list\)/ })).toBeInTheDocument()
  })

  it('survives a lookup category that failed to load', () => {
    render(<FormField field={{ key: 'gender', label: 'Gender', lookup: 'gender' }}
                      value="" lookups={{}} onChange={() => {}} />)
    expect(screen.getByLabelText('Gender')).toBeInTheDocument()
  })
})

describe('displayValue', () => {
  it('shows the label, not the stored code — "M" is not an answer to "Gender"', () => {
    expect(displayValue({ lookup: 'gender' }, 'M', LOOKUPS)).toBe('Male')
  })

  it('falls back to the raw value when the code is unknown', () => {
    expect(displayValue({ lookup: 'gender' }, 'X', LOOKUPS)).toBe('X')
  })

  it('passes non-lookup fields straight through', () => {
    expect(displayValue({}, 'Banker', LOOKUPS)).toBe('Banker')
  })

  it('renders nothing for an empty value', () => {
    expect(displayValue({ lookup: 'gender' }, '', LOOKUPS)).toBeNull()
  })
})

describe('optionsFor', () => {
  it('appends the current value when it is missing from the list', () => {
    expect(optionsFor(LOOKUPS.gender, 'Z')).toHaveLength(3)
  })

  it('does not duplicate a value already in the list', () => {
    expect(optionsFor(LOOKUPS.gender, 'M')).toHaveLength(2)
  })

  it('tolerates a malformed lookup payload', () => {
    expect(optionsFor(undefined, 'M')).toEqual([{ code: 'M', label: 'M (not in list)' }])
  })
})
