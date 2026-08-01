// Vitest setup — runs once per test file, before tests execute (jsdom env).
//
// - The `jsdom` environment provides a fresh `localStorage` and DOM per test
//   file, and `globals: true` (see vitest.config.ts) exposes describe/it/expect.
// - @testing-library/react auto-cleans the DOM between tests (it registers an
//   afterEach hook when a global is present), so no manual cleanup() is needed.
// - `msw` via `msw/node` setupServer is used for API mocking where components
//   fetch from the backend (see App.test.tsx).
//
// Note: @testing-library/jest-dom is intentionally NOT a dependency, so tests
// assert with plain vitest matchers (toBeDefined(), toBe(), ...) instead.
