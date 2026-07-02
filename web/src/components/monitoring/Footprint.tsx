/**
 * Footprint - 脚印图组件
 * 每根 K 线内每价位 Bid×Ask 成交量 | Delta 标记 | 失衡标记 | Canvas 渲染
 */
import { useRef, useEffect, useCallback, useState, memo, useMemo } from 'react'
import { Typography, Space, Switch, Select, Tooltip } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface FootprintCell {
  price: number
  bidVol: number   // 主动买入量
  askVol: number   // 主动卖出量
  delta: number    // bidVol - askVol
  trades: number   // 成交笔数
}

export interface FootprintBar {
  open: number
  high: number
  low: number
  close: number
  volume: number
  timestamp: number
  cells: FootprintCell[]  // 按价格升序
}

export interface FootprintProps {
  /** K 线脚印数据 */
  bars: FootprintBar[]
  /** 可见 K 线数 */
  visibleBars?: number
  /** 显示模式 */
  mode?: 'delta' | 'volume' | 'trades'
  /** 是否显示失衡标记 */
  showImbalance?: boolean
  /** 失衡阈值（倍数） */
  imbalanceThreshold?: number
  /** 宽度 */
  width?: number
  /** 高度 */
  height?: number
}

/* ---------- 常量 ---------- */
const COLORS = {
  bg: '#0d1117',
  grid: 'rgba(48, 54, 61, 0.5)',
  bullish: '#26a65b',
  bearish: '#ef5350',
  deltaPos: 'rgba(38, 166, 91, 0.7)',
  deltaNeg: 'rgba(239, 83, 80, 0.7)',
  text: '#c9d1d9',
  textDim: '#484f58',
  imbalance: '#d29922',
  poc: 'rgba(88, 166, 255, 0.6)', // 成交量最大价
  valueArea: 'rgba(88, 166, 255, 0.08)',
  bidHeat: [
    'rgba(38, 166, 91, 0.1)',
    'rgba(38, 166, 91, 0.25)',
    'rgba(38, 166, 91, 0.45)',
    'rgba(38, 166, 91, 0.7)',
    'rgba(38, 166, 91, 0.95)',
  ],
  askHeat: [
    'rgba(239, 83, 80, 0.1)',
    'rgba(239, 83, 80, 0.25)',
    'rgba(239, 83, 80, 0.45)',
    'rgba(239, 83, 80, 0.7)',
    'rgba(239, 83, 80, 0.95)',
  ],
}

/* ---------- 工具函数 ---------- */
function formatVol(v: number): string {
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toFixed(0)
}

function heatColor(value: number, max: number, palette: string[]): string {
  const ratio = Math.min(1, value / Math.max(1, max))
  const idx = Math.min(palette.length - 1, Math.floor(ratio * palette.length))
  return palette[idx]
}

function detectImbalance(cell: FootprintCell, threshold: number): 'bid' | 'ask' | null {
  if (cell.bidVol > cell.askVol * threshold && cell.bidVol > 100) return 'bid'
  if (cell.askVol > cell.bidVol * threshold && cell.askVol > 100) return 'ask'
  return null
}

