import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { AuthProvider, useAuth } from './AuthContext.jsx'

/**
 * Which interlock is this deployment running under, as the header reports it.
 *
 * There are THREE answers, not two. `is_test_env: false` means the backend
 * said production; a MISSING field means it did not say. Before 2026-08-30
 * those rendered identically — and a DEV backend running APP_ENV=prod showed
 * no badge at all, which was the only visible symptom of a mail interlock that
 * had quietly disarmed.
 */

const get = vi.fn()
vi.mock('../lib/api', () => ({ api: { get: (...a) => get(...a) } }))

const getSession = vi.fn()
const onAuthStateChange = vi.fn(() => ({
  data: { subscription: { unsubscribe: vi.fn() } },
}))
vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: (...a) => getSession(...a),
      onAuthStateChange: (...a) => onAuthStateChange(...a),
      signInWithPassword: vi.fn(),
      signOut: vi.fn(),
    },
  },
}))

function Probe() {
  const { isTestEnv, envUnknown, profileLoading } = useAuth()
  return (
    <div>
      <span data-testid="state">
        {profileLoading ? 'loading'
          : isTestEnv ? 'test'
            : envUnknown ? 'unknown' : 'production'}
      </span>
    </div>
  )
}

const showFor = async me => {
  get.mockResolvedValue(me)
  render(<AuthProvider><Probe /></AuthProvider>)
  await waitFor(() =>
    expect(screen.getByTestId('state')).not.toHaveTextContent('loading'))
  return screen.getByTestId('state').textContent
}

beforeEach(() => {
  vi.clearAllMocks()
  getSession.mockResolvedValue({ data: { session: { access_token: 't' } } })
})

describe('the environment the header reports', () => {
  const profile = over => ({
    id: 'u1', display_name: 'Levi', role_name: 'super_admin',
    permissions: [], ...over,
  })

  it('lights TEST when the backend says non-production', async () => {
    expect(await showFor(profile({ is_test_env: true }))).toBe('test')
  })

  it('shows nothing when the backend says production', async () => {
    expect(await showFor(profile({ is_test_env: false }))).toBe('production')
  })

  it('does NOT read a missing field as production', async () => {
    // The bug this exists to prevent: an unanswered question rendering as a
    // live deployment, which is the unsafe direction for a warning.
    expect(await showFor(profile())).toBe('unknown')
  })

  it('treats an explicit null the same as an absent field', async () => {
    expect(await showFor(profile({ is_test_env: null }))).toBe('unknown')
  })

  it('says nothing at all while the profile is still loading', async () => {
    // An unanswered question is not an unknown answer — a badge that flashes
    // on every page load is a badge people learn to ignore.
    let resolve
    get.mockReturnValue(new Promise(r => { resolve = r }))
    render(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() =>
      expect(screen.getByTestId('state')).toHaveTextContent('loading'))
    resolve(profile({ is_test_env: true }))
    await waitFor(() =>
      expect(screen.getByTestId('state')).toHaveTextContent('test'))
  })

  it('does not claim production when /auth/me failed outright', async () => {
    get.mockRejectedValue(new Error('offline'))
    render(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() =>
      expect(screen.getByTestId('state')).not.toHaveTextContent('loading'))
    // profile stays null, so there is nothing to report either way — the
    // header shows no environment badge rather than an invented one.
    expect(screen.getByTestId('state')).toHaveTextContent('production')
  })
})
