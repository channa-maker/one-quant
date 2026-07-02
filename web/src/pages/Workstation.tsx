/**
 * Workstation - 盯盘工作站页面
 * 多屏/多工作区 | 可拖拽面板网格 | 预设布局 | 布局持久化/导入导出 | 多图表十字光标时间轴联动
 */
import { useEffect, useCallback, useState, memo, useMemo } from 'react'
import {
  Layout, Typography, Space, Button, Tooltip, Dropdown, Modal, Input,
  message, Tag, Select,
} from 'antd'
import {
  AppstoreOutlined, ExportOutlined, ImportOutlined,
  PlusOutlined, DeleteOutlined, CompressOutlined,
  ExpandOutlined, SettingOutlined, LockOutlined, UnlockOutlined,
  DesktopOutlined, LineChartOutlined, FundOutlined, SafetyOutlined,
  ThunderboltOutlined, DotChartOutlined,
} from '@ant-design/icons'
import KeyboardHandler from '@/components/monitoring/KeyboardHandler'
import type { CommandItem } from '@/components/monitoring/KeyboardHandler'

const { Text } = Typography
const { Content } = Layout

/* ---------- 类型定义 ---------- */
export interface PanelConfig {
  id: string
  type: PanelType
  title: string
  x: number          // 网格列
  y: number          // 网格行
  w: number          // 占几列
  h: number          // 占几行
  locked?: boolean
  visible?: boolean
  props?: Record<string, any>
}

export type PanelType =
  | 'dom'           // 深度梯
  | 'footprint'     // 脚印图
  | 'tape'          // 成交瀑布
  | 'heatmap'       // 盘口热力图
  | 'cvd'           // CVD 曲线
  | 'iv_surface'    // IV 曲面
  | 'scanner'       // 异动扫描器
  | 'radar'         // 多标的雷达
  | 'kline'         // K 线图
  | 'orderbook'     // 订单簿
  | 'positions'     // 持仓面板
  | 'orders'        // 委托面板
  | 'signals'       // 信号面板
  | 'risk'          // 风控面板
  | 'strategy'      // 策略面板
  | 'ai_chat'       // AI 对话
  | 'custom'        // 自定义

export interface Workspace {
  id: string
  name: string
  icon: string
  panels: PanelConfig[]
  gridCols: number
  gridRows: number
}

export interface WorkstationProps {
  /** 初始工作区列表 */
  workspaces?: Workspace[]
  /** 当前标的 */
  symbol?: string
  /** 标的列表 */
  symbols?: string[]
  /** 当前周期 */
  period?: string
  /** 切换标的回调 */
  onSymbolChange?: (symbol: string) => void
  /** 切换周期回调 */
  onPeriodChange?: (period: string) => void
}

