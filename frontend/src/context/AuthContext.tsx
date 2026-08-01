import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { authApi, TwoFactorRequiredError } from '@/api/auth'
import type { AuthUser } from '@/api/auth'
import { getToken, setToken, clearToken } from '@/api/client'

interface AuthContextType {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = getToken()
    if (token) {
      authApi.getMe()
        .then(setUser)
        .catch(clearToken)
        .finally(() => setIsLoading(false))
    } else {
      setIsLoading(false)
    }
  }, [])

  const login = async (username: string, password: string, twoFactorCode?: string) => {
    const response = await authApi.login(username, password, twoFactorCode)
    if (response.requires_2fa) {
      throw new TwoFactorRequiredError('Enter your 2FA code')
    }
    if (response.requires_verification) {
      throw new Error('Please verify your email before signing in')
    }
    if (!response.access_token) {
      throw new Error('Login failed')
    }
    setToken(response.access_token)
    const userData = await authApi.getMe()
    setUser(userData)
  }

  const logout = () => {
    clearToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
