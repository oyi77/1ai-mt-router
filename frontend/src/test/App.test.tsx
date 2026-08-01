import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import App from '@/App'

// The landing page fetches pricing tiers on mount; stub the endpoint so the
// shell renders without a backend. No token in localStorage means AuthProvider
// performs no getMe() call, so this is the only request the shell makes.
const server = setupServer(
  http.get('/api/v1/billing/tiers', () => HttpResponse.json({})),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('App shell', () => {
  it('renders the landing page at the root route', () => {
    renderApp('/')

    // The brand name appears in the nav, footer, and copyright line.
    const brand = screen.getAllByText('MT5 Router')
    expect(brand.length).toBeGreaterThan(0)

    expect(
      screen.getByRole('heading', { name: /Cloud MT5 Infrastructure/i }),
    ).toBeDefined()
  })
})
