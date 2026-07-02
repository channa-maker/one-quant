/**
 * Scanner - 异动扫描器组件
 * 可视化配置规则 | 命中进榜 | 推送
 */
import { useCallback, useState, memo, useMemo, useEffect } from 'react'
import {
  Typography, Space, Tag, Switch, Button, Modal, Form,
  InputNumber, Select, Badge, Tooltip, notification,
} from 'antd'
import {
  SearchOutlined, SettingOutlined, BellOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/* ---------- 类型定义 ---------- */
export type ScannerRuleType =
  | 'volume_spike'       // 放量 N 倍
  | 'breakout'           // 突破 N 日高
  | 'funding_extreme'    // 资金费率极值
  | 'big_order_flow'     // 大单净流入
  | 'iv_spike'           // IV 突变
  | 'price_needle'       // 插针

export interface ScannerRule {
  id: string
  type: ScannerRuleType
  name: string
  enabled: boolean
  params: Record<string, number>
  color: string
  icon: string
}

export interface ScannerHit {
  id: string
  ruleId: string
  ruleType: ScannerRuleType
  symbol: string
  timestamp: number
  value: number
  threshold: number
  description: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  price?: number
  change24h?: number
}

export interface ScannerProps {
  /** 扫描命中结果 */
  hits: ScannerHit[]
  /** 可用标的列表 */
  symbols?: string[]
  /** 规则变更回调 */
  onRulesChange?: (rules: ScannerRule[]) => void
  /** 点击命中回调 */
  onHitClick?: (hit: ScannerHit) => void
  /** 最大显示条数 */
  maxRows?: number
}

/* ---------- 默认规则 ---------- */
const DEFAULT_RULES: ScannerRule[] = [
  {
    id: 'vol_spike',
    type: 'volume_spike',
    name: '放量异动',
    enabled: true,
    params: { multiplier: 5, windowMin: 5 },
    color: '#f59e0b',
    icon: '🔥',
  },
  {
    id: 'breakout_high',
    type: 'breakout',
    name: '突破新高',
    enabled: true,
    params: { days: 20 },
    color: '#3fb950',
    icon: '🚀',
  },
  {
    id: 'funding_extreme',
    type: 'funding_extreme',
    name: '资金费率极值',
    enabled: true,
    params: { threshold: 0.001 },
    color: '#8b5cf6',
    icon: '💰',
  },
  {
    id: 'big_order',
    type: 'big_order_flow',
    name: '大单净流入',
    enabled: true,
    params: { minAmount: 100000 },
    color: '#58a6ff',
    icon: '🐋',
  },
  {
    id: 'iv_spike',
    type: 'iv_spike',
    name: 'IV 突变',
    enabled: true,
    params: { changePct: 20, windowMin: 15 },
    color: '#ec4899',
    icon: '📊',
  },
  {
    id: 'needle',
    type: 'price_needle',
    name: '插针检测',
    enabled: true,
    params: { deviationPct: 3, recoveryPct: 80, windowSec: 60 },
    color: '#ef4444',
    icon: '📌',
  },
]

/* ---------- 规则配置表单 ---------- */
function RuleConfigForm({
  rule,
  onChange,
}: {
  rule: ScannerRule
  onChange: (r: ScannerRule) => void
}) {
  const updateParam = (key: string, value: number) => {
    onChange({ ...rule, params: { ...rule.params, [key]: value } })
  }

  const paramLabels: Record<ScannerRuleType, Record<string, string>> = {
    volume_spike: { multiplier: '放量倍数', windowMin: '窗口(分钟)' },
    breakout: { days: '突破天数' },
    funding_extreme: { threshold: '费率阈值' },
    big_order_flow: { minAmount: '最小金额(USDT)' },
    iv_spike: { changePct: '变化幅度(%)', windowMin: '窗口(分钟)' },
    price_needle: { deviationPct: '偏离(%)', recoveryPct: '回弹(%)', windowSec: '窗口(秒)' },
  }

  const labels = paramLabels[rule.type] || {}

  return (
    <Form layout="inline" size="small">
      {Object.entries(rule.params).map(([key, val]) => (
        <Form.Item key={key} label={labels[key] || key}>
          <InputNumber
            value={val}
            onChange={(v) => v != null && updateParam(key, v)}
            style={{ width: 100 }}
            step={val < 1 ? 0.001 : 1}
          />
        </Form.Item>
      ))}
    </Form>
  )
}

/* ---------- 组件 ---------- */
const Scanner = memo(function Scanner({
  hits,
  onRulesChange,
  onHitClick,
  maxRows = 100,
}: ScannerProps) {
  const [rules, setRules] = useState<ScannerRule[]>(DEFAULT_RULES)
  const [configVisible, setConfigVisible] = useState(false)
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [soundEnabled, setSoundEnabled] = useState(true)

  // 规则变更
  const handleRuleChange = useCallback((updated: ScannerRule) => {
    setRules((prev) => {
      const next = prev.map((r) => (r.id === updated.id ? updated : r))
      onRulesChange?.(next)
      return next
    })
  }, [onRulesChange])

  const toggleRule = useCallback((id: string) => {
    setRules((prev) => {
      const next = prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r))
      onRulesChange?.(next)
      return next
    })
  }, [onRulesChange])

  // 过滤
  const filtered = useMemo(() => {
    let result = hits
    if (severityFilter !== 'all') result = result.filter((h) => h.severity === severityFilter)
    if (typeFilter !== 'all') result = result.filter((h) => h.ruleType === typeFilter)
    return result.slice(0, maxRows)
  }, [hits, severityFilter, typeFilter, maxRows])

  // 统计
  const stats = useMemo(() => {
    const critical = hits.filter((h) => h.severity === 'critical').length
    const high = hits.filter((h) => h.severity === 'high').length
    const byType = new Map<string, number>()
    for (const h of hits) byType.set(h.ruleType, (byType.get(h.ruleType) || 0) + 1)
    return { critical, high, total: hits.length, byType }
  }, [hits])

  // 严重程度颜色
  const severityColor = (s: string) => {
    switch (s) {
      case 'critical': return '#ef4444'
      case 'high': return '#f59e0b'
      case 'medium': return '#58a6ff'
      default: return '#484f58'
    }
  }

  const severityLabel = (s: string) => {
    switch (s) {
      case 'critical': return '紧急'
      case 'high': return '高'
      case 'medium': return '中'
      default: return '低'
    }
  }

  // 规则类型中文名
  const ruleTypeName = (t: ScannerRuleType) => {
    const map: Record<ScannerRuleType, string> = {
      volume_spike: '放量',
      breakout: '突破',
      funding_extreme: '费率',
      big_order_flow: '大单',
      iv_spike: 'IV突变',
      price_needle: '插针',
    }
    return map[t] || t
  }

  // 新命中提示音
  useEffect(() => {
    if (hits.length > 0 && soundEnabled) {
      const latest = hits[0]
      if (latest.severity === 'critical' || latest.severity === 'high') {
        notification.warning({
          message: `⚡ ${ruleTypeName(latest.ruleType)} 异动`,
          description: `${latest.symbol}: ${latest.description}`,
          duration: 5,
          placement: 'topRight',
        })
      }
    }
  }, [hits.length, soundEnabled])

  return (
    <div style={{ background: '#0d1117', borderRadius: 8, overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 头部 */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #21262d' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <Space>
            <Text strong style={{ color: '#58a6ff' }}>
              <SearchOutlined /> 异动扫描器
            </Text>
            <Badge count={stats.critical} size="small" offset={[0, 0]}>
              <Tag color="red" style={{ margin: 0 }}>紧急 {stats.critical}</Tag>
            </Badge>
            <Badge count={stats.high} size="small" offset={[0, 0]}>
              <Tag color="orange" style={{ margin: 0 }}>高 {stats.high}</Tag>
            </Badge>
            <Text type="secondary" style={{ fontSize: 11 }}>共 {stats.total} 条</Text>
          </Space>
          <Space>
            <Tooltip title="提示音">
              <Switch
                size="small"
                checked={soundEnabled}
                onChange={setSoundEnabled}
                checkedChildren={<BellOutlined />}
                unCheckedChildren="静音"
              />
            </Tooltip>
            <Tooltip title="规则配置">
              <Button
                size="small"
                icon={<SettingOutlined />}
                onClick={() => setConfigVisible(true)}
              />
            </Tooltip>
          </Space>
        </div>

        {/* 规则开关 */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {rules.map((rule) => (
            <Tooltip key={rule.id} title={`${rule.name} (${rule.enabled ? '开启' : '关闭'})`}>
              <Tag
                color={rule.enabled ? rule.color : 'default'}
                style={{ cursor: 'pointer', opacity: rule.enabled ? 1 : 0.4 }}
                onClick={() => toggleRule(rule.id)}
              >
                {rule.icon} {rule.name}
              </Tag>
            </Tooltip>
          ))}
        </div>
      </div>

      {/* 筛选栏 */}
      <div style={{ padding: '4px 12px', display: 'flex', gap: 8, borderBottom: '1px solid #21262d' }}>
        <Select
          size="small"
          value={severityFilter}
          style={{ width: 80 }}
          options={[
            { label: '全部', value: 'all' },
            { label: '紧急', value: 'critical' },
            { label: '高', value: 'high' },
            { label: '中', value: 'medium' },
            { label: '低', value: 'low' },
          ]}
          onChange={setSeverityFilter}
        />
        <Select
          size="small"
          value={typeFilter}
          style={{ width: 90 }}
          options={[
            { label: '全部类型', value: 'all' },
            ...rules.map((r) => ({ label: r.name, value: r.type })),
          ]}
          onChange={setTypeFilter}
        />
      </div>

      {/* 命中列表 */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <Text type="secondary">暂无异动信号</Text>
          </div>
        ) : (
          filtered.map((hit) => {
            const rule = rules.find((r) => r.id === hit.ruleId)
            return (
              <div
                key={hit.id}
                style={{
                  padding: '8px 12px',
                  borderBottom: '1px solid #21262d',
                  cursor: 'pointer',
                  transition: 'background 0.15s',
                }}
                onClick={() => onHitClick?.(hit)}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(88, 166, 255, 0.06)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space>
                    <span style={{ fontSize: 16 }}>{rule?.icon || '⚡'}</span>
                    <Text strong style={{ color: '#58a6ff' }}>{hit.symbol}</Text>
                    <Tag
                      color={severityColor(hit.severity)}
                      style={{ margin: 0, fontSize: 10, padding: '0 4px', lineHeight: '18px' }}
                    >
                      {severityLabel(hit.severity)}
                    </Tag>
                    <Tag
                      style={{
                        margin: 0,
                        fontSize: 10,
                        padding: '0 4px',
                        lineHeight: '18px',
                        background: rule?.color ? `${rule.color}22` : undefined,
                        borderColor: rule?.color,
                        color: rule?.color,
                      }}
                    >
                      {ruleTypeName(hit.ruleType)}
                    </Tag>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {new Date(hit.timestamp).toLocaleTimeString('zh-CN')}
                  </Text>
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: '#c9d1d9' }}>
                  {hit.description}
                </div>
                {hit.price != null && (
                  <div style={{ marginTop: 2, fontSize: 11, color: '#484f58' }}>
                    价格: {hit.price.toFixed(2)}
                    {hit.change24h != null && (
                      <span style={{ color: hit.change24h >= 0 ? '#3fb950' : '#f85149', marginLeft: 8 }}>
                        {hit.change24h >= 0 ? '+' : ''}{hit.change24h.toFixed(2)}%
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* 规则配置弹窗 */}
      <Modal
        title="⚡ 扫描规则配置"
        open={configVisible}
        onCancel={() => setConfigVisible(false)}
        onOk={() => setConfigVisible(false)}
        width={600}
      >
        {rules.map((rule) => (
          <div key={rule.id} style={{ marginBottom: 16, padding: 12, background: '#161b22', borderRadius: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Space>
                <span style={{ fontSize: 18 }}>{rule.icon}</span>
                <Text strong>{rule.name}</Text>
                <Tag style={{ background: `${rule.color}22`, borderColor: rule.color, color: rule.color }}>
                  {ruleTypeName(rule.type)}
                </Tag>
              </Space>
              <Switch
                size="small"
                checked={rule.enabled}
                onChange={() => toggleRule(rule.id)}
              />
            </div>
            <RuleConfigForm rule={rule} onChange={handleRuleChange} />
          </div>
        ))}
      </Modal>
    </div>
  )
})

export default Scanner
