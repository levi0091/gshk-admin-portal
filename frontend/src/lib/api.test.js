import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./supabaseClient', () => ({
  supabase: {
    auth: { getSession: vi.fn(async () => ({ data: { session: { access_token: 'TOK' } } })) },
  },
}))
import { supabase } from './supabaseClient'
import { api } from './api.js'

beforeEach(() => {
  vi.clearAllMocks()
  supabase.auth.getSession.mockResolvedValue({ data: { session: { access_token: 'TOK' } } })
  global.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ ok: 1 }) }))
})

describe('api.get', () => {
  it('sends the auth token and returns the parsed body', async () => {
    const body = await api.get('/companies?page=1')
    expect(body).toEqual({ ok: 1 })
    const [, init] = global.fetch.mock.calls[0]
    expect(init.headers.Authorization).toBe('Bearer TOK')
  })

  // useAbortableGet's whole purpose (UAT W-8) is cancelling superseded
  // requests. Every page and hook test mocks api.get, so nothing else in the
  // suite would notice if this forwarding broke — the aborts would silently
  // stop happening while every test stayed green.
  it('forwards an AbortSignal through to fetch', async () => {
    const controller = new AbortController()
    await api.get('/companies?page=1', { signal: controller.signal })

    const [, init] = global.fetch.mock.calls[0]
    expect(init.signal).toBe(controller.signal)
  })

  it('still works when no options are passed', async () => {
    await expect(api.get('/companies?page=1')).resolves.toEqual({ ok: 1 })
  })

  it('rejects when the request is aborted', async () => {
    const controller = new AbortController()
    global.fetch = vi.fn(async (_url, init) => {
      if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      return { ok: true, json: async () => ({ ok: 1 }) }
    })
    controller.abort()

    await expect(api.get('/x', { signal: controller.signal })).rejects.toThrow()
  })

  it('raises the API detail message on a non-2xx response', async () => {
    global.fetch = vi.fn(async () => ({
      ok: false, statusText: 'Bad Request',
      json: async () => ({ detail: 'anniv_op must be one of lte, gte, eq' }),
    }))
    await expect(api.get('/companies?anniv_op=nope'))
      .rejects.toThrow('anniv_op must be one of lte, gte, eq')
  })
})
