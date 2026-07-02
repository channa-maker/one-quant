/**
 * CVDChart - 累计成交量差曲线组件
 * CVD 曲线 | 背离标记 | 与K线图联动 | Canvas 渲染
 */
import { useRef, useEffect, useCallback, useState, memo, useMemo } from 'react'
import { Typography, Space, Switch, Tooltip } from 'antd'
import { LineChartOutlined, AlertOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface CVDPoint {
  timestamp: number
  cvd: number         // 累计成交量差
  price: number       // 对应价格
  delta: number       // 当前bar的delta
  volume: number      // 当前bar成交量
}

export interface Divergence {
  type: 'bullish' | 'bearish'
  startIdx: number
  endIdx: number
  priceStart: number
  priceEnd: number
  cvdStart: number
  cvdEnd: number
  description: string
}

export interface CVDChartProps {
  /** CVD 数据点（时间升序） */
  data: CVDPoint[]
  /** K 线数据（用于联动，时间升序） */
  klineData?: { timestamp: number; open: number; high: number; low: number; close: number }[]
  /** 可见数据点数 */
  visiblePoints?: number
  /** 是否显示背离标记 */
  showDivergence?: boolean
  /** 背离检测窗口 */
  divergenceWindow?: number
  /** 联动时间轴高亮 */
  highlightTime?: number | null
  /** 宽度 */
  width?: number
  /** 高度 */
  height?: number
  /** 点击回调 */
  onPointClick?: (point: CVDPoint) => void
}

/* ---------- 常量 ---------- */
const COLORS = {
  bg: '#0d1117',
  grid: 'rgba(48, 54, 61, 0.4)',
  cvdLine: '#58a6ff',
  cvdFill: 'rgba(88, 166, 255, 0.08)',
  priceLine: '#c9d1d9',
  deltaPos: 'rgba(38, 166, 91, 0.7)',
  deltaNeg: 'rgba(239, 83, 80, 0.7)',
  divergenceBull: '#3fb950',
  divergenceBear: '#f85149',
  divergenceZone: 'rgba(210, 153, 34, 0.1)',
  text: '#c9d1d9',
  textDim: '#484f58',
  zeroLine: 'rgba(139, 148, 158, 0.3)',
}

/* ---------- 背离检测 ---------- */
function detectDivergences(
  data: CVDPoint[],
  window: number
): Divergence[] {
  const divergences: Divergence[] = []

  for (let i = window; i < data.length; i++) {
    const start = i - window
    const end = i

    // 寻找窗口内的价格极值
    let priceHigh = -Infinity, priceLow = Infinity
    let priceHighIdx = start, priceLowIdx = start
    let cvdHigh = -Infinity, cvdLow = Infinity

    for (let j = start; j <= end; j++) {
      if (data[j].price > priceHigh) { priceHigh = data[j].price; priceHighIdx = j }
      if (data[j].price < priceLow) { priceLow = data[j].price; priceLowIdx = j }
      if (data[j].cvd > cvdHigh) cvdHigh = data[j].cvd
      if (data[j].cvd < cvdLow) cvdLow = data[j].cvd
    }

    // 看跌背离：价格新高但 CVD 不创新高
    if (priceHighIdx === end) {
      const prevCvdAtPriceHigh = data[Math.max(start, priceHighIdx - Math.floor(window / 2))].cvd
      if (data[end].cvd < prevCvdAtPriceHigh * 0.98) {
        divergences.push({
          type: 'bearish',
          startIdx: start,
          endIdx: end,
          priceStart: data[start].price,
          priceEnd: data[end].price,
          cvdStart: data[start].cvd,
          cvdEnd: data[end].cvd,
          description: '价格新高 · CVD 走弱',
        })
      }
    }

    // 看涨背离：价格新低但 CVD 不创新低
    if (priceLowIdx === end) {
      const prevCvdAtPriceLow = data[Math.max(start, priceLowIdx - Math.floor(window / 2))].cvd
      if (data[end].cvd > prevCvdAtPriceLow * 1.02) {
        divergences.push({
          type: 'bullish',
          startIdx: start,
          endIdx: end,
          priceStart: data[start].price,
          priceEnd: data[end].price,
          cvdStart: data[start].cvd,
          cvdEnd: data[end].cvd,
          description: '价格新低 · CVD 走强',
        })
      }
    }
  }

  // 去重：同一区域只保留最强背离
  return divergences.filter((d, i) => {
    if (i === 0) return true
    return Math.abs(d.endIdx - divergences[i - 1].endIdx) > window / 2
  })
}

/* ---------- 组件 ---------- */
const CVDChart = memo(function CVDChart({
  data,
  klineData,
  visiblePoints = 100,
  showDivergence = true,
  divergenceWindow = 20,
  highlightTime,
  width = 800,
  height = 400,
  onPointClick,
}: CVDChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const [hoverIdx, setHoverIdx] = useState<number>(-1)

  const visible = useMemo(() => data.slice(-visiblePoints), [data, visiblePoints])

  const divergences = useMemo(() => {
    if (!showDivergence) return []
    return detectDivergences(visible, divergenceWindow)
  }, [visible, showDivergence, divergenceWindow])

  // 合并 K 线数据
  const mergedData = useMemo(() => {
    if (!klineData) return visible.map((p) => ({ ...p, kline: null }))
    const klineMap = new Map(klineData.map((k) => [k.timestamp, k]))
    return visible.map((p) => ({
      ...p,
      kline: klineMap.get(p.timestamp) || null,
    }))
  }, [visible, klineData])

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

    if (visible.length < 2) return

    const padding = { top: 30, right: 70, bottom: 40, left: 60 }
    const chartW = width - padding.left - padding.right
    const chartH = height - padding.top - padding.bottom

    // 数据范围
    const cvdValues = visible.map((p) => p.cvd)
    const priceValues = visible.map((p) => p.price)
    const cvdMin = Math.min(...cvdValues)
    const cvdMax = Math.max(...cvdValues)
    const cvdRange = cvdMax - cvdMin || 1
    const priceMin = Math.min(...priceValues)
    const priceMax = Math.max(...priceValues)
    const priceRange = priceMax - priceMin || 1

    const xScale = (i: number) => padding.left + (i / (visible.length - 1)) * chartW
    const cvdY = (v: number) => padding.top + (1 - (v - cvdMin) / cvdRange) * chartH
    const priceY = (v: number) => padding.top + (1 - (v - priceMin) / priceRange) * chartH

    // 网格
    ctx.strokeStyle = COLORS.grid
    ctx.lineWidth = 0.5
    for (let i = 0; i <= 5; i++) {
      const y = padding.top + (chartH * i) / 5
      ctx.beginPath()
      ctx.moveTo(padding.left, y)
      ctx.lineTo(width - padding.right, y)
      ctx.stroke()
    }

    // 零线 / CVD 中位
    const cvdMid = (cvdMin + cvdMax) / 2
    const cvdMidY = cvdY(cvdMid)
    ctx.strokeStyle = COLORS.zeroLine
    ctx.lineWidth = 1
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(padding.left, cvdMidY)
    ctx.lineTo(width - padding.right, cvdMidY)
    ctx.stroke()
    ctx.setLineDash([])

    // Delta 柱
    const maxDelta = Math.max(1, ...visible.map((p) => Math.abs(p.delta)))
    visible.forEach((p, i) => {
      const x = xScale(i)
      const barW = Math.max(2, chartW / visible.length - 1)
      const barH = Math.abs(p.delta) / maxDelta * (chartH * 0.15)
      const barY = p.delta >= 0 ? cvdMidY - barH : cvdMidY
      ctx.fillStyle = p.delta >= 0 ? COLORS.deltaPos : COLORS.deltaNeg
      ctx.fillRect(x - barW / 2, barY, barW, barH)
    })

    // CVD 填充区域
    ctx.beginPath()
    ctx.moveTo(xScale(0), cvdY(visible[0].cvd))
    for (let i = 1; i < visible.length; i++) {
      ctx.lineTo(xScale(i), cvdY(visible[i].cvd))
    }
    ctx.lineTo(xScale(visible.length - 1), cvdMidY)
    ctx.lineTo(xScale(0), cvdMidY)
    ctx.closePath()
    ctx.fillStyle = COLORS.cvdFill
    ctx.fill()

    // CVD 曲线
    ctx.strokeStyle = COLORS.cvdLine
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(xScale(0), cvdY(visible[0].cvd))
    for (let i = 1; i < visible.length; i++) {
      ctx.lineTo(xScale(i), cvdY(visible[i].cvd))
    }
    ctx.stroke()

    // 价格曲线（叠加，右轴）
    ctx.strokeStyle = COLORS.priceLine
    ctx.lineWidth = 1.5
    ctx.setLineDash([3, 2])
    ctx.beginPath()
    ctx.moveTo(xScale(0), priceY(visible[0].price))
    for (let i = 1; i < visible.length; i++) {
      ctx.lineTo(xScale(i), priceY(visible[i].price))
    }
    ctx.stroke()
    ctx.setLineDash([])

    // 背离标记
    for (const div of divergences) {
      const sx = xScale(div.startIdx)
      const ex = xScale(div.endIdx)
      const isBull = div.type === 'bullish'

      // 背离区域
      ctx.fillStyle = COLORS.divergenceZone
      ctx.fillRect(sx, padding.top, ex - sx, chartH)

      // 箭头
      const arrowY = isBull ? padding.top + chartH - 20 : padding.top + 10
      ctx.fillStyle = isBull ? COLORS.divergenceBull : COLORS.divergenceBear
      ctx.font = 'bold 14px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(isBull ? '🔺 看涨背离' : '🔻 看跌背离', (sx + ex) / 2, arrowY)

      // 连线
      ctx.strokeStyle = isBull ? COLORS.divergenceBull : COLORS.divergenceBear
      ctx.lineWidth = 1.5
      ctx.setLineDash([2, 2])
      ctx.beginPath()
      ctx.moveTo(sx, cvdY(div.cvdStart))
      ctx.lineTo(ex, cvdY(div.cvdEnd))
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(sx, priceY(div.priceStart))
      ctx.lineTo(ex, priceY(div.priceEnd))
      ctx.stroke()
      ctx.setLineDash([])
    }

    // 联动高亮
    if (highlightTime != null) {
      const idx = visible.findIndex((p) => Math.abs(p.timestamp - highlightTime) < 1000)
      if (idx >= 0) {
        const x = xScale(idx)
        ctx.strokeStyle = 'rgba(88, 166, 255, 0.6)'
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(x, padding.top)
        ctx.lineTo(x, height - padding.bottom)
        ctx.stroke()
      }
    }

    // 悬浮十字线
    if (hoverIdx >= 0 && hoverIdx < visible.length) {
      const x = xScale(hoverIdx)
      ctx.strokeStyle = 'rgba(88, 166, 255, 0.4)'
      ctx.lineWidth = 0.5
      ctx.beginPath()
      ctx.moveTo(x, padding.top)
      ctx.lineTo(x, height - padding.bottom)
      ctx.stroke()

      // 数据标签
      const p = visible[hoverIdx]
      ctx.fillStyle = 'rgba(22, 27, 34, 0.95)'
      const boxW = 160
      const boxH = 70
      const bx = Math.min(x + 10, width - boxW - 10)
      const by = Math.max(10, cvdY(p.cvd) - boxH - 10)
      ctx.fillRect(bx, by, boxW, boxH)
      ctx.strokeStyle = '#30363d'
      ctx.lineWidth = 1
      ctx.strokeRect(bx, by, boxW, boxH)

      ctx.fillStyle = COLORS.text
      ctx.font = '11px monospace'
      ctx.textAlign = 'left'
      ctx.fillText(`价格: ${p.price.toFixed(2)}`, bx + 8, by + 16)
      ctx.fillText(`CVD: ${p.cvd.toFixed(0)}`, bx + 8, by + 32)
      ctx.fillText(`Delta: ${p.delta >= 0 ? '+' : ''}${p.delta.toFixed(0)}`, bx + 8, by + 48)
      ctx.fillText(`成交量: ${p.volume.toFixed(0)}`, bx + 8, by + 64)

      // 点
      ctx.beginPath()
      ctx.arc(x, cvdY(p.cvd), 4, 0, Math.PI * 2)
      ctx.fillStyle = COLORS.cvdLine
      ctx.fill()
    }

    // 轴标签
    // Y 轴左 - CVD
    ctx.fillStyle = COLORS.cvdLine
    ctx.font = '10px monospace'
    ctx.textAlign = 'right'
    for (let i = 0; i <= 5; i++) {
      const v = cvdMin + (cvdRange * (5 - i)) / 5
      ctx.fillText(v.toFixed(0), padding.left - 6, padding.top + (chartH * i) / 5 + 3)
    }

    // Y 轴右 - 价格
    ctx.fillStyle = COLORS.priceLine
    ctx.textAlign = 'left'
    for (let i = 0; i <= 5; i++) {
      const v = priceMin + (priceRange * (5 - i)) / 5
      ctx.fillText(v.toFixed(2), width - padding.right + 6, padding.top + (chartH * i) / 5 + 3)
    }

    // X 轴时间
    ctx.fillStyle = COLORS.textDim
    ctx.font = '10px monospace'
    ctx.textAlign = 'center'
    const step = Math.max(1, Math.floor(visible.length / 8))
    for (let i = 0; i < visible.length; i += step) {
      const d = new Date(visible[i].timestamp)
      ctx.fillText(
        `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`,
        xScale(i),
        height - padding.bottom + 16
      )
    }

    // 标题
    ctx.fillStyle = COLORS.textDim
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText('— CVD', padding.left, 14)
    ctx.fillStyle = COLORS.priceLine
    ctx.fillText('--- 价格', padding.left + 60, 14)
  }, [visible, divergences, highlightTime, hoverIdx, mergedData, width, height])

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
      const padding = { left: 60, right: 70 }
      const chartW = width - padding.left - padding.right
      const x = e.clientX - rect.left - padding.left
      const idx = Math.round((x / chartW) * (visible.length - 1))
      setHoverIdx(idx >= 0 && idx < visible.length ? idx : -1)
    },
    [visible.length, width]
  )

  return (
    <div style={{ background: COLORS.bg, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #21262d' }}>
        <Space>
          <Text strong style={{ color: '#58a6ff' }}>
            <LineChartOutlined /> CVD 曲线
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            累计成交量差
          </Text>
          {divergences.length > 0 && (
            <Text style={{ color: '#d29922', fontSize: 11 }}>
              <AlertOutlined /> {divergences.length} 背离
            </Text>
          )}
        </Space>
        <Space>
          <Tooltip title="显示背离标记">
            <Switch size="small" defaultChecked={showDivergence} />
          </Tooltip>
        </Space>
      </div>
      <canvas
        ref={canvasRef}
        style={{ width, height, cursor: 'crosshair' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(-1)}
        onClick={() => {
          if (hoverIdx >= 0 && hoverIdx < visible.length && onPointClick) {
            onPointClick(visible[hoverIdx])
          }
        }}
      />
    </div>
  )
})

export default CVDChart
