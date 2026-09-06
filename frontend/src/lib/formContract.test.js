import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./api.js', () => ({ api: { get: vi.fn() } }))
import { api } from './api.js'
import {
  fetchFormContract, fieldWarning, warningsFor, _resetFormContract,
} from './formContract.js'

const CONTRACT = {
  addresses: {
    line1: { max_length: 60, mandatory: false, cr_fields: ['flatFlrBlk'] },
    country: { max_length: 3, mandatory: true, cr_fields: ['ctryRegion'] },
  },
  persons: {
    surname: { max_length: 50, mandatory: true, cr_fields: ['indvEngSname'] },
    alias_en: { max_length: 150, mandatory: false, cr_fields: ['indvAlsEngName'] },
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  _resetFormContract()
})

describe('fetchFormContract', () => {
  it('fetches once however many components ask', async () => {
    api.get.mockResolvedValue(CONTRACT)

    await Promise.all([fetchFormContract(), fetchFormContract(), fetchFormContract()])

    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('renders the page rather than failing when the contract cannot be read', async () => {
    // A role without companies:read on a person profile still has to see the
    // profile. Highlighting is an aid, not a precondition.
    api.get.mockRejectedValue(new Error('403'))

    await expect(fetchFormContract()).resolves.toEqual({})
  })
})

describe('fieldWarning', () => {
  it('flags a value longer than CR accepts, and says by how much', () => {
    const warning = fieldWarning(CONTRACT, 'addresses', 'line1', 'x'.repeat(61))

    expect(warning.kind).toBe('too_long')
    expect(warning.message).toContain('61')
    expect(warning.message).toContain('60')
  })

  it('accepts a value exactly at the limit', () => {
    expect(fieldWarning(CONTRACT, 'addresses', 'line1', 'x'.repeat(60))).toBeNull()
  })

  it('flags a field CR requires and nobody filled in', () => {
    expect(fieldWarning(CONTRACT, 'addresses', 'country', '').kind).toBe('missing')
    expect(fieldWarning(CONTRACT, 'addresses', 'country', null).kind).toBe('missing')
    expect(fieldWarning(CONTRACT, 'addresses', 'country', '   ').kind).toBe('missing')
  })

  it('says nothing about an empty field CR does not require', () => {
    expect(fieldWarning(CONTRACT, 'persons', 'alias_en', '')).toBeNull()
  })

  it('says nothing about a column the contract has never heard of', () => {
    // `unsourced` fields are never highlighted — the portal does not nag about
    // data it decided not to hold.
    expect(fieldWarning(CONTRACT, 'persons', 'shoe_size', '')).toBeNull()
    expect(fieldWarning(CONTRACT, 'nowhere', 'nothing', '')).toBeNull()
  })

  it('says nothing at all before the contract has loaded', () => {
    expect(fieldWarning({}, 'addresses', 'country', '')).toBeNull()
    expect(fieldWarning(undefined, 'addresses', 'country', '')).toBeNull()
  })

  it('measures a number by the characters CR would receive', () => {
    const contract = { share_classes: { total_issued: { max_length: 3, mandatory: true } } }

    expect(fieldWarning(contract, 'share_classes', 'total_issued', 1000).kind).toBe('too_long')
    expect(fieldWarning(contract, 'share_classes', 'total_issued', 100)).toBeNull()
  })

  it('does not call a zero missing', () => {
    // 0 shares paid up is an answer. `!value` would have called it absent.
    const contract = { share_classes: { total_paid: { max_length: 16, mandatory: true } } }

    expect(fieldWarning(contract, 'share_classes', 'total_paid', 0)).toBeNull()
  })
})

describe('warningsFor', () => {
  it('counts every problem on a record so a card header can show one number', () => {
    const person = { surname: '', alias_en: 'x'.repeat(200) }

    const warnings = warningsFor(CONTRACT, 'persons', person)

    expect(Object.keys(warnings).sort()).toEqual(['alias_en', 'surname'])
    expect(warnings.surname.kind).toBe('missing')
    expect(warnings.alias_en.kind).toBe('too_long')
  })

  it('returns nothing for a complete record', () => {
    expect(warningsFor(CONTRACT, 'persons', { surname: 'Smith' })).toEqual({})
  })

  it('does not report a mandatory column the record does not carry at all', () => {
    // A list row selects a few columns. Absent-from-the-payload is not the
    // same fact as empty-in-the-database, and guessing turns a narrow SELECT
    // into a screenful of false warnings.
    expect(warningsFor(CONTRACT, 'persons', { alias_en: 'JD' })).toEqual({})
  })
})
