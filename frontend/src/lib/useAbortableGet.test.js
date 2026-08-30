import { renderHook, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./api.js', () => ({ api: { get: vi.fn() } }))
import { api } from './api.js'
import useAbortableGet from './useAbortableGet.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

// Let queued .then/.catch callbacks run. waitFor would pass on its first tick,
// before they fire, and prove nothing about what a late response does.
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

beforeEach(() => vi.clearAllMocks())

describe('useAbortableGet', () => {
  it('starts loading and returns the response', async () => {
    api.get.mockResolvedValue({ ok: 1 })
    const { result } = renderHook(() => useAbortableGet('/companies?page=1'))

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual({ ok: 1 })
    expect(result.current.error).toBe('')
  })

  it('surfaces the failure message when the current request fails', async () => {
    api.get.mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useAbortableGet('/companies?page=1'))

    await waitFor(() => expect(result.current.error).toBe('boom'))
    expect(result.current.loading).toBe(false)
  })

  it('refetches when the path changes', async () => {
    api.get.mockResolvedValue({ ok: 1 })
    const { rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/companies?page=1' },
    })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))

    rerender({ p: '/companies?page=2' })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(api.get.mock.calls[1][0]).toBe('/companies?page=2')
  })

  it('does not refetch when the path is unchanged', async () => {
    api.get.mockResolvedValue({ ok: 1 })
    const { rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/companies?page=1' },
    })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))

    rerender({ p: '/companies?page=1' })
    await flush()
    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('ignores a superseded response that resolves late', async () => {
    const first = deferred()
    const second = deferred()
    api.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const { result, rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/a' },
    })
    rerender({ p: '/b' })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))

    second.resolve({ which: 'b' })
    await waitFor(() => expect(result.current.data).toEqual({ which: 'b' }))

    first.resolve({ which: 'a' })       // stale, lands last
    await flush()
    expect(result.current.data).toEqual({ which: 'b' })
  })

  it('ignores a superseded request that fails late', async () => {
    // The UAT symptom: an error banner over a view that had loaded fine.
    const first = deferred()
    const second = deferred()
    api.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const { result, rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/a' },
    })
    rerender({ p: '/b' })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))

    first.reject(new Error('boom'))
    second.resolve({ which: 'b' })

    await waitFor(() => expect(result.current.data).toEqual({ which: 'b' }))
    expect(result.current.error).toBe('')
  })

  it('leaves loading true when only the superseded request has settled', async () => {
    const first = deferred()
    const second = deferred()
    api.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const { result, rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/a' },
    })
    rerender({ p: '/b' })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))

    first.resolve({ which: 'a' })
    await flush()
    expect(result.current.loading).toBe(true)
  })

  it('aborts the superseded request and not the current one', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    const { rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/a' },
    })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))
    expect(api.get.mock.calls[0][1].signal.aborted).toBe(false)

    rerender({ p: '/b' })
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(api.get.mock.calls[0][1].signal.aborted).toBe(true)
    expect(api.get.mock.calls[1][1].signal.aborted).toBe(false)
  })

  it('aborts on unmount', async () => {
    api.get.mockReturnValue(new Promise(() => {}))
    const { unmount } = renderHook(() => useAbortableGet('/a'))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))

    const { signal } = api.get.mock.calls[0][1]
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })

  it('clears a previous error when a new request starts', async () => {
    api.get.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({ ok: 1 })
    const { result, rerender } = renderHook(({ p }) => useAbortableGet(p), {
      initialProps: { p: '/a' },
    })
    await waitFor(() => expect(result.current.error).toBe('boom'))

    rerender({ p: '/b' })
    await waitFor(() => expect(result.current.data).toEqual({ ok: 1 }))
    expect(result.current.error).toBe('')
  })
})
