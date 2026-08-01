import { useState, useEffect } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatCents, type Tier } from "@/api/billing"
import {
  Server,
  Activity,
  Copy,
  Monitor,
  Webhook,
  CreditCard,
  ArrowRight,
  Check,
  Shield,
  ChevronRight,
  Zap,
  Globe,
  Menu,
  X,
} from "lucide-react"

const features = [
  {
    icon: Server,
    title: "Multi-Server Management",
    description: "Deploy MT5 across any SSH server. Manage your entire infrastructure from a single dashboard.",
  },
  {
    icon: Activity,
    title: "Real-Time Monitoring",
    description: "CPU, memory, and trading metrics per instance. Instant alerts when things need attention.",
  },
  {
    icon: Copy,
    title: "Copy Trading API",
    description: "Replicate trades across accounts instantly. Build custom signal distribution networks.",
  },
  {
    icon: Monitor,
    title: "VNC Remote Access",
    description: "Full desktop access to any MT5 instance directly from your browser. No extra software needed.",
  },
  {
    icon: Webhook,
    title: "Webhook Integration",
    description: "Connect to TradingView, custom signals, and third-party platforms with flexible webhooks.",
  },
  {
    icon: CreditCard,
    title: "Enterprise Billing",
    description: "Usage-based pricing with Stripe integration. Transparent costs that scale with your operation.",
  },
]

const steps = [
  {
    step: "01",
    title: "Connect Your Servers",
    description: "Add your SSH servers and we handle Docker deployment automatically. Any cloud provider, any region.",
  },
  {
    step: "02",
    title: "Deploy MT5 Instances",
    description: "One click to spin up fully configured MetaTrader 5 terminals with your broker credentials.",
  },
  {
    step: "03",
    title: "Trade & Monitor",
    description: "Real-time metrics, VNC access, API control, and webhook integrations. Everything you need.",
  },
]

