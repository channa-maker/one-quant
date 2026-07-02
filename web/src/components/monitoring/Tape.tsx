/**
 * Tape - 成交瀑布组件
 * 逐笔成交流 | 大单高亮 | 扫单识别 | 主动买卖染色
 */
import { useRef, useEffect, useState, memo, useMemo } from 'react'
import { Typography, Space, Select, Tag, Badge } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface TapeTrade {
  id: string
  timestamp: number
  price: number
  size: number
  side: 'buy' | 'sell'        // 主动方向
  isAggressor: boolean         // 是否主动吃单
  /** 扫单标识：连续同方向大单 */
  sweepId?: string
}

export interface TapeProps {
  /** 逐笔成交数据（最新在前） */
  trades: TapeTrade[]
  /** 最大显示条数 */
  maxRows?: number
  /** 大单阈值（绝对量） */
  bigOrderThreshold?: number
  /** 扫单检测窗口（毫秒） */
  sweepWindowMs?: number
  /** 扫单最小笔数 */
  sweepMinCount?: number
  /** 是否自动滚动 */
  autoScroll?: boolean
  /** 高亮价格（联动用） */
  highlightPrice?: number | null
  /** 点击成交回调 */
  onTradeClick?: (trade: TapeTrade) => void
}

/* ---------- 常量 ---------- */
const COLORS = {
  bg: '#0d1117',
  buyText: '#3fb950',
  sellText: '#f85149',
  bigBuy: 'rgba(63, 185, 80, 0.15)',
  bigSell: 'rgba(248, 81, 73, 0.15)',
  sweep: 'rgba(210, 153, 34, 0.2)',
  text: '#c9d1d9',
  textDim: '#484f58',
  grid: 'rgba(48, 54, 61, 0.4)',
  hover: 'rgba(88, 166, 255, 0.08)',
}

/* ---------- 工具函数 ---------- */
function formatSize(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toFixed(0)
}

