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

  // When the request never completes at all — the network is down, or the
  // server answered with an error carrying no CORS headers, which is what a
  // FastAPI 500 looks like from the browser — fetch REJECTS. Its message is
  // "Failed to fetch", which every screen then printed verbatim. Levi read that
  // on the dashboard and took it for an empty table.
  it('replaces the browser’s "Failed to fetch" with something actionable', async () => {
    global.fetch = vi.fn(async () => { throw new TypeError('Failed to fetch') })
    await expect(api.get('/cases?scope=dashboard'))
      .rejects.toThrow(/Could not reach the server/)
  })

  it('keeps the original failure as the cause, so it is still debuggable', async () => {
    const underlying = new TypeError('Failed to fetch')
    global.fetch = vi.fn(async () => { throw underlying })
    await expect(api.get('/cases')).rejects.toMatchObject({
      offline: true, cause: underlying,
    })
  })

  it('leaves an AbortError exactly as it is', async () => {
    // Every listing aborts superseded requests on purpose, and useAbortableGet
    // recognises the error BY NAME. Rewriting it would turn each of those into
    // a visible "could not reach the server" banner on a request the user
    // themselves replaced.
    global.fetch = vi.fn(async () => { throw new DOMException('Aborted', 'AbortError') })
    await expect(api.get('/cases')).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('describeApiError — the drift refusal (spec §6)', () => {
  it('carries `differences` through, rather than flattening them into a message', async () => {
    // Nothing else in the suite would notice if this forwarding broke: every
    // Submission-stage test builds its own error object, so the panel would
    // keep rendering in tests while showing nothing in the browser. This is the
    // only place the wiring itself is asserted.
    const differences = [
      { path: 'roAddr/bldg', field: 'Registered office · Building',
        validated: 'Test Tower', current: 'New Tower' },
    ]
    global.fetch = vi.fn(async () => ({
      ok: false, status: 409, statusText: 'Conflict',
      json: async () => ({
        detail: { message: 'the validated form no longer matches', differences },
      }),
    }))
    await expect(api.post('/tpsi/filings/f1/submit', { confirm: true }))
      .rejects.toMatchObject({ status: 409, differences })
  })

  it('leaves `differences` unset on an ordinary refusal', async () => {
    global.fetch = vi.fn(async () => ({
      ok: false, status: 409, statusText: 'Conflict',
      json: async () => ({ detail: 'filing is not signed' }),
    }))
    const error = await api.post('/x', {}).catch(e => e)
    expect(error.differences).toBeUndefined()
  })
})
