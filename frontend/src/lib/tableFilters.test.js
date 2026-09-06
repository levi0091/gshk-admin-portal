import { describe, it, expect } from 'vitest'
import {
  DATE, ENUM, ID, ID_OPS, OWNER, RANGE, TEXT, TEXT_OPS,
  appendTo, chipsFor, columnsTouched, draftFromFilters, filtersFromDraft,
  opsFor, setColumn, toParams,
} from './tableFilters.js'

const NAME = { col: 'company_name', label: 'Company Name', filter: { kind: TEXT } }
const STATUS = {
  col: 'status', label: 'Status',
  filter: { kind: ENUM, options: [
    { value: 'live', label: 'Live' },
    { value: 'ceased', label: 'Ceased' },
    { value: 'pending_aml', label: 'Pending AML' },
  ] },
}
const DAYS = {
  col: 'days_to_anniversary', label: 'Days to anniversary',
  filter: { kind: RANGE, unit: 'days' },
}
const UPDATED = { col: 'updated_at', label: 'Last Updated', filter: { kind: DATE } }
const OWNER_COL = {
  col: 'created_by', label: 'Created By',
  filter: { kind: OWNER, meId: 'u-1', nameCol: 'created_by_name' },
}

describe('the wire format', () => {
  it('encodes a filter as column:op:value', () => {
    expect(toParams([{ col: 'company_name', op: 'contains', value: 'acme' }]))
      .toEqual(['company_name:contains:acme'])
  })

  it('joins an enum list with commas', () => {
    expect(toParams([{ col: 'status', op: 'in', value: ['live', 'ceased'] }]))
      .toEqual(['status:in:live,ceased'])
  })

  it('sorts the params so the same filter set is always the same URL', () => {
    // The request path IS the cache key useAbortableGet compares on. Unsorted,
    // re-picking the same checkboxes in a different order would refetch a set
    // the screen is already showing.
    const a = appendTo(new URLSearchParams(), [
      { col: 'status', op: 'in', value: ['live'] },
      { col: 'company_name', op: 'contains', value: 'acme' },
    ]).toString()
    const b = appendTo(new URLSearchParams(), [
      { col: 'company_name', op: 'contains', value: 'acme' },
      { col: 'status', op: 'in', value: ['live'] },
    ]).toString()
    expect(a).toBe(b)
  })
})

describe('draft ↔ filters', () => {
  it('reads a text filter back into its editor', () => {
    expect(draftFromFilters(NAME, [{ col: 'company_name', op: 'eq', value: 'ACME' }]))
      .toEqual({ op: 'eq', value: 'ACME' })
  })

  it('leaves the value box empty for a valueless op', () => {
    expect(draftFromFilters(NAME, [{ col: 'company_name', op: 'empty', value: '' }]))
      .toEqual({ op: 'empty', value: '' })
  })

  it('reads both ends of a range', () => {
    const filters = [
      { col: 'days_to_anniversary', op: 'gte', value: -42 },
      { col: 'days_to_anniversary', op: 'lte', value: 60 },
    ]
    expect(draftFromFilters(DAYS, filters)).toEqual({ min: '-42', max: '60' })
  })

  it('a range writes one filter per bound', () => {
    expect(filtersFromDraft(DAYS, { min: '-42', max: '60' })).toEqual([
      { col: 'days_to_anniversary', op: 'gte', value: -42 },
      { col: 'days_to_anniversary', op: 'lte', value: 60 },
    ])
  })

  it('a half-open range writes only the bound that was given', () => {
    expect(filtersFromDraft(DAYS, { min: '', max: '0' })).toEqual([
      { col: 'days_to_anniversary', op: 'lte', value: 0 },
    ])
  })

  it('keeps a zero bound, which is not the same as no bound', () => {
    // 0 days is the anniversary itself — the boundary the whole screen is about.
    expect(filtersFromDraft(DAYS, { min: '0', max: '' })).toEqual([
      { col: 'days_to_anniversary', op: 'gte', value: 0 },
    ])
  })

  it('an empty text box is no filter, not a filter for the empty string', () => {
    expect(filtersFromDraft(NAME, { op: 'contains', value: '   ' })).toEqual([])
  })

  it('an empty checkbox list is no filter', () => {
    expect(filtersFromDraft(STATUS, { picked: [] })).toEqual([])
  })

  it('a valueless op survives with no value', () => {
    expect(filtersFromDraft(NAME, { op: 'notempty', value: '' }))
      .toEqual([{ col: 'company_name', op: 'notempty', value: '' }])
  })

  it('an owner draft writes the uuid, not the name', () => {
    // Two people can share a display name; "mine" is an exact identity.
    expect(filtersFromDraft(OWNER_COL, { mine: true, name: '' }))
      .toEqual([{ col: 'created_by', op: 'eq', value: 'u-1' }])
  })

  it('an owner draft can search somebody else by name', () => {
    expect(filtersFromDraft(OWNER_COL, { mine: false, name: 'Levi' }))
      .toEqual([{ col: 'created_by_name', op: 'contains', value: 'Levi' }])
  })

  it('an owner column owns two underlying columns', () => {
    // Clearing it has to drop both, or the name filter survives invisibly
    // behind a funnel that reads as off.
    expect(columnsTouched(OWNER_COL)).toEqual(['created_by', 'created_by_name'])
    expect(columnsTouched(NAME)).toEqual(['company_name'])
  })
})

