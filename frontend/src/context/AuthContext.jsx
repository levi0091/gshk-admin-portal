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

  function hasPermission(module, permission) {
    if (isSuperAdmin) return true
    return (profile?.permissions || []).includes(`${module}:${permission}`)
  }

  return (
    <AuthContext.Provider value={{ session, profile, isSuperAdmin, hasPermission, profileLoading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
