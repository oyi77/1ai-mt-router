import { api } from './client'

export interface Tier {
  name: string
  price_monthly: number
  price_yearly: number
  limits: {
    max_servers: number
    max_instances: number
    max_api_calls_per_day: number
    max_users: number
    support_level: string
  }
  features: string[]
}

export interface Subscription {
  tier: string
  status: string
  current_period_end: string | null
  cancel_at_period_end: boolean
  stripe_customer_id?: string
  limits: Record<string, number>
  features: string[]
}

export interface Usage {
  tier: string
  usage: {
    servers: { current: number; limit: number; unlimited: boolean }
    instances: { current: number; limit: number; unlimited: boolean }
  }
  period: { start: string; end: string }
}

export interface Invoice {
  id: string
  amount: number
  currency: string
  status: string
  invoice_url: string | null
  pdf_url: string | null
  created: string
}

export const billingApi = {
  getTiers: () => api.get<Record<string, Tier>>('/billing/tiers'),
  
  getSubscription: () => api.get<Subscription>('/billing/subscription'),
  
  getUsage: () => api.get<Usage>('/billing/usage'),
  
  createCheckout: (tier: string, billingPeriod: 'monthly' | 'yearly') =>
    api.post<{ session_id: string; url: string }>('/billing/checkout', {
      tier,
      billing_period: billingPeriod
    }),
  
  getPortalUrl: () => api.get<{ url: string }>('/billing/portal'),
  
  cancelSubscription: (immediate: boolean = false) =>
    api.post('/billing/cancel', { immediate }),
  
  reactivateSubscription: () => api.post('/billing/reactivate'),
  
  getInvoices: (limit: number = 10) =>
    api.get<Invoice[]>(`/billing/invoices?limit=${limit}`),
}

// Backend prices and invoice amounts are integer cents — never divide in the
// API layer; use this for display only.
export const formatCents = (cents: number): string => `$${(cents / 100).toFixed(2)}`
