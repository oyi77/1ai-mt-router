import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { instancesApi } from "@/api/instances"
import { tradingApi } from "@/api/trading"
import { serversApi } from "@/api/servers"
import { useMetrics } from "@/hooks/useMetrics"
import { MetricsCard } from "@/components/dashboard/MetricsCard"
import { InstanceCard } from "@/components/dashboard/InstanceCard"
import { InstanceMetricsChart } from "@/components/dashboard/InstanceMetricsChart"
import { MetricsPanel } from "@/components/dashboard/MetricsPanel"
import { AccountCard } from "@/components/trading/AccountCard"
import { PositionsTable } from "@/components/trading/PositionsTable"
import { VNCViewer } from "@/components/vnc/VNCViewer"
import { NotificationsPanel } from "@/components/notifications/NotificationsPanel"
import { ServersPanel } from "@/components/servers/ServersPanel"
import { BillingPanel } from "@/components/billing/BillingPanel"
import { AccountsPanel } from "@/components/accounts/AccountsPanel"
import { StatisticsPanel } from "@/components/statistics/StatisticsPanel"
import { WebhooksPanel } from "@/components/webhooks/WebhooksPanel"
import { AdminUsersPanel } from "@/components/admin/AdminUsersPanel"
import { AdminTiersPanel } from "@/components/admin/AdminTiersPanel"
import { AdminAnalyticsPanel } from "@/components/admin/AdminAnalyticsPanel"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { AlertDialog } from "@/components/ui/alert-dialog"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Server, Plus, RefreshCw, Activity, Wallet, Monitor,
  LogOut, Bell, CreditCard, Key, BarChart3, Webhook,
  Shield, Globe, Users, DollarSign, TrendingUp
} from "lucide-react"
import { useAuth } from "@/context/AuthContext"

function MetricsCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-4" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-16 mb-1" />
        <Skeleton className="h-3 w-20" />
      </CardContent>
    </Card>
  )
}

function InstanceCardSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Skeleton className="h-3 w-3 rounded-full" />
            <Skeleton className="h-5 w-32" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-3">
          <div>
            <div className="flex justify-between mb-1">
              <Skeleton className="h-4 w-8" />
              <Skeleton className="h-4 w-12" />
            </div>
            <Skeleton className="h-2 w-full" />
          </div>
          <div>
            <div className="flex justify-between mb-1">
              <Skeleton className="h-4 w-12" />
              <Skeleton className="h-4 w-20" />
            </div>
            <Skeleton className="h-2 w-full" />
          </div>
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-8 w-14" />
          <Skeleton className="h-8 w-14" />
        </div>
      </CardContent>
    </Card>
  )
}

