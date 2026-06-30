import { create } from 'zustand'
import type { Ticker, Order, Position, Signal, StrategyInfo } from '@/types'

interface AppState {
  // 行情
  tickers: Record<string, Ticker>
  setTicker: (ticker: Ticker) => void

  // 订单
  orders: Order[]
  addOrder: (order: Order) => void
  updateOrder: (orderId: string, status: string) => void

  // 持仓
  positions: Position[]
  setPositions: (positions: Position[]) => void

  // 信号
  signals: Signal[]
  addSignal: (signal: Signal) => void

  // 策略
  strategies: StrategyInfo[]
  setStrategies: (strategies: StrategyInfo[]) => void

  // WebSocket
  wsConnected: boolean
  setWsConnected: (connected: boolean) => void

  // 主题设置
  colorMode: 'red-up' | 'green-up'
  setColorMode: (mode: 'red-up' | 'green-up') => void
}

export const useAppStore = create<AppState>((set) => ({
  tickers: {},
  setTicker: (ticker) =>
    set((state) => ({ tickers: { ...state.tickers, [ticker.symbol]: ticker } })),

  orders: [],
  addOrder: (order) =>
    set((state) => ({ orders: [order, ...state.orders] })),
  updateOrder: (orderId, status) =>
    set((state) => ({
      orders: state.orders.map((o) =>
        o.client_order_id === orderId ? { ...o, status } : o
      ),
    })),

  positions: [],
  setPositions: (positions) => set({ positions }),

  signals: [],
  addSignal: (signal) =>
    set((state) => ({ signals: [signal, ...state.signals].slice(0, 100) })),

  strategies: [],
  setStrategies: (strategies) => set({ strategies }),

  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),

  colorMode: 'red-up',
  setColorMode: (mode) => set({ colorMode: mode }),
}))
