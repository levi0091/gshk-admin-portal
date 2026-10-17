import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'

import PendingChangeChip, { pendingFor } from './PendingChangeChip.jsx'

const CASES = [
  { id: 'k1', case_no: 'ND2A-2026-0001', case_type: 'ND2A', entries: [
    { id: 'n1', kind: 'cessation', capacity: 'director', officer_id: 'o1', person_id: 'p1' },
    { id: 'n2', kind: 'appointment', capacity: 'company_secretary', person_id: null,
      corporate_entity_id: 'c9' },
  ] },
  { id: 'k2', case_no: 'ND2B-2026-0002', case_type: 'ND2B', entries: [
    { id: 'n3', kind: 'change', capacity: 'company_secretary', officer_id: 'o7', person_id: 'p7' },
  ] },
]

describe('pendingFor', () => {
  it('finds a director by their officer row', () => {
    expect(pendingFor(CASES, { officerId: 'o1', capacity: 'director' })?.case.id).toBe('k1')
  })

  it('finds a register secretary by the person or company in that capacity', () => {
    expect(pendingFor(CASES, { personId: 'p7', capacity: 'company_secretary' })?.entry.id).toBe('n3')
    expect(pendingFor(CASES, { corporateEntityId: 'c9', capacity: 'company_secretary' })?.entry.id)
      .toBe('n2')
  })

  it('does not cross capacities, and answers null for nobody', () => {
    expect(pendingFor(CASES, { personId: 'p1', capacity: 'company_secretary' })).toBeNull()
    expect(pendingFor(CASES, { officerId: 'zz', capacity: 'director' })).toBeNull()
    expect(pendingFor(undefined, { officerId: 'o1' })).toBeNull()
  })
})

describe('PendingChangeChip', () => {
  it('says what is pending and links to the case', () => {
    render(<MemoryRouter><PendingChangeChip pending={pendingFor(CASES, { officerId: 'o1' })} /></MemoryRouter>)
    const link = screen.getByRole('link', { name: /Cessation pending/ })
    expect(link).toHaveAttribute('href', '/officer-changes/k1')
    expect(link).toHaveTextContent('ND2A-2026-0001')
  })

  it('renders nothing when nothing is pending', () => {
    const { container } = render(<MemoryRouter><PendingChangeChip pending={null} /></MemoryRouter>)
    expect(container).toBeEmptyDOMElement()
  })
})
