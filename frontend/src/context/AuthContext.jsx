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
      if (event === 'SIGNED_IN') {
        fetchProfile()
      } else if (event === 'SIGNED_OUT') {
        setProfile(null)
        setProfileLoading(false)
      }
      // TOKEN_REFRESHED: session token updated silently — profile unchanged, no re-fetch
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
