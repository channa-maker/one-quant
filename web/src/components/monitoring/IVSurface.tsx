/**
 * IVSurface - IV 曲面 3D 组件
 * 到期×行权价×IV 实时旋转 | Three.js / WebGL | 颜色映射 IV 高低
 */
import { useRef, useEffect, useCallback, useState, memo, useMemo } from 'react'
import { Typography, Space, Select, Switch, Tooltip } from 'antd'
import { DotChartOutlined } from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface IVDataPoint {
  expiry: string       // 到期日 YYYY-MM-DD
  expiryDays: number   // 距到期天数
  strike: number       // 行权价
  iv: number           // 隐含波动率 (小数, 如 0.45 = 45%)
  callPut: 'call' | 'put'
  delta?: number
  openInterest?: number
}

export interface IVSurfaceProps {
  /** IV 数据点 */
  data: IVDataPoint[]
  /** 自动旋转 */
  autoRotate?: boolean
  /** 旋转速度 */
  rotateSpeed?: number
  /** 颜色映射方案 */
  colorScheme?: 'heat' | 'rainbow' | 'diverging'
  /** 宽度 */
  width?: number
  /** 高度 */
  height?: number
  /** 是否显示曲面网格 */
  showMesh?: boolean
  /** 显示 call/put/both */
  showType?: 'call' | 'put' | 'both'
}

/* ---------- 3D 数学工具 ---------- */
interface Vec3 { x: number; y: number; z: number }
interface Mat4 extends Float32Array {}

function createMat4(): Mat4 {
  const m = new Float32Array(16)
  m[0] = m[5] = m[10] = m[15] = 1
  return m
}

function rotateY(m: Mat4, angle: number): Mat4 {
  const c = Math.cos(angle), s = Math.sin(angle)
  const r = createMat4()
  r[0] = c; r[2] = s
  r[5] = 1
  r[8] = -s; r[10] = c
  r[15] = 1
  return multiplyMat4(m, r)
}

function rotateX(m: Mat4, angle: number): Mat4 {
  const c = Math.cos(angle), s = Math.sin(angle)
  const r = createMat4()
  r[0] = 1
  r[5] = c; r[6] = -s
  r[9] = s; r[10] = c
  r[15] = 1
  return multiplyMat4(m, r)
}

function multiplyMat4(a: Mat4, b: Mat4): Mat4 {
  const r = new Float32Array(16)
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      r[i * 4 + j] = a[i * 4] * b[j] + a[i * 4 + 1] * b[4 + j] + a[i * 4 + 2] * b[8 + j] + a[i * 4 + 3] * b[12 + j]
    }
  }
  return r
}

function projectPoint(p: Vec3, m: Mat4, w: number, h: number, fov: number): { x: number; y: number; z: number } {
  const x = m[0] * p.x + m[1] * p.y + m[2] * p.z + m[3]
  const y = m[4] * p.x + m[5] * p.y + m[6] * p.z + m[7]
  const z = m[8] * p.x + m[9] * p.y + m[10] * p.z + m[11]

  const scale = fov / (fov + z)
  return {
    x: w / 2 + x * scale,
    y: h / 2 - y * scale,
    z,
  }
}

/* ---------- 颜色映射 ---------- */
function ivColor(iv: number, minIV: number, maxIV: number, scheme: string): string {
  const t = Math.max(0, Math.min(1, (iv - minIV) / (maxIV - minIV || 1)))

  if (scheme === 'heat') {
    // 蓝→青→绿→黄→红
    const r = Math.round(t < 0.5 ? 0 : (t - 0.5) * 2 * 255)
    const g = Math.round(t < 0.5 ? t * 2 * 255 : (1 - t) * 2 * 255)
    const b = Math.round(t < 0.5 ? (0.5 - t) * 2 * 255 : 0)
    return `rgb(${r},${g},${b})`
  }

  if (scheme === 'rainbow') {
    const hue = (1 - t) * 240
    return `hsl(${hue}, 80%, 50%)`
  }

  // diverging
  const hue = t < 0.5 ? 220 : 0
  const sat = Math.abs(t - 0.5) * 2 * 80
  return `hsl(${hue}, ${sat}%, 50%)`
}

