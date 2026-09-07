import { describe, it, expect, vi, afterEach } from 'vitest'

import {
  formatDate, formatDateTime, formatMoney, formatNumber, HK_TZ,
} from './format.js'

afterEach(() => vi.useRealTimers())

describe('formatDate', () => {
  it('renders a date-only value as written', () => {
    expect(formatDate('2024-05-20')).toBe('20 May 2024')
  })

  it('shows an em dash for a missing value', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('')).toBe('—')
  })

  // 2026-08-15T23:30Z is already the 16th in Hong Kong. Rendering the UTC date
  // would tell a Hong Kong operator something happened the day before it did.
  it('reports the Hong Kong calendar date, not the UTC one', () => {
    expect(formatDate('2026-08-15T23:30:00Z')).toBe('16 Aug 2026')
  })

  it('does not roll a late-morning UTC timestamp forward', () => {
    expect(formatDate('2026-08-15T09:00:00Z')).toBe('15 Aug 2026')
  })
})

describe('formatDateTime', () => {
  it('renders the Hong Kong wall-clock time', () => {
    // 06:39 UTC == 14:39 HKT
    expect(formatDateTime('2026-04-12T06:39:00Z')).toBe('12 Apr 2026, 14:39')
  })

  it('crosses the date boundary in Hong Kong terms', () => {
    expect(formatDateTime('2026-08-15T17:05:00Z')).toBe('16 Aug 2026, 01:05')
  })

  it('uses a 24-hour clock', () => {
    expect(formatDateTime('2026-04-12T13:00:00Z')).toBe('12 Apr 2026, 21:00')
  })

  it('shows an em dash for a missing value', () => {
    expect(formatDateTime(null)).toBe('—')
  })
})

describe('HK_TZ', () => {
  it('is the single place the zone is named', () => {
    expect(HK_TZ).toBe('Asia/Hong_Kong')
  })
})

describe('formatNumber', () => {
  it('groups every three digits — 1,234,567', () => {
    expect(formatNumber(1234567)).toBe('1,234,567')
  })

  it('groups a figure that arrived from the API as a string', () => {
    // Share capital and issued amounts are `numeric` server-side and are
    // serialised as strings, so this is the shape the screens actually get.
    expect(formatNumber('10000')).toBe('10,000')
    expect(formatNumber(' 5000 ')).toBe('5,000')
  })

  it('leaves a figure under a thousand alone', () => {
    expect(formatNumber(999)).toBe('999')
    expect(formatNumber(0)).toBe('0')
  })

  it('keeps the decimals a figure actually carries', () => {
    expect(formatNumber(1234.5)).toBe('1,234.5')
  })

  it('returns null for an absent value rather than inventing a zero', () => {
    expect(formatNumber(null)).toBeNull()
    expect(formatNumber(undefined)).toBeNull()
    expect(formatNumber('')).toBeNull()
  })

  it('shows a non-numeric legacy value exactly as stored', () => {
    // Viewpoint free text. Mangling it would hide the thing that needs fixing.
    expect(formatNumber('n/a')).toBe('n/a')
  })
})

describe('formatMoney', () => {
  it('always shows two decimals, grouped', () => {
    expect(formatMoney('12480')).toBe('12,480.00')
    expect(formatMoney(3480)).toBe('3,480.00')
    expect(formatMoney('2610.5')).toBe('2,610.50')
  })

  it('prints a genuine zero balance rather than hiding it', () => {
    expect(formatMoney(0)).toBe('0.00')
  })

  it('shows an em dash when there is no figure at all — never "0.00"', () => {
    // `Number(null)` is 0, so the copies this replaced turned a missing deposit
    // balance into the claim that the account was empty.
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney('')).toBe('—')
  })
})
