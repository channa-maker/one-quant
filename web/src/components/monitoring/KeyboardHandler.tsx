/**
 * KeyboardHandler - 键盘流操作组件
 * 全键盘快捷键 | 切标的/切周期/下单撤单/一键平仓/一键熔断 | Cmd+K 命令面板 | 危险操作组合键+二次确认
 */
import { useRef, useEffect, useCallback, useState, memo, useMemo } from 'react'
import { Modal, Input, Typography, Space, Tag, message, Alert, type InputRef } from 'antd'
import {
  MacCommandOutlined, WarningOutlined,
  SearchOutlined, 
} from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export interface KeyBinding {
  id: string
  keys: string[]           // 按键组合，如 ['Ctrl', 'Shift', 'F']
  label: string            // 操作名称
  category: string         // 分类
  description: string      // 详细描述
  action: () => void       // 执行函数
  dangerous?: boolean      // 危险操作
  confirmMessage?: string  // 二次确认消息
  enabled?: boolean
}

export interface CommandItem {
  id: string
  label: string
  description: string
  category: string
  shortcut?: string
  action: () => void
  icon?: React.ReactNode
}

export interface KeyboardHandlerProps {
  /** 自定义快捷键绑定 */
  bindings?: KeyBinding[]
  /** 命令面板命令列表 */
  commands?: CommandItem[]
  /** 切换标的回调 */
  onSymbolSwitch?: (direction: 'prev' | 'next' | 'first' | 'last') => void
  /** 切换周期回调 */
  onPeriodSwitch?: (direction: 'prev' | 'next') => void
  /** 下单回调 */
  onQuickOrder?: (side: 'buy' | 'sell', type: 'market' | 'limit') => void
  /** 撤单回调 */
  onCancelAll?: () => void
  /** 一键平仓回调 */
  onFlattenAll?: () => void
  /** 一键熔断回调 */
  onCircuitBreak?: () => void
  /** 是否启用 */
  enabled?: boolean
}

/* ---------- 默认周期列表 ---------- */

/* ---------- 按键解析 ---------- */
function parseKeyCombo(e: KeyboardEvent): string[] {
  const keys: string[] = []
  if (e.ctrlKey || e.metaKey) keys.push('Ctrl')
  if (e.shiftKey) keys.push('Shift')
  if (e.altKey) keys.push('Alt')

  const key = e.key
  if (!['Control', 'Shift', 'Alt', 'Meta'].includes(key)) {
    keys.push(key.length === 1 ? key.toUpperCase() : key)
  }
  return keys
}

function matchKeys(pressed: string[], binding: string[]): boolean {
  if (pressed.length !== binding.length) return false
  return pressed.every((k, i) => k === binding[i])
}

function formatKeys(keys: string[]): string {
  return keys.map((k) => {
    switch (k) {
      case 'Ctrl': return navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'
      case 'Shift': return navigator.platform.includes('Mac') ? '⇧' : 'Shift'
      case 'Alt': return navigator.platform.includes('Mac') ? '⌥' : 'Alt'
      case 'ArrowUp': return '↑'
      case 'ArrowDown': return '↓'
      case 'ArrowLeft': return '←'
      case 'ArrowRight': return '→'
      case 'Escape': return 'Esc'
      case ' ': return 'Space'
      default: return k
    }
  }).join(' + ')
}

