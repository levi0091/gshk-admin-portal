import { describe, it, expect, vi } from 'vitest'

vi.mock('./api.js', () => ({ api: { get: vi.fn() } }))
import { DEFAULT_LIMITS, extensionOf, groupByBucket, refusalFor } from './documentSections.js'

const BUCKETS = [
  { key: 'payments' }, { key: 'maintenance' }, { key: 'other', fallback: true },
]

describe('groupByBucket', () => {
  it('groups by the bucket the API placed each document in, newest upload first', () => {
    const g = groupByBucket([
      { id: 'a', bucket: 'payments', uploaded_at: '2026-01-01T00:00:00Z' },
      { id: 'b', bucket: 'payments', uploaded_at: '2026-11-01T00:00:00Z' },
      { id: 'c', bucket: 'maintenance', created_at: '2026-05-01T00:00:00Z' },
    ], BUCKETS)
    expect(g.payments.map(d => d.id)).toEqual(['b', 'a'])
    expect(g.maintenance.map(d => d.id)).toEqual(['c'])
    expect(g.other).toEqual([])
  })

  it('puts an unknown bucket in the fallback rather than losing it', () => {
    expect(groupByBucket([{ id: 'x', bucket: 'retired' }], BUCKETS).other.map(d => d.id))
      .toEqual(['x'])
  })

  it('leaves out removed documents and identity scans (no bucket)', () => {
    const g = groupByBucket([
      { id: 'gone', bucket: 'payments', status: 'deleted' },
      { id: 'scan', bucket: null },
    ], BUCKETS)
    expect(Object.values(g).flat()).toEqual([])
  })

  it('copes with nothing at all', () => {
    expect(groupByBucket(undefined, undefined)).toEqual({})
  })
})

describe('refusalFor', () => {
  const limits = { ...DEFAULT_LIMITS, blocked_extensions: ['exe'] }
  const f = (name, size) => ({ name, size })
  it.each([
    ['report.pdf', 10, ''],
    ['minutes.DOCX', 10, ''],
    ['NOEXT', 10, ''],
    ['run.EXE', 10, '.exe files can run code'],
    ['empty.pdf', 0, 'The file is empty'],
    ['big.pdf', DEFAULT_LIMITS.max_file_bytes + 1, 'Larger than 50 MB'],
  ])('%s', (name, size, expected) => {
    const reason = refusalFor(f(name, size), limits)
    if (expected) expect(reason).toContain(expected)
    else expect(reason).toBe('')
  })
})

describe('extensionOf', () => {
  it('is the last dot, lower-cased', () => {
    expect(extensionOf('a.tar.GZ')).toBe('gz')
    expect(extensionOf('.hidden')).toBe('')
    expect(extensionOf('trailing.')).toBe('')
    expect(extensionOf(null)).toBe('')
  })
})
