import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { billingApi } from '@/api/billing'
import { paymentsApi } from '@/api/payments'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { CreditCard, Check } from 'lucide-react'
import { cn, formatCents } from '@/lib/utils'

export function BillingPanel() {
  const queryClient = useQueryClient()
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'yearly'>('monthly')
  const [paymentMethod, setPaymentMethod] = useState<'stripe' | '1ai'>('stripe')
  const [actionError, setActionError] = useState<string | null>(null)

  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ['subscription'],
    queryFn: billingApi.getSubscription,
  })

  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ['usage'],
    queryFn: billingApi.getUsage,
  })

  const { data: tiers, isLoading: tiersLoading } = useQuery({
    queryKey: ['tiers'],
    queryFn: billingApi.getTiers,
  })

  const { data: invoices } = useQuery({
    queryKey: ['invoices'],
    queryFn: () => billingApi.getInvoices(10),
    retry: false,
  })

  const createCheckout = useMutation({
    mutationFn: ({ tier, period }: { tier: string; period: 'monthly' | 'yearly' }) =>
      billingApi.createCheckout(tier, period),
    onSuccess: (data) => {
      window.location.href = data.url
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const createPayment = useMutation({
    mutationFn: ({ tier, period }: { tier: string; period: 'monthly' | 'yearly' }) =>
      paymentsApi.createCheckout(tier, period),
    onSuccess: (data) => {
      window.location.href = data.payment_url
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const cancelSubscription = useMutation({
    mutationFn: () => billingApi.cancelSubscription(false),
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['subscription'] })
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const reactivate = useMutation({
    mutationFn: billingApi.reactivateSubscription,
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['subscription'] })
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const isLoading = subLoading || usageLoading || tiersLoading

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-32" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-4 w-48" />
            <div className="grid grid-cols-2 gap-4 mt-4">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          </CardContent>
        </Card>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            Current Plan
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h3 className="text-2xl font-bold capitalize">{subscription?.tier || 'Free'}</h3>
              <p className="text-muted-foreground">
                {subscription?.status === 'active' ? 'Active' : subscription?.status || 'Active'}
                {subscription?.current_period_end && (
                  <> - Renews {new Date(subscription.current_period_end).toLocaleDateString()}</>
                )}
              </p>
            </div>
            <div className="flex gap-2">
              {subscription?.cancel_at_period_end ? (
                <Button onClick={() => reactivate.mutate()} disabled={reactivate.isPending}>
                  {reactivate.isPending ? "Reactivating..." : "Reactivate Subscription"}
                </Button>
              ) : subscription?.tier && subscription.tier !== 'free' ? (
                <Button variant="outline" onClick={() => cancelSubscription.mutate()} disabled={cancelSubscription.isPending}>
                  {cancelSubscription.isPending ? "Cancelling..." : "Cancel Subscription"}
                </Button>
              ) : null}
            </div>
          </div>

          {usage && (
            <div className="mt-6 grid grid-cols-2 gap-4">
              <div className="p-4 border rounded-lg">
                <div className="flex justify-between mb-2 text-sm">
                  <span className="text-muted-foreground">Servers</span>
                  <span className="font-medium">{usage.usage.servers.current} / {usage.usage.servers.unlimited ? '∞' : usage.usage.servers.limit}</span>
                </div>
                {!usage.usage.servers.unlimited && (
                  <Progress value={(usage.usage.servers.current / usage.usage.servers.limit) * 100} className="h-2" />
                )}
              </div>
              <div className="p-4 border rounded-lg">
                <div className="flex justify-between mb-2 text-sm">
                  <span className="text-muted-foreground">Instances</span>
                  <span className="font-medium">{usage.usage.instances.current} / {usage.usage.instances.unlimited ? '∞' : usage.usage.instances.limit}</span>
                </div>
                {!usage.usage.instances.unlimited && (
                  <Progress value={(usage.usage.instances.current / usage.usage.instances.limit) * 100} className="h-2" />
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h2 className="text-xl font-bold">Available Plans</h2>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex gap-1 p-1 bg-muted rounded-lg">
              <Button
                size="sm"
                variant={billingPeriod === 'monthly' ? 'secondary' : 'ghost'}
                onClick={() => setBillingPeriod('monthly')}
              >
                Monthly
              </Button>
              <Button
                size="sm"
                variant={billingPeriod === 'yearly' ? 'secondary' : 'ghost'}
                onClick={() => setBillingPeriod('yearly')}
              >
                Yearly
                <Badge variant="outline" className="ml-2 text-xs">-17%</Badge>
              </Button>
            </div>
            <div className="flex gap-1 p-1 bg-muted rounded-lg">
              <Button
                size="sm"
                variant={paymentMethod === 'stripe' ? 'secondary' : 'ghost'}
                onClick={() => setPaymentMethod('stripe')}
              >
                Card (Stripe)
              </Button>
              <Button
                size="sm"
                variant={paymentMethod === '1ai' ? 'secondary' : 'ghost'}
                onClick={() => setPaymentMethod('1ai')}
              >
                1ai Payment
              </Button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {tiers && Object.entries(tiers).map(([key, tier]) => {
            const isCurrentPlan = subscription?.tier === key
            const price = billingPeriod === 'monthly' ? tier.price_monthly : tier.price_yearly

            return (
              <Card key={key} className={cn(
                "relative",
                isCurrentPlan && "border-primary ring-2 ring-primary"
              )}>
                {isCurrentPlan && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <Badge>Current Plan</Badge>
                  </div>
                )}
                <CardHeader>
                  <CardTitle>{tier.name}</CardTitle>
                  <CardDescription>
                    <span className="text-3xl font-bold text-foreground">
                      {price === 0 ? 'Free' : formatCents(price)}
                    </span>
                    {price > 0 && (
                      <span className="text-muted-foreground">/{billingPeriod === 'monthly' ? 'mo' : 'yr'}</span>
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2 mb-6">
                    {tier.features.map((feature: string, i: number) => (
                      <li key={i} className="flex items-center gap-2 text-sm">
                        <Check className="h-4 w-4 text-green-500 shrink-0" />
                        {feature}
                      </li>
                    ))}
                  </ul>
                  <Button
                    className="w-full"
                    variant={isCurrentPlan ? "outline" : "default"}
                    disabled={isCurrentPlan || createCheckout.isPending || createPayment.isPending}
                    onClick={() => {
                      if (price === 0) return
                      if (paymentMethod === '1ai') {
                        createPayment.mutate({ tier: key, period: billingPeriod })
                      } else {
                        createCheckout.mutate({ tier: key, period: billingPeriod })
                      }
                    }}
                  >
                    {isCurrentPlan ? 'Current Plan' : price === 0 ? 'Free Forever' : 'Upgrade'}
                  </Button>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>

      {invoices && Array.isArray(invoices) && invoices.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Recent Invoices</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto -mx-4 sm:mx-0">
              <table className="w-full text-sm min-w-[400px]">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-2 sm:px-4">Date</th>
                  <th className="text-right py-2 px-2 sm:px-4">Amount</th>
                  <th className="text-center py-2 px-2 sm:px-4">Status</th>
                  <th className="text-right py-2 px-2 sm:px-4">Actions</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice) => (
                  <tr key={invoice.id} className="border-b">
                    <td className="py-2 px-2 sm:px-4">{new Date(invoice.created).toLocaleDateString()}</td>
                    <td className="py-2 px-2 sm:px-4 text-right">${(invoice.amount / 100).toFixed(2)}</td>
                    <td className="py-2 px-2 sm:px-4 text-center">
                      <Badge variant={invoice.status === 'paid' ? 'success' : 'secondary'}>
                        {invoice.status}
                      </Badge>
                    </td>
                    <td className="py-2 px-2 sm:px-4 text-right">
                      <div className="flex gap-1 sm:gap-2 justify-end">
                        {invoice.invoice_url && (
                          <Button size="sm" variant="ghost" onClick={() => window.open(invoice.invoice_url!, '_blank')}>
                            View
                          </Button>
                        )}
                        {invoice.pdf_url && (
                          <Button size="sm" variant="ghost" onClick={() => window.open(invoice.pdf_url!, '_blank')}>
                            PDF
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
