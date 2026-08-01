import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { serversApi, ServerHealth, SSHServer } from '@/api/servers'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AlertDialog } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  Server, Plus, RefreshCw, Trash2, Activity,
  Cpu, HardDrive, MemoryStick, ChevronDown, ChevronUp, Home
} from 'lucide-react'
import { ServerMetricsChart } from '@/components/servers/ServerMetricsChart'
import { cn } from '@/lib/utils'

export function ServersPanel() {
  const queryClient = useQueryClient()
  const [showAddForm, setShowAddForm] = useState(false)
  const [expandedServer, setExpandedServer] = useState<number | null>(null)
  const [localExpanded, setLocalExpanded] = useState(true)
  const [newServer, setNewServer] = useState({
    name: '',
    host: '',
    port: 22,
    username: 'root',
    private_key: '',
    password: '',
    use_key_auth: true
  })
  const [actionError, setActionError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SSHServer | null>(null)

  const { data: servers = [], isLoading } = useQuery({
    queryKey: ['servers'],
    queryFn: serversApi.list,
  })

  const { data: localHealth, isLoading: localLoading, refetch: refetchLocal } = useQuery({
    queryKey: ['localServerHealth'],
    queryFn: serversApi.localHealth,
    refetchInterval: 30000,
  })

  const createServer = useMutation({
    mutationFn: serversApi.create,
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      setShowAddForm(false)
      setNewServer({ name: '', host: '', port: 22, username: 'root', private_key: '', password: '', use_key_auth: true })
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const deleteServer = useMutation({
    mutationFn: serversApi.delete,
    onSuccess: () => {
      setActionError(null)
      setDeleteTarget(null)
      queryClient.invalidateQueries({ queryKey: ['servers'] })
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const checkHealth = useMutation({
    mutationFn: serversApi.checkHealth,
  })

  const healthData = useQuery({
    queryKey: ['serverHealth'],
    queryFn: async () => {
      const results: Record<number, ServerHealth> = {}
      for (const server of servers) {
        try {
          results[server.id] = await serversApi.checkHealth(server.id)
        } catch (e) {
          results[server.id] = { server_id: server.id, status: 'error', metrics: null, instances: [], checked_at: new Date().toISOString() } as ServerHealth
        }
      }
      return results
    },
    enabled: servers.length > 0,
    refetchInterval: 30000,
  })

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'success'
      case 'unhealthy': return 'warning'
      case 'offline': return 'destructive'
      default: return 'secondary'
    }
  }

  const totalServers = servers.length + 1

  return (
    <div className="space-y-4">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            Servers ({totalServers})
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['serverHealth'] })
              refetchLocal()
            }}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <Button size="sm" onClick={() => { setActionError(null); setShowAddForm(!showAddForm) }}>
              <Plus className="h-4 w-4 mr-2" />
              Add Server
            </Button>
          </div>
        </CardHeader>
      </Card>

      {showAddForm && (
        <Card>
          <CardHeader>
            <CardTitle>Add SSH Server</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium">Name</label>
                <Input placeholder="My VPS 1" value={newServer.name} onChange={e => setNewServer({...newServer, name: e.target.value})} />
              </div>
              <div>
                <label className="text-sm font-medium">Host</label>
                <Input placeholder="192.168.1.100" value={newServer.host} onChange={e => setNewServer({...newServer, host: e.target.value})} />
              </div>
              <div>
                <label className="text-sm font-medium">Port</label>
                <Input type="number" placeholder="22" value={newServer.port} onChange={e => setNewServer({...newServer, port: parseInt(e.target.value)})} />
              </div>
              <div>
                <label className="text-sm font-medium">Username</label>
                <Input placeholder="root" value={newServer.username} onChange={e => setNewServer({...newServer, username: e.target.value})} />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex gap-4">
                <label className="flex items-center gap-2">
                  <input type="radio" checked={newServer.use_key_auth} onChange={() => setNewServer({...newServer, use_key_auth: true})} />
                  SSH Key
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" checked={!newServer.use_key_auth} onChange={() => setNewServer({...newServer, use_key_auth: false})} />
                  Password
                </label>
              </div>

              {newServer.use_key_auth ? (
                <div>
                  <label className="text-sm font-medium">Private Key</label>
                  <textarea
                    className="w-full h-32 p-2 border rounded-md bg-background font-mono text-sm"
                    placeholder="-----BEGIN RSA PRIVATE KEY-----..."
                    value={newServer.private_key}
                    onChange={e => setNewServer({...newServer, private_key: e.target.value})}
                  />
                </div>
              ) : (
                <div>
                  <label className="text-sm font-medium">Password</label>
                  <Input type="password" value={newServer.password} onChange={e => setNewServer({...newServer, password: e.target.value})} />
                </div>
              )}
            </div>

            <div className="flex gap-2 justify-end">
              <Button variant="outline" onClick={() => setShowAddForm(false)}>Cancel</Button>
              <Button
                onClick={() => createServer.mutate(newServer)}
                disabled={!newServer.name || !newServer.host || !newServer.username}
              >
                Add Server
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Local Server - always shown */}
      <Card className="border-green-500/30">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse" />
              <div className="flex items-center gap-2">
                <Home className="h-4 w-4 text-muted-foreground" />
                <CardTitle className="text-lg">Local Server</CardTitle>
              </div>
              <p className="text-sm text-muted-foreground">Docker socket</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="success">healthy</Badge>
              <Button size="sm" variant="outline" onClick={() => refetchLocal()}>
                <Activity className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="outline" onClick={() => setLocalExpanded(!localExpanded)}>
                {localExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </CardHeader>

        {localExpanded && localHealth?.metrics && (
          <CardContent className="pt-0 border-t">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <Cpu className="h-4 w-4" />
                  <span>CPU</span>
                  <span className="ml-auto font-mono">{localHealth.metrics.cpu_percent}%</span>
                </div>
                <Progress value={localHealth.metrics.cpu_percent} />
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <MemoryStick className="h-4 w-4" />
                  <span>Memory</span>
                  <span className="ml-auto font-mono">{localHealth.metrics.memory?.percent}%</span>
                </div>
                <Progress value={localHealth.metrics.memory?.percent} />
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm">
                  <HardDrive className="h-4 w-4" />
                  <span>Disk</span>
                  <span className="ml-auto font-mono">{localHealth.metrics.disk?.percent}%</span>
                </div>
                <Progress value={localHealth.metrics.disk?.percent} />
              </div>
            </div>

            {localHealth.instances && localHealth.instances.length > 0 && (
              <div className="mt-4">
                <h4 className="text-sm font-medium mb-2">MT5 Instances ({localHealth.instances.length})</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {localHealth.instances.map((instance) => (
                    <div key={instance.id} className="flex items-center justify-between p-2 border rounded">
                      <span className="text-sm truncate">{instance.name}</span>
                      <Badge variant={instance.status === 'running' ? 'success' : 'secondary'} className="text-xs">
                        {instance.status === 'running' ? 'Running' : 'Stopped'}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(!localHealth.instances || localHealth.instances.length === 0) && (
              <div className="mt-4 text-sm text-muted-foreground text-center py-4">
                No MT5 instances on local server
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Remote SSH Servers */}
      {servers.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-sm font-medium text-muted-foreground px-1">Remote SSH Servers</h3>
          <div className="space-y-4">
            {servers.map((server) => {
              const health = healthData.data?.[server.id]
              const isExpanded = expandedServer === server.id

              return (
                <Card key={server.id} className={cn(
                  "transition-all",
                  server.health_status === 'healthy' && "border-green-500/30",
                  server.health_status === 'unhealthy' && "border-yellow-500/30",
                  server.health_status === 'offline' && "border-red-500/30"
                )}>
                  <CardHeader className="pb-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          "w-3 h-3 rounded-full shrink-0",
                          server.health_status === 'healthy' && "bg-green-500 animate-pulse",
                          server.health_status === 'unhealthy' && "bg-yellow-500",
                          server.health_status === 'offline' && "bg-red-500",
                          server.health_status === 'unknown' && "bg-gray-500"
                        )} />
                        <div>
                          <CardTitle className="text-lg">{server.name}</CardTitle>
                          <p className="text-sm text-muted-foreground">{server.username}@{server.host}:{server.port}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant={getStatusColor(server.health_status)}>
                          {server.health_status}
                        </Badge>
                        <Button size="sm" variant="outline" onClick={() => checkHealth.mutate(server.id)}>
                          <Activity className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => setExpandedServer(isExpanded ? null : server.id)}>
                          {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                        </Button>
                        <Button size="sm" variant="destructive" onClick={() => { setActionError(null); setDeleteTarget(server) }}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardHeader>

                  {isExpanded && health?.metrics && (
                    <CardContent className="pt-0 border-t">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-sm">
                            <Cpu className="h-4 w-4" />
                            <span>CPU</span>
                            <span className="ml-auto font-mono">{health.metrics.cpu_percent}%</span>
                          </div>
                          <Progress value={health.metrics.cpu_percent} />
                        </div>
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-sm">
                            <MemoryStick className="h-4 w-4" />
                            <span>Memory</span>
                            <span className="ml-auto font-mono">{health.metrics.memory?.percent}%</span>
                          </div>
                          <Progress value={health.metrics.memory?.percent} />
                        </div>
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-sm">
                            <HardDrive className="h-4 w-4" />
                            <span>Disk</span>
                            <span className="ml-auto font-mono">{health.metrics.disk?.percent}%</span>
                          </div>
                          <Progress value={health.metrics.disk?.percent} />
                        </div>
                      </div>

                      {health.instances && health.instances.length > 0 && (
                        <div className="mt-4">
                          <h4 className="text-sm font-medium mb-2">MT5 Instances ({health.instances.length})</h4>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {health.instances.map((instance) => (
                              <div key={instance.id} className="flex items-center justify-between p-2 border rounded">
                                <span className="text-sm truncate">{instance.name}</span>
                                <Badge variant={instance.status.includes('Up') ? 'success' : 'secondary'} className="text-xs">
                                  {instance.status.includes('Up') ? 'Running' : 'Stopped'}
                                </Badge>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="mt-4 border-t pt-2">
                        <h4 className="text-sm font-medium mb-1">Metrics History</h4>
                        <ServerMetricsChart serverId={server.id} />
                      </div>
                    </CardContent>
                  )}
                </Card>
              )
            })}
          </div>
        </div>
      )}

      {/* Empty state for remote servers */}
      {!isLoading && servers.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center">
            <Server className="h-8 w-8 mx-auto text-muted-foreground mb-3" />
            <p className="text-sm text-muted-foreground">No remote SSH servers configured</p>
            <p className="text-xs text-muted-foreground mt-1">Add a remote VPS to manage MT5 instances on other machines</p>
            <Button className="mt-4" size="sm" onClick={() => setShowAddForm(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add Remote Server
            </Button>
          </CardContent>
        </Card>
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete Server"
        description={deleteTarget ? `Delete "${deleteTarget.name}"?` : ''}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteTarget && deleteServer.mutate(deleteTarget.id)}
        isLoading={deleteServer.isPending}
      />
    </div>
  )
}
