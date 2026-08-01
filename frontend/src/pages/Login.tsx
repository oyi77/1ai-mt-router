import { useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { TwoFactorRequiredError } from "@/api/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { LogIn, Shield, ArrowLeft } from "lucide-react"

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [twoFactorCode, setTwoFactorCode] = useState("")
  const [requiresTwoFactor, setRequiresTwoFactor] = useState(false)
  const [error, setError] = useState("")
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsLoading(true)

    try {
      // AuthContext types login as (u, p) but the implementation accepts an
      // optional 2FA code — widen locally to surface the third argument.
      const loginWithCode = login as (
        username: string,
        password: string,
        twoFactorCode?: string
      ) => Promise<void>
      await loginWithCode(username, password, requiresTwoFactor ? twoFactorCode : undefined)
      const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname
      navigate(from ?? "/dashboard", { replace: true })
    } catch (err) {
      if (err instanceof TwoFactorRequiredError) {
        setRequiresTwoFactor(true)
      } else {
        setError(err instanceof Error ? err.message : "Invalid credentials")
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary">
            <Shield className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-2xl">MT5 Router</CardTitle>
          <CardDescription>Sign in to your dashboard</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {requiresTwoFactor && (
              <Alert>
                <AlertDescription>
                  Two-factor authentication is enabled on this account. Enter
                  the code from your authenticator app to continue.
                </AlertDescription>
              </Alert>
            )}
            
            <div className="space-y-2">
              <label htmlFor="username" className="text-sm font-medium">
                Username
              </label>
              <Input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                disabled={requiresTwoFactor}
                required
              />
            </div>
            
            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium">
                Password
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={requiresTwoFactor}
                required
              />
            </div>

            {requiresTwoFactor && (
              <div className="space-y-2">
                <label htmlFor="twoFactorCode" className="text-sm font-medium">
                  Authenticator Code
                </label>
                <Input
                  id="twoFactorCode"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={6}
                  autoComplete="one-time-code"
                  value={twoFactorCode}
                  onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, ""))}
                  placeholder="••••••"
                  autoFocus
                  required
                />
              </div>
            )}
            
            <Button type="submit" className="w-full" disabled={isLoading}>
              <LogIn className="mr-2 h-4 w-4" />
              {isLoading ? "Signing in..." : requiresTwoFactor ? "Verify" : "Sign In"}
            </Button>
          </form>
          
          <div className="mt-6 space-y-2 text-center text-sm">
            <p className="text-muted-foreground">
              Don't have an account?{" "}
              <Link to="/register" className="text-primary hover:underline font-medium">
                Sign up
              </Link>
            </p>
            <p>
              <Link
                to="/"
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 transition-colors"
              >
                <ArrowLeft className="h-3 w-3" />
                Back to home
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
