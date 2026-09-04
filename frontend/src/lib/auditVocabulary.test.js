import { describe, it, expect } from 'vitest'
import {
  MODULES, MODULE_LABELS, SUBJECT_KIND_LABELS, subjectHref, subjectOf,
} from './auditVocabulary.js'

describe('the module vocabulary', () => {
  // These five strings go on the wire as `filter=module:in:...` and land in a
  // CLOSED enum in backend/routers/audit.py. backend/tests/test_audit_subject.py
  // pins the same literals, so a rename on either side fails CI rather than
  // shipping a filter option that silently matches nothing.
  it('is exactly what the backend stores', () => {
    expect(MODULES.map(m => m.value)).toEqual([
      'post_incorporation', 'body_corporate', 'natural_person',
      'documents', 'cr_filing',
    ])
  })

  it('labels each module with the sidebar’s own name', () => {
    expect(MODULES.map(m => m.label)).toEqual([
      'Post-incorporation', 'Body Corporate', 'Natural Person',
      'Documents', 'CR Filing',
    ])
    expect(MODULE_LABELS.cr_filing).toBe('CR Filing')
  })

  it('keeps the subject-kind chips short', () => {
    expect(SUBJECT_KIND_LABELS).toEqual({
      case: 'Case', company: 'Company', person: 'Person',
    })
  })
})

describe('subjectOf', () => {
  it('reads a company as name (BRN)', () => {
    expect(subjectOf({
      subject_kind: 'company',
      company_name: 'Kanenas Holding Limited',
      subject_ref: '69123456',
    })).toEqual({ name: 'Kanenas Holding Limited', ref: '69123456' })
  })

  it('reads a person as name (identity number)', () => {
    expect(subjectOf({
      subject_kind: 'person',
      company_name: 'Ilze TSERKEZIS',
      subject_ref: 'A123456(7)',
    })).toEqual({ name: 'Ilze TSERKEZIS', ref: 'A123456(7)' })
  })

  it('INVERTS for a case: the case number leads, the company qualifies it', () => {
    // A workflow row is about one filing of one year, not about the company in
    // general — so it reads "NAR1-2026-0042 (Kanenas Holding Limited)".
    expect(subjectOf({
      subject_kind: 'case',
      company_name: 'Kanenas Holding Limited',
      subject_ref: 'NAR1-2026-0042',
    })).toEqual({ name: 'NAR1-2026-0042', ref: 'Kanenas Holding Limited' })
  })

  it('falls back to the company when a case has no number yet', () => {
    expect(subjectOf({ subject_kind: 'case', company_name: 'Kanenas Holding Limited' }))
      .toEqual({ name: 'Kanenas Holding Limited', ref: null })
  })

  it('marks an unresolved Viewpoint key as raw rather than as a name', () => {
    const out = subjectOf({ source_keycode: 'ITUTORS' })
    expect(out).toEqual({ name: 'ITUTORS', ref: null, raw: true })
  })

  it('says nothing when there is nothing to say', () => {
    expect(subjectOf({})).toBe(null)
    expect(subjectOf(null)).toBe(null)
  })
})

describe('subjectHref', () => {
  it('links a person to their profile', () => {
    expect(subjectHref({ subject_kind: 'person', subject_id: 'p1' }))
      .toBe('/persons/p1')
  })

  it('links a case to its workflow screen, not to its company', () => {
    expect(subjectHref({ subject_kind: 'case', subject_id: 'c1', case_id: 'e1' }))
      .toBe('/cases/c1')
  })

  it('links a company to its profile', () => {
    expect(subjectHref({ subject_kind: 'company', subject_id: 'e1' }))
      .toBe('/companies/e1')
  })

  it('falls back to the company on a row with no subject id', () => {
    // `case_id` has always held the ENTITY id, so a pre-034 row still reaches
    // somewhere useful.
    expect(subjectHref({ case_id: 'e1' })).toBe('/companies/e1')
  })

  it('links nowhere when nothing identifies the record', () => {
    expect(subjectHref({ source_keycode: 'ITUTORS' })).toBe(null)
    expect(subjectHref(null)).toBe(null)
  })
})
