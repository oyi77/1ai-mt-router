import { api } from './client'

export interface PaymentCheckout {
  payment_url: string
  payment_id: string
  gateway: string
}

export const paymentsApi = {
  createCheckout: (tier: string, billingPeriod: 'monthly' | 'yearly') =>
    api.post<PaymentCheckout>('/payments/checkout', {
      tier,
      billing_period: billingPeriod
    }),
}
