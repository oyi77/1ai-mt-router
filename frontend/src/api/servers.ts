import { api } from './client'

export interface SSHServer {
  id: number
  name: string
  host: string
  port: number
  username: string
  use_key_auth: boolean
  is_active: boolean
  health_status: 'healthy' | 'unhealthy' | 'offline' | 'unknown'
  last_health_check: string | null
  created_at: string
}

export interface ServerHealth {
  server_id: number
  status: string
  metrics: {
    cpu_percent: number
    memory: { total: number; used: number; percent: number }
    disk: { total: string; used: string; percent: number }
    containers: Array<{ name: string; status: string }>
    containers_total: number
    containers_running: number
  } | null
  instances: Array<{
    id: string
    name: string
    status: string
    rpyc_port: number | null
    vnc_port: number | null
  }>
  checked_at: string
}

export interface ServerCreate {
  name: string
  host: string
  port?: number
  username: string
  private_key?: string
  password?: string
  use_key_auth: boolean
}

export interface ServerInstance {
  id: string
  name: string
  server: string
  status: string
  rpyc_port: number | null
  vnc_port: number | null
}

export const serversApi = {
  // Local server health
  localHealth: () => api.get<ServerHealth>('/servers/local/health'),

  // Server CRUD
  list: () => api.get<SSHServer[]>('/servers'),
  
  get: (id: number) => api.get<SSHServer>(`/servers/${id}`),
  
  create: (data: ServerCreate) => api.post<SSHServer>('/servers', data),
  
  update: (id: number, data: Partial<ServerCreate>) => api.put(`/servers/${id}`, data),
  
  delete: (id: number) => api.delete(`/servers/${id}`),
  
  // Health & Metrics
  checkHealth: (id: number) => api.post<ServerHealth>(`/servers/${id}/health`),
  
  // Server Instances
  listInstances: (serverId: number) => api.get<ServerInstance[]>(`/servers/${serverId}/instances`),
  
  createInstance: (serverId: number, data: { name?: string; image?: string }) =>
    api.post<ServerInstance>(`/servers/${serverId}/instances`, data),
  
  controlInstance: (serverId: number, instanceName: string, action: 'start' | 'stop' | 'restart' | 'delete') =>
    api.post(`/servers/${serverId}/instances/${instanceName}/${action}`),
  
  getInstanceLogs: (serverId: number, instanceName: string, lines: number = 100) =>
    api.get<{ logs: string[] }>(`/servers/${serverId}/instances/${instanceName}/logs?lines=${lines}`),
}
