import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { AuthProvider, useAuth } from './AuthContext.jsx'

/**
 * What happens when `/auth/me` does not answer.
 *
 * IT USED TO BE SILENT. `fetchProfile` swallowed every failure into
 * `profile = null` and never tried again, and nothing on screen said so. The
 * result is indistinguishable from a role with no permissions at all: the
 * sidebar renders an empty Main section, every `hasPermission` answers false,
 * and the user is left in a portal that looks like it has been taken away from
 * them. Levi hit exactly that on 2026-09-04 — an empty menu beside "Failed to
 * load cases: Invalid token".
 *
 * So: one retry, because the failures that happen here are transient; a stated
 * error, because an empty menu must never be ambiguous; and a sign-out on a
 * 401 that survives the retry, because that token really is dead and sitting
 * in a shell where every request fails helps nobody.
 */
const get = vi.fn()
vi.mock('../lib/api', () => ({ api: { get: (...a) => get(...a) } }))

const getSession = vi.fn()
const signOut = vi.fn()
const onAuthStateChange = vi.fn(() => ({
  data: { subscription: { unsubscribe: vi.fn() } },
}))
vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: (...a) => getSession(...a),
      onAuthStateChange: (...a) => onAuthStateChange(...a),
      signInWithPassword: vi.fn(),
      signOut: (...a) => signOut(...a),
    },
  },
}))

const PROFILE = {
  id: 'u1', display_name: 'Tester', role_name: 'tester',
  permissions: ['companies:read', 'persons:read', 'persons:write'],
  is_test_env: true, must_change_password: false,
}

function Probe() {
  const { profileLoading, profileError, hasPermission } = useAuth()
  return (
    <div>
      <span data-testid="state">
        {profileLoading ? 'loading' : profileError ? `error:${profileError}` : 'ready'}
      </span>
      <span data-testid="companies">
        {hasPermission('companies', 'read') ? 'yes' : 'no'}
      </span>
    </div>
  )
}

const renderProvider = () =>
  render(<AuthProvider><Probe /></AuthProvider>)

const withSession = () =>
  getSession.mockResolvedValue({ data: { session: { access_token: 't' } } })

beforeEach(() => {
  vi.clearAllMocks()
  withSession()
  signOut.mockResolvedValue({})
})

describe('AuthProvider — loading the identity', () => {
  it('reads the permission list when /auth/me answers', async () => {
    get.mockResolvedValue(PROFILE)
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'))
    expect(screen.getByTestId('companies')).toHaveTextContent('yes')
  })

  it('RETRIES once, so one transient failure does not cost the whole menu', async () => {
    // A Railway cold start, a Cloudflare-dropped connection, a token being
    // refreshed underneath us — all of these resolve on the second ask, and
    // all of them used to strip every nav item until a manual reload.
    get.mockRejectedValueOnce(Object.assign(new Error('Could not reach the server')))
    get.mockResolvedValueOnce(PROFILE)
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'),
                  { timeout: 4000 })
    expect(screen.getByTestId('companies')).toHaveTextContent('yes')
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('states the error when both attempts fail, rather than looking like an empty role', async () => {
    get.mockRejectedValue(new Error('Could not reach the server'))
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('state'))
      .toHaveTextContent('error:Could not reach the server'), { timeout: 4000 })
    expect(screen.getByTestId('companies')).toHaveTextContent('no')
  })

  it('does not retry forever on a dead API', async () => {
    get.mockRejectedValue(new Error('down'))
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('error:'),
                  { timeout: 4000 })
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('signs out on a 401 that survives the retry', async () => {
    // The token really is not valid — expired while the tab slept, or the
    // account was deactivated. Leaving the user in a shell where every request
    // fails is the worst of both: they cannot work, and nothing tells them to
    // sign in again.
    get.mockRejectedValue(Object.assign(new Error('Invalid token'), { status: 401 }))
    renderProvider()

    await waitFor(() => expect(signOut).toHaveBeenCalled(), { timeout: 4000 })
  })

  it('does NOT sign out on a failure that is not a 401', async () => {
    // A cold-starting API is not a revoked session, and signing the user out
    // over one would be a logout loop every time Railway wakes up.
    get.mockRejectedValue(Object.assign(new Error('down'), { status: 503 }))
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('error:'),
                  { timeout: 4000 })
    expect(signOut).not.toHaveBeenCalled()
  })

  it('asks for nothing at all when there is no session', async () => {
    getSession.mockResolvedValue({ data: { session: null } })
    renderProvider()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'))
    expect(get).not.toHaveBeenCalled()
  })
})

describe('useAuth outside a provider', () => {
  it('denies everything instead of throwing', async () => {
    // `createContext(null)` plus a destructuring hook means a component
    // rendered outside the provider throws DURING RENDER. The root
    // ErrorBoundary catches it, so the user gets "something went wrong"
    // instead of the page they asked for — which is still a bad answer to a
    // component mounted in the wrong place. A locked-down shell is better.
    render(<Probe />)
    expect(screen.getByTestId('state')).toHaveTextContent('ready')
    expect(screen.getByTestId('companies')).toHaveTextContent('no')
  })
})
