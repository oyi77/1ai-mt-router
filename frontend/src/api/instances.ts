import { api } from './client'

export interface Instance {
  id: string
  name: string
  status: 'running' | 'stopped' | 'restarting' | 'created' | 'exited' | 'paused' | 'dead'
  image: string
  created: string
  rpyc_port: string | null
  vnc_port: string | null
  labels: Record<string, string>
}

export interface InstanceStats {
  cpu_percent: number
  memory_usage_mb: number
  memory_limit_mb: number
  memory_percent: number
  network_rx: number
  network_tx: number
}

export const instancesApi = {
  list: () => api.get<Instance[]>('/instances'),
  
  get: (id: string) => api.get<Instance>(`/instances/${id}`),
  
  create: () => api.post<Instance>('/instances'),
  
  start: (id: string) => api.post<{ status: string }>(`/instances/${id}/start`),
  
  stop: (id: string) => api.post<{ status: string }>(`/instances/${id}/stop`),
  
  restart: (id: string) => api.post<{ status: string }>(`/instances/${id}/restart`),
  
  delete: (id: string) => api.delete<{ status: string }>(`/instances/${id}`),
  
  getLogs: (id: string, lines = 100) =>
    api.get<{ logs: string[] }>(`/instances/${id}/logs?lines=${lines}`),
  
  getStats: (id: string) => api.get<InstanceStats>(`/instances/${id}/stats`),
}
