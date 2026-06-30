/**
 * Heatmap - 盘口热力图组件
 * Bookmap 风格 | 盘口挂单热力 | 流动性墙/冰山可视 | Canvas 渲染
 */
import { useRef, useEffect, useCallback, useState, memo, useMemo } from 'react'
import { Typography, Space, Switch, Slider, Select } from 'antd'
import { HeatMapOutlined, EyeOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface BookSnapshot {
  timestamp: number
  bids: { price: number; size: number }[]
  asks: { price: number; size: number }[]
}

export interface HeatmapProps {
  /** 盘口快照序列（时间升序） */
  snapshots: BookSnapshot[]
  /** 最新价 */
  lastPrice: number
  /** 价格步进 */
  tickSize: number
  /** 可见档位数（单侧） */
  depthLevels?: number
  /** 最大时间切片数 */
  maxSlices?: number
  /** 宽度 */
  width?: number
  /** 高度 */
  height?: number
  /** 是否显示流动性墙标记 */
  showWalls?: boolean
  /** 流动性墙阈值（相对均值倍数） */
  wallThreshold?: number
  /** 冰山单检测灵敏度 */
  icebergSensitivity?: number
}

/* ---------- 颜色映射 ---------- */
const HEAT_COLORS = [
  [13, 17, 23],       // 0%  - 背景色
  [22, 41, 59],       // 20%
  [26, 74, 86],       // 40%
  [32, 120, 100],     // 60%
  [64, 168, 92],      // 80%
  [150, 210, 96],     // 100%
  [255, 235, 59],     // 超量
]

function heatColor(value: number, max: number): string {
  const ratio = Math.min(1.2, value / Math.max(1, max))
  const idx = Math.min(HEAT_COLORS.length - 1, Math.floor(ratio * (HEAT_COLORS.length - 1)))
  const nextIdx = Math.min(HEAT_COLORS.length - 1, idx + 1)
  const t = ratio * (HEAT_COLORS.length - 1) - idx

  const c1 = HEAT_COLORS[idx]
  const c2 = HEAT_COLORS[nextIdx]
  const r = Math.round(c1[0] + (c2[0] - c1[0]) * t)
  const g = Math.round(c1[1] + (c2[1] - c1[1]) * t)
  const b = Math.round(c1[2] + (c2[2] - c1[2]) * t)
  return `rgb(${r},${g},${b})`
}

/* ---------- 冰山单检测 ---------- */
interface IcebergCandidate {
  price: number
  replenishCount: number   // 补单次数
  totalVolume: number      // 累计成交量
  firstSeen: number
  lastSeen: number
}

function detectIcebergs(
  snapshots: BookSnapshot[],
  tickSize: number,
  sensitivity: number
): IcebergCandidate[] {
  const candidates = new Map<number, IcebergCandidate>()

  for (let i = 1; i < snapshots.length; i++) {
    const prev = snapshots[i - 1]
    const curr = snapshots[i]

    // 检测挂单被吃后又补回的情况
    const allPrevLevels = [...prev.bids, ...prev.asks]
    const allCurrLevels = [...curr.bids, ...curr.asks]
    const currMap = new Map(allCurrLevels.map((l) => [l.price, l.size]))
    const prevMap = new Map(allPrevLevels.map((l) => [l.price, l.size]))

    for (const [price, prevSize] of prevMap) {
      const currSize = currMap.get(price) || 0
      // 如果之前量大、现在量小（被吃了），之后又补回来
      if (prevSize > 100 && currSize < prevSize * 0.3) {
        // 检查后续快照是否补回
        for (let j = i + 1; j < Math.min(i + 5, snapshots.length); j++) {
          const futureMap = new Map(
            [...snapshots[j].bids, ...snapshots[j].asks].map((l) => [l.price, l.size])
          )
          const futureSize = futureMap.get(price) || 0
          if (futureSize > prevSize * 0.5) {
            const existing = candidates.get(price)
            if (existing) {
              existing.replenishCount++
              existing.totalVolume += prevSize - currSize
              existing.lastSeen = curr.timestamp
            } else {
              candidates.set(price, {
                price,
                replenishCount: 1,
                totalVolume: prevSize - currSize,
                firstSeen: curr.timestamp,
                lastSeen: curr.timestamp,
              })
            }
            break
          }
        }
      }
    }
  }

  return Array.from(candidates.values())
    .filter((c) => c.replenishCount >= sensitivity)
    .sort((a, b) => b.totalVolume - a.totalVolume)
}

/* ---------- 组件 ---------- */
const Heatmap = memo(function Heatmap({
  snapshots,
  lastPrice,
  tickSize,
  depthLevels = 20,
  maxSlices = 120,
  width = 800,
  height = 500,
  showWalls = true,
  wallThreshold = 3,
  icebergSensitivity = 2,
}: HeatmapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null)
  const [colorScheme, setColorScheme] = useState<'green' | 'blue' | 'purple'>('green')

  // 计算价格范围
  const priceRange = useMemo(() => {
    const center = lastPrice
    const half = depthLevels * tickSize
    return { low: center - half, high: center + half }
  }, [lastPrice, depthLevels, tickSize])

  // 计算全局最大挂单量
  const globalMax = useMemo(() => {
    let max = 1
    const recent = snapshots.slice(-maxSlices)
    for (const snap of recent) {
      for (const lv of [...snap.bids, ...snap.asks]) {
        if (lv.price >= priceRange.low && lv.price <= priceRange.high) {
          max = Math.max(max, lv.size)
        }
      }
    }
    return max
  }, [snapshots, maxSlices, priceRange])

  // 流动性墙检测
  const walls = useMemo(() => {
    if (!showWalls || snapshots.length === 0) return []
    const latest = snapshots[snapshots.length - 1]
    if (!latest) return []

    const allLevels = [...latest.bids, ...latest.asks]
    const avgSize = allLevels.reduce((s, l) => s + l.size, 0) / Math.max(1, allLevels.length)
    return allLevels
      .filter((l) => l.size > avgSize * wallThreshold)
      .map((l) => ({ price: l.price, size: l.size, ratio: l.size / avgSize }))
  }, [snapshots, showWalls, wallThreshold])

  // 冰山单检测
  const icebergs = useMemo(() => {
    return detectIcebergs(snapshots, tickSize, icebergSensitivity)
  }, [snapshots, tickSize, icebergSensitivity])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)

    // 背景
    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, width, height)

    if (snapshots.length === 0) return

    const recent = snapshots.slice(-maxSlices)
    const timeSliceW = Math.max(2, (width - 80) / recent.length)
    const priceStep = tickSize
    const totalLevels = depthLevels * 2
    const levelH = Math.max(3, (height - 60) / totalLevels)

    // 绘制热力格子
    recent.forEach((snap, tIdx) => {
      const x = 60 + tIdx * timeSliceW

      // 构建价格→挂单量映射
      const sizeMap = new Map<number, number>()
      for (const lv of snap.bids) sizeMap.set(lv.price, (sizeMap.get(lv.price) || 0) + lv.size)
      for (const lv of snap.asks) sizeMap.set(lv.price, (sizeMap.get(lv.price) || 0) + lv.size)

      for (let lvl = 0; lvl < totalLevels; lvl++) {
        const price = priceRange.high - lvl * priceStep
        const size = sizeMap.get(price) || 0
        const y = 40 + lvl * levelH

        ctx.fillStyle = heatColor(size, globalMax * 0.4)
        ctx.fillRect(x, y, timeSliceW + 0.5, levelH + 0.5)
      }

      // 最新价线
      if (tIdx === recent.length - 1) {
        const priceY = 40 + ((priceRange.high - lastPrice) / priceStep) * levelH
        ctx.strokeStyle = '#58a6ff'
        ctx.lineWidth = 1
        ctx.setLineDash([4, 2])
        ctx.beginPath()
        ctx.moveTo(60, priceY)
        ctx.lineTo(width, priceY)
        ctx.stroke()
        ctx.setLineDash([])
      }
    })

    // 价格刻度
    ctx.fillStyle = '#484f58'
    ctx.font = '10px monospace'
    ctx.textAlign = 'right'
    for (let lvl = 0; lvl < totalLevels; lvl += 4) {
      const price = priceRange.high - lvl * priceStep
      const y = 40 + lvl * levelH
      ctx.fillText(price.toFixed(2), 56, y + 3)

      ctx.strokeStyle = 'rgba(48, 54, 61, 0.3)'
      ctx.lineWidth = 0.3
      ctx.beginPath()
      ctx.moveTo(60, y)
      ctx.lineTo(width, y)
      ctx.stroke()
    }

    // 时间刻度
    ctx.fillStyle = '#484f58'
    ctx.font = '10px monospace'
    ctx.textAlign = 'center'
    const timeStep = Math.max(1, Math.floor(recent.length / 6))
    for (let i = 0; i < recent.length; i += timeStep) {
      const x = 60 + i * timeSliceW
      const d = new Date(recent[i].timestamp)
      ctx.fillText(
        `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`,
        x,
        height - 8
      )
    }

    // 流动性墙标记
    if (showWalls) {
      for (const wall of walls) {
        const lvl = (priceRange.high - wall.price) / priceStep
        if (lvl < 0 || lvl >= totalLevels) continue
        const y = 40 + lvl * levelH

        ctx.strokeStyle = 'rgba(255, 215, 0, 0.8)'
        ctx.lineWidth = 2
        ctx.setLineDash([6, 3])
        ctx.beginPath()
        ctx.moveTo(60, y + levelH / 2)
        ctx.lineTo(width, y + levelH / 2)
        ctx.stroke()
        ctx.setLineDash([])

        // 标签
        ctx.fillStyle = 'rgba(255, 215, 0, 0.9)'
        ctx.font = 'bold 10px sans-serif'
        ctx.textAlign = 'left'
        ctx.fillText(`🧱 ${wall.ratio.toFixed(1)}x`, 62, y + levelH / 2 - 2)
      }
    }

    // 冰山单标记
    for (const ib of icebergs) {
      const lvl = (priceRange.high - ib.price) / priceStep
      if (lvl < 0 || lvl >= totalLevels) continue
      const y = 40 + lvl * levelH

      ctx.fillStyle = 'rgba(139, 92, 246, 0.8)'
      ctx.font = 'bold 10px sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(`🧊 x${ib.replenishCount}`, 58, y + levelH / 2 + 3)
    }

    // 悬浮信息
    if (hoverPos) {
      const tIdx = Math.floor((hoverPos.x - 60) / timeSliceW)
      const lvl = Math.floor((hoverPos.y - 40) / levelH)
      if (tIdx >= 0 && tIdx < recent.length && lvl >= 0 && lvl < totalLevels) {
        const price = priceRange.high - lvl * priceStep
        const snap = recent[tIdx]
        const sizeMap = new Map<number, number>()
        for (const lv of snap.bids) sizeMap.set(lv.price, (sizeMap.get(lv.price) || 0) + lv.size)
        for (const lv of snap.asks) sizeMap.set(lv.price, (sizeMap.get(lv.price) || 0) + lv.size)
        const size = sizeMap.get(price) || 0

        // 十字线
        ctx.strokeStyle = 'rgba(88, 166, 255, 0.4)'
        ctx.lineWidth = 0.5
        ctx.beginPath()
        ctx.moveTo(hoverPos.x, 40)
        ctx.lineTo(hoverPos.x, height - 30)
        ctx.moveTo(60, hoverPos.y)
        ctx.lineTo(width, hoverPos.y)
        ctx.stroke()

        // 信息框
        const boxW = 140
        const boxH = 50
        const bx = Math.min(hoverPos.x + 10, width - boxW - 10)
        const by = Math.max(10, hoverPos.y - boxH - 10)
        ctx.fillStyle = 'rgba(22, 27, 34, 0.95)'
        ctx.fillRect(bx, by, boxW, boxH)
        ctx.strokeStyle = '#30363d'
        ctx.lineWidth = 1
        ctx.strokeRect(bx, by, boxW, boxH)
        ctx.fillStyle = '#c9d1d9'
        ctx.font = '11px monospace'
        ctx.textAlign = 'left'
        ctx.fillText(`价格: ${price.toFixed(2)}`, bx + 8, by + 18)
        ctx.fillText(`挂单: ${size.toFixed(0)}`, bx + 8, by + 34)
      }
    }

    // 图例
    ctx.fillStyle = '#484f58'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText('挂单密度:', 60, 30)
    for (let i = 0; i < 5; i++) {
      const v = (globalMax * 0.4 * i) / 4
      ctx.fillStyle = heatColor(v, globalMax * 0.4)
      ctx.fillRect(130 + i * 30, 22, 28, 10)
    }
    ctx.fillStyle = '#484f58'
    ctx.fillText('低', 130, 42)
    ctx.fillText('高', 250, 42)
  }, [snapshots, lastPrice, tickSize, depthLevels, maxSlices, width, height, priceRange, globalMax, walls, icebergs, showWalls, hoverPos])

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

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #21262d' }}>
        <Space>
          <Text strong style={{ color: '#58a6ff' }}>
            <HeatMapOutlined /> 盘口热力图
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {snapshots.length} 快照 · {walls.length} 墙 · {icebergs.length} 冰山
          </Text>
        </Space>
        <Space>
          <Switch size="small" defaultChecked={showWalls} />
          <Text type="secondary" style={{ fontSize: 11 }}>流动性墙</Text>
        </Space>
      </div>
      <canvas
        ref={canvasRef}
        style={{ width, height, cursor: 'crosshair' }}
        onMouseMove={(e) => {
          const rect = canvasRef.current?.getBoundingClientRect()
          if (rect) setHoverPos({ x: e.clientX - rect.left, y: e.clientY - rect.top })
        }}
        onMouseLeave={() => setHoverPos(null)}
      />
    </div>
  )
})

export default Heatmap
