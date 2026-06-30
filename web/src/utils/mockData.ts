/**
 * ONE量化 · 前端 Mock 数据
 * 模拟持仓、订单、信号、盈亏曲线
 */

// ── 持仓数据 ──────────────────────────────────────────────
export interface MockPosition {
  id: string
  symbol: string
  name: string
  market: 'A股' | '港股' | '美股' | '加密'
  side: 'long' | 'short'
  quantity: number
  entryPrice: number
  currentPrice: number
  costPrice: number
  unrealizedPnl: number
  unrealizedPnlPercent: number
  todayPnl: number
  weight: number
}

export const mockPositions: MockPosition[] = [
  { id: 'p1', symbol: '600519', name: '贵州茅台', market: 'A股', side: 'long', quantity: 100, entryPrice: 1620.0, currentPrice: 1680.0, costPrice: 1620.0, unrealizedPnl: 6000, unrealizedPnlPercent: 3.70, todayPnl: 2800, weight: 13.2 },
  { id: 'p2', symbol: '000858', name: '五粮液', market: 'A股', side: 'long', quantity: 200, entryPrice: 148.0, currentPrice: 152.5, costPrice: 148.0, unrealizedPnl: 900, unrealizedPnlPercent: 3.04, todayPnl: 520, weight: 2.4 },
  { id: 'p3', symbol: '601318', name: '中国平安', market: 'A股', side: 'long', quantity: 500, entryPrice: 50.1, currentPrice: 48.2, costPrice: 50.1, unrealizedPnl: -950, unrealizedPnlPercent: -3.79, todayPnl: -380, weight: 1.9 },
  { id: 'p4', symbol: 'BTCUSDT', name: '比特币', market: '加密', side: 'long', quantity: 0.5, entryPrice: 62000, currentPrice: 68500, costPrice: 62000, unrealizedPnl: 3250, unrealizedPnlPercent: 10.48, todayPnl: 1200, weight: 26.8 },
  { id: 'p5', symbol: 'ETHUSDT', name: '以太坊', market: '加密', side: 'long', quantity: 5, entryPrice: 3200, currentPrice: 3580, costPrice: 3200, unrealizedPnl: 1900, unrealizedPnlPercent: 11.88, todayPnl: 650, weight: 14.2 },
  { id: 'p6', symbol: '09988', name: '阿里巴巴-W', market: '港股', side: 'long', quantity: 500, entryPrice: 78.5, currentPrice: 82.3, costPrice: 78.5, unrealizedPnl: 1900, unrealizedPnlPercent: 4.84, todayPnl: 420, weight: 3.2 },
  { id: 'p7', symbol: 'NVDA', name: '英伟达', market: '美股', side: 'long', quantity: 30, entryPrice: 118.0, currentPrice: 125.6, costPrice: 118.0, unrealizedPnl: 228, unrealizedPnlPercent: 6.44, todayPnl: 180, weight: 2.9 },
  { id: 'p8', symbol: 'IF2407', name: '沪深300期货', market: 'A股', side: 'long', quantity: 3, entryPrice: 3580, currentPrice: 3625, costPrice: 3580, unrealizedPnl: 13500, unrealizedPnlPercent: 1.26, todayPnl: 4200, weight: 8.3 },
]

// ── 订单数据 ──────────────────────────────────────────────
export interface MockOrder {
  id: string
  symbol: string
  name: string
  side: 'buy' | 'sell'
  orderType: 'limit' | 'market'
  price: number | null
  quantity: number
  filledQuantity: number
  status: 'pending' | 'partial' | 'filled' | 'cancelled' | 'rejected'
  exchange: string
  createdAt: string
  updatedAt: string
  strategyName: string | null
}

