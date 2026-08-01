import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import { authApi } from '@/api/auth'

vi.mock('@/api/auth', () => ({
  authApi: {
    login: vi.fn(),
    getMe: vi.fn(),
    logout: vi.fn(),
  },
}))

const mockedAuth = vi.mocked(authApi)

function TestHarness() {
  const { user, isAuthenticated, login, logout } = useAuth()
  return (
    <div>
      <p data-testid="authed">{String(isAuthenticated)}</p>
      <p data-testid="username">{user ? user.username : 'anonymous'}</p>
      <button onClick={() => login('alice', 'secret')}>Login</button>
      <button onClick={logout}>Logout</button>
    </div>
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('token persistence (C52)', () => {
  it('persists the access token and loads the user after a successful login', async () => {
    mockedAuth.login.mockResolvedValue({
      access_token: 'test-jwt',
      token_type: 'bearer',
      expires_in: 3600,
    })
    mockedAuth.getMe.mockResolvedValue({
      id: '1',
      username: 'alice',
      role: 'admin',
    })

    render(
      <AuthProvider>
        <TestHarness />
      </AuthProvider>,
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Login' }))
    })

    expect(localStorage.getItem('token')).toBe('test-jwt')
    expect(screen.getByTestId('username').textContent).toBe('alice')
    expect(screen.getByTestId('authed').textContent).toBe('true')
  })

  it('clears the persisted token on logout', async () => {
    localStorage.setItem('token', 'existing-jwt')
    mockedAuth.getMe.mockResolvedValue({
      id: '1',
      username: 'alice',
      role: 'admin',
    })

    render(
      <AuthProvider>
        <TestHarness />
      </AuthProvider>,
    )

    // Wait for the on-mount getMe() to resolve and set the user.
    await screen.findByText('alice')

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Logout' }))
    })

    expect(localStorage.getItem('token')).toBeNull()
    expect(screen.getByTestId('authed').textContent).toBe('false')
    expect(screen.getByTestId('username').textContent).toBe('anonymous')
  })
})
