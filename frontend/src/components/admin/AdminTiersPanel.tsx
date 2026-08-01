import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { adminApi, TierConfig } from "@/api/admin"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Edit, Check, DollarSign } from "lucide-react"
import { formatCents } from "@/lib/utils"

export function AdminTiersPanel() {
  const queryClient = useQueryClient()
  const [editTier, setEditTier] = useState<(TierConfig & { key: string }) | null>(null)
  const [editForm, setEditForm] = useState({
    price_monthly: 0,
    price_yearly: 0,
    max_servers: 0,
    max_instances: 0,
    max_api_calls_per_day: 0,
    max_users: 0,
    support_level: "",
  })
  const [saveError, setSaveError] = useState<string | null>(null)

  const { data: tiers, isLoading } = useQuery({
    queryKey: ["admin-tiers"],
    queryFn: adminApi.getTiers,
  })

  const updateTier = useMutation({
    mutationFn: ({ name, data }: { name: string; data: Partial<TierConfig> }) =>
      adminApi.updateTier(name, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tiers"] })
      setEditTier(null)
      setSaveError(null)
    },
    onError: (e: Error) => setSaveError(e.message),
  })

  function openEdit(key: string, tier: TierConfig) {
    setEditTier({ ...tier, key })
    setSaveError(null)
    setEditForm({
      price_monthly: tier.price_monthly / 100,
      price_yearly: tier.price_yearly / 100,
      max_servers: tier.limits.max_servers,
      max_instances: tier.limits.max_instances,
      max_api_calls_per_day: tier.limits.max_api_calls_per_day,
      max_users: tier.limits.max_users,
      support_level: tier.limits.support_level,
    })
  }

  function handleSave() {
    if (!editTier) return
    updateTier.mutate({
      name: editTier.key,
      data: {
        price_monthly: Math.round(editForm.price_monthly * 100),
        price_yearly: Math.round(editForm.price_yearly * 100),
        limits: {
          max_servers: editForm.max_servers,
          max_instances: editForm.max_instances,
          max_api_calls_per_day: editForm.max_api_calls_per_day,
          max_users: editForm.max_users,
          support_level: editForm.support_level,
        },
      },
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-7 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-6 w-24" />
              </CardHeader>
              <CardContent className="space-y-3">
                <Skeleton className="h-8 w-20" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-8 w-16 mt-2" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  const tierEntries = tiers ? Object.entries(tiers) : []

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Tier Configuration</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {tierEntries.map(([key, tier]) => (
          <Card key={key}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-base capitalize">{tier.name}</CardTitle>
              <Button variant="outline" size="sm" onClick={() => openEdit(key, tier)}>
                <Edit className="h-3 w-3 mr-1" />
                Edit
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-bold">{formatCents(tier.price_monthly)}</span>
                  <span className="text-sm text-muted-foreground">/mo</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {formatCents(tier.price_yearly)}/yr (save{" "}
                  {Math.round((1 - tier.price_yearly / (tier.price_monthly * 12)) * 100)}%)
                </p>
              </div>

              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Servers</span>
                  <span className="font-medium">{tier.limits.max_servers}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Instances</span>
                  <span className="font-medium">{tier.limits.max_instances}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">API Calls/Day</span>
                  <span className="font-medium">
                    {tier.limits.max_api_calls_per_day.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Support</span>
                  <Badge variant="outline" className="text-xs capitalize">
                    {tier.limits.support_level}
                  </Badge>
                </div>
              </div>

              {tier.features.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    Features
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {tier.features.map((f) => (
                      <Badge key={f} variant="secondary" className="text-xs">
                        <Check className="h-3 w-3 mr-1" />
                        {f}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={!!editTier} onOpenChange={(open) => !open && setEditTier(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Tier: {editTier?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Monthly Price ($)</Label>
                <Input
                  type="number"
                  value={editForm.price_monthly}
                  onChange={(e) =>
                    setEditForm({ ...editForm, price_monthly: Number(e.target.value) })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Yearly Price ($)</Label>
                <Input
                  type="number"
                  value={editForm.price_yearly}
                  onChange={(e) =>
                    setEditForm({ ...editForm, price_yearly: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Max Servers</Label>
                <Input
                  type="number"
                  value={editForm.max_servers}
                  onChange={(e) =>
                    setEditForm({ ...editForm, max_servers: Number(e.target.value) })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Max Instances</Label>
                <Input
                  type="number"
                  value={editForm.max_instances}
                  onChange={(e) =>
                    setEditForm({ ...editForm, max_instances: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>API Calls/Day</Label>
                <Input
                  type="number"
                  value={editForm.max_api_calls_per_day}
                  onChange={(e) =>
                    setEditForm({ ...editForm, max_api_calls_per_day: Number(e.target.value) })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Support Level</Label>
                <select
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={editForm.support_level}
                  onChange={(e) =>
                    setEditForm({ ...editForm, support_level: e.target.value })
                  }
                >
                  <option value="community">Community</option>
                  <option value="email">Email</option>
                  <option value="priority">Priority</option>
                  <option value="dedicated">Dedicated</option>
                </select>
              </div>
            </div>
          </div>
          {saveError && <p className="text-sm text-destructive">{saveError}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTier(null)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={updateTier.isPending}>
              {updateTier.isPending ? "Saving..." : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