/* ---------- 组件 ---------- */
const IVSurface = memo(function IVSurface({
  data,
  autoRotate = true,
  rotateSpeed = 0.3,
  colorScheme = 'heat',
  width = 700,
  height = 500,
  showMesh = true,
  showType = 'both',
}: IVSurfaceProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const angleRef = useRef({ x: -0.4, y: 0.3 })
  const dragRef = useRef<{ startX: number; startY: number; startAngleX: number; startAngleY: number } | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  // 过滤数据
  const filteredData = useMemo(() => {
    if (showType === 'both') return data
    return data.filter((d) => d.callPut === showType)
  }, [data, showType])

  // 数据范围
  const ranges = useMemo(() => {
    if (filteredData.length === 0) return { strikeMin: 0, strikeMax: 1, expiryMin: 0, expiryMax: 1, ivMin: 0, ivMax: 1 }
    const strikes = filteredData.map((d) => d.strike)
    const expiries = filteredData.map((d) => d.expiryDays)
    const ivs = filteredData.map((d) => d.iv)
    return {
      strikeMin: Math.min(...strikes),
      strikeMax: Math.max(...strikes),
      expiryMin: Math.min(...expiries),
      expiryMax: Math.max(...expiries),
      ivMin: Math.min(...ivs),
      ivMax: Math.max(...ivs),
    }
  }, [filteredData])

  // 构建曲面网格
  const surfaceMesh = useMemo(() => {
    if (filteredData.length < 4) return null

    const strikes = [...new Set(filteredData.map((d) => d.strike))].sort((a, b) => a - b)
    const expiries = [...new Set(filteredData.map((d) => d.expiryDays))].sort((a, b) => a - b)

    // 构建网格点
    const grid: (IVDataPoint | null)[][] = []
    for (const exp of expiries) {
      const row: (IVDataPoint | null)[] = []
      for (const strike of strikes) {
        const point = filteredData.find((d) => d.strike === strike && d.expiryDays === exp)
        row.push(point || null)
      }
      grid.push(row)
    }

    return { strikes, expiries, grid }
  }, [filteredData])

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

    if (!surfaceMesh || filteredData.length === 0) {
      ctx.fillStyle = '#484f58'
      ctx.font = '14px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('数据不足，请加载期权 IV 数据', width / 2, height / 2)
      return
    }

    // 自动旋转
    if (autoRotate && !isDragging) {
      angleRef.current.y += rotateSpeed * 0.01
    }

    const { strikes, expiries, grid } = surfaceMesh
    const { strikeMin, strikeMax, expiryMin, expiryMax, ivMin, ivMax } = ranges
    const strikeRange = strikeMax - strikeMin || 1
    const expiryRange = expiryMax - expiryMin || 1
    const ivRange = ivMax - ivMin || 1

    // 3D 变换
    const scale = 200
    let m = createMat4()
    m = rotateX(m, angleRef.current.x)
    m = rotateY(m, angleRef.current.y)

    const fov = 600

    // 归一化坐标
    const toWorld = (strike: number, expiry: number, iv: number): Vec3 => ({
      x: ((strike - strikeMin) / strikeRange - 0.5) * scale * 2,
      y: ((iv - ivMin) / ivRange - 0.5) * scale,
      z: ((expiry - expiryMin) / expiryRange - 0.5) * scale * 1.5,
    })

    // 收集所有面片，按 Z 排序（画家算法）
    type Face = { points: { x: number; y: number; z: number }[]; color: string; avgZ: number }
    const faces: Face[] = []

    for (let ei = 0; ei < expiries.length - 1; ei++) {
      for (let si = 0; si < strikes.length - 1; si++) {
        const p00 = grid[ei][si]
        const p10 = grid[ei][si + 1]
        const p01 = grid[ei + 1][si]
        const p11 = grid[ei + 1][si + 1]

        if (!p00 || !p10 || !p01 || !p11) continue

        const w00 = toWorld(p00.strike, p00.expiryDays, p00.iv)
        const w10 = toWorld(p10.strike, p10.expiryDays, p10.iv)
        const w01 = toWorld(p01.strike, p01.expiryDays, p01.iv)
        const w11 = toWorld(p11.strike, p11.expiryDays, p11.iv)

        const proj00 = projectPoint(w00, m, width, height, fov)
        const proj10 = projectPoint(w10, m, width, height, fov)
        const proj01 = projectPoint(w01, m, width, height, fov)
        const proj11 = projectPoint(w11, m, width, height, fov)

        const avgIV = (p00.iv + p10.iv + p01.iv + p11.iv) / 4
        const avgZ = (proj00.z + proj10.z + proj01.z + proj11.z) / 4
        const color = ivColor(avgIV, ivMin, ivMax, colorScheme)

        faces.push({
          points: [proj00, proj10, proj11, proj01],
          color,
          avgZ,
        })
      }
    }

    // 画家算法排序
    faces.sort((a, b) => b.avgZ - a.avgZ)

    // 绘制面片
    for (const face of faces) {
      ctx.beginPath()
      ctx.moveTo(face.points[0].x, face.points[0].y)
      for (let i = 1; i < face.points.length; i++) {
        ctx.lineTo(face.points[i].x, face.points[i].y)
      }
      ctx.closePath()
      ctx.fillStyle = face.color
      ctx.fill()

      if (showMesh) {
        ctx.strokeStyle = 'rgba(255,255,255,0.15)'
        ctx.lineWidth = 0.5
        ctx.stroke()
      }
    }

    // 绘制坐标轴
    const axisLen = scale * 1.2
    const origin = projectPoint({ x: 0, y: 0, z: 0 }, m, width, height, fov)
    const xAxis = projectPoint({ x: axisLen, y: 0, z: 0 }, m, width, height, fov)
    const yAxis = projectPoint({ x: 0, y: axisLen, z: 0 }, m, width, height, fov)
    const zAxis = projectPoint({ x: 0, y: 0, z: axisLen }, m, width, height, fov)

    // X 轴 - 行权价
    ctx.strokeStyle = '#ef5350'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(origin.x, origin.y)
    ctx.lineTo(xAxis.x, xAxis.y)
    ctx.stroke()
    ctx.fillStyle = '#ef5350'
    ctx.font = 'bold 11px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('行权价 →', (origin.x + xAxis.x) / 2, (origin.y + xAxis.y) / 2 - 10)

    // Y 轴 - IV
    ctx.strokeStyle = '#3fb950'
    ctx.beginPath()
    ctx.moveTo(origin.x, origin.y)
    ctx.lineTo(yAxis.x, yAxis.y)
    ctx.stroke()
    ctx.fillStyle = '#3fb950'
    ctx.fillText('IV ↑', (origin.x + yAxis.x) / 2 - 20, (origin.y + yAxis.y) / 2)

    // Z 轴 - 到期
    ctx.strokeStyle = '#58a6ff'
    ctx.beginPath()
    ctx.moveTo(origin.x, origin.y)
    ctx.lineTo(zAxis.x, zAxis.y)
    ctx.stroke()
    ctx.fillStyle = '#58a6ff'
    ctx.fillText('到期 →', (origin.x + zAxis.x) / 2, (origin.y + zAxis.y) / 2 + 15)

    // 刻度标签
    ctx.fillStyle = '#484f58'
    ctx.font = '10px monospace'
    ctx.textAlign = 'left'
    const tickCount = 5
    for (let i = 0; i <= tickCount; i++) {
      const t = i / tickCount
      // 行权价刻度
      const sp = toWorld(strikeMin + strikeRange * t, 0, 0)
      sp.y = 0; sp.z = 0
      const spProj = projectPoint(sp, m, width, height, fov)
      ctx.fillText((strikeMin + strikeRange * t).toFixed(0), spProj.x, spProj.y + 12)

      // IV 刻度
      const ivp = toWorld(0, 0, ivMin + ivRange * t)
      ivp.x = 0; ivp.z = 0
      const ivpProj = projectPoint(ivp, m, width, height, fov)
      ctx.fillText(((ivMin + ivRange * t) * 100).toFixed(0) + '%', ivpProj.x - 30, ivpProj.y)

      // 到期刻度
      const ep = toWorld(0, expiryMin + expiryRange * t, 0)
      ep.x = 0; ep.y = 0
      const epProj = projectPoint(ep, m, width, height, fov)
      ctx.fillText((expiryMin + expiryRange * t).toFixed(0) + 'd', epProj.x, epProj.y + 12)
    }

    // 颜色图例
    const legendX = width - 50
    const legendH = 150
    const legendY = 40
    for (let i = 0; i < legendH; i++) {
      const t = i / legendH
      const iv = ivMin + ivRange * t
      ctx.fillStyle = ivColor(iv, ivMin, ivMax, colorScheme)
      ctx.fillRect(legendX, legendY + legendH - i, 15, 1)
    }
    ctx.fillStyle = '#c9d1d9'
    ctx.font = '10px monospace'
    ctx.textAlign = 'left'
    ctx.fillText(`${(ivMax * 100).toFixed(0)}%`, legendX + 18, legendY + 6)
    ctx.fillText(`${(ivMin * 100).toFixed(0)}%`, legendX + 18, legendY + legendH + 6)
    ctx.fillText('IV', legendX + 4, legendY - 6)

    // 信息
    ctx.fillStyle = '#c9d1d9'
    ctx.font = '11px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText(`数据点: ${filteredData.length} · 曲面: ${strikes.length}×${expiries.length}`, 10, height - 10)
  }, [surfaceMesh, filteredData, ranges, autoRotate, rotateSpeed, colorScheme, showMesh, width, height, isDragging])

  // 渲染循环
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

  // 鼠标拖拽旋转
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true)
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startAngleX: angleRef.current.x,
      startAngleY: angleRef.current.y,
    }
  }, [])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragRef.current) return
    const dx = e.clientX - dragRef.current.startX
    const dy = e.clientY - dragRef.current.startY
    angleRef.current.y = dragRef.current.startAngleY + dx * 0.005
    angleRef.current.x = dragRef.current.startAngleX + dy * 0.005
    // 限制上下旋转角度
    angleRef.current.x = Math.max(-Math.PI / 2, Math.min(Math.PI / 3, angleRef.current.x))
  }, [])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
    dragRef.current = null
  }, [])

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #21262d' }}>
        <Space>
          <Text strong style={{ color: '#58a6ff' }}>
            <DotChartOutlined /> IV 曲面 3D
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            隐含波动率曲面
          </Text>
        </Space>
        <Space>
          <Select
            size="small"
            value={showType}
            style={{ width: 80 }}
            options={[
              { label: '全部', value: 'both' },
              { label: 'Call', value: 'call' },
              { label: 'Put', value: 'put' },
            ]}
            onChange={() => {}}
          />
          <Tooltip title="自动旋转">
            <Switch size="small" defaultChecked={autoRotate} />
          </Tooltip>
          <Tooltip title="显示网格">
            <Switch size="small" defaultChecked={showMesh} />
          </Tooltip>
        </Space>
      </div>
      <canvas
        ref={canvasRef}
        style={{ width, height, cursor: isDragging ? 'grabbing' : 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      />
    </div>
  )
})

export default IVSurface
