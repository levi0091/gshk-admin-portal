import { createContext, useContext, useEffect, useState } from 'react'
import { supabase } from '../lib/supabaseClient'
import { api } from '../lib/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined) // undefined = loading
  const [profile, setProfile] = useState(null)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      if (session) fetchProfile()
    })

    const { data: listener } = supabase.auth.onAuthStateChange((_, session) => {
      setSession(session)
      if (session) fetchProfile()
      else setProfile(null)
    })

    return () => listener.subscription.unsubscribe()
  }, [])

  async function fetchProfile() {
    try {
      const data = await api.get('/auth/me')
      setProfile(data)
    } catch {
      setProfile(null)
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

  return (
    <AuthContext.Provider value={{ session, profile, isSuperAdmin, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