export const mockOrders: MockOrder[] = [
  { id: 'ord-001', symbol: '600519', name: '贵州茅台', side: 'buy', orderType: 'limit', price: 1675.0, quantity: 100, filledQuantity: 100, status: 'filled', exchange: 'SSE', createdAt: '2026-06-30T09:35:00Z', updatedAt: '2026-06-30T09:35:12Z', strategyName: '趋势跟踪A' },
  { id: 'ord-002', symbol: '300750', name: '宁德时代', side: 'buy', orderType: 'limit', price: 198.0, quantity: 300, filledQuantity: 200, status: 'partial', exchange: 'SZSE', createdAt: '2026-06-30T10:02:00Z', updatedAt: '2026-06-30T10:15:00Z', strategyName: '动量突破B' },
  { id: 'ord-003', symbol: 'BTCUSDT', name: '比特币', side: 'buy', orderType: 'market', price: null, quantity: 0.1, filledQuantity: 0.1, status: 'filled', exchange: 'Binance', createdAt: '2026-06-30T08:00:00Z', updatedAt: '2026-06-30T08:00:01Z', strategyName: '加密网格C' },
  { id: 'ord-004', symbol: '601318', name: '中国平安', side: 'sell', orderType: 'limit', price: 52.0, quantity: 500, filledQuantity: 0, status: 'pending', exchange: 'SSE', createdAt: '2026-06-30T11:20:00Z', updatedAt: '2026-06-30T11:20:00Z', strategyName: null },
  { id: 'ord-005', symbol: 'ETHUSDT', name: '以太坊', side: 'sell', orderType: 'limit', price: 3600.0, quantity: 2, filledQuantity: 2, status: 'filled', exchange: 'Binance', createdAt: '2026-06-30T10:45:00Z', updatedAt: '2026-06-30T10:52:00Z', strategyName: '加密网格C' },
  { id: 'ord-006', symbol: '000001', name: '平安银行', side: 'buy', orderType: 'market', price: null, quantity: 1000, filledQuantity: 0, status: 'cancelled', exchange: 'SZSE', createdAt: '2026-06-30T09:30:00Z', updatedAt: '2026-06-30T09:31:00Z', strategyName: null },
  { id: 'ord-007', symbol: 'NVDA', name: '英伟达', side: 'buy', orderType: 'limit', price: 120.0, quantity: 50, filledQuantity: 0, status: 'rejected', exchange: 'NASDAQ', createdAt: '2026-06-30T21:30:00Z', updatedAt: '2026-06-30T21:30:05Z', strategyName: '美股动量D' },
]

// ── 信号数据 ──────────────────────────────────────────────
export interface MockSignal {
  id: string
  symbol: string
  name: string
  direction: 'LONG' | 'SHORT'
  grade: 'S' | 'A' | 'B' | 'C'
  confidence: number
  entryPrice: number
  stopLoss: number
  takeProfit: number
  riskReward: number
  reasoning: string
  factors: string[]
  strategyName: string
  market: 'A股' | '港股' | '美股' | '加密'
  createdAt: string
  expiresAt: string
  status: 'active' | 'expired' | 'executed'
}

