import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { api } from '../lib/api'

const AuthContext = createContext(null)

/** How long to wait before the one retry below. */
const PROFILE_RETRY_MS = 700

export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined) // undefined = still checking Supabase
  const [profile, setProfile] = useState(null)
  const [profileLoading, setProfileLoading] = useState(true)
  // WHY THIS EXISTS. `fetchProfile` used to swallow every failure into
  // `profile = null` and never try again, and nothing anywhere said so. The
  // result is indistinguishable from a role with no permissions: the sidebar
  // renders an empty Main section, every `hasPermission` answers false, and the
  // user is left in a portal that looks like it has been taken away from them.
  // Levi hit exactly this on 2026-09-04 — an empty menu beside "Failed to load
  // cases: Invalid token".
  const [profileError, setProfileError] = useState(null)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      if (session) {
        fetchProfile()
      } else {
        setProfileLoading(false)
      }
    })

    const { data: listener } = supabase.auth.onAuthStateChange((event, session) => {
      setSession(session)
      if (event === 'SIGNED_OUT') {
        setProfile(null)
        setProfileError(null)
        setProfileLoading(false)
      }
      // SIGNED_IN / TOKEN_REFRESHED / INITIAL_SESSION: only update the session token.
      // Profile is fetched once on mount (via getSession) and once after signIn().
      // Never re-fetch here — it sets profileLoading(true) which unmounts the current page.
    })

    return () => listener.subscription.unsubscribe()
  }, [])

  /**
   * Load the identity, and be honest when it cannot be loaded.
   *
   * ONE RETRY, because the failures that actually happen here are transient:
   * Railway cold-starting, a Cloudflare-dropped connection, a token being
   * refreshed underneath us. Retrying forever would hammer a genuinely dead
   * API; not retrying at all cost a working user their entire menu.
   *
   * A 401 THAT SURVIVES THE RETRY ENDS THE SESSION. It means the token really
   * is not valid — expired while the tab was asleep, or the account was
   * deactivated — and leaving the user inside an app shell where every request
   * fails is the worst of both: they cannot work, and nothing tells them to
   * sign in again. Signing out returns them to the login screen, which is the
   * one action that actually fixes it.
   */
  async function fetchProfile() {
    setProfileLoading(true)
    try {
      let lastError
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const data = await api.get('/auth/me')
          setProfile(data)
          setProfileError(null)
          return data
        } catch (err) {
          lastError = err
          if (attempt === 0) {
            await new Promise(r => setTimeout(r, PROFILE_RETRY_MS))
          }
        }
      }

      setProfile(null)
      setProfileError(lastError?.message || 'Could not load your account')

      if (lastError?.status === 401) {
        // Deliberately not awaited into the caller's success path — signOut
        // fires SIGNED_OUT, which clears this state anyway.
        supabase.auth.signOut().catch(() => {})
      }
      return null
    } finally {
      setProfileLoading(false)
    }
  }

  async function signIn(email, password) {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
    // explicit fetch after successful sign-in (onAuthStateChange won't do it)
    const loaded = await fetchProfile()
    if (!loaded) {
      // THE PASSWORD WAS RIGHT AND THE PORTAL STILL CANNOT BE USED. Reported
      // here, on the login screen, rather than letting the caller navigate
      // into an app shell with an empty menu and no explanation for it — which
      // is what happened before and reads as "my access was revoked".
      throw new Error(
        'Signed in, but your account details could not be loaded from the API. '
        + 'Try again in a moment — if it keeps happening the API may be down or '
        + 'still starting up.')
    }
  }

  async function signOut() {
    await supabase.auth.signOut()
  }

  const isSuperAdmin = profile?.role_name === 'super_admin'

  // Strict `=== true` for the same reason `isTestEnv` is: a profile that has
  // not loaded, or a backend too old to send the field, must not lock a
  // working account out of the portal. The API refuses independently, so
  // failing open HERE costs a confusing 409, while failing closed would show
  // a set-password screen to everyone the moment /auth/me hiccuped.
  const mustChangePassword = profile?.must_change_password === true

  // Strict `=== true`, so a profile that has not loaded yet, or a backend too
  // old to send the field, does NOT light the TEST badge. A missing badge on a
  // test deployment is a smaller lie than a TEST badge on production, which
  // would tell an operator their real filing was a rehearsal.
  const isTestEnv = profile?.is_test_env === true

  // THE THIRD STATE. `is_test_env` absent is not the same as "production", and
  // rendering it as production means the one indicator of which interlock is
  // running fails silently, in the unsafe direction. `profile != null` keeps
  // this off the screen while the profile is still loading — an unanswered
  // question is not an unknown answer.
  const envUnknown = profile != null && profile.is_test_env == null

  function hasPermission(module, permission) {
    if (isSuperAdmin) return true
    return (profile?.permissions || []).includes(`${module}:${permission}`)
  }

  return (
    <AuthContext.Provider value={{ session, profile, isSuperAdmin, isTestEnv,
                                   envUnknown, hasPermission, profileLoading,
                                   profileError,
                                   mustChangePassword, refreshProfile: fetchProfile,
                                   signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

/**
 * The value `useAuth()` returns when there is no provider above it.
 *
 * WHY IT IS NOT `null`. Every screen destructures this hook, so a component
 * rendered outside the provider throws during render. `main.jsx` does have a
 * root ErrorBoundary, so that is a caught error page rather than a blank
 * screen — but an entire page replaced by "something went wrong" is still a
 * bad answer to a component being mounted in the wrong place, and a shell that
 * is merely locked down is a far better failure than no shell at all.
 *
 * It DENIES everything, which is the safe direction: a screen that cannot find
 * out what you may do must not assume you may do it. The API refuses
 * independently in any case.
 */
const NO_AUTH = {
  session: undefined,
  profile: null,
  profileLoading: false,
  profileError: null,
  isSuperAdmin: false,
  isTestEnv: false,
  envUnknown: false,
  mustChangePassword: false,
  hasPermission: () => false,
  refreshProfile: async () => null,
  signIn: async () => { throw new Error('Auth is not available') },
  signOut: async () => {},
}

export function useAuth() {
  return useContext(AuthContext) || NO_AUTH
}
