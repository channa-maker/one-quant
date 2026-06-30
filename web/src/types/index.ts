/** 全局类型定义 */

export interface ApiResponse<T = any> {
  success: boolean
  data: T
  error: string | null
  meta?: Record<string, any>
}

export interface Ticker {
  symbol: string
  market: string
  exchange: string
  last_price: string
  bid: string
  ask: string
  volume_24h: string
  timestamp_ns: number
}

export interface Order {
  client_order_id: string
  symbol: string
  market: string
  side: 'buy' | 'sell'
  order_type: string
  quantity: string
  price: string | null
  status: string
  exchange: string
}

export interface Position {
  symbol: string
  market: string
  side: 'long' | 'short' | 'flat'
  quantity: string
  entry_price: string
  unrealized_pnl: string
  realized_pnl: string
}

export interface Signal {
  symbol: string
  side: 'buy' | 'sell'
  strength: number
  strategy_name: string
  reason: string
}

export interface StrategyInfo {
  name: string
  enabled: boolean
  stats: Record<string, any>
}

export interface RiskDecision {
  decision: 'APPROVE' | 'REJECT' | 'REDUCE' | 'FLATTEN'
  rule_name: string
  reason: string
}
