import { describe, it, expect } from 'vitest'
import { liveCases, liveCaseWarning } from './liveCase.js'

const caseAt = (code, over = {}) => ({
  id: 'c1', case_no: 'NAR-2026-0041',
  workflow_status: { code, label: code, off_portal: false, overdue: false },
  ...over,
})

const company = (...cases) => ({ cases: { nar1: cases, nnc1: [] } })

describe('liveCases', () => {
  it.each([
    'client_verification', 'awaiting_client', 'client_rejected',
    'signing', 'submission',
  ])('counts %s as holding a frozen snapshot', code => {
    expect(liveCases(company(caseAt(code)))).toHaveLength(1)
  })

  it('does NOT warn about data_verification — nothing is frozen yet', () => {
    // Warning here would fire on every edit to every company with an open
    // case, which is how a warning stops being read.
    expect(liveCases(company(caseAt('data_verification')))).toEqual([])
  })

  it('does NOT warn about a completed case — that return is filed and closed', () => {
    expect(liveCases(company(caseAt('completed')))).toEqual([])
  })

  it('accepts a bare code string as well as the composite object', () => {
    // The dashboard view emits a string; derive() emits an object. Reading
    // only one of them makes the guard silently absent on half the payloads.
    expect(liveCases(company({ id: 'c1', workflow_status: 'signing' }))).toHaveLength(1)
  })

  it('is safe on a company with no cases at all', () => {
    expect(liveCases({})).toEqual([])
    expect(liveCases(null)).toEqual([])
    expect(liveCases({ cases: { nar1: [] } })).toEqual([])
  })
})

describe('liveCaseWarning', () => {
  it('is null when nothing would disagree', () => {
    expect(liveCaseWarning(company(caseAt('data_verification')))).toBeNull()
    expect(liveCaseWarning({})).toBeNull()
  })

  it('names the case so the operator knows what to go and look at', () => {
    const warning = liveCaseWarning(company(caseAt('signing')))
    expect(warning.body).toContain('Case NAR-2026-0041')
    expect(warning.title).toMatch(/conflicts with a live case/i)
  })

  it('names every live case, not just the first', () => {
    const warning = liveCaseWarning(company(
      caseAt('signing'),
      caseAt('awaiting_client', { id: 'c2', case_no: 'NAR-2025-0007' }),
    ))
    expect(warning.body).toContain('NAR-2026-0041')
    expect(warning.body).toContain('NAR-2025-0007')
    expect(warning.cases).toHaveLength(2)
  })

  it('says the snapshot is NOT updated by the edit', () => {
    // The commonest wrong assumption is that editing the profile fixes the
    // return. It does not, and the sentence has to say so.
    const warning = liveCaseWarning(company(caseAt('submission')))
    expect(warning.body).toMatch(/case snapshot is not touched/i)
    expect(warning.body).toMatch(/restart\s+verification/i)
  })

  it('copes with a case that has no case number yet', () => {
    const warning = liveCaseWarning(company(caseAt('signing', { case_no: null })))
    expect(warning.body).toContain('1 on-going NAR1 case')
  })
})
