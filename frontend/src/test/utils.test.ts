import { describe, it, expect } from 'vitest'
import { formatCents } from '@/lib/utils'

describe('formatCents', () => {
  it('renders cents as dollars', () => {
    expect(formatCents(5000)).toBe('$50.00')
  })
  it('renders zero as $0.00', () => {
    expect(formatCents(0)).toBe('$0.00')
  })
  it('falls back to $0.00 for non-finite input', () => {
    expect(formatCents(NaN)).toBe('$0.00')
    expect(formatCents(Infinity)).toBe('$0.00')
  })
  it('supports a custom currency', () => {
    expect(formatCents(1999, 'EUR')).toBe('€19.99')
  })
})
