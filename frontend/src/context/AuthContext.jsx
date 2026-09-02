import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { api } from '../lib/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined) // undefined = still checking Supabase
  const [profile, setProfile] = useState(null)
  const [profileLoading, setProfileLoading] = useState(true)

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
        setProfileLoading(false)
      }
      // SIGNED_IN / TOKEN_REFRESHED / INITIAL_SESSION: only update the session token.
      // Profile is fetched once on mount (via getSession) and once after signIn().
      // Never re-fetch here — it sets profileLoading(true) which unmounts the current page.
    })

    return () => listener.subscription.unsubscribe()
  }, [])

  async function fetchProfile() {
    setProfileLoading(true)
    try {
      const data = await api.get('/auth/me')
      setProfile(data)
    } catch {
      setProfile(null)
    } finally {
      setProfileLoading(false)
    }
  }

  async function signIn(email, password) {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
    await fetchProfile() // explicit fetch after successful sign-in (onAuthStateChange won't do it)
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
                                   mustChangePassword, refreshProfile: fetchProfile,
                                   signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
