import { api } from './client'

export interface AccountInfo {
  login: number
  balance: number
  equity: number
  margin: number
  free_margin: number
  margin_level: number
  currency: string
  leverage: number
  server: string
  name: string
}

export interface Position {
  ticket: number
  symbol: string
  type: 'BUY' | 'SELL'
  volume: number
  open_price: number
  current_price: number
  sl: number | null
  tp: number | null
  profit: number
  swap: number
  commission: number
  comment: string
  time: string
}

export interface Order {
  ticket: number
  symbol: string
  type: string
  volume: number
  price: number
  sl: number | null
  tp: number | null
  magic: number
  comment: string
  time_setup: string
}

export interface OrderRequest {
  symbol: string
  order_type: string
  volume: number
  price?: number
  sl?: number
  tp?: number
  magic?: number
  comment?: string
}

export interface SymbolInfo {
  name: string
  point: number
  digits: number
  spread: number
  bid: number | null
  ask: number | null
  volume_min: number
  volume_max: number
  volume_step: number
  trade_allowed: boolean
}

export interface ModifyPositionRequest {
  sl?: number | null
  tp?: number | null
}

export interface PartialCloseRequest {
  volume: number
}

export interface PartialCloseResult {
  ticket: number
  closed_volume: number
  remaining_volume: number
  price: number
  status: string
}

export interface CandleData {
  time: string
  open: number
  high: number
  low: number
  close: number
  tick_volume: number
  spread: number
}

export interface OrderBookLevel {
  type: 'buy' | 'sell'
  price: number
  volume: number
  count: number
}

export interface OrderBookData {
  symbol: string
  timestamp: string
  bids: OrderBookLevel[]
  asks: OrderBookLevel[]
}

export const tradingApi = {
  getAccount: (instanceId: string) =>
    api.get<AccountInfo>(`/trading/account?instance_id=${instanceId}`),
  
  getPositions: (instanceId: string, symbol?: string) =>
    api.get<Position[]>(`/trading/positions?instance_id=${instanceId}${symbol ? `&symbol=${symbol}` : ''}`),
  
  getOrders: (instanceId: string, symbol?: string) =>
    api.get<Order[]>(`/trading/orders?instance_id=${instanceId}${symbol ? `&symbol=${symbol}` : ''}`),
  
  placeOrder: (instanceId: string, order: OrderRequest) =>
    api.post<Order>(`/trading/orders?instance_id=${instanceId}`, order),
  
  cancelOrder: (instanceId: string, ticket: number) =>
    api.delete<{ status: string }>(`/trading/orders/${ticket}?instance_id=${instanceId}`),
  
  closePosition: (instanceId: string, ticket: number) =>
    api.post<{ status: string }>(`/trading/positions/${ticket}/close?instance_id=${instanceId}`),
  
  getSymbolInfo: (instanceId: string, symbol: string) =>
    api.get<SymbolInfo>(`/trading/symbols/${symbol}?instance_id=${instanceId}`),
  
  getHistory: (instanceId: string, symbol?: string, days = 30) =>
    api.get<any[]>(`/trading/history?instance_id=${instanceId}${symbol ? `&symbol=${symbol}` : ''}&days=${days}`),
  
  modifyPosition: (instanceId: string, ticket: number, data: ModifyPositionRequest) =>
    api.put<{ status: string }>(`/trading/positions/${ticket}/modify?instance_id=${instanceId}`, data),
  
  partialClosePosition: (instanceId: string, ticket: number, volume: number) =>
    api.post<PartialCloseResult>(
      `/trading/positions/${ticket}/partial-close?instance_id=${instanceId}`,
      { volume }
    ),
  
  modifyOrder: (instanceId: string, ticket: number, data: { price?: number; sl?: number; tp?: number }) =>
    api.put<{ status: string }>(`/trading/orders/${ticket}/modify?instance_id=${instanceId}`, data),
  
  getCandles: (instanceId: string, symbol: string, timeframe: string = "M1", count: number = 100) =>
    api.get<CandleData[]>(
      `/trading/symbols/${symbol}/candles?instance_id=${instanceId}&timeframe=${timeframe}&count=${count}`
    ),
  
  getOrderBook: (instanceId: string, symbol: string) =>
    api.get<OrderBookData>(`/trading/symbols/${symbol}/depth?instance_id=${instanceId}`),
}
