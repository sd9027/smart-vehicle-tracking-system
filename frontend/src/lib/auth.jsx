import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, tokenStore } from './api'

const AuthContext = createContext(null)
const RANK = { VIEWER: 0, MANAGER: 1, ADMIN: 2 }

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(Boolean(tokenStore.get()))

  // On first load, confirm the saved token is still valid.
  useEffect(() => {
    if (!tokenStore.get()) return
    api.get('/auth/me')
      .then((r) => setUser(r.data))
      .catch(() => tokenStore.clear())
      .finally(() => setChecking(false))
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  // api.js fires this when any request comes back 401.
  useEffect(() => {
    window.addEventListener('tracktech:logout', logout)
    return () => window.removeEventListener('tracktech:logout', logout)
  }, [logout])

  const login = useCallback(async (email, password) => {
    const { data } = await api.post('/auth/login', { email, password })
    tokenStore.set(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const applyToken = useCallback((data) => {
    tokenStore.set(data.access_token)
    setUser(data.user)
  }, [])

  const value = useMemo(() => ({
    user,
    checking,
    login,
    logout,
    applyToken,
    can: (role) => Boolean(user) && RANK[user.role] >= RANK[role],
  }), [user, checking, login, logout, applyToken])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