describe('setColumn', () => {
  it('replaces every filter on the named column and leaves the rest', () => {
    const before = [
      { col: 'days_to_anniversary', op: 'gte', value: -42 },
      { col: 'days_to_anniversary', op: 'lte', value: 60 },
      { col: 'company_name', op: 'contains', value: 'acme' },
    ]
    const after = setColumn(before, 'days_to_anniversary', [])
    expect(after).toEqual([{ col: 'company_name', op: 'contains', value: 'acme' }])
  })
})

describe('the chip row', () => {
  it('says nothing when nothing is applied', () => {
    expect(chipsFor([NAME, STATUS], [])).toEqual([])
  })

  it('names a text filter and what it is looking for', () => {
    const [chip] = chipsFor([NAME], [{ col: 'company_name', op: 'contains', value: 'acme' }])
    expect(chip.label).toBe('Company Name')
    expect(chip.text).toBe('contains “acme”')
  })

  it('spells out a short enum selection and counts a long one', () => {
    const two = chipsFor([STATUS], [{ col: 'status', op: 'in', value: ['live', 'ceased'] }])
    expect(two[0].text).toBe('Live, Ceased')
    const three = chipsFor([STATUS],
      [{ col: 'status', op: 'in', value: ['live', 'ceased', 'pending_aml'] }])
    expect(three[0].text).toBe('3 selected')
  })

  it('reads a range as a range and a half-range as a bound', () => {
    expect(chipsFor([DAYS], [
      { col: 'days_to_anniversary', op: 'gte', value: -42 },
      { col: 'days_to_anniversary', op: 'lte', value: 60 },
    ])[0].text).toBe('-42 to 60 days')
    expect(chipsFor([DAYS], [
      { col: 'days_to_anniversary', op: 'lte', value: 0 },
    ])[0].text).toBe('0 days or less')
  })

  it('names the default the dashboard opens with', () => {
    // A default that hides rows without saying so cannot be told apart from a
    // table that is simply missing data.
    const [chip] = chipsFor([OWNER_COL], [{ col: 'created_by', op: 'eq', value: 'u-1' }])
    expect(chip.label).toBe('Created By')
    expect(chip.text).toBe('Me')
    expect(chip.cols).toEqual(['created_by', 'created_by_name'])
  })

  it('describes a date range with both ends', () => {
    const [chip] = chipsFor([UPDATED], [
      { col: 'updated_at', op: 'gte', value: '2026-06-01' },
      { col: 'updated_at', op: 'lte', value: '2026-06-30' },
    ])
    expect(chip.text).toBe('2026-06-01 to 2026-06-30')
  })

  it('says "No value" rather than showing an empty filter as blank', () => {
    expect(chipsFor([NAME], [{ col: 'company_name', op: 'empty', value: '' }])[0].text)
      .toBe('No value')
  })
})

// A uuid column is text-shaped in the editor and nothing like text on the wire.
// `contains` on one reaches PostgREST as an ilike, which Postgres refuses on a
// uuid — the 500 that reached the dashboard as "Failed to fetch".
describe('uuid columns', () => {
  const ENTITY = { col: 'entity_id', label: 'Entity ID', filter: { kind: ID } }
  const UUID = '4a20786b-7b50-4f35-8e4d-c3e342766db9'

  it('offers only the ops the server will run', () => {
    expect(opsFor(ID)).toBe(ID_OPS)
    expect(ID_OPS.map(o => o.value)).toEqual(['eq', 'empty', 'notempty'])
    expect(ID_OPS.map(o => o.value)).not.toContain('contains')
  })

  it('leaves every other kind on the full text op list', () => {
    expect(opsFor(TEXT)).toBe(TEXT_OPS)
    expect(opsFor(undefined)).toBe(TEXT_OPS)
  })

  it('defaults to exact match, where a text column defaults to contains', () => {
    expect(draftFromFilters(ENTITY, []).op).toBe('eq')
    expect(draftFromFilters(NAME, []).op).toBe('contains')
  })

  it('writes an eq filter from a bare value', () => {
    expect(filtersFromDraft(ENTITY, { op: '', value: UUID }))
      .toEqual([{ col: 'entity_id', op: 'eq', value: UUID }])
  })

  it('is still no filter when the box is empty', () => {
    expect(filtersFromDraft(ENTITY, { op: 'eq', value: '   ' })).toEqual([])
  })

  it('describes itself as an exact match in the chip row', () => {
    expect(chipsFor([ENTITY], [{ col: 'entity_id', op: 'eq', value: UUID }])[0].text)
      .toBe(`is “${UUID}”`)
  })
})
