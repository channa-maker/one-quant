/**
 * MultiSymbolRadar - 多标的雷达组件
 * 异动扫描滚动榜 | 放量/突破/插针/资金流 | 实时更新
 */
import { useRef, useEffect, useCallback, useState, memo, useMemo } from 'react'
import { Typography, Space, Tag, Badge, Select } from 'antd'
import { RadarChartOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export type RadarSignalType = 'volume' | 'breakout' | 'needle' | 'funding' | 'bigOrder' | 'ivSpike'

export interface RadarSignal {
  symbol: string
  type: RadarSignalType
  timestamp: number
  magnitude: number     // 信号强度 0-1
  description: string
  price: number
  change24h: number
  volume24h: number
}

export interface SymbolState {
  symbol: string
  price: number
  change24h: number
  volume24h: number
  signals: RadarSignal[]
  lastUpdate: number
}

export interface MultiSymbolRadarProps {
  /** 各标的状态 */
  symbols: SymbolState[]
  /** 最大显示数 */
  maxDisplay?: number
  /** 信号类型过滤 */
  signalFilter?: RadarSignalType[]
  /** 点击标的回调 */
  onSymbolClick?: (symbol: string) => void
  /** 宽度 */
  width?: number
  /** 高度 */
  height?: number
}

/* ---------- 常量 ---------- */
const SIGNAL_CONFIG: Record<RadarSignalType, { label: string; icon: string; color: string }> = {
  volume: { label: '放量', icon: '🔥', color: '#f59e0b' },
  breakout: { label: '突破', icon: '🚀', color: '#3fb950' },
  needle: { label: '插针', icon: '📌', color: '#ef4444' },
  funding: { label: '费率', icon: '💰', color: '#8b5cf6' },
  bigOrder: { label: '大单', icon: '🐋', color: '#58a6ff' },
  ivSpike: { label: 'IV', icon: '📊', color: '#ec4899' },
}

/* ---------- 组件 ---------- */
const MultiSymbolRadar = memo(function MultiSymbolRadar({
  symbols,
  maxDisplay = 30,
  onSymbolClick,
  width = 400,
  height = 600,
}: MultiSymbolRadarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const scrollRef = useRef(0)
  const [hoverIdx, setHoverIdx] = useState(-1)
  const [sortBy, setSortBy] = useState<'signals' | 'volume' | 'change'>('signals')
  const [typeFilter, setTypeFilter] = useState<RadarSignalType | 'all'>('all')

  // 排序和过滤
  const sorted = useMemo(() => {
    let result = [...symbols]

    // 信号类型过滤
    if (typeFilter !== 'all') {
      result = result.filter((s) => s.signals.some((sig) => sig.type === typeFilter))
    }

    // 排序
    switch (sortBy) {
      case 'signals':
        result.sort((a, b) => {
          const aScore = a.signals.reduce((s, sig) => s + sig.magnitude, 0)
          const bScore = b.signals.reduce((s, sig) => s + sig.magnitude, 0)
          return bScore - aScore
        })
        break
      case 'volume':
        result.sort((a, b) => b.volume24h - a.volume24h)
        break
      case 'change':
        result.sort((a, b) => Math.abs(b.change24h) - Math.abs(a.change24h))
        break
    }

    return result.slice(0, maxDisplay)
  }, [symbols, sortBy, typeFilter, maxDisplay])

  const rowHeight = 52

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)

    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, width, height)

    const scroll = scrollRef.current
    const visibleStart = Math.floor(scroll / rowHeight)
    const visibleEnd = Math.min(sorted.length, visibleStart + Math.ceil(height / rowHeight) + 1)

    for (let i = visibleStart; i < visibleEnd; i++) {
      const sym = sorted[i]
      const y = i * rowHeight - scroll

      // 行背景
      if (i === hoverIdx) {
        ctx.fillStyle = 'rgba(88, 166, 255, 0.08)'
        ctx.fillRect(0, y, width, rowHeight)
      }

      // 分割线
      ctx.strokeStyle = 'rgba(48, 54, 61, 0.4)'
      ctx.lineWidth = 0.5
      ctx.beginPath()
      ctx.moveTo(8, y + rowHeight)
      ctx.lineTo(width - 8, y + rowHeight)
      ctx.stroke()

      // 排名
      ctx.fillStyle = i < 3 ? '#d29922' : '#484f58'
      ctx.font = i < 3 ? 'bold 12px monospace' : '12px monospace'
      ctx.textAlign = 'left'
      ctx.fillText(`${i + 1}`, 8, y + 18)

      // 标的名
      ctx.fillStyle = '#58a6ff'
      ctx.font = 'bold 13px monospace'
      ctx.fillText(sym.symbol, 36, y + 18)

      // 价格和涨跌
      ctx.fillStyle = '#c9d1d9'
      ctx.font = '12px monospace'
      ctx.fillText(sym.price.toFixed(2), 140, y + 18)

      const chgColor = sym.change24h >= 0 ? '#3fb950' : '#f85149'
      ctx.fillStyle = chgColor
      ctx.font = '11px monospace'
      ctx.fillText(
        `${sym.change24h >= 0 ? '+' : ''}${sym.change24h.toFixed(2)}%`,
        230, y + 18
      )

      // 成交量
      const volStr = sym.volume24h >= 1e9
        ? (sym.volume24h / 1e9).toFixed(1) + 'B'
        : sym.volume24h >= 1e6
          ? (sym.volume24h / 1e6).toFixed(1) + 'M'
          : sym.volume24h >= 1e3
            ? (sym.volume24h / 1e3).toFixed(1) + 'K'
            : sym.volume24h.toFixed(0)
      ctx.fillStyle = '#484f58'
      ctx.font = '10px monospace'
      ctx.fillText(`Vol: ${volStr}`, 8, y + 34)

      // 信号标签
      let tagX = 140
      const recentSignals = sym.signals.slice(0, 4)
      for (const sig of recentSignals) {
        const config = SIGNAL_CONFIG[sig.type]
        if (!config) continue

        const tagW = ctx.measureText(config.icon + config.label).width + 12
        ctx.fillStyle = `${config.color}22`
        ctx.beginPath()
        const tagY = y + 26
        const r = 3
        ctx.moveTo(tagX + r, tagY)
        ctx.lineTo(tagX + tagW - r, tagY)
        ctx.arcTo(tagX + tagW, tagY, tagX + tagW, tagY + r, r)
        ctx.lineTo(tagX + tagW, tagY + 16 - r)
        ctx.arcTo(tagX + tagW, tagY + 16, tagX + tagW - r, tagY + 16, r)
        ctx.lineTo(tagX + r, tagY + 16)
        ctx.arcTo(tagX, tagY + 16, tagX, tagY + 16 - r, r)
        ctx.lineTo(tagX, tagY + r)
        ctx.arcTo(tagX, tagY, tagX + r, tagY, r)
        ctx.fill()
        ctx.strokeStyle = config.color
        ctx.lineWidth = 0.5
        ctx.stroke()

        ctx.fillStyle = config.color
        ctx.font = '10px sans-serif'
        ctx.textAlign = 'left'
        ctx.fillText(`${config.icon}${config.label}`, tagX + 4, tagY + 12)

        tagX += tagW + 4
      }

      // 信号强度指示器
      const totalStrength = sym.signals.reduce((s, sig) => s + sig.magnitude, 0)
      const maxStrength = sym.signals.length || 1
      const strengthRatio = Math.min(1, totalStrength / maxStrength)
      const barW = 40
      const barH = 4
      const barX = width - barW - 12
      const barY = y + 12

      ctx.fillStyle = 'rgba(48, 54, 61, 0.6)'
      ctx.fillRect(barX, barY, barW, barH)

      const barColor = strengthRatio > 0.7 ? '#ef4444' : strengthRatio > 0.4 ? '#f59e0b' : '#3fb950'
      ctx.fillStyle = barColor
      ctx.fillRect(barX, barY, barW * strengthRatio, barH)
    }

    // 空状态
    if (sorted.length === 0) {
      ctx.fillStyle = '#484f58'
      ctx.font = '14px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('暂无异动标的', width / 2, height / 2)
    }
  }, [sorted, hoverIdx, width, height, rowHeight])

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

  // 滚动
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const maxScroll = Math.max(0, sorted.length * rowHeight - height + 40)
    scrollRef.current = Math.max(0, Math.min(maxScroll, scrollRef.current + e.deltaY))
  }, [sorted.length, rowHeight, height])

  // 鼠标
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const y = e.clientY - rect.top + scrollRef.current
    setHoverIdx(Math.floor(y / rowHeight))
  }, [rowHeight])

  const handleClick = useCallback((_e: React.MouseEvent<HTMLCanvasElement>) => {
    if (hoverIdx >= 0 && hoverIdx < sorted.length) {
      onSymbolClick?.(sorted[hoverIdx].symbol)
    }
  }, [hoverIdx, sorted, onSymbolClick])

  // 信号统计
  const signalStats = useMemo(() => {
    const stats = new Map<RadarSignalType, number>()
    for (const sym of symbols) {
      for (const sig of sym.signals) {
        stats.set(sig.type, (stats.get(sig.type) || 0) + 1)
      }
    }
    return stats
  }, [symbols])

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 头部 */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #21262d' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Space>
            <Text strong style={{ color: '#58a6ff' }}>
              <RadarChartOutlined /> 多标的雷达
            </Text>
            <Badge count={symbols.filter((s) => s.signals.length > 0).length} size="small">
              <Tag color="blue" style={{ margin: 0 }}>活跃标的</Tag>
            </Badge>
          </Space>
          <Select
            size="small"
            value={sortBy}
            style={{ width: 80 }}
            options={[
              { label: '信号', value: 'signals' },
              { label: '成交量', value: 'volume' },
              { label: '涨跌', value: 'change' },
            ]}
            onChange={setSortBy}
          />
        </div>

        {/* 信号统计 */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <Tag
            style={{ cursor: 'pointer', opacity: typeFilter === 'all' ? 1 : 0.5 }}
            onClick={() => setTypeFilter('all')}
            color={typeFilter === 'all' ? 'blue' : undefined}
          >
            全部
          </Tag>
          {Object.entries(SIGNAL_CONFIG).map(([type, config]) => {
            const count = signalStats.get(type as RadarSignalType) || 0
            return (
              <Tag
                key={type}
                style={{
                  cursor: 'pointer',
                  opacity: typeFilter === type ? 1 : count > 0 ? 0.8 : 0.4,
                  background: typeFilter === type ? `${config.color}33` : undefined,
                  borderColor: typeFilter === type ? config.color : undefined,
                }}
                onClick={() => setTypeFilter(type as RadarSignalType)}
              >
                {config.icon} {config.label} {count}
              </Tag>
            )
          })}
        </div>
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        style={{ flex: 1, width, cursor: 'pointer' }}
        onWheel={handleWheel}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(-1)}
        onClick={handleClick}
      />
    </div>
  )
})

export default MultiSymbolRadar