export function Dashboard() {
  const { user, logout } = useAuth()
  const queryClient = useQueryClient()
  const [selectedInstance, setSelectedInstance] = useState<string | null>(null)
  const [expandedInstance, setExpandedInstance] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState("instances")
  const { systemMetrics, instanceMetrics, isLoading: metricsLoading } = useMetrics()

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  // Logs modal
  const [logsTarget, setLogsTarget] = useState<{ id: string; name: string } | null>(null)

  const isAdmin = user?.role === "admin"

  // Queries
  const { data: instances = [], isLoading: instancesLoading, refetch: refetchInstances } = useQuery({
    queryKey: ['instances'],
    queryFn: instancesApi.list,
  })

  const { data: servers = [] } = useQuery({
    queryKey: ['servers'],
    queryFn: serversApi.list,
  })

  const { data: account } = useQuery({
    queryKey: ['account', selectedInstance],
    queryFn: () => tradingApi.getAccount(selectedInstance!),
    enabled: !!selectedInstance,
    refetchInterval: 5000,
  })

  const { data: positions = [] } = useQuery({
    queryKey: ['positions', selectedInstance],
    queryFn: () => tradingApi.getPositions(selectedInstance!),
    enabled: !!selectedInstance,
    refetchInterval: 3000,
  })

  const { data: instanceLogs } = useQuery({
    queryKey: ['logs', logsTarget?.id],
    queryFn: () => instancesApi.getLogs(logsTarget!.id, 200),
    enabled: !!logsTarget,
    refetchInterval: 5000,
  })

  // Mutations
  const createInstance = useMutation({
    mutationFn: instancesApi.create,
    onSuccess: () => refetchInstances(),
  })

  const startInstance = useMutation({
    mutationFn: instancesApi.start,
    onSuccess: () => { refetchInstances() },
  })

  const stopInstance = useMutation({
    mutationFn: instancesApi.stop,
    onSuccess: () => { refetchInstances() },
  })

  const restartInstance = useMutation({
    mutationFn: instancesApi.restart,
    onSuccess: () => { refetchInstances() },
  })

  const deleteInstance = useMutation({
    mutationFn: instancesApi.delete,
    onSuccess: () => {
      refetchInstances()
      setDeleteTarget(null)
    },
  })

  const closePosition = useMutation({
    mutationFn: (ticket: number) => tradingApi.closePosition(selectedInstance!, ticket),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['positions', selectedInstance] }),
  })

  const modifyPosition = useMutation({
    mutationFn: ({ ticket, sl, tp }: { ticket: number; sl: number | null; tp: number | null }) =>
      tradingApi.modifyPosition(selectedInstance!, ticket, { sl, tp }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['positions', selectedInstance] }),
  })

  const partialClosePosition = useMutation({
    mutationFn: ({ ticket, volume }: { ticket: number; volume: number }) =>
      tradingApi.partialClosePosition(selectedInstance!, ticket, volume),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['positions', selectedInstance] }),
  })

  const runningInstances = instances.filter(i => i.status === 'running')
  const connectedServers = servers.length + 1 // +1 for local server

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card">
        <div className="container mx-auto px-4 py-3 sm:py-4">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2 sm:gap-3">
              <div className="flex h-8 w-8 sm:h-10 sm:w-10 items-center justify-center rounded-lg bg-primary">
                <Activity className="h-4 w-4 sm:h-5 sm:w-5 text-primary-foreground" />
              </div>
              <div>
                <h1 className="text-lg sm:text-xl font-bold">MT5 Router</h1>
                <p className="text-xs sm:text-sm text-muted-foreground hidden sm:block">Trading Dashboard</p>
              </div>
            </div>

            <div className="flex items-center gap-2 sm:gap-4">
              <div className="flex items-center gap-1 sm:gap-2">
                {isAdmin && (
                  <Badge variant="outline" className="gap-1 text-xs">
                    <Shield className="h-3 w-3" />
                    Admin
                  </Badge>
                )}
                <span className="text-xs sm:text-sm text-muted-foreground max-w-[100px] sm:max-w-none truncate">
                  {user?.username}
                </span>
              </div>
              <Button variant="outline" size="sm" onClick={logout} className="h-8 sm:h-9">
                <LogOut className="h-3 w-3 sm:h-4 sm:w-4 sm:mr-2" />
                <span className="hidden sm:inline">Logout</span>
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-6">
        {/* Overview Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
          {metricsLoading ? (
            <>
              <MetricsCardSkeleton />
              <MetricsCardSkeleton />
              <MetricsCardSkeleton />
              <MetricsCardSkeleton />
              <MetricsCardSkeleton />
            </>
          ) : (
            <>
              <MetricsCard
                title="Total Instances"
                value={instances.length}
                subtitle={`${runningInstances.length} running`}
                icon={Server}
              />
              <MetricsCard
                title="Servers Connected"
                value={connectedServers}
                subtitle={`${servers.length} remote + 1 local`}
                icon={Globe}
              />
              <MetricsCard
                title="System CPU"
                value={systemMetrics ? `${systemMetrics.cpu_percent.toFixed(1)}%` : "N/A"}
                icon={Activity}
                progress={systemMetrics?.cpu_percent}
              />
              <MetricsCard
                title="Memory"
                value={systemMetrics ? `${systemMetrics.memory.percent.toFixed(1)}%` : "N/A"}
                icon={Server}
                progress={systemMetrics?.memory.percent}
              />
              <MetricsCard
                title="Open Positions"
                value={positions.length}
                subtitle={selectedInstance ? `$${positions.reduce((sum, p) => sum + p.profit, 0).toFixed(2)}` : "Select instance"}
                icon={Wallet}
              />
            </>
          )}
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <div className="overflow-x-auto -mx-4 px-4 mb-4">
            <TabsList className="mb-0">
            <TabsTrigger value="instances">
              <Server className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Instances</span>
            </TabsTrigger>
            <TabsTrigger value="trading">
              <Wallet className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Trading</span>
            </TabsTrigger>
            <TabsTrigger value="vnc">
              <Monitor className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">VNC</span>
            </TabsTrigger>
            <TabsTrigger value="monitoring">
              <Activity className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Monitoring</span>
            </TabsTrigger>
            <TabsTrigger value="notifications">
              <Bell className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Notifications</span>
            </TabsTrigger>
            <TabsTrigger value="servers">
              <Server className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Servers</span>
            </TabsTrigger>
            {isAdmin && (
              <TabsTrigger value="billing">
                <CreditCard className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Billing</span>
              </TabsTrigger>
            )}
            <TabsTrigger value="accounts">
              <Key className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Accounts</span>
            </TabsTrigger>
            <TabsTrigger value="statistics">
              <BarChart3 className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Statistics</span>
            </TabsTrigger>
            {isAdmin && (
              <TabsTrigger value="webhooks">
                <Webhook className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Webhooks</span>
              </TabsTrigger>
            )}
            {isAdmin && (
              <TabsTrigger value="admin-users">
                <Users className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Users</span>
              </TabsTrigger>
            )}
            {isAdmin && (
              <TabsTrigger value="admin-tiers">
                <DollarSign className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Tiers</span>
              </TabsTrigger>
            )}
            {isAdmin && (
              <TabsTrigger value="admin-analytics">
                <TrendingUp className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Analytics</span>
              </TabsTrigger>
            )}
          </TabsList>
          </div>

          <TabsContent value="instances">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">MT5 Instances</h2>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => refetchInstances()}>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Refresh
                </Button>
                <Button size="sm" onClick={() => createInstance.mutate()} disabled={createInstance.isPending}>
                  <Plus className="h-4 w-4 mr-2" />
                  {createInstance.isPending ? "Creating..." : "New Instance"}
                </Button>
              </div>
            </div>

            {instancesLoading ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <InstanceCardSkeleton />
                <InstanceCardSkeleton />
              </div>
            ) : instances.length === 0 ? (
              <div className="text-center py-12 border rounded-lg">
                <Server className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <p className="text-muted-foreground">No MT5 instances</p>
                <Button className="mt-4" onClick={() => createInstance.mutate()} disabled={createInstance.isPending}>
                  <Plus className="h-4 w-4 mr-2" />
                  Create Instance
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {instances.map((instance) => (
                  <div key={instance.id} className="space-y-0">
                    <InstanceCard
                      instance={instance}
                      isActionLoading={
                        startInstance.isPending || stopInstance.isPending ||
                        restartInstance.isPending || deleteInstance.isPending
                      }
                      onStart={() => startInstance.mutate(instance.id)}
                      onStop={() => stopInstance.mutate(instance.id)}
                      onRestart={() => restartInstance.mutate(instance.id)}
                      onDelete={() => setDeleteTarget({ id: instance.id, name: instance.name })}
                      onVNC={() => {
                        setSelectedInstance(instance.id)
                        setActiveTab("vnc")
                      }}
                      onLogs={() => setLogsTarget({ id: instance.id, name: instance.name })}
                      className={expandedInstance === instance.id ? "rounded-b-none border-b-0" : "cursor-pointer"}
                      onClick={() => setExpandedInstance(expandedInstance === instance.id ? null : instance.id)}
                    />
                    {expandedInstance === instance.id && (
                      <Card className="rounded-t-none border-t-0">
                        <CardContent className="pt-2 pb-4">
                          <InstanceMetricsChart instanceId={instance.id} />
                        </CardContent>
                      </Card>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="trading">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Trading</h2>
                {runningInstances.length > 0 && (
                  <select
                    className="rounded-md border bg-background px-3 py-2 text-sm"
                    value={selectedInstance || ""}
                    onChange={(e) => setSelectedInstance(e.target.value || null)}
                  >
                    <option value="">Select instance...</option>
                    {runningInstances.map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </select>
                )}
              </div>

              {!selectedInstance ? (
                <div className="text-center py-12 border rounded-lg">
                  <Wallet className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                  <p className="text-muted-foreground">Select a running instance to view trading data</p>
                </div>
              ) : (
                <>
                  <AccountCard account={account || null} />
                  <PositionsTable
                    positions={positions}
                    currency={account?.currency}
                    onClosePosition={(ticket) => closePosition.mutate(ticket)}
                    onModifyPosition={(ticket, sl, tp) => modifyPosition.mutate({ ticket, sl, tp })}
                    onPartialClose={(ticket, volume) => partialClosePosition.mutate({ ticket, volume })}
                    isLoading={closePosition.isPending || modifyPosition.isPending || partialClosePosition.isPending}
                  />
                </>
              )}
            </div>
          </TabsContent>

          <TabsContent value="vnc">
            {selectedInstance ? (
              <VNCViewer
                instanceId={selectedInstance}
                vncPort={instances.find(i => i.id === selectedInstance)?.vnc_port}
              />
            ) : (
              <div className="text-center py-12 border rounded-lg">
                <Monitor className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <p className="text-muted-foreground">Select an instance to view VNC</p>
                {runningInstances.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2 justify-center">
                    {runningInstances.map((i) => (
                      <Button key={i.id} variant="outline" size="sm" onClick={() => setSelectedInstance(i.id)}>
                        {i.name}
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </TabsContent>

          <TabsContent value="monitoring">
            <MetricsPanel
              systemMetrics={systemMetrics}
              instanceMetrics={instanceMetrics}
            />
          </TabsContent>

          <TabsContent value="notifications">
            <NotificationsPanel />
          </TabsContent>

          <TabsContent value="servers">
            <ServersPanel />
          </TabsContent>

          {isAdmin && (
            <TabsContent value="billing">
              <BillingPanel />
            </TabsContent>
          )}

          <TabsContent value="accounts">
            <AccountsPanel />
          </TabsContent>

          <TabsContent value="statistics">
            <StatisticsPanel instanceId={selectedInstance || ''} />
          </TabsContent>

          {isAdmin && (
            <TabsContent value="webhooks">
              <WebhooksPanel />
            </TabsContent>
          )}

          {isAdmin && (
            <TabsContent value="admin-users">
              <AdminUsersPanel />
            </TabsContent>
          )}

          {isAdmin && (
            <TabsContent value="admin-tiers">
              <AdminTiersPanel />
            </TabsContent>
          )}

          {isAdmin && (
            <TabsContent value="admin-analytics">
              <AdminAnalyticsPanel />
            </TabsContent>
          )}
        </Tabs>
      </main>

      {/* Delete Confirmation Dialog */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete Instance"
        description={`Are you sure you want to delete "${deleteTarget?.name}"? This action cannot be undone and all data will be lost.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteTarget && deleteInstance.mutate(deleteTarget.id)}
        isLoading={deleteInstance.isPending}
      />

      {/* Logs Modal */}
      <Dialog open={!!logsTarget} onOpenChange={(open) => !open && setLogsTarget(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Logs - {logsTarget?.name}</DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-auto bg-black rounded-md p-4 min-h-[300px]">
            {instanceLogs?.logs ? (
              <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap">
                {instanceLogs.logs.join("\n")}
              </pre>
            ) : (
              <div className="flex items-center justify-center h-full">
                <p className="text-muted-foreground text-sm">Loading logs...</p>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
