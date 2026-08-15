import { describe, it, expect, vi, afterEach } from 'vitest'

import {
  daysToAnniversary, daysSinceAnniversary, anniversaryLabel, hongKongToday,
} from './anniversary.js'

const on = (iso) => new Date(`${iso}T00:00:00`)

afterEach(() => vi.useRealTimers())

describe('hongKongToday', () => {
  // GSHK works to Hong Kong dates. Deriving "today" from the browser clock puts
  // the whole column a day out for anyone not sitting in HKT — and, because the
  // backend view is pinned to Asia/Hong_Kong, would make the rendered day count
  // disagree with the sort order.
  it('is already tomorrow when Hong Kong has passed midnight', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-15T17:00:00Z'))   // 01:00 on the 16th, HKT
    const d = hongKongToday()
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 7, 16])
  })

  it('is still today one minute before Hong Kong midnight', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-15T15:59:00Z'))   // 23:59 on the 15th, HKT
    const d = hongKongToday()
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 7, 15])
  })

  it('drives the day count when no date is supplied', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-15T17:00:00Z'))   // HK: 16 Aug
    // Anniversary 18 Sept is 33 days from 16 Aug, 34 from the 15th.
    expect(daysToAnniversary('2018-09-18')).toBe(33)
  })
})

describe('daysToAnniversary', () => {
  it('counts the days to the next anniversary later this year', () => {
    expect(daysToAnniversary('2018-09-18', on('2026-08-15'))).toBe(34)
  })

  it('rolls into next year once this year’s anniversary has passed', () => {
    // 12 Aug 2026 is 3 days behind 15 Aug 2026 -> next is 12 Aug 2027
    expect(daysToAnniversary('2023-08-12', on('2026-08-15'))).toBe(362)
  })

  it('reports 0 on the anniversary itself', () => {
    expect(daysToAnniversary('2011-08-15', on('2026-08-15'))).toBe(0)
  })

  it('treats a 29 February anniversary as 28 February in a common year', () => {
    expect(daysToAnniversary('2016-02-29', on('2026-02-28'))).toBe(0)
  })

  it('returns null when the company has no incorporation date', () => {
    expect(daysToAnniversary(null, on('2026-08-15'))).toBeNull()
    expect(daysToAnniversary('', on('2026-08-15'))).toBeNull()
  })

  it('returns null for an unparseable date rather than NaN days', () => {
    expect(daysToAnniversary('not-a-date', on('2026-08-15'))).toBeNull()
  })
})

describe('daysSinceAnniversary', () => {
  it('counts the days since the anniversary just passed', () => {
    expect(daysSinceAnniversary('2023-08-12', on('2026-08-15'))).toBe(3)
  })

  it('reports 0 on the anniversary itself', () => {
    expect(daysSinceAnniversary('2011-08-15', on('2026-08-15'))).toBe(0)
  })

  it('looks back to last year when the anniversary is still ahead', () => {
    expect(daysSinceAnniversary('2018-09-18', on('2026-08-15'))).toBe(331)
  })
})

describe('anniversaryLabel', () => {
  it('counts down to an anniversary that is still ahead', () => {
    expect(anniversaryLabel('2018-09-18', on('2026-08-15')))
      .toEqual({ text: 'in 34 days', due: false })
  })

  it('says today on the anniversary itself', () => {
    expect(anniversaryLabel('2011-08-15', on('2026-08-15')))
      .toEqual({ text: 'today', due: true })
  })

  it('counts up while inside the 42-day filing window', () => {
    expect(anniversaryLabel('2023-08-12', on('2026-08-15')))
      .toEqual({ text: '3 days ago', due: true })
  })

  it('flags the last day of the 42-day filing window as still due', () => {
    expect(anniversaryLabel('2023-07-04', on('2026-08-15')))
      .toEqual({ text: '42 days ago', due: true })
  })

  it('goes back to counting down once the 42-day window has closed', () => {
    // 43 days past — the filing window is shut, so the live fact is the next one
    const label = anniversaryLabel('2023-07-03', on('2026-08-15'))
    expect(label.due).toBe(false)
    expect(label.text).toBe('in 322 days')
  })

  it('renders an em dash when there is no incorporation date', () => {
    expect(anniversaryLabel(null, on('2026-08-15'))).toEqual({ text: '—', due: false })
  })

  it('says day, not days, at exactly one', () => {
    expect(anniversaryLabel('2018-08-16', on('2026-08-15')).text).toBe('in 1 day')
    expect(anniversaryLabel('2018-08-14', on('2026-08-15')).text).toBe('1 day ago')
  })
})
