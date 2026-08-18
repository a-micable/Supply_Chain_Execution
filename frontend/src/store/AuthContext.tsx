import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../services/apiClient'

type Me = {
  user_id: string
  username: string
  roles: string[]
}

type AuthContextValue = {
  me: Me | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [me, setMe] = useState<Me | null>(null)

  useEffect(() => {
    let cancelled = false
    async function loadMe() {
      if (!token) return
      try {
        const res = await api.getMe(token)
        if (!cancelled) setMe(res)
      } catch {
        if (!cancelled) {
          setToken(null)
          setMe(null)
          localStorage.removeItem('token')
        }
      }
    }
    loadMe()
    return () => {
      cancelled = true
    }
  }, [token])

  const value = useMemo<AuthContextValue>(
    () => ({
      me,
      token,
      login: async (username, password) => {
        const tokenRes = await api.login(username, password)
        setToken(tokenRes.access_token)
        localStorage.setItem('token', tokenRes.access_token)
        const res = await api.getMe(tokenRes.access_token)
        setMe(res)
      },
      logout: () => {
        localStorage.removeItem('token')
        setToken(null)
        setMe(null)
      },
    }),
    [me, token],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

