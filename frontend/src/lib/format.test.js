import { describe, it, expect, vi, afterEach } from 'vitest'

import { formatDate, formatDateTime, HK_TZ } from './format.js'

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