export function Landing() {
  const [tiers, setTiers] = useState<Record<string, Tier> | null>(null)
  const [tiersError, setTiersError] = useState(false)
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "yearly">("monthly")
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  useEffect(() => {
    fetch("/api/v1/billing/tiers")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch tiers")
        return res.json()
      })
      .then((data) => setTiers(data))
      .catch(() => setTiersError(true))
  }, [])

  const scrollToPricing = () => {
    document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth" })
  }

  const tierOrder = ["free", "basic", "pro"]
  const sortedTiers = tiers
    ? tierOrder
        .filter((key) => tiers[key])
        .map((key) => ({ key, ...tiers[key] }))
    : []

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-md">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-16 items-center justify-between">
            <div className="flex items-center gap-2">
              <Shield className="h-7 w-7 text-primary" />
              <span className="text-lg font-bold">MT5 Router</span>
            </div>
            
            {/* Desktop navigation */}
            <div className="hidden sm:flex items-center gap-3">
              <Button variant="ghost" size="sm" onClick={scrollToPricing}>
                Pricing
              </Button>
              <Link to="/login">
                <Button variant="ghost" size="sm">
                  Log In
                </Button>
              </Link>
              <Link to="/register">
                <Button size="sm">
                  Get Started
                  <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </Link>
            </div>

            {/* Mobile menu button */}
            <Button
              variant="ghost"
              size="sm"
              className="sm:hidden"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            >
              {mobileMenuOpen ? (
                <X className="h-5 w-5" />
              ) : (
                <Menu className="h-5 w-5" />
              )}
            </Button>
          </div>

          {/* Mobile navigation */}
          {mobileMenuOpen && (
            <div className="sm:hidden py-4 border-t border-border/40">
              <div className="flex flex-col gap-2">
                <Button
                  variant="ghost"
                  className="justify-start"
                  onClick={() => {
                    scrollToPricing()
                    setMobileMenuOpen(false)
                  }}
                >
                  Pricing
                </Button>
                <Link to="/login" onClick={() => setMobileMenuOpen(false)}>
                  <Button variant="ghost" className="w-full justify-start">
                    Log In
                  </Button>
                </Link>
                <Link to="/register" onClick={() => setMobileMenuOpen(false)}>
                  <Button className="w-full">
                    Get Started
                    <ArrowRight className="ml-1 h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </div>
          )}
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative overflow-hidden pt-32 pb-20 sm:pt-40 sm:pb-28">
        {/* Background grid effect */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,hsl(var(--muted)/0.3)_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--muted)/0.3)_1px,transparent_1px)] bg-[size:4rem_4rem]" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,hsl(var(--primary)/0.12),transparent)]" />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <Badge variant="secondary" className="mb-6 px-3 py-1 text-sm">
              <Zap className="mr-1 h-3 w-3" />
              Built for serious traders
            </Badge>
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
              Cloud MT5 Infrastructure,{" "}
              <span className="text-primary">Simplified</span>
            </h1>
            <p className="mt-6 text-lg text-muted-foreground sm:text-xl">
              Deploy, manage, and monitor MetaTrader 5 instances across unlimited
              servers. Built for traders, funds, and prop firms.
            </p>
            <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
              <Link to="/register">
                <Button size="lg" className="w-full sm:w-auto text-base px-8">
                  Get Started Free
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
              <Button
                size="lg"
                variant="outline"
                className="w-full sm:w-auto text-base px-8"
                onClick={scrollToPricing}
              >
                View Pricing
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center mb-16">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Everything you need to run MT5 at scale
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              From single-account traders to multi-server prop firms, MT5 Router
              gives you the tools to operate efficiently.
            </p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => (
              <Card
                key={feature.title}
                className="group border-border/50 bg-card/50 transition-colors hover:border-primary/30 hover:bg-card"
              >
                <CardHeader>
                  <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                    <feature.icon className="h-5 w-5" />
                  </div>
                  <CardTitle className="text-lg">{feature.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {feature.description}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-20 sm:py-28 border-t border-border/40">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center mb-16">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Up and running in minutes
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Three steps from zero to a fully managed MT5 infrastructure.
            </p>
          </div>

          <div className="grid gap-8 md:grid-cols-3">
            {steps.map((step, index) => (
              <div key={step.step} className="relative">
                {index < steps.length - 1 && (
                  <div className="absolute top-8 left-full hidden w-full md:block">
                    <ChevronRight className="mx-auto h-5 w-5 text-muted-foreground/40" />
                  </div>
                )}
                <div className="text-center">
                  <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border-2 border-primary/20 bg-primary/5">
                    <span className="text-xl font-bold text-primary">
                      {step.step}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section
        id="pricing"
        className="py-20 sm:py-28 border-t border-border/40"
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center mb-12">
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Simple, transparent pricing
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Start free. Scale when you are ready. No hidden fees.
            </p>

            {/* Billing Toggle */}
            <div className="mt-8 inline-flex items-center rounded-full border border-border p-1 bg-muted/30">
              <button
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                  billingPeriod === "monthly"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setBillingPeriod("monthly")}
              >
                Monthly
              </button>
              <button
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                  billingPeriod === "yearly"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setBillingPeriod("yearly")}
              >
                Yearly
                <span className="ml-1 text-xs opacity-80">Save 20%</span>
              </button>
            </div>
          </div>

          {tiersError && (
            <div className="mx-auto max-w-md text-center">
              <Card className="border-border/50 bg-card/50">
                <CardContent className="pt-6">
                  <p className="text-muted-foreground">
                    Pricing information is currently unavailable. Please check
                    back later or contact us for details.
                  </p>
                  <Link to="/register" className="mt-4 inline-block">
                    <Button>Get Started Free</Button>
                  </Link>
                </CardContent>
              </Card>
            </div>
          )}

          {!tiers && !tiersError && (
            <div className="grid gap-6 md:grid-cols-3 mx-auto max-w-5xl">
              {[1, 2, 3].map((i) => (
                <Card key={i} className="border-border/50 bg-card/30 animate-pulse">
                  <CardContent className="pt-6">
                    <div className="h-6 w-20 rounded bg-muted mb-4" />
                    <div className="h-10 w-32 rounded bg-muted mb-6" />
                    <div className="space-y-3">
                      {[1, 2, 3, 4].map((j) => (
                        <div key={j} className="h-4 rounded bg-muted" />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {sortedTiers.length > 0 && (
            <div className="grid gap-6 md:grid-cols-3 mx-auto max-w-5xl">
              {sortedTiers.map((tier) => {
                const isPopular = tier.key === "basic"
                const price =
                  billingPeriod === "monthly"
                    ? tier.price_monthly
                    : tier.price_yearly
                const safePrice =
                  typeof price === "number" && Number.isFinite(price) ? price : 0
                const monthlyEquivalent =
                  billingPeriod === "yearly" && Number.isFinite(tier.price_yearly)
                    ? Math.round(tier.price_yearly / 12)
                    : null

                return (
                  <Card
                    key={tier.key}
                    className={`relative flex flex-col border-border/50 bg-card/50 transition-colors hover:border-primary/30 ${
                      isPopular ? "border-primary/50 shadow-lg shadow-primary/5" : ""
                    }`}
                  >
                    {isPopular && (
                      <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                        <Badge className="px-3 py-0.5">Most Popular</Badge>
                      </div>
                    )}
                    <CardHeader className="pb-4">
                      <CardTitle className="text-xl capitalize">
                        {tier.name}
                      </CardTitle>
                      <div className="mt-2">
                        <span className="text-4xl font-bold">
                          {safePrice === 0 ? "$0" : formatCents(safePrice)}
                        </span>
                        <span className="text-muted-foreground">
                          /{billingPeriod === "monthly" ? "mo" : "yr"}
                        </span>
                        {monthlyEquivalent !== null && safePrice > 0 && (
                          <p className="mt-1 text-sm text-muted-foreground">
                            {formatCents(monthlyEquivalent)}/mo billed yearly
                          </p>
                        )}
                      </div>
                    </CardHeader>
                    <CardContent className="flex flex-1 flex-col">
                      <div className="mb-4 space-y-2 text-sm text-muted-foreground">
                        <div className="flex items-center justify-between border-b border-border/30 pb-2">
                          <span>Servers</span>
                          <span className="font-medium text-foreground">
                            {tier.limits.max_servers === -1
                              ? "Unlimited"
                              : tier.limits.max_servers}
                          </span>
                        </div>
                        <div className="flex items-center justify-between border-b border-border/30 pb-2">
                          <span>Instances</span>
                          <span className="font-medium text-foreground">
                            {tier.limits.max_instances === -1
                              ? "Unlimited"
                              : tier.limits.max_instances}
                          </span>
                        </div>
                        <div className="flex items-center justify-between border-b border-border/30 pb-2">
                          <span>API Calls / Day</span>
                          <span className="font-medium text-foreground">
                            {tier.limits.max_api_calls_per_day === -1
                              ? "Unlimited"
                              : tier.limits.max_api_calls_per_day.toLocaleString()}
                          </span>
                        </div>
                        <div className="flex items-center justify-between pb-2">
                          <span>Support</span>
                          <span className="font-medium text-foreground capitalize">
                            {tier.limits.support_level}
                          </span>
                        </div>
                      </div>

                      <ul className="mb-6 flex-1 space-y-2">
                        {tier.features.map((feature) => (
                          <li
                            key={feature}
                            className="flex items-start gap-2 text-sm"
                          >
                            <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                            <span className="text-muted-foreground">
                              {feature}
                            </span>
                          </li>
                        ))}
                      </ul>

                      <Link to="/register" className="mt-auto">
                        <Button
                          className="w-full"
                          variant={isPopular ? "default" : "outline"}
                        >
                          {safePrice === 0 ? "Start Free" : "Get Started"}
                        </Button>
                      </Link>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 sm:py-28 border-t border-border/40">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center">
            <Globe className="mx-auto h-10 w-10 text-primary mb-6" />
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Ready to scale your trading?
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Join traders and prop firms managing their MT5 infrastructure with
              confidence.
            </p>
            <div className="mt-8">
              <Link to="/register">
                <Button size="lg" className="px-8 text-base">
                  Get Started Free
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border/40 py-10">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col items-center justify-between gap-6 sm:flex-row">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-primary" />
              <span className="font-semibold">MT5 Router</span>
            </div>
            <nav className="flex items-center gap-6 text-sm text-muted-foreground">
              <Link
                to="/login"
                className="transition-colors hover:text-foreground"
              >
                Login
              </Link>
              <Link
                to="/register"
                className="transition-colors hover:text-foreground"
              >
                Register
              </Link>
              <a
                href="/api/v1/docs"
                className="transition-colors hover:text-foreground"
                target="_blank"
                rel="noopener noreferrer"
              >
                API Docs
              </a>
            </nav>
            <p className="text-sm text-muted-foreground">
              &copy; {new Date().getFullYear()} MT5 Router. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}