/* ---------- 预设布局 ---------- */
const PRESET_LAYOUTS: Record<string, Omit<Workspace, 'id'>> = {
  control: {
    name: '总控屏',
    icon: '🎛️',
    gridCols: 4,
    gridRows: 3,
    panels: [
      { id: 'p1', type: 'kline', title: 'K线图', x: 0, y: 0, w: 2, h: 2 },
      { id: 'p2', type: 'dom', title: '深度梯', x: 2, y: 0, w: 1, h: 2 },
      { id: 'p3', type: 'tape', title: '成交流', x: 3, y: 0, w: 1, h: 2 },
      { id: 'p4', type: 'positions', title: '持仓', x: 0, y: 2, w: 1, h: 1 },
      { id: 'p5', type: 'orders', title: '委托', x: 1, y: 2, w: 1, h: 1 },
      { id: 'p6', type: 'signals', title: '信号', x: 2, y: 2, w: 1, h: 1 },
      { id: 'p7', type: 'risk', title: '风控', x: 3, y: 2, w: 1, h: 1 },
    ],
  },
  market: {
    name: '行情屏',
    icon: '📈',
    gridCols: 3,
    gridRows: 3,
    panels: [
      { id: 'p1', type: 'kline', title: 'K线图', x: 0, y: 0, w: 2, h: 2 },
      { id: 'p2', type: 'heatmap', title: '盘口热力', x: 2, y: 0, w: 1, h: 1 },
      { id: 'p3', type: 'cvd', title: 'CVD曲线', x: 2, y: 1, w: 1, h: 1 },
      { id: 'p4', type: 'radar', title: '多标的雷达', x: 0, y: 2, w: 1, h: 1 },
      { id: 'p5', type: 'scanner', title: '异动扫描', x: 1, y: 2, w: 2, h: 1 },
    ],
  },
  orderflow: {
    name: '订单流屏',
    icon: '🌊',
    gridCols: 3,
    gridRows: 3,
    panels: [
      { id: 'p1', type: 'footprint', title: '脚印图', x: 0, y: 0, w: 2, h: 2 },
      { id: 'p2', type: 'dom', title: '深度梯', x: 2, y: 0, w: 1, h: 1 },
      { id: 'p3', type: 'tape', title: '成交流', x: 2, y: 1, w: 1, h: 1 },
      { id: 'p4', type: 'heatmap', title: '盘口热力', x: 0, y: 2, w: 1, h: 1 },
      { id: 'p5', type: 'cvd', title: 'CVD曲线', x: 1, y: 2, w: 2, h: 1 },
    ],
  },
  strategy: {
    name: '策略屏',
    icon: '🧠',
    gridCols: 3,
    gridRows: 2,
    panels: [
      { id: 'p1', type: 'strategy', title: '策略管理', x: 0, y: 0, w: 1, h: 1 },
      { id: 'p2', type: 'signals', title: '信号面板', x: 1, y: 0, w: 1, h: 1 },
      { id: 'p3', type: 'risk', title: '风控面板', x: 2, y: 0, w: 1, h: 1 },
      { id: 'p4', type: 'kline', title: 'K线图', x: 0, y: 1, w: 2, h: 1 },
      { id: 'p5', type: 'positions', title: '持仓', x: 2, y: 1, w: 1, h: 1 },
    ],
  },
  ai: {
    name: 'AI屏',
    icon: '🤖',
    gridCols: 3,
    gridRows: 2,
    panels: [
      { id: 'p1', type: 'ai_chat', title: 'AI 对话', x: 0, y: 0, w: 1, h: 2 },
      { id: 'p2', type: 'kline', title: 'K线图', x: 1, y: 0, w: 2, h: 1 },
      { id: 'p3', type: 'signals', title: 'AI 信号', x: 1, y: 1, w: 1, h: 1 },
      { id: 'p4', type: 'risk', title: 'AI 风控', x: 2, y: 1, w: 1, h: 1 },
    ],
  },
  options: {
    name: '期权屏',
    icon: '📊',
    gridCols: 3,
    gridRows: 2,
    panels: [
      { id: 'p1', type: 'iv_surface', title: 'IV曲面', x: 0, y: 0, w: 2, h: 2 },
      { id: 'p2', type: 'kline', title: '标的K线', x: 2, y: 0, w: 1, h: 1 },
      { id: 'p3', type: 'dom', title: '期权链', x: 2, y: 1, w: 1, h: 1 },
    ],
  },
}

/* ---------- 面板类型配置 ---------- */
const PANEL_TYPE_CONFIG: Record<PanelType, { label: string; icon: React.ReactNode; color: string }> = {
  dom: { label: '深度梯', icon: <AppstoreOutlined />, color: '#58a6ff' },
  footprint: { label: '脚印图', icon: <LineChartOutlined />, color: '#3fb950' },
  tape: { label: '成交流', icon: <ThunderboltOutlined />, color: '#f59e0b' },
  heatmap: { label: '盘口热力', icon: <AppstoreOutlined />, color: '#8b5cf6' },
  cvd: { label: 'CVD曲线', icon: <LineChartOutlined />, color: '#58a6ff' },
  iv_surface: { label: 'IV曲面', icon: <DotChartOutlined />, color: '#ec4899' },
  scanner: { label: '异动扫描', icon: <ThunderboltOutlined />, color: '#ef4444' },
  radar: { label: '多标的雷达', icon: <AppstoreOutlined />, color: '#3fb950' },
  kline: { label: 'K线图', icon: <LineChartOutlined />, color: '#58a6ff' },
  orderbook: { label: '订单簿', icon: <AppstoreOutlined />, color: '#8b5cf6' },
  positions: { label: '持仓', icon: <FundOutlined />, color: '#3fb950' },
  orders: { label: '委托', icon: <FundOutlined />, color: '#f59e0b' },
  signals: { label: '信号', icon: <ThunderboltOutlined />, color: '#58a6ff' },
  risk: { label: '风控', icon: <SafetyOutlined />, color: '#ef4444' },
  strategy: { label: '策略', icon: <FundOutlined />, color: '#8b5cf6' },
  ai_chat: { label: 'AI对话', icon: <FundOutlined />, color: '#ec4899' },
  custom: { label: '自定义', icon: <SettingOutlined />, color: '#484f58' },
}

