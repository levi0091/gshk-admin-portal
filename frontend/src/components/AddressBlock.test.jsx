import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AddressBlock, { LIMIT } from './AddressBlock.jsx'

const HK_DISTRICTS = [
  { code: 'CENTRAL', label: 'CENTRAL' },
  { code: 'WANCHAI', label: 'WANCHAI' },
]
// `cr_country` is CR's own Country & Region sheet. `country` is Viewpoint's
// 270-row list, which carries 20 codes CR cannot resolve — it is deliberately
// here in the fixture so the test can prove the component ignores it.
const LOOKUPS = {
  cr_district: HK_DISTRICTS,
  cr_country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'CY', label: 'Cyprus' }],
  country: [{ code: 'HK-CH', label: '香港' }, { code: 'US-DE', label: 'Delaware' }],
}

const ADDRESS = {
  line1: 'Suite C, Level 7',
  line2: 'World Trust Tower',
  line3: '50 Stanley Street, Central',
  city: 'CENTRAL',
  country: 'HK',
  shared_by: 1,
}

function setup(props = {}) {
  const onChange = vi.fn()
  render(
    <AddressBlock
      value={ADDRESS}
      lookups={LOOKUPS}
      onChange={onChange}
      {...props}
    />,
  )
  return { onChange }
}

describe('AddressBlock', () => {
  it('shows every line CR receives, so nothing is filed that was never displayed', () => {
    setup()
    expect(screen.getByLabelText(/Flat \/ Floor \/ Block/i)).toHaveValue('Suite C, Level 7')
    expect(screen.getByLabelText(/Building/i)).toHaveValue('World Trust Tower')
    expect(screen.getByLabelText(/Street \/ Estate/i)).toHaveValue('50 Stanley Street, Central')
    expect(screen.getByLabelText(/Country/i)).toHaveValue('HK')
  })

  it('reports the character count against CR\'s limit', () => {
    setup()
    expect(screen.getByTestId('count-line1')).toHaveTextContent(`16/${LIMIT}`)
  })

  it('marks a line that exceeds the limit, because CR will refuse it', async () => {
    setup({ value: { ...ADDRESS, line3: 'x'.repeat(LIMIT + 1) } })
    expect(screen.getByTestId('count-line3')).toHaveAttribute('data-over', 'true')
    expect(screen.getByLabelText(/Street \/ Estate/i)).toHaveAttribute('aria-invalid', 'true')
  })

  it('does not mark a line of exactly the limit', () => {
    setup({ value: { ...ADDRESS, line3: 'x'.repeat(LIMIT) } })
    expect(screen.getByTestId('count-line3')).toHaveAttribute('data-over', 'false')
  })

  it('offers CR\'s district codes as a dropdown for a Hong Kong address', () => {
    setup()
    const district = screen.getByLabelText(/District/i)
    expect(district.tagName).toBe('SELECT')
    expect(screen.getByRole('option', { name: 'WANCHAI' })).toBeInTheDocument()
  })

  it('takes free text for a district outside Hong Kong', () => {
    setup({ value: { ...ADDRESS, country: 'CY', city: 'Nicosia' } })
    const district = screen.getByLabelText(/District/i)
    expect(district.tagName).toBe('INPUT')
    expect(district).toHaveValue('Nicosia')
  })

  it('warns that a shared address will be copied, before the save is pressed', () => {
    setup({ value: { ...ADDRESS, shared_by: 4446 } })
    expect(screen.getByRole('note')).toHaveTextContent(/4,446/)
    expect(screen.getByRole('note')).toHaveTextContent(/separate address/i)
  })

  it('says nothing about sharing when this record is the only user', () => {
    setup()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('reports edits to its parent', async () => {
    const { onChange } = setup()
    await userEvent.type(screen.getByLabelText(/Building/i), '!')
    expect(onChange).toHaveBeenCalled()
    const [field, next] = onChange.mock.calls.at(-1)
    expect(field).toBe('line2')
    expect(next).toBe('World Trust Tower!')
  })

  it('shows the values but takes no input when read-only', () => {
    setup({ readOnly: true })
    expect(screen.getByText('World Trust Tower')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Building/i)).not.toBeInTheDocument()
  })

  it('renders an empty address without crashing', () => {
    setup({ value: null })
    expect(screen.getByLabelText(/Flat \/ Floor \/ Block/i)).toHaveValue('')
  })

  // -- The country list must be CR's, not Viewpoint's -----------------------
  //
  // THE DEFECT. This dropdown fed on `lookup_values.country`, 20 of whose
  // codes CR has no code for — three of them labelled only in Chinese. An
  // operator picked the Chinese Hong Kong, it stored 'HK-CH', and the NAR1
  // died at Data Verification with "no CR region code is known for country
  // 'HK-CH'". The fee is taken before that check, so this list is load-bearing.

  it('offers CRs countries and never Viewpoints unfilable ones', () => {
    setup()
    const select = screen.getByLabelText('Country')
    const options = [...select.querySelectorAll('option')].map(o => o.value)

    expect(options).toContain('HK')
    expect(options).toContain('CY')
    expect(options).not.toContain('HK-CH')
    expect(options).not.toContain('US-DE')
  })

  it('shows every label in English', () => {
    setup()
    const labels = [...screen.getByLabelText('Country').querySelectorAll('option')]
      .map(o => o.textContent)
      // The empty-value placeholder is "Select…" — its ellipsis is not ASCII
      // and it is not a country, so it is not what this test is about.
      .filter(l => l !== 'Select…')

    expect(labels).not.toContain('香港')
    expect(labels.every(l => [...l].every(ch => ch.charCodeAt(0) < 128))).toBe(true)
  })

  it('still shows a stored country CR cannot resolve, flagged rather than dropped', () => {
    // 7 real address rows hold one. Silently blanking it on the next save
    // would destroy the only evidence of what someone meant.
    setup({ value: { ...ADDRESS, country: 'HK-CH' } })

    expect(screen.getByLabelText('Country')).toHaveValue('HK-CH')
    expect(screen.getByText(/not in list/)).toBeInTheDocument()
  })
})