function formatPrice(p: number): string {
  return p.toFixed(2)
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}.${d.getMilliseconds().toString().padStart(3, '0')}`
}

/** 检测扫单 */
function detectSweeps(trades: TapeTrade[], windowMs: number, minCount: number): Set<string> {
  const sweepIds = new Set<string>()

  // 按时间窗口分组
  const sorted = [...trades].sort((a, b) => a.timestamp - b.timestamp)
  let windowStart = 0
  let currentSide: 'buy' | 'sell' | null = null
  let consecutive: TapeTrade[] = []

  for (const t of sorted) {
    if (currentSide !== t.side || t.timestamp - windowStart > windowMs) {
      // 检查之前的连续
      if (consecutive.length >= minCount && currentSide) {
        const id = `sweep_${windowStart}`
        consecutive.forEach((ct) => {
          ct.sweepId = id
          sweepIds.add(id)
        })
      }
      currentSide = t.side
      windowStart = t.timestamp
      consecutive = [t]
    } else {
      consecutive.push(t)
    }
  }
  // 最后一组
  if (consecutive.length >= minCount && currentSide) {
    const id = `sweep_${windowStart}`
    consecutive.forEach((ct) => {
      ct.sweepId = id
      sweepIds.add(id)
    })
  }

  return sweepIds
}

/* ---------- 组件 ---------- */
const Tape = memo(function Tape({
  trades,
  maxRows = 200,
  bigOrderThreshold = 10000,
  sweepWindowMs = 3000,
  sweepMinCount = 5,
  autoScroll = true,
  highlightPrice,
  onTradeClick,
}: TapeProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoverRow, setHoverRow] = useState<string | null>(null)
  const [filterSide, setFilterSide] = useState<'all' | 'buy' | 'sell' | 'big'>('all')

  // 标记大单和扫单
  const enrichedTrades = useMemo(() => {
    const result = trades.slice(0, maxRows).map((t) => ({
      ...t,
      isBig: t.size >= bigOrderThreshold,
      isSweep: false,
    }))

    // 扫单检测
    const sweepSet = detectSweeps([...trades], sweepWindowMs, sweepMinCount)
    for (const t of result) {
      if (t.sweepId && sweepSet.has(t.sweepId)) {
        ;(t as any).isSweep = true
      }
    }

    return result
  }, [trades, maxRows, bigOrderThreshold, sweepWindowMs, sweepMinCount])

  // 过滤
  const filtered = useMemo(() => {
    switch (filterSide) {
      case 'buy': return enrichedTrades.filter((t) => t.side === 'buy')
      case 'sell': return enrichedTrades.filter((t) => t.side === 'sell')
      case 'big': return enrichedTrades.filter((t) => (t as any).isBig)
      default: return enrichedTrades
    }
  }, [enrichedTrades, filterSide])

  // 统计
  const stats = useMemo(() => {
    const buyVol = enrichedTrades.filter((t) => t.side === 'buy').reduce((s, t) => s + t.size, 0)
    const sellVol = enrichedTrades.filter((t) => t.side === 'sell').reduce((s, t) => s + t.size, 0)
    const bigCount = enrichedTrades.filter((t) => (t as any).isBig).length
    const sweepCount = new Set(enrichedTrades.filter((t) => (t as any).isSweep).map((t) => t.sweepId)).size
    return { buyVol, sellVol, bigCount, sweepCount, delta: buyVol - sellVol }
  }, [enrichedTrades])

  // 自动滚动
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = 0
    }
  }, [trades.length, autoScroll])

  return (
    <div style={{ background: COLORS.bg, borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 头部 */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #21262d' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Space>
            <Text strong style={{ color: '#58a6ff' }}>
              <ThunderboltOutlined /> 成交瀑布
            </Text>
            <Badge count={stats.sweepCount} size="small" style={{ backgroundColor: '#d29922' }}>
              <Tag color="gold" style={{ margin: 0 }}>扫单</Tag>
            </Badge>
          </Space>
          <Select
            size="small"
            value={filterSide}
            style={{ width: 80 }}
            options={[
              { label: '全部', value: 'all' },
              { label: '买入', value: 'buy' },
              { label: '卖出', value: 'sell' },
              { label: '大单', value: 'big' },
            ]}
            onChange={setFilterSide}
          />
        </div>

        {/* 统计栏 */}
        <div style={{ display: 'flex', gap: 16, fontSize: 11 }}>
          <span>
            <Text type="secondary">买量 </Text>
            <Text style={{ color: COLORS.buyText }}>{formatSize(stats.buyVol)}</Text>
          </span>
          <span>
            <Text type="secondary">卖量 </Text>
            <Text style={{ color: COLORS.sellText }}>{formatSize(stats.sellVol)}</Text>
          </span>
          <span>
            <Text type="secondary">Delta </Text>
            <Text style={{ color: stats.delta >= 0 ? COLORS.buyText : COLORS.sellText }}>
              {stats.delta >= 0 ? '+' : ''}{formatSize(stats.delta)}
            </Text>
          </span>
          <span>
            <Text type="secondary">大单 </Text>
            <Text style={{ color: '#d29922' }}>{stats.bigCount}</Text>
          </span>
        </div>
      </div>

      {/* 表头 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '90px 1fr 80px 60px 50px',
        padding: '4px 12px',
        background: '#161b22',
        fontSize: 11,
        color: COLORS.textDim,
        borderBottom: '1px solid #21262d',
      }}>
        <span>时间</span>
        <span style={{ textAlign: 'right' }}>价格</span>
        <span style={{ textAlign: 'right' }}>数量</span>
        <span style={{ textAlign: 'center' }}>方向</span>
        <span style={{ textAlign: 'center' }}>标记</span>
      </div>

      {/* 成交流 */}
      <div
        ref={containerRef}
        style={{ flex: 1, overflow: 'auto' }}
      >
        {filtered.slice(0, maxRows).map((trade) => {
          const isBig = (trade as any).isBig
          const isSweep = (trade as any).isSweep
          const isHighlighted = highlightPrice != null && Math.abs(trade.price - highlightPrice) < 0.01

          return (
            <div
              key={trade.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '90px 1fr 80px 60px 50px',
                padding: '3px 12px',
                fontSize: 12,
                fontFamily: 'monospace',
                cursor: 'pointer',
                background: isBig
                  ? trade.side === 'buy' ? COLORS.bigBuy : COLORS.bigSell
                  : isSweep
                    ? COLORS.sweep
                    : isHighlighted
                      ? COLORS.hover
                      : hoverRow === trade.id
                        ? COLORS.hover
                        : 'transparent',
                borderBottom: `1px solid ${COLORS.grid}`,
                transition: 'background 0.15s',
              }}
              onMouseEnter={() => setHoverRow(trade.id)}
              onMouseLeave={() => setHoverRow(null)}
              onClick={() => onTradeClick?.(trade)}
            >
              <span style={{ color: COLORS.textDim, fontSize: 11 }}>
                {formatTime(trade.timestamp)}
              </span>
              <span style={{
                textAlign: 'right',
                color: trade.side === 'buy' ? COLORS.buyText : COLORS.sellText,
                fontWeight: isBig ? 'bold' : 'normal',
                fontSize: isBig ? 13 : 12,
              }}>
                {formatPrice(trade.price)}
              </span>
              <span style={{
                textAlign: 'right',
                color: isBig ? '#d29922' : COLORS.text,
                fontWeight: isBig ? 'bold' : 'normal',
              }}>
                {formatSize(trade.size)}
              </span>
              <span style={{ textAlign: 'center' }}>
                {trade.side === 'buy' ? (
                  <span style={{ color: COLORS.buyText }}>↑ 买</span>
                ) : (
                  <span style={{ color: COLORS.sellText }}>↓ 卖</span>
                )}
              </span>
              <span style={{ textAlign: 'center' }}>
                {isSweep && <Tag color="gold" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '18px' }}>扫</Tag>}
                {isBig && !isSweep && <Tag color="orange" style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '18px' }}>大</Tag>}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
})

export default Tape