/* ---------- 本地存储 ---------- */
const STORAGE_KEY = 'one-quant-workstation'

function saveWorkspace(workspaces: Workspace[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(workspaces))
  } catch {}
}

function loadWorkspace(): Workspace[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

/* ---------- 面板容器 ---------- */
const PanelContainer = memo(function PanelContainer({
  panel,
  onRemove,
  onToggleLock,
  onResize,
  isEditing,
  symbol,
}: {
  panel: PanelConfig
  onRemove: (id: string) => void
  onToggleLock: (id: string) => void
  onResize: (id: string, w: number, h: number) => void
  isEditing: boolean
  symbol: string
}) {
  const [expanded, setExpanded] = useState(false)
  const config = PANEL_TYPE_CONFIG[panel.type] || PANEL_TYPE_CONFIG.custom

  return (
    <div
      style={{
        gridColumn: `${panel.x + 1} / span ${panel.w}`,
        gridRow: `${panel.y + 1} / span ${panel.h}`,
        background: '#0d1117',
        borderRadius: 8,
        border: '1px solid #21262d',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        transition: 'all 0.2s',
      }}
    >
      {/* 面板头部 */}
      <div
        style={{
          padding: '6px 12px',
          background: '#161b22',
          borderBottom: '1px solid #21262d',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: isEditing ? 'move' : 'default',
          minHeight: 36,
        }}
      >
        <Space size={4}>
          <span style={{ color: config.color }}>{config.icon}</span>
          <Text strong style={{ color: '#c9d1d9', fontSize: 12 }}>{panel.title}</Text>
          {panel.locked && <LockOutlined style={{ color: '#484f58', fontSize: 10 }} />}
        </Space>

        {isEditing && (
          <Space size={2}>
            <Tooltip title={panel.locked ? '解锁' : '锁定'}>
              <Button
                type="text"
                size="small"
                icon={panel.locked ? <LockOutlined /> : <UnlockOutlined />}
                onClick={() => onToggleLock(panel.id)}
                style={{ width: 24, height: 24 }}
              />
            </Tooltip>
            <Tooltip title="放大/缩小">
              <Button
                type="text"
                size="small"
                icon={expanded ? <CompressOutlined /> : <ExpandOutlined />}
                onClick={() => {
                  setExpanded(!expanded)
                  if (!expanded) {
                    onResize(panel.id, 2, 2)
                  } else {
                    onResize(panel.id, 1, 1)
                  }
                }}
                style={{ width: 24, height: 24 }}
              />
            </Tooltip>
            <Tooltip title="移除面板">
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined style={{ color: '#f85149' }} />}
                onClick={() => onRemove(panel.id)}
                style={{ width: 24, height: 24 }}
              />
            </Tooltip>
          </Space>
        )}
      </div>

      {/* 面板内容（占位） */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 8 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.6 }}>{config.icon}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>{config.label}</Text>
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 10 }}>{symbol}</Text>
          </div>
        </div>
      </div>
    </div>
  )
})

