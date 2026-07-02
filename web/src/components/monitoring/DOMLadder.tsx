/**
 * DOMLadder - 深度梯 DOM 组件
 * 实时买卖挂单量 | 撤补单闪烁 | 点价下单 | Canvas 60fps 渲染
 */
import { useRef, useEffect, useCallback, useState, memo } from 'react'
import { Switch, Typography, Space, Tooltip } from 'antd'
import { AimOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface DOMLevel {
  price: number
  bidSize: number
  askSize: number
  bidOrders: number
  askOrders: number
  /** 撤单量（负数表示撤单） */
  bidCancel: number
  askCancel: number
}

export interface DOMLadderProps {
  /** 标的代码 */
  symbol: string
  /** 深度数据（价格升序） */
  levels: DOMLevel[]
  /** 最新成交价 */
  lastPrice: number
  /** 价格步进 */
  tickSize: number
  /** 可见行数 */
  visibleRows?: number
  /** 点价下单回调 */
  onPriceClick?: (price: number, side: 'buy' | 'sell') => void
  /** 行高 px */
  rowHeight?: number
  /** 最大挂单量（用于柱宽归一化） */
  maxBookSize?: number
}

/* ---------- 常量 ---------- */
const COLORS = {
  bidBar: 'rgba(38, 166, 91, 0.55)',
  bidBarFlash: 'rgba(38, 166, 91, 0.95)',
  askBar: 'rgba(239, 83, 80, 0.55)',
  askBarFlash: 'rgba(239, 83, 80, 0.95)',
  cancelFlash: 'rgba(255, 215, 0, 0.8)',
  bg: '#0d1117',
  bgHover: 'rgba(88, 166, 255, 0.08)',
  bgLast: 'rgba(56, 132, 244, 0.15)',
  text: '#c9d1d9',
  textDim: '#484f58',
  spread: 'rgba(210, 153, 34, 0.25)',
  grid: 'rgba(48, 54, 61, 0.6)',
}

/* ---------- 工具函数 ---------- */
function formatSize(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toFixed(0)
}

function formatPrice(p: number, tick: number): string {
  const decimals = Math.max(0, -Math.floor(Math.log10(tick)))
  return p.toFixed(decimals)
}

/* ---------- 组件 ---------- */
const DOMLadder = memo(function DOMLadder({
  symbol,
  levels,
  lastPrice,
  tickSize,
  visibleRows = 25,
  onPriceClick,
  rowHeight = 28,
  maxBookSize,
}: DOMLadderProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const rafRef = useRef<number>(0)
  const flashMapRef = useRef<Map<number, { ts: number; type: 'add' | 'cancel' }>>(new Map())
  const prevLevelsRef = useRef<Map<number, { bid: number; ask: number }>>(new Map())
  const [clickOrderEnabled, setClickOrderEnabled] = useState(true)
  const [hoverRow, setHoverRow] = useState<number>(-1)

  const canvasWidth = 400
  const canvasHeight = visibleRows * rowHeight

  // 计算最大挂单量
  const computedMax = maxBookSize ?? Math.max(
    1,
    ...levels.map((l) => Math.max(l.bidSize, l.askSize))
  )

  // 检测撤补单，记录闪烁
  useEffect(() => {
    const prev = prevLevelsRef.current
    const flashes = flashMapRef.current
    const now = performance.now()

    for (const lv of levels) {
      const p = prev.get(lv.price)
      if (!p) continue
      if (lv.bidSize > p.bid || lv.askSize > p.ask) {
        flashes.set(lv.price, { ts: now, type: 'add' })
      } else if (lv.bidSize < p.bid || lv.askSize < p.ask) {
        flashes.set(lv.price, { ts: now, type: 'cancel' })
      }
    }

    // 清理过期闪烁 (>600ms)
    for (const [k, v] of flashes) {
      if (now - v.ts > 600) flashes.delete(k)
    }

    const newMap = new Map<number, { bid: number; ask: number }>()
    for (const lv of levels) newMap.set(lv.price, { bid: lv.bidSize, ask: lv.askSize })
    prevLevelsRef.current = newMap
  }, [levels])

  // Canvas 绘制
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = canvasWidth * dpr
    canvas.height = canvasHeight * dpr
    ctx.scale(dpr, dpr)

    // 背景
    ctx.fillStyle = COLORS.bg
    ctx.fillRect(0, 0, canvasWidth, canvasHeight)

    // 列布局: [价格列] [卖单柱] [买单柱] [数量]
    const priceColW = 90
    const barAreaW = (canvasWidth - priceColW - 80) / 2
    const askBarX = priceColW
    const bidBarX = askBarX + barAreaW

    // 找到 lastPrice 所在行
    const sortedLevels = [...levels].sort((a, b) => b.price - a.price) // 价格降序
    const centerIdx = sortedLevels.findIndex((l) => l.price <= lastPrice)
    const startIdx = Math.max(0, Math.min(centerIdx - Math.floor(visibleRows / 2), sortedLevels.length - visibleRows))
    const visible = sortedLevels.slice(startIdx, startIdx + visibleRows)

    const now = performance.now()
    const flashes = flashMapRef.current

    visible.forEach((lv, i) => {
      const y = i * rowHeight

      // 当前行背景
      const isLast = Math.abs(lv.price - lastPrice) < tickSize / 2
      const isHover = i === hoverRow

      if (isLast) {
        ctx.fillStyle = COLORS.bgLast
        ctx.fillRect(0, y, canvasWidth, rowHeight)
      } else if (isHover) {
        ctx.fillStyle = COLORS.bgHover
        ctx.fillRect(0, y, canvasWidth, rowHeight)
      }

      // 闪烁背景
      const flash = flashes.get(lv.price)
      if (flash) {
        const elapsed = now - flash.ts
        const alpha = Math.max(0, 1 - elapsed / 600)
        if (flash.type === 'cancel') {
          ctx.fillStyle = `rgba(255, 215, 0, ${alpha * 0.3})`
        } else {
          ctx.fillStyle = `rgba(88, 166, 255, ${alpha * 0.2})`
        }
        ctx.fillRect(0, y, canvasWidth, rowHeight)
      }

      // 网格线
      ctx.strokeStyle = COLORS.grid
      ctx.lineWidth = 0.5
      ctx.beginPath()
      ctx.moveTo(0, y + rowHeight)
      ctx.lineTo(canvasWidth, y + rowHeight)
      ctx.stroke()

      // 价格列
      ctx.fillStyle = isLast ? '#58a6ff' : COLORS.text
      ctx.font = isLast ? 'bold 13px monospace' : '13px monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(formatPrice(lv.price, tickSize), priceColW / 2, y + rowHeight / 2)

      // 卖单柱（向左延伸）
      const askRatio = Math.min(1, lv.askSize / computedMax)
      const askBarW = askRatio * barAreaW * 0.9
      const askFlashAlpha = flash?.type === 'add' ? Math.max(0, 1 - (now - flash.ts) / 600) : 0
      ctx.fillStyle = askFlashAlpha > 0 ? COLORS.askBarFlash : COLORS.askBar
      ctx.fillRect(askBarX + barAreaW - askBarW, y + 2, askBarW, rowHeight - 4)

      // 买单柱（向右延伸）
      const bidRatio = Math.min(1, lv.bidSize / computedMax)
      const bidBarW = bidRatio * barAreaW * 0.9
      const bidFlashAlpha = flash?.type === 'add' ? Math.max(0, 1 - (now - flash.ts) / 600) : 0
      ctx.fillStyle = bidFlashAlpha > 0 ? COLORS.bidBarFlash : COLORS.bidBar
      ctx.fillRect(bidBarX, y + 2, bidBarW, rowHeight - 4)

      // 数量
      ctx.fillStyle = COLORS.textDim
      ctx.font = '11px monospace'
      ctx.textAlign = 'right'
      ctx.fillText(formatSize(lv.bidSize), canvasWidth - 8, y + rowHeight / 2)

      // 订单数小字
      if (lv.bidOrders > 0 || lv.askOrders > 0) {
        ctx.fillStyle = 'rgba(201, 209, 217, 0.3)'
        ctx.font = '9px monospace'
        ctx.textAlign = 'left'
        ctx.fillText(`${lv.askOrders}`, askBarX + 2, y + rowHeight / 2 + 10)
        ctx.textAlign = 'right'
        ctx.fillText(`${lv.bidOrders}`, bidBarX + barAreaW - 2, y + rowHeight / 2 + 10)
      }
    })

    // 中间价差区域
    const spreadIdx = visible.findIndex((l) => l.price <= lastPrice)
    if (spreadIdx >= 0) {
      const sy = spreadIdx * rowHeight
      ctx.fillStyle = COLORS.spread
      ctx.fillRect(0, sy, canvasWidth, rowHeight)
    }

    // 点价下单标识
    if (clickOrderEnabled && hoverRow >= 0 && hoverRow < visible.length) {
      const hy = hoverRow * rowHeight
      const hoverLv = visible[hoverRow]
      ctx.strokeStyle = '#58a6ff'
      ctx.lineWidth = 1.5
      ctx.setLineDash([4, 2])
      ctx.strokeRect(1, hy + 1, canvasWidth - 2, rowHeight - 2)
      ctx.setLineDash([])

      // 左右下单箭头
      ctx.fillStyle = hoverLv.price > lastPrice ? COLORS.askBar : COLORS.bidBar
      ctx.font = 'bold 11px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(
        hoverLv.price > lastPrice ? '⬅ 卖' : '买 ➡',
        canvasWidth / 2,
        hy + rowHeight / 2
      )
    }
  }, [levels, lastPrice, tickSize, visibleRows, rowHeight, computedMax, clickOrderEnabled, hoverRow, canvasWidth, canvasHeight])

  // 60fps 渲染循环
  useEffect(() => {
    let running = true
    const loop = () => {
      if (!running) return
      draw()
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      running = false
      cancelAnimationFrame(rafRef.current)
    }
  }, [draw])

  // 鼠标事件
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return
      const y = e.clientY - rect.top
      setHoverRow(Math.floor(y / rowHeight))
    },
    [rowHeight]
  )

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!clickOrderEnabled || !onPriceClick) return
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return
      const y = e.clientY - rect.top
      const rowIdx = Math.floor(y / rowHeight)

      const sortedLevels = [...levels].sort((a, b) => b.price - a.price)
      const centerIdx = sortedLevels.findIndex((l) => l.price <= lastPrice)
      const startIdx = Math.max(0, Math.min(centerIdx - Math.floor(visibleRows / 2), sortedLevels.length - visibleRows))
      const visible = sortedLevels.slice(startIdx, startIdx + visibleRows)

      if (rowIdx >= 0 && rowIdx < visible.length) {
        const lv = visible[rowIdx]
        const x = e.clientX - rect.left
        const side = x < canvasWidth / 2 ? 'sell' : 'buy'
        onPriceClick(lv.price, side)
      }
    },
    [clickOrderEnabled, onPriceClick, levels, lastPrice, rowHeight, visibleRows, canvasWidth, tickSize]
  )

  // 计算价差
  const bestBid = levels.find((l) => l.bidSize > 0)
  const bestAsk = levels.find((l) => l.askSize > 0)
  const spread = bestBid && bestAsk ? bestAsk.price - bestBid.price : 0
  const spreadPct = bestBid ? (spread / bestBid.price) * 100 : 0

  return (
    <div ref={containerRef} style={{ background: COLORS.bg, borderRadius: 8, overflow: 'hidden' }}>
      {/* 工具栏 */}
      <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #21262d' }}>
        <Space>
          <Text strong style={{ color: '#58a6ff' }}>📊 {symbol}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            深度 · {levels.length} 档
          </Text>
        </Space>
        <Space>
          <Tooltip title="点价下单">
            <Switch
              size="small"
              checked={clickOrderEnabled}
              onChange={setClickOrderEnabled}
              checkedChildren={<AimOutlined />}
              unCheckedChildren="关"
            />
          </Tooltip>
        </Space>
      </div>

      {/* 行头 */}
      <div style={{ padding: '4px 12px', display: 'flex', justifyContent: 'space-between', background: '#161b22' }}>
        <Text type="secondary" style={{ fontSize: 11, color: COLORS.askBar }}>卖单</Text>
        <Text type="secondary" style={{ fontSize: 11 }}>价差: {formatPrice(spread, tickSize)} ({spreadPct.toFixed(3)}%)</Text>
        <Text type="secondary" style={{ fontSize: 11, color: COLORS.bidBar }}>买单</Text>
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        style={{ width: canvasWidth, height: canvasHeight, cursor: clickOrderEnabled ? 'crosshair' : 'default' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverRow(-1)}
        onClick={handleClick}
      />

      {/* 底栏 */}
      <div style={{ padding: '6px 12px', background: '#161b22', borderTop: '1px solid #21262d' }}>
        <Space>
          <Text style={{ color: '#58a6ff', fontWeight: 'bold', fontSize: 16 }}>
            {formatPrice(lastPrice, tickSize)}
          </Text>
          {bestBid && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              买一 {formatPrice(bestBid.price, tickSize)} × {formatSize(bestBid.bidSize)}
            </Text>
          )}
          {bestAsk && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              卖一 {formatPrice(bestAsk.price, tickSize)} × {formatSize(bestAsk.askSize)}
            </Text>
          )}
        </Space>
      </div>
    </div>
  )
})

export default DOMLadder
