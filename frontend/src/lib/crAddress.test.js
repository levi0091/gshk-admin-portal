import { describe, it, expect } from 'vitest'
import { CR_ADDRESS_LABELS, crAddressLines, countryName } from './crAddress.js'

const LOOKUPS = { cr_country: [{ code: 'HK', label: 'Hong Kong' }, { code: 'GB', label: 'United Kingdom' }] }

describe('crAddress', () => {
  it("uses the Companies Registry's own five labels, in order (Jacqueline B3)", () => {
    expect(CR_ADDRESS_LABELS).toEqual([
      'Flat/Floor/Block etc.',
      'Building (Name)',
      'Street/Estate/Lot/Village etc.',
      'District/City/Province/State/Postal Code etc.',
      'Country/Region',
    ])
  })

  it('joins city, region and postcode into the district line and names the country', () => {
    const lines = crAddressLines({ line1: '', line2: 'Sample Garden', line3: '18 Example Street',
      city: 'London', state_region: 'Greater London', postal_code: 'SW1A 1AA', country: 'GB' }, LOOKUPS)
    expect(lines).toEqual([
      { label: 'Flat/Floor/Block etc.', value: '' },
      { label: 'Building (Name)', value: 'Sample Garden' },
      { label: 'Street/Estate/Lot/Village etc.', value: '18 Example Street' },
      { label: 'District/City/Province/State/Postal Code etc.', value: 'London Greater London SW1A 1AA' },
      { label: 'Country/Region', value: 'United Kingdom' },
    ])
  })

  it('is empty-safe', () => {
    expect(crAddressLines(null).every(l => l.value === '')).toBe(true)
  })

  it('falls back to the stored code when the country is not in the list', () => {
    expect(countryName('ZZ', LOOKUPS)).toBe('ZZ')
    expect(countryName('HK', LOOKUPS)).toBe('Hong Kong')
    expect(countryName('', LOOKUPS)).toBe('')
  })
})