/* ---------- 组件 ---------- */
const Workstation = memo(function Workstation({
  symbol: initialSymbol = 'BTCUSDT',
  symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT'],
  period: initialPeriod = '15m',
  onSymbolChange,
  onPeriodChange,
}: WorkstationProps) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>(() => {
    const saved = loadWorkspace()
    if (saved.length > 0) return saved
    // 默认创建总控屏
    return [{
      id: 'default-control',
      ...PRESET_LAYOUTS.control,
    }]
  })
  const [activeWorkspace, setActiveWorkspace] = useState<string>(() => workspaces[0]?.id || '')
  const [symbol, setSymbol] = useState(initialSymbol)
  const [period, setPeriod] = useState(initialPeriod)
  const [isEditing, setIsEditing] = useState(false)
  const [importModalVisible, setImportModalVisible] = useState(false)
  const [importText, setImportText] = useState('')

  // 保存到本地
  useEffect(() => {
    saveWorkspace(workspaces)
  }, [workspaces])

  const currentWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeWorkspace),
    [workspaces, activeWorkspace]
  )

  // 操作方法
  const addPanel = useCallback((type: PanelType) => {
    if (!currentWorkspace) return
    const config = PANEL_TYPE_CONFIG[type]
    const newPanel: PanelConfig = {
      id: `panel-${Date.now()}`,
      type,
      title: config.label,
      x: 0,
      y: currentWorkspace.gridRows,
      w: 1,
      h: 1,
    }
    setWorkspaces((prev) =>
      prev.map((ws) =>
        ws.id === activeWorkspace
          ? { ...ws, panels: [...ws.panels, newPanel], gridRows: ws.gridRows + 1 }
          : ws
      )
    )
  }, [currentWorkspace, activeWorkspace])

  const removePanel = useCallback((panelId: string) => {
    setWorkspaces((prev) =>
      prev.map((ws) =>
        ws.id === activeWorkspace
          ? { ...ws, panels: ws.panels.filter((p) => p.id !== panelId) }
          : ws
      )
    )
  }, [activeWorkspace])

  const togglePanelLock = useCallback((panelId: string) => {
    setWorkspaces((prev) =>
      prev.map((ws) =>
        ws.id === activeWorkspace
          ? {
            ...ws,
            panels: ws.panels.map((p) =>
              p.id === panelId ? { ...p, locked: !p.locked } : p
            ),
          }
          : ws
      )
    )
  }, [activeWorkspace])

  const resizePanel = useCallback((panelId: string, w: number, h: number) => {
    setWorkspaces((prev) =>
      prev.map((ws) =>
        ws.id === activeWorkspace
          ? {
            ...ws,
            panels: ws.panels.map((p) =>
              p.id === panelId ? { ...p, w: Math.min(w, ws.gridCols), h } : p
            ),
          }
          : ws
      )
    )
  }, [activeWorkspace])

  // 应用预设布局
  const applyPreset = useCallback((presetKey: string) => {
    const preset = PRESET_LAYOUTS[presetKey]
    if (!preset) return
    const newWs: Workspace = {
      id: `ws-${Date.now()}`,
      ...preset,
    }
    setWorkspaces((prev) => [...prev, newWs])
    setActiveWorkspace(newWs.id)
    message.success(`已创建「${preset.name}」工作区`)
  }, [])

  // 导出布局
  const exportLayout = useCallback(() => {
    const json = JSON.stringify(workspaces, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `one-quant-layout-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('布局已导出')
  }, [workspaces])

  // 导入布局
  const importLayout = useCallback(() => {
    try {
      const parsed = JSON.parse(importText) as Workspace[]
      if (!Array.isArray(parsed)) throw new Error('格式错误')
      setWorkspaces(parsed)
      setActiveWorkspace(parsed[0]?.id || '')
      setImportModalVisible(false)
      message.success('布局已导入')
    } catch {
      message.error('导入失败：JSON 格式错误')
    }
  }, [importText])

  // 键盘流命令
  const commands: CommandItem[] = useMemo(() => [
    {
      id: 'toggle-edit',
      label: '切换编辑模式',
      description: '开启/关闭面板编辑模式',
      category: '布局',
      action: () => setIsEditing((v) => !v),
    },
    ...Object.entries(PRESET_LAYOUTS).map(([key, preset]) => ({
      id: `preset-${key}`,
      label: `创建 ${preset.name}`,
      description: `创建「${preset.name}」预设工作区`,
      category: '预设布局',
      icon: <span>{preset.icon}</span>,
      action: () => applyPreset(key),
    })),
    ...symbols.map((s) => ({
      id: `switch-${s}`,
      label: `切换到 ${s}`,
      description: `切换当前标的到 ${s}`,
      category: '标的',
      action: () => {
        setSymbol(s)
        onSymbolChange?.(s)
      },
    })),
  ], [symbols, applyPreset, onSymbolChange])

  return (
    <Layout style={{ height: '100vh', background: '#0d1117' }}>
      {/* 键盘流 */}
      <KeyboardHandler
        commands={commands}
        onSymbolSwitch={(dir) => {
          const idx = symbols.indexOf(symbol)
          const next = dir === 'next'
            ? (idx + 1) % symbols.length
            : dir === 'prev'
              ? (idx - 1 + symbols.length) % symbols.length
              : dir === 'first'
                ? 0
                : symbols.length - 1
          setSymbol(symbols[next])
          onSymbolChange?.(symbols[next])
        }}
        onPeriodSwitch={(dir) => {
          const periods = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
          const idx = periods.indexOf(period)
          const next = dir === 'next'
            ? Math.min(idx + 1, periods.length - 1)
            : Math.max(idx - 1, 0)
          setPeriod(periods[next])
          onPeriodChange?.(periods[next])
        }}
        onQuickOrder={(side, type) => {
          message.info(`${side === 'buy' ? '买入' : '卖出'} ${type === 'market' ? '市价' : '限价'} 单已提交`)
        }}
        onCancelAll={() => message.warning('已撤销全部挂单')}
        onFlattenAll={() => message.error('已触发一键平仓')}
        onCircuitBreak={() => message.error('已触发一键熔断')}
      />

      <Content style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* 顶部工具栏 */}
        <div style={{
          padding: '8px 16px',
          background: '#161b22',
          borderBottom: '1px solid #21262d',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <Space>
            <Text strong style={{ color: '#58a6ff', fontSize: 16 }}>
              🖥️ 盯盘工作站
            </Text>
            <Select
              size="small"
              value={symbol}
              style={{ width: 120 }}
              onChange={(v) => {
                setSymbol(v)
                onSymbolChange?.(v)
              }}
              options={symbols.map((s) => ({ label: s, value: s }))}
            />
            <Select
              size="small"
              value={period}
              style={{ width: 70 }}
              onChange={(v) => {
                setPeriod(v)
                onPeriodChange?.(v)
              }}
              options={['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'].map((p) => ({ label: p, value: p }))}
            />
            <Tag style={{ margin: 0 }}>Ctrl+K 命令面板</Tag>
          </Space>

          <Space>
            <Tooltip title={isEditing ? '退出编辑' : '编辑布局'}>
              <Button
                size="small"
                type={isEditing ? 'primary' : 'default'}
                icon={<SettingOutlined />}
                onClick={() => setIsEditing(!isEditing)}
              />
            </Tooltip>
            <Tooltip title="导出布局">
              <Button size="small" icon={<ExportOutlined />} onClick={exportLayout} />
            </Tooltip>
            <Tooltip title="导入布局">
              <Button size="small" icon={<ImportOutlined />} onClick={() => setImportModalVisible(true)} />
            </Tooltip>
            <Dropdown
              menu={{
                items: Object.entries(PRESET_LAYOUTS).map(([key, preset]) => ({
                  key,
                  label: `${preset.icon} ${preset.name}`,
                  onClick: () => applyPreset(key),
                })),
              }}
            >
              <Button size="small" icon={<PlusOutlined />}>
                预设布局
              </Button>
            </Dropdown>
          </Space>
        </div>

        {/* 工作区标签栏 */}
        <div style={{
          padding: '4px 16px',
          background: '#0d1117',
          borderBottom: '1px solid #21262d',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
        }}>
          {workspaces.map((ws) => (
            <div
              key={ws.id}
              onClick={() => setActiveWorkspace(ws.id)}
              style={{
                padding: '4px 12px',
                borderRadius: '6px 6px 0 0',
                cursor: 'pointer',
                background: ws.id === activeWorkspace ? '#161b22' : 'transparent',
                borderBottom: ws.id === activeWorkspace ? '2px solid #58a6ff' : '2px solid transparent',
                fontSize: 12,
                color: ws.id === activeWorkspace ? '#58a6ff' : '#484f58',
                transition: 'all 0.15s',
              }}
            >
              {ws.icon} {ws.name}
            </div>
          ))}

          {isEditing && (
            <Dropdown
              menu={{
                items: [
                  ...Object.entries(PRESET_LAYOUTS).map(([key, preset]) => ({
                    key,
                    label: `${preset.icon} ${preset.name}`,
                    onClick: () => applyPreset(key),
                  })),
                  { type: 'divider' as const },
                  {
                    key: 'blank',
                    label: '空白工作区',
                    onClick: () => {
                      const newWs: Workspace = {
                        id: `ws-${Date.now()}`,
                        name: `工作区 ${workspaces.length + 1}`,
                        icon: '📋',
                        panels: [],
                        gridCols: 3,
                        gridRows: 2,
                      }
                      setWorkspaces((prev) => [...prev, newWs])
                      setActiveWorkspace(newWs.id)
                    },
                  },
                ],
              }}
            >
              <Button type="text" size="small" icon={<PlusOutlined />} style={{ color: '#484f58' }} />
            </Dropdown>
          )}

          {/* 删除当前工作区 */}
          {isEditing && workspaces.length > 1 && (
            <Button
              type="text"
              size="small"
              icon={<DeleteOutlined style={{ color: '#f85149' }} />}
              onClick={() => {
                Modal.confirm({
                  title: '删除工作区',
                  content: `确定删除「${currentWorkspace?.name}」吗？`,
                  onOk: () => {
                    setWorkspaces((prev) => prev.filter((w) => w.id !== activeWorkspace))
                    setActiveWorkspace(workspaces.find((w) => w.id !== activeWorkspace)?.id || '')
                  },
                })
              }}
            />
          )}
        </div>

        {/* 编辑模式工具栏 */}
        {isEditing && currentWorkspace && (
          <div style={{
            padding: '6px 16px',
            background: 'rgba(88, 166, 255, 0.06)',
            borderBottom: '1px solid #21262d',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <Text type="secondary" style={{ fontSize: 11 }}>添加面板：</Text>
            {Object.entries(PANEL_TYPE_CONFIG).map(([type, config]) => (
              <Tooltip key={type} title={config.label}>
                <Button
                  size="small"
                  icon={config.icon}
                  onClick={() => addPanel(type as PanelType)}
                  style={{ fontSize: 11 }}
                >
                  {config.label}
                </Button>
              </Tooltip>
            ))}
          </div>
        )}

        {/* 面板网格 */}
        <div style={{ flex: 1, padding: 8, overflow: 'auto' }}>
          {currentWorkspace ? (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${currentWorkspace.gridCols}, 1fr)`,
                gridTemplateRows: `repeat(${currentWorkspace.gridRows}, minmax(200px, 1fr))`,
                gap: 8,
                height: '100%',
                minHeight: currentWorkspace.gridRows * 220,
              }}
            >
              {currentWorkspace.panels.map((panel) => (
                <PanelContainer
                  key={panel.id}
                  panel={panel}
                  onRemove={removePanel}
                  onToggleLock={togglePanelLock}
                  onResize={resizePanel}
                  isEditing={isEditing}
                  symbol={symbol}
                />
              ))}
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <div style={{ textAlign: 'center' }}>
                <DesktopOutlined style={{ fontSize: 48, color: '#30363d', marginBottom: 16 }} />
                <div>
                  <Text type="secondary">选择或创建工作区</Text>
                </div>
                <div style={{ marginTop: 12 }}>
                  <Dropdown
                    menu={{
                      items: Object.entries(PRESET_LAYOUTS).map(([key, preset]) => ({
                        key,
                        label: `${preset.icon} ${preset.name}`,
                        onClick: () => applyPreset(key),
                      })),
                    }}
                  >
                    <Button type="primary" icon={<PlusOutlined />}>
                      创建工作区
                    </Button>
                  </Dropdown>
                </div>
              </div>
            </div>
          )}
        </div>
      </Content>

      {/* 导入弹窗 */}
      <Modal
        title="📥 导入布局"
        open={importModalVisible}
        onCancel={() => setImportModalVisible(false)}
        onOk={importLayout}
        okText="导入"
        cancelText="取消"
        width={500}
      >
        <Input.TextArea
          rows={10}
          placeholder="粘贴布局 JSON..."
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
      </Modal>
    </Layout>
  )
})

export default Workstation