export const mockSignals: MockSignal[] = [
  {
    id: 'sig-001', symbol: '600519', name: '贵州茅台', direction: 'LONG', grade: 'S', confidence: 0.92,
    entryPrice: 1680.0, stopLoss: 1640.0, takeProfit: 1780.0, riskReward: 2.5,
    reasoning: '多因子模型综合研判：技术面突破关键压力位，资金面北向持续流入，基本面业绩超预期。三因子共振，形成 S 级做多信号。',
    factors: ['技术面突破', '北向资金流入', '业绩超预期', 'MACD金叉', '成交量放大'],
    strategyName: '趋势跟踪A', market: 'A股', createdAt: '2026-06-30T10:30:00Z', expiresAt: '2026-07-01T10:30:00Z', status: 'active',
  },
  {
    id: 'sig-002', symbol: '300750', name: '宁德时代', direction: 'LONG', grade: 'S', confidence: 0.88,
    entryPrice: 198.0, stopLoss: 188.0, takeProfit: 228.0, riskReward: 3.0,
    reasoning: '新能源板块资金回流，宁德时代获北向大额买入。技术面周线级别底部反转确认，月线级别支撑有效。',
    factors: ['板块轮动', '北向买入', '周线反转', 'MACD底背离'],
    strategyName: '动量突破B', market: 'A股', createdAt: '2026-06-30T09:45:00Z', expiresAt: '2026-07-01T09:45:00Z', status: 'active',
  },
  {
    id: 'sig-003', symbol: 'BTCUSDT', name: '比特币', direction: 'LONG', grade: 'A', confidence: 0.78,
    entryPrice: 68000, stopLoss: 65000, takeProfit: 75000, riskReward: 2.33,
    reasoning: '链上数据显示巨鲸持续增持，交易所净流出创近期新高。技术面站稳 68000 关键支撑，短期有望挑战前高。',
    factors: ['巨鲸增持', '交易所净流出', '关键支撑', '均线多头排列'],
    strategyName: '加密网格C', market: '加密', createdAt: '2026-06-30T08:15:00Z', expiresAt: '2026-07-01T08:15:00Z', status: 'active',
  },
  {
    id: 'sig-004', symbol: '09988', name: '阿里巴巴-W', direction: 'LONG', grade: 'A', confidence: 0.75,
    entryPrice: 82.0, stopLoss: 76.0, takeProfit: 95.0, riskReward: 2.17,
    reasoning: '港股科技板块估值修复，阿里巴巴回购力度加大。AI 业务发展超预期，云业务增速回升。',
    factors: ['估值修复', '公司回购', 'AI业务', '云增速回升'],
    strategyName: '港股价值E', market: '港股', createdAt: '2026-06-30T07:00:00Z', expiresAt: '2026-07-01T07:00:00Z', status: 'active',
  },
  {
    id: 'sig-005', symbol: '601318', name: '中国平安', direction: 'SHORT', grade: 'B', confidence: 0.62,
    entryPrice: 48.5, stopLoss: 52.0, takeProfit: 42.0, riskReward: 1.86,
    reasoning: '保险行业利差损风险加大，长端利率持续下行。技术面跌破关键均线，短期趋势偏空。',
    factors: ['利差损风险', '利率下行', '均线死叉'],
    strategyName: '趋势跟踪A', market: 'A股', createdAt: '2026-06-29T14:00:00Z', expiresAt: '2026-06-30T14:00:00Z', status: 'expired',
  },
  {
    id: 'sig-006', symbol: 'ETHUSDT', name: '以太坊', direction: 'LONG', grade: 'A', confidence: 0.81,
    entryPrice: 3500, stopLoss: 3300, takeProfit: 4000, riskReward: 2.5,
    reasoning: '以太坊 ETF 获批预期升温，链上活跃度持续上升。技术面突破三角形整理区间，量能配合良好。',
    factors: ['ETF预期', '链上活跃', '技术突破', '量价配合'],
    strategyName: '加密网格C', market: '加密', createdAt: '2026-06-30T06:30:00Z', expiresAt: '2026-07-01T06:30:00Z', status: 'active',
  },
]

// ── 盈亏曲线数据 ──────────────────────────────────────────
export interface PnlCurvePoint {
  date: string
  value: number
  dailyPnl: number
  cumulativePnl: number
  drawdown: number
}

export function generatePnlCurve(days: number = 90): PnlCurvePoint[] {
  const data: PnlCurvePoint[] = []
  let nav = 1000000 // 初始资金 100 万
  let peak = nav
  let cumulativePnl = 0

  for (let i = days; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })

    // 模拟日内波动，略微偏正（正期望系统）
    const dailyReturn = (Math.random() - 0.45) * 0.025
    const dailyPnl = nav * dailyReturn
    nav += dailyPnl
    cumulativePnl += dailyPnl
    peak = Math.max(peak, nav)
    const drawdown = (peak - nav) / peak

    data.push({
      date: dateStr,
      value: +nav.toFixed(2),
      dailyPnl: +dailyPnl.toFixed(2),
      cumulativePnl: +cumulativePnl.toFixed(2),
      drawdown: +(drawdown * 100).toFixed(2),
    })
  }
  return data
}

// ── 策略数据 ──────────────────────────────────────────────
export interface MockStrategy {
  id: string
  name: string
  enabled: boolean
  market: string
  todayPnl: number
  totalPnl: number
  winRate: number
  sharpeRatio: number
  maxDrawdown: number
  tradeCount: number
  description: string
}

