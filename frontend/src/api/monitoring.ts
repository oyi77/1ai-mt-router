import { api, getToken } from './client'

export interface ServerMetricsHistory {
  id: number
  server_id: number
  cpu_percent: number
  memory_total_mb: number
  memory_used_mb: number
  disk_total_gb: number
  disk_used_gb: number
  docker_containers_total: number
  docker_containers_running: number
  recorded_at: string
}

export interface InstanceMetricsHistory {
  id: number
  instance_id: string
  instance_name: string
  cpu_percent: number
  memory_usage_mb: number
  memory_limit_mb: number
  memory_percent: number
  network_rx_mb: number
  network_tx_mb: number
  recorded_at: string
}

export interface SystemMetrics {
  cpu_percent: number
  memory: {
    total: number
    available: number
    percent: number
    used: number
  }
  disk: {
    total: number
    used: number
    free: number
    percent: number
  }
  timestamp: string
}

export interface InstanceMetric {
  id: string
  name: string
  status: string
  cpu_percent: number
  memory_usage_mb: number
  memory_limit_mb: number
  memory_percent: number
}

export interface Alert {
  // Backend alert ids are the triggering rule id (string), not a numeric row id.
  id: string
  type: string
  message: string
  severity: 'info' | 'warning' | 'critical'
  instance_id: string | null
  acknowledged: boolean
  created_at: string
}

export const monitoringApi = {
  getSystemMetrics: () => api.get<SystemMetrics>('/monitoring/system'),
  
  getInstanceMetrics: () => api.get<InstanceMetric[]>('/monitoring/instances'),
  
  getAlerts: () => api.get<{ alerts: Alert[]; count: number }>('/monitoring/alerts'),
  
  getServerMetricsHistory: (serverId: number, hours = 24) =>
    api.get<ServerMetricsHistory[]>(`/monitoring/servers/${serverId}/metrics?hours=${hours}`),

  getInstanceMetricsHistory: (instanceId: string, hours = 24) =>
    api.get<InstanceMetricsHistory[]>(`/monitoring/instances/${instanceId}/metrics?hours=${hours}`),

  connectMetricsStream: (onMessage: (data: any) => void) => {
    // Backend reads ?token= first, else Bearer; missing token closes with 4401.
    const token = getToken()
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/api/v1/monitoring/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`
    const ws = new WebSocket(url)
    ws.onmessage = (event) => {
      onMessage(JSON.parse(event.data))
    }
    return ws
  },
}