/* ---------- 组件 ---------- */
const Footprint = memo(function Footprint({
  bars,
  visibleBars = 20,
  mode = 'delta',
  showImbalance = true,
  imbalanceThreshold = 3,
  width = 800,
  height = 500,
}: FootprintProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const [hoverBar, setHoverBar] = useState<number>(-1)

  // 计算全局最大值用于颜色映射
  const globalMax = useMemo(() => {
    let max = 1
    for (const bar of bars) {
      for (const cell of bar.cells) {
        max = Math.max(max, cell.bidVol, cell.askVol)
      }
    }
    return max
  }, [bars])

  // 计算每根 K 线的 POC（成交量最大价）
  const pocMap = useMemo(() => {
    const map = new Map<number, number>()
    for (const bar of bars) {
      let maxVol = 0
      let pocPrice = bar.open
      for (const cell of bar.cells) {
        const vol = cell.bidVol + cell.askVol
        if (vol > maxVol) {
          maxVol = vol
          pocPrice = cell.price
        }
      }
      map.set(bar.timestamp, pocPrice)
    }
    return map
  }, [bars])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)

    ctx.fillStyle = COLORS.bg
    ctx.fillRect(0, 0, width, height)

    if (bars.length === 0) return

    const visible = bars.slice(-visibleBars)
    const barWidth = Math.max(30, (width - 60) / visible.length - 2)

    // 全局价格范围
    let globalHigh = -Infinity
    let globalLow = Infinity
    for (const bar of visible) {
      globalHigh = Math.max(globalHigh, bar.high)
      globalLow = Math.min(globalLow, bar.low)
    }
    const priceRange = globalHigh - globalLow || 1
    const priceToY = (p: number) => 20 + ((globalHigh - p) / priceRange) * (height - 60)

    // 价格刻度
    ctx.fillStyle = COLORS.textDim
    ctx.font = '10px monospace'
    ctx.textAlign = 'right'
    const tickCount = 10
    for (let i = 0; i <= tickCount; i++) {
      const p = globalLow + (priceRange * i) / tickCount
      const y = priceToY(p)
      ctx.fillText(p.toFixed(2), width - 4, y + 3)
      ctx.strokeStyle = COLORS.grid
      ctx.lineWidth = 0.3
      ctx.beginPath()
      ctx.moveTo(40, y)
      ctx.lineTo(width - 50, y)
      ctx.stroke()
    }

    // 绘制每根 K 线的脚印
    visible.forEach((bar, barIdx) => {
      const x = 50 + barIdx * (barWidth + 2)
      const pocPrice = pocMap.get(bar.timestamp)

      // K 线背景区域
      const barTop = priceToY(bar.high)
      const barBottom = priceToY(bar.low)
      const isBullish = bar.close >= bar.open
      ctx.fillStyle = isBullish ? 'rgba(38, 166, 91, 0.04)' : 'rgba(239, 83, 80, 0.04)'
      ctx.fillRect(x, barTop, barWidth, barBottom - barTop)

      // 每个价位单元格
      const maxCellHeight = 14
      const cellHeight = Math.min(maxCellHeight, (barBottom - barTop) / Math.max(1, bar.cells.length))

      bar.cells.forEach((cell) => {
        const cy = priceToY(cell.price) - cellHeight / 2
        if (cy < 10 || cy > height - 40) return

        // 热力色
        const bidColor = heatColor(cell.bidVol, globalMax * 0.3, COLORS.bidHeat)
        const askColor = heatColor(cell.askVol, globalMax * 0.3, COLORS.askHeat)

        // 左半 bid，右半 ask
        const halfW = barWidth / 2
        ctx.fillStyle = bidColor
        ctx.fillRect(x, cy, halfW - 1, cellHeight - 1)
        ctx.fillStyle = askColor
        ctx.fillRect(x + halfW, cy, halfW - 1, cellHeight - 1)

        // POC 标记
        if (pocPrice && Math.abs(cell.price - pocPrice) < 0.01) {
          ctx.fillStyle = COLORS.poc
          ctx.fillRect(x, cy, barWidth, cellHeight - 1)
        }

        // 失衡标记
        if (showImbalance) {
          const imb = detectImbalance(cell, imbalanceThreshold)
          if (imb) {
            ctx.fillStyle = COLORS.imbalance
            ctx.font = 'bold 10px sans-serif'
            ctx.textAlign = 'center'
            const arrow = imb === 'bid' ? '⬅' : '➡'
            ctx.fillText(arrow, x + halfW, cy + cellHeight / 2 + 3)
          }
        }

        // 数值（仅在单元格足够大时显示）
        if (cellHeight >= 10 && barWidth >= 40) {
          ctx.fillStyle = COLORS.text
          ctx.font = '9px monospace'
          ctx.textAlign = 'left'
          ctx.fillText(formatVol(cell.bidVol), x + 2, cy + cellHeight / 2 + 3)
          ctx.textAlign = 'right'
          ctx.fillText(formatVol(cell.askVol), x + barWidth - 2, cy + cellHeight / 2 + 3)
        }
      })

      // Delta 柱（底部）
      if (mode === 'delta') {
        const totalDelta = bar.cells.reduce((s, c) => s + c.delta, 0)
        const maxDelta = globalMax * 0.5
        const deltaH = Math.min(20, Math.abs(totalDelta) / maxDelta * 20)
        const deltaY = height - 35 - deltaH
        ctx.fillStyle = totalDelta >= 0 ? COLORS.deltaPos : COLORS.deltaNeg
        ctx.fillRect(x + 2, deltaY, barWidth - 4, deltaH)
        ctx.fillStyle = COLORS.text
        ctx.font = '9px monospace'
        ctx.textAlign = 'center'
        ctx.fillText(totalDelta >= 0 ? `+${formatVol(totalDelta)}` : `-${formatVol(Math.abs(totalDelta))}`, x + barWidth / 2, deltaY - 2)
      }

      // OHLC 标注
      ctx.fillStyle = isBullish ? COLORS.bullish : COLORS.bearish
      ctx.font = 'bold 10px monospace'
      ctx.textAlign = 'center'
      ctx.fillText(bar.close.toFixed(2), x + barWidth / 2, barBottom + 12)

      // 高亮选中
      if (barIdx === hoverBar) {
        ctx.strokeStyle = '#58a6ff'
        ctx.lineWidth = 1.5
        ctx.strokeRect(x - 1, barTop - 1, barWidth + 2, barBottom - barTop + 2)
      }
    })

    // 图例
    ctx.fillStyle = COLORS.textDim
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillStyle = COLORS.bidHeat[3]
    ctx.fillRect(50, 5, 12, 8)
    ctx.fillStyle = COLORS.text
    ctx.fillText('Bid', 66, 12)
    ctx.fillStyle = COLORS.askHeat[3]
    ctx.fillRect(90, 5, 12, 8)
    ctx.fillStyle = COLORS.text
    ctx.fillText('Ask', 106, 12)
    if (showImbalance) {
      ctx.fillStyle = COLORS.imbalance
      ctx.fillText('⚡ 失衡', 130, 12)
    }
    ctx.fillStyle = COLORS.poc
    ctx.fillRect(180, 5, 12, 8)
    ctx.fillStyle = COLORS.text
    ctx.fillText('POC', 196, 12)
  }, [bars, visibleBars, mode, showImbalance, imbalanceThreshold, globalMax, pocMap, width, height, hoverBar])

  // 60fps 渲染
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

  // 鼠标交互
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return
      const visible = bars.slice(-visibleBars)
      const barWidth = Math.max(30, (width - 60) / visible.length - 2)
      const x = e.clientX - rect.left - 50
      const barIdx = Math.floor(x / (barWidth + 2))
      setHoverBar(barIdx >= 0 && barIdx < visible.length ? barIdx : -1)
    },
    [bars, visibleBars, width]
  )

  return (
    <div style={{ background: COLORS.bg, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #21262d' }}>
        <Space>
          <Text strong style={{ color: '#58a6ff' }}>
            <BarChartOutlined /> 脚印图
          </Text>
          <Select
            size="small"
            value={mode}
            style={{ width: 90 }}
            options={[
              { label: 'Delta', value: 'delta' },
              { label: '成交量', value: 'volume' },
              { label: '笔数', value: 'trades' },
            ]}
            onChange={() => {}}
          />
        </Space>
        <Space>
          <Tooltip title="显示失衡标记">
            <Switch size="small" defaultChecked={showImbalance} />
          </Tooltip>
        </Space>
      </div>
      <canvas
        ref={canvasRef}
        style={{ width, height, cursor: 'crosshair' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverBar(-1)}
      />
    </div>
  )
})

export default Footprint