export const mockStrategies: MockStrategy[] = [
  { id: 'st-1', name: '趋势跟踪A', enabled: true, market: 'A股', todayPnl: 8500, totalPnl: 125600, winRate: 0.58, sharpeRatio: 1.82, maxDrawdown: 8.5, tradeCount: 342, description: '基于均线系统和动量指标的趋势跟踪策略，适用于中大盘股。' },
  { id: 'st-2', name: '动量突破B', enabled: true, market: 'A股', todayPnl: 3200, totalPnl: 89400, winRate: 0.52, sharpeRatio: 1.45, maxDrawdown: 12.3, tradeCount: 215, description: '捕捉突破关键阻力位的动量机会，配合量能确认。' },
  { id: 'st-3', name: '加密网格C', enabled: true, market: '加密', todayPnl: 1850, totalPnl: 203000, winRate: 0.72, sharpeRatio: 2.15, maxDrawdown: 6.8, tradeCount: 1580, description: '在 BTC/ETH 上运行网格交易，高抛低吸赚取波动收益。' },
  { id: 'st-4', name: '美股动量D', enabled: false, market: '美股', todayPnl: 0, totalPnl: 45200, winRate: 0.48, sharpeRatio: 1.12, maxDrawdown: 15.6, tradeCount: 89, description: '跟踪美股科技股动量，利用盘后数据进行选股。' },
  { id: 'st-5', name: '港股价值E', enabled: true, market: '港股', todayPnl: 420, totalPnl: 32800, winRate: 0.61, sharpeRatio: 1.35, maxDrawdown: 9.2, tradeCount: 67, description: '基于基本面估值的港股价值投资策略，低估值高分红标的。' },
]

// ── 风控数据 ──────────────────────────────────────────────
export interface MockRiskMetric {
  name: string
  value: number
  threshold: number
  unit: string
  status: 'normal' | 'warning' | 'danger'
}

export const mockRiskMetrics: MockRiskMetric[] = [
  { name: '日内最大亏损', value: 12580, threshold: 50000, unit: '元', status: 'normal' },
  { name: '策略集中度', value: 35, threshold: 40, unit: '%', status: 'warning' },
  { name: '保证金使用率', value: 68, threshold: 80, unit: '%', status: 'normal' },
  { name: '最大单标的敞口', value: 26.8, threshold: 30, unit: '%', status: 'warning' },
  { name: '连亏天数', value: 1, threshold: 5, unit: '天', status: 'normal' },
  { name: 'VaR (95%)', value: 35200, threshold: 80000, unit: '元', status: 'normal' },
]

// ── 交易统计 ──────────────────────────────────────────────
export const mockTradingStats = {
  totalAssets: 1285632.45,
  todayPnl: 12580.32,
  todayPnlPercent: 0.99,
  weekPnl: 28950.0,
  weekPnlPercent: 2.30,
  monthPnl: 85200.0,
  monthPnlPercent: 7.08,
  totalPnl: 285632.45,
  totalPnlPercent: 28.56,
  availableCash: 356200.0,
  frozenCash: 45800.0,
  positionCount: 8,
  todayTradeCount: 12,
  winRate: 0.62,
  sharpeRatio: 1.85,
  maxDrawdown: 8.5,
}

// ── 格式化工具函数 ────────────────────────────────────────
export function formatMoney(n: number): string {
  if (Math.abs(n) >= 10000) {
    return `¥${(n / 10000).toFixed(2)}万`
  }
  return n.toLocaleString('zh-CN', { style: 'currency', currency: 'CNY' })
}

export function formatPercent(n: number): string {
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

export function pnlColor(n: number): string {
  if (n > 0) return '#FF5252'   // A股红涨
  if (n < 0) return '#4CAF50'   // 绿跌
  return '#888'
}

export function orderStatusText(status: string): string {
  const map: Record<string, string> = {
    pending: '待成交',
    partial: '部分成交',
    filled: '已成交',
    cancelled: '已撤单',
    rejected: '已拒绝',
  }
  return map[status] || status
}

export function orderStatusColor(status: string): string {
  const map: Record<string, string> = {
    pending: '#faad14',
    partial: '#1677ff',
    filled: '#52c41a',
    cancelled: '#888',
    rejected: '#ff4d4f',
  }
  return map[status] || '#888'
}