/* ---------- 组件 ---------- */
const KeyboardHandler = memo(function KeyboardHandler({
  bindings: customBindings = [],
  commands: customCommands = [],
  onSymbolSwitch,
  onPeriodSwitch,
  onQuickOrder,
  onCancelAll,
  onFlattenAll,
  onCircuitBreak,
  enabled = true,
}: KeyboardHandlerProps) {
  const [commandPanelVisible, setCommandPanelVisible] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [confirmModal, setConfirmModal] = useState<{
    visible: boolean
    title: string
    message: string
    onConfirm: () => void
  }>({ visible: false, title: '', message: '', onConfirm: () => {} })
  const [pressedKeys, setPressedKeys] = useState<string[]>([])
  const searchRef = useRef<InputRef>(null)

  // 默认快捷键绑定
  const defaultBindings: KeyBinding[] = useMemo(() => [
    {
      id: 'cmd-k',
      keys: ['Ctrl', 'K'],
      label: '命令面板',
      category: '通用',
      description: '打开命令面板，快速搜索和执行操作',
      action: () => {
        setCommandPanelVisible(true)
        setSearchQuery('')
        setSelectedIdx(0)
      },
    },
    {
      id: 'symbol-prev',
      keys: ['Ctrl', 'ArrowUp'],
      label: '上一个标的',
      category: '标的',
      description: '切换到上一个标的',
      action: () => onSymbolSwitch?.('prev'),
    },
    {
      id: 'symbol-next',
      keys: ['Ctrl', 'ArrowDown'],
      label: '下一个标的',
      category: '标的',
      description: '切换到下一个标的',
      action: () => onSymbolSwitch?.('next'),
    },
    {
      id: 'symbol-first',
      keys: ['Ctrl', 'Home'],
      label: '第一个标的',
      category: '标的',
      description: '切换到第一个标的',
      action: () => onSymbolSwitch?.('first'),
    },
    {
      id: 'symbol-last',
      keys: ['Ctrl', 'End'],
      label: '最后一个标的',
      category: '标的',
      description: '切换到最后一个标的',
      action: () => onSymbolSwitch?.('last'),
    },
    {
      id: 'period-prev',
      keys: ['['],
      label: '上一周期',
      category: '周期',
      description: '切换到上一个K线周期',
      action: () => onPeriodSwitch?.('prev'),
    },
    {
      id: 'period-next',
      keys: [']'],
      label: '下一周期',
      category: '周期',
      description: '切换到下一个K线周期',
      action: () => onPeriodSwitch?.('next'),
    },
    {
      id: 'buy-market',
      keys: ['B'],
      label: '市价买入',
      category: '交易',
      description: '以市价快速买入',
      action: () => onQuickOrder?.('buy', 'market'),
    },
    {
      id: 'sell-market',
      keys: ['S'],
      label: '市价卖出',
      category: '交易',
      description: '以市价快速卖出',
      action: () => onQuickOrder?.('sell', 'market'),
    },
    {
      id: 'buy-limit',
      keys: ['Shift', 'B'],
      label: '限价买入',
      category: '交易',
      description: '以当前价限价买入',
      action: () => onQuickOrder?.('buy', 'limit'),
    },
    {
      id: 'sell-limit',
      keys: ['Shift', 'S'],
      label: '限价卖出',
      category: '交易',
      description: '以当前价限价卖出',
      action: () => onQuickOrder?.('sell', 'limit'),
    },
    {
      id: 'cancel-all',
      keys: ['Ctrl', 'X'],
      label: '撤全部单',
      category: '交易',
      description: '撤销所有挂单',
      action: () => {
        message.warning('已撤销全部挂单')
        onCancelAll?.()
      },
    },
    {
      id: 'flatten-all',
      keys: ['Ctrl', 'Shift', 'F'],
      label: '一键平仓',
      category: '危险操作',
      description: '立即平掉所有持仓',
      dangerous: true,
      confirmMessage: '确定要一键平掉所有持仓吗？此操作不可撤销！',
      action: () => onFlattenAll?.(),
    },
    {
      id: 'circuit-break',
      keys: ['Ctrl', 'Shift', 'X'],
      label: '一键熔断',
      category: '危险操作',
      description: '立即停止所有策略并平仓',
      dangerous: true,
      confirmMessage: '⚠️ 确定要触发一键熔断吗？\n\n这将：\n1. 停止所有运行中的策略\n2. 撤销所有挂单\n3. 平掉所有持仓\n\n此操作不可撤销！',
      action: () => onCircuitBreak?.(),
    },
    {
      id: 'escape',
      keys: ['Escape'],
      label: '关闭/取消',
      category: '通用',
      description: '关闭当前弹窗或取消操作',
      action: () => {
        if (commandPanelVisible) {
          setCommandPanelVisible(false)
        }
        if (confirmModal.visible) {
          setConfirmModal((prev) => ({ ...prev, visible: false }))
        }
      },
    },
  ], [onSymbolSwitch, onPeriodSwitch, onQuickOrder, onCancelAll, onFlattenAll, onCircuitBreak, commandPanelVisible, confirmModal.visible])

  // 合并所有绑定
  const allBindings = useMemo(() => [...defaultBindings, ...customBindings], [defaultBindings, customBindings])

  // 命令列表
  const allCommands: CommandItem[] = useMemo(() => {
    const fromBindings = allBindings.map((b) => ({
      id: b.id,
      label: b.label,
      description: b.description,
      category: b.category,
      shortcut: formatKeys(b.keys),
      action: b.action,
      icon: b.dangerous ? <WarningOutlined style={{ color: '#ef4444' }} /> : undefined,
    }))
    return [...fromBindings, ...customCommands]
  }, [allBindings, customCommands])

  // 搜索过滤命令
  const filteredCommands = useMemo(() => {
    if (!searchQuery) return allCommands
    const q = searchQuery.toLowerCase()
    return allCommands.filter(
      (c) => c.label.toLowerCase().includes(q) ||
             c.description.toLowerCase().includes(q) ||
             c.category.toLowerCase().includes(q)
    )
  }, [allCommands, searchQuery])

  // 键盘事件处理
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return

      // 忽略输入框内的按键
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        // 只处理 Escape 和 Cmd+K
        if (e.key !== 'Escape' && !(e.key === 'k' && (e.ctrlKey || e.metaKey))) return
      }

      const pressed = parseKeyCombo(e)
      setPressedKeys(pressed)

      // 匹配绑定
      for (const binding of allBindings) {
        if (!binding.enabled === false) continue
        if (matchKeys(pressed, binding.keys)) {
          e.preventDefault()
          e.stopPropagation()

          // 危险操作二次确认
          if (binding.dangerous && binding.confirmMessage) {
            setConfirmModal({
              visible: true,
              title: `⚠️ ${binding.label}`,
              message: binding.confirmMessage,
              onConfirm: () => {
                binding.action()
                setConfirmModal((prev) => ({ ...prev, visible: false }))
              },
            })
          } else {
            binding.action()
          }
          return
        }
      }
    },
    [enabled, allBindings]
  )

  const handleKeyUp = useCallback(() => {
    setPressedKeys([])
  }, [])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [handleKeyDown, handleKeyUp])

  // 命令面板快捷键导航
  useEffect(() => {
    if (!commandPanelVisible) return

    const handlePanelKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIdx((prev) => Math.min(prev + 1, filteredCommands.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIdx((prev) => Math.max(prev - 1, 0))
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const cmd = filteredCommands[selectedIdx]
        if (cmd) {
          setCommandPanelVisible(false)
          cmd.action()
        }
      }
    }

    window.addEventListener('keydown', handlePanelKey)
    return () => window.removeEventListener('keydown', handlePanelKey)
  }, [commandPanelVisible, filteredCommands, selectedIdx])

  // 打开命令面板时聚焦搜索框
  useEffect(() => {
    if (commandPanelVisible) {
      setTimeout(() => searchRef.current?.focus(), 100)
    }
  }, [commandPanelVisible])

  // 按分类分组命令
  const groupedCommands = useMemo(() => {
    const groups = new Map<string, CommandItem[]>()
    for (const cmd of filteredCommands) {
      const list = groups.get(cmd.category) || []
      list.push(cmd)
      groups.set(cmd.category, list)
    }
    return groups
  }, [filteredCommands])

  return (
    <>
      {/* 命令面板 */}
      <Modal
        open={commandPanelVisible}
        onCancel={() => setCommandPanelVisible(false)}
        footer={null}
        closable={false}
        width={520}
        styles={{ body: { padding: 0, background: '#161b22', borderRadius: 8 } }}
        destroyOnClose
      >
        <div style={{ borderBottom: '1px solid #21262d' }}>
          <Input
            ref={searchRef}
            prefix={<SearchOutlined style={{ color: '#484f58' }} />}
            placeholder="搜索命令... (↑↓ 导航，Enter 执行)"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value)
              setSelectedIdx(0)
            }}
            style={{
              background: 'transparent',
              border: 'none',
              boxShadow: 'none',
              fontSize: 16,
              padding: '16px 20px',
              color: '#c9d1d9',
            }}
          />
        </div>

        <div style={{ maxHeight: 400, overflow: 'auto', padding: '8px 0' }}>
          {Array.from(groupedCommands.entries()).map(([category, cmds]) => (
            <div key={category}>
              <div style={{ padding: '6px 20px', fontSize: 11, color: '#484f58', fontWeight: 'bold', textTransform: 'uppercase' }}>
                {category}
              </div>
              {cmds.map((cmd) => {
                const globalIdx = filteredCommands.indexOf(cmd)
                const isSelected = globalIdx === selectedIdx
                return (
                  <div
                    key={cmd.id}
                    style={{
                      padding: '8px 20px',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      cursor: 'pointer',
                      background: isSelected ? 'rgba(88, 166, 255, 0.12)' : 'transparent',
                      borderLeft: isSelected ? '3px solid #58a6ff' : '3px solid transparent',
                      transition: 'all 0.1s',
                    }}
                    onClick={() => {
                      setCommandPanelVisible(false)
                      cmd.action()
                    }}
                    onMouseEnter={() => setSelectedIdx(globalIdx)}
                  >
                    <Space>
                      {cmd.icon}
                      <div>
                        <div style={{ color: '#c9d1d9', fontSize: 13 }}>{cmd.label}</div>
                        <div style={{ color: '#484f58', fontSize: 11 }}>{cmd.description}</div>
                      </div>
                    </Space>
                    {cmd.shortcut && (
                      <Tag style={{ margin: 0, fontSize: 11, background: '#21262d', borderColor: '#30363d', color: '#8b949e' }}>
                        {cmd.shortcut}
                      </Tag>
                    )}
                  </div>
                )
              })}
            </div>
          ))}

          {filteredCommands.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: '#484f58' }}>
              未找到匹配的命令
            </div>
          )}
        </div>

        <div style={{ padding: '8px 20px', borderTop: '1px solid #21262d', display: 'flex', justifyContent: 'space-between' }}>
          <Space>
            <Tag style={{ margin: 0, fontSize: 10, background: '#21262d', borderColor: '#30363d', color: '#8b949e' }}>↑↓</Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>导航</Text>
            <Tag style={{ margin: 0, fontSize: 10, background: '#21262d', borderColor: '#30363d', color: '#8b949e' }}>Enter</Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>执行</Text>
            <Tag style={{ margin: 0, fontSize: 10, background: '#21262d', borderColor: '#30363d', color: '#8b949e' }}>Esc</Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>关闭</Text>
          </Space>
          <Text type="secondary" style={{ fontSize: 11 }}>
            <MacCommandOutlined /> {filteredCommands.length} 命令
          </Text>
        </div>
      </Modal>

      {/* 危险操作确认弹窗 */}
      <Modal
        open={confirmModal.visible}
        title={confirmModal.title}
        onCancel={() => setConfirmModal((prev) => ({ ...prev, visible: false }))}
        onOk={confirmModal.onConfirm}
        okText="确认执行"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        width={420}
      >
        <Alert
          type="warning"
          showIcon
          message="此操作不可撤销，请确认"
          style={{ marginBottom: 16 }}
        />
        <div style={{ whiteSpace: 'pre-line', color: '#c9d1d9', lineHeight: 1.8 }}>
          {confirmModal.message}
        </div>
        <div style={{ marginTop: 16, padding: 8, background: '#21262d', borderRadius: 4 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            提示：按 <Tag style={{ margin: 0, fontSize: 10 }}>Esc</Tag> 取消
          </Text>
        </div>
      </Modal>

      {/* 快捷键提示条（底部） */}
      {pressedKeys.length > 0 && (
        <div style={{
          position: 'fixed',
          bottom: 20,
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'rgba(22, 27, 34, 0.95)',
          border: '1px solid #30363d',
          borderRadius: 8,
          padding: '8px 16px',
          display: 'flex',
          gap: 8,
          zIndex: 9999,
          backdropFilter: 'blur(8px)',
        }}>
          {pressedKeys.map((k, i) => (
            <Tag key={i} color="blue" style={{ margin: 0, fontSize: 13 }}>
              {k}
            </Tag>
          ))}
        </div>
      )}
    </>
  )
})

export default KeyboardHandler
