import { describe, it, expect } from 'vitest'

import { capacityLabel, capacityWithPrincipal } from './capacity.js'

describe('capacity labels', () => {
  it('names all three capacities, alternate included', () => {
    expect(capacityLabel('director')).toBe('Director')
    expect(capacityLabel('company_secretary')).toBe('Company Secretary')
    expect(capacityLabel('alternate_director')).toBe('Alternate Director')
  })

  it('passes an unknown value through, and shows nothing for none', () => {
    expect(capacityLabel('reserve_director')).toBe('reserve_director')
    expect(capacityLabel(undefined)).toBe('')
  })

  it('names who an alternate acts for, from an officer or an entry', () => {
    expect(capacityWithPrincipal({ role: 'alternate_director', alternate_to_name: 'CHAN Tai Man' }))
      .toBe('Alternate Director (alternate to CHAN Tai Man)')
    expect(capacityWithPrincipal({ capacity: 'alternate_director', alternate_to_name: 'CHAN Tai Man' }))
      .toBe('Alternate Director (alternate to CHAN Tai Man)')
    expect(capacityWithPrincipal({ role: 'alternate_director' })).toBe('Alternate Director')
    expect(capacityWithPrincipal({ role: 'director', alternate_to_name: 'x' })).toBe('Director')
  })
})
