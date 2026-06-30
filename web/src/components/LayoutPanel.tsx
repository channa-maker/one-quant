import React, { useState, useCallback, useRef, useEffect } from 'react'
import { Card, Button, Space, Tooltip, Dropdown, Modal, message, Typography } from 'antd'
import {
  DragOutlined,
  FullscreenOutlined,
  ExportOutlined,
  ImportOutlined,
  CloseOutlined,
  CompressOutlined,
  PlusOutlined,
  SettingOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/** 面板配置 */
export interface PanelConfig {
  id: string
  title: string
  x: number
  y: number
  width: number
  height: number
  minW?: number
  minH?: number
  content?: React.ReactNode
  closable?: boolean
  floating?: boolean
}

/** 布局配置 */
export interface LayoutConfig {
  name: string
  panels: Omit<PanelConfig, 'content'>[]
  createdAt: number
}

interface LayoutPanelProps {
  panels: PanelConfig[]
  onLayoutChange?: (panels: PanelConfig[]) => void
  onPanelClose?: (id: string) => void
  onPanelFloat?: (id: string) => void
  gridCols?: number
  gridRows?: number
  gap?: number
}

/** 拖拽状态 */
interface DragState {
  panelId: string
  startX: number
  startY: number
  startPanelX: number
  startPanelY: number
}

/** 缩放状态 */
interface ResizeState {
  panelId: string
  startX: number
  startY: number
  startW: number
  startH: number
}

const GRID_SIZE = 20

export const LayoutPanel: React.FC<LayoutPanelProps> = ({
  panels,
  onLayoutChange,
  onPanelClose,
  onPanelFloat,
  gridCols = 24,
  gridRows = 12,
  gap = 8,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [resizeState, setResizeState] = useState<ResizeState | null>(null)
  const [layouts, setLayouts] = useState<LayoutConfig[]>(() => {
    try {
      const saved = localStorage.getItem('one-quant-layouts')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })

  /** 对齐到网格 */
  const snapToGrid = useCallback((val: number, max: number) => {
    return Math.max(0, Math.min(Math.round(val / GRID_SIZE) * GRID_SIZE, max))
  }, [])

  /** 鼠标按下 - 拖拽 */
  const handleDragStart = useCallback((e: React.MouseEvent, panel: PanelConfig) => {
    e.preventDefault()
    setDragState({
      panelId: panel.id,
      startX: e.clientX,
      startY: e.clientY,
      startPanelX: panel.x,
      startPanelY: panel.y,
    })
  }, [])

  /** 鼠标按下 - 缩放 */
  const handleResizeStart = useCallback((e: React.MouseEvent, panel: PanelConfig) => {
    e.preventDefault()
    e.stopPropagation()
    setResizeState({
      panelId: panel.id,
      startX: e.clientX,
      startY: e.clientY,
      startW: panel.width,
      startH: panel.height,
    })
  }, [])

  /** 全局鼠标移动 */
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (dragState && onLayoutChange) {
        const dx = e.clientX - dragState.startX
        const dy = e.clientY - dragState.startY
        const containerRect = containerRef.current?.getBoundingClientRect()
        const maxW = containerRect?.width || 800
        const maxH = containerRect?.height || 600

        const updated = panels.map((p) =>
          p.id === dragState.panelId
            ? {
                ...p,
                x: snapToGrid(dragState.startPanelX + dx, maxW - p.width),
                y: snapToGrid(dragState.startPanelY + dy, maxH - p.height),
              }
            : p
        )
        onLayoutChange(updated)
      }

      if (resizeState && onLayoutChange) {
        const dx = e.clientX - resizeState.startX
        const dy = e.clientY - resizeState.startY

        const updated = panels.map((p) =>
          p.id === resizeState.panelId
            ? {
                ...p,
                width: Math.max(p.minW || 200, snapToGrid(resizeState.startW + dx, 2000)),
                height: Math.max(p.minH || 150, snapToGrid(resizeState.startH + dy, 1500)),
              }
            : p
        )
        onLayoutChange(updated)
      }
    }

    const handleMouseUp = () => {
      setDragState(null)
      setResizeState(null)
    }

    if (dragState || resizeState) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragState, resizeState, panels, onLayoutChange, snapToGrid])

  /** 保存当前布局 */
  const saveLayout = useCallback(() => {
    const name = `布局 ${new Date().toLocaleString('zh-CN')}`
    const layout: LayoutConfig = {
      name,
      panels: panels.map(({ content, ...rest }) => rest),
      createdAt: Date.now(),
    }
    const updated = [...layouts, layout]
    setLayouts(updated)
    localStorage.setItem('one-quant-layouts', JSON.stringify(updated))
    message.success('布局已保存')
  }, [panels, layouts])

  /** 加载布局 */
  const loadLayout = useCallback(
    (layout: LayoutConfig) => {
      if (onLayoutChange) {
        const restored = layout.panels.map((p) => ({
          ...p,
          content: panels.find((op) => op.id === p.id)?.content,
        })) as PanelConfig[]
        onLayoutChange(restored)
        message.success(`已加载布局: ${layout.name}`)
      }
    },
    [panels, onLayoutChange]
  )

  /** 导出为 JSON */
  const exportLayout = useCallback(() => {
    const data: LayoutConfig = {
      name: '导出布局',
      panels: panels.map(({ content, ...rest }) => rest),
      createdAt: Date.now(),
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `one-quant-layout-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('布局已导出')
  }, [panels])

  /** 从 JSON 导入 */
  const importLayout = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = (ev) => {
        try {
          const data: LayoutConfig = JSON.parse(ev.target?.result as string)
          loadLayout(data)
        } catch {
          message.error('无效的布局文件')
        }
      }
      reader.readAsText(file)
    }
    input.click()
  }, [loadLayout])

  /** 面板弹出为独立窗口 */
  const floatPanel = useCallback(
    (id: string) => {
      if (onPanelFloat) onPanelFloat(id)
      message.info('面板已弹出为独立窗口')
    },
    [onPanelFloat]
  )

  return (
    <div>
      {/* 工具栏 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
          padding: '4px 0',
        }}
      >
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <DragOutlined /> 拖拽面板调整位置，拖拽右下角缩放
          </Text>
        </Space>
        <Space>
          <Tooltip title="保存当前布局">
            <Button size="small" icon={<SettingOutlined />} onClick={saveLayout}>
              保存布局
            </Button>
          </Tooltip>
          {layouts.length > 0 && (
            <Dropdown
              menu={{
                items: layouts.map((l, i) => ({
                  key: i,
                  label: l.name,
                  onClick: () => loadLayout(l),
                })),
              }}
            >
              <Button size="small">加载布局</Button>
            </Dropdown>
          )}
          <Tooltip title="导出为 JSON">
            <Button size="small" icon={<ExportOutlined />} onClick={exportLayout} />
          </Tooltip>
          <Tooltip title="从 JSON 导入">
            <Button size="small" icon={<ImportOutlined />} onClick={importLayout} />
          </Tooltip>
        </Space>
      </div>

      {/* 面板容器 */}
      <div
        ref={containerRef}
        style={{
          position: 'relative',
          width: '100%',
          minHeight: 600,
          background: '#1a1a1a',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        {panels.map((panel) => (
          <div
            key={panel.id}
            style={{
              position: 'absolute',
              left: panel.x,
              top: panel.y,
              width: panel.width,
              height: panel.height,
              transition: dragState?.panelId === panel.id || resizeState?.panelId === panel.id
                ? 'none'
                : 'all 0.2s ease',
              zIndex: dragState?.panelId === panel.id ? 100 : 1,
            }}
          >
            <Card
              size="small"
              style={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                background: '#1f1f1f',
                border: '1px solid #303030',
              }}
              styles={{
                body: { flex: 1, overflow: 'auto', padding: 8 },
                header: { cursor: 'move', userSelect: 'none' },
              }}
              title={
                <span
                  onMouseDown={(e) => handleDragStart(e, panel)}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                >
                  <DragOutlined style={{ fontSize: 12, color: '#8c8c8c' }} />
                  {panel.title}
                </span>
              }
              extra={
                <Space size={4}>
                  <Tooltip title="弹出为独立窗口">
                    <Button
                      type="text"
                      size="small"
                      icon={<FullscreenOutlined />}
                      onClick={() => floatPanel(panel.id)}
                    />
                  </Tooltip>
                  {panel.closable !== false && onPanelClose && (
                    <Tooltip title="关闭面板">
                      <Button
                        type="text"
                        size="small"
                        icon={<CloseOutlined />}
                        onClick={() => onPanelClose(panel.id)}
                      />
                    </Tooltip>
                  )}
                </Space>
              }
            >
              {panel.content}
            </Card>

            {/* 缩放手柄 */}
            <div
              onMouseDown={(e) => handleResizeStart(e, panel)}
              style={{
                position: 'absolute',
                right: 0,
                bottom: 0,
                width: 16,
                height: 16,
                cursor: 'nwse-resize',
                background: 'linear-gradient(135deg, transparent 50%, #404040 50%)',
                borderRadius: '0 0 4px 0',
              }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

export default LayoutPanel
