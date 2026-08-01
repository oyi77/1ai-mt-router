import { api, clearToken } from './client'

export interface AuthUser {
  id: string
  username: string
  role: string
  email?: string
  two_factor_enabled?: boolean
}

// 2FA/verification gates are reported as HTTP 200 bodies from /auth/login,
// so access_token must be optional here.
export interface LoginResponse {
  access_token?: string
  token_type?: string
  expires_in?: number
  requires_2fa?: boolean
  requires_verification?: boolean
  message?: string
}

export class TwoFactorRequiredError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'TwoFactorRequiredError'
  }
}

export const authApi = {
  // 2FA is a re-POST to the same /auth/login endpoint with two_factor_code;
  // there is no separate endpoint. No code -> 200 { requires_2fa: true }.
  login: async (username: string, password: string, twoFactorCode?: string): Promise<LoginResponse> => {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        password,
        ...(twoFactorCode ? { two_factor_code: twoFactorCode } : {}),
      }),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Login failed' }))
      throw new Error(error.detail || 'Login failed')
    }

    return response.json()
  },

  register: async (data: { username: string; password: string; email?: string }) => {
    const response = await fetch('/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Registration failed' }))
      throw new Error(error.detail || 'Registration failed')
    }

    return response.json()
  },

  getMe: () => api.get<AuthUser>('/auth/me'),

  logout: () => clearToken(),
}
