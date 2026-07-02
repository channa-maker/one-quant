/**
 * ONE量化 · 总览大盘
 * 总资产、盈亏、净值曲线、持仓分布、风控状态、AI研报、实时告警
 */
import { useState, useEffect, useMemo } from 'react'
import {
  Card,
  Row,
  Col,
  Statistic,
  Typography,
  Tag,
  List,
  Space,
  Progress,
  Spin,
  Badge,
  Tooltip,
  Table,
} from 'antd'
import {
  FundOutlined,
  SafetyOutlined,
  FileTextOutlined,
  AlertOutlined,
  RiseOutlined,
  FallOutlined,
} from '@ant-design/icons'
import { useAppStore } from '@/store'
import {
  mockPositions,
  mockSignals,
  generatePnlCurve,
  mockStrategies,
  mockRiskMetrics,
  mockTradingStats,
  formatMoney,
  formatPercent,
  pnlColor,
} from '@/utils/mockData'

const { Text, Paragraph } = Typography

/** 模拟持仓分布 */
const positionDistribution = [
  { type: 'BTC', value: 35 },
  { type: 'ETH', value: 25 },
  { type: 'A股', value: 20 },
  { type: '期权', value: 12 },
  { type: '现金', value: 8 },
]

/** 风控层级 */

/** AI 研报 */
const aiReportSummary = {
  title: 'AI 每日研报摘要',
  date: new Date().toLocaleDateString('zh-CN'),
  summary: '市场情绪偏多，BTC 站稳 68000 关键支撑。建议关注 ETH/BTC 汇率反弹机会，A股半导体板块资金流入明显。风险提示：美联储议息会议临近，注意波动放大。',
  sentiment: '偏多',
  confidence: 78,
}

/** 告警数据 */
const mockAlerts = [
  { id: 1, level: '高', msg: 'BTCUSDT 多头仓位接近策略限额 80%', time: '2 分钟前' },
  { id: 2, level: '中', msg: 'ETHUSDT 波动率突破 2 倍标准差', time: '15 分钟前' },
  { id: 3, level: '低', msg: '策略 TrendFollowing_A 连续亏损 3 次', time: '1 小时前' },
  { id: 4, level: '高', msg: 'L3 账户日内亏损达阈值 70%', time: '2 小时前' },
]

const alertLevelColor: Record<string, string> = {
  '高': '#ff4d4f',
  '中': '#faad14',
  '低': '#1677ff',
}

/** 信号等级颜色 */
const gradeColor: Record<string, string> = {
  S: '#FFD700',
  A: '#FF6D00',
  B: '#1677ff',
  C: '#888',
}

export default function Dashboard() {
  const tickers = useAppStore((s) => s.tickers)
  const wsConnected = useAppStore((s) => s.wsConnected)

  const [loading, setLoading] = useState(true)
  const netValueData = useMemo(() => generatePnlCurve(30), [])

  useEffect(() => {
    const timer = setTimeout(() => setLoading(false), 500)
    return () => clearTimeout(timer)
  }, [])

  /** 总资产 */
  const totalAssets = useMemo(() => {
    const base = mockTradingStats.totalAssets
    const tickerSum = Object.values(tickers).reduce(
      (sum, t) => sum + parseFloat(t.last_price || '0') * 0.01,
      0
    )
    return base + tickerSum
  }, [tickers])

  /** 今日盈亏 */
  const todayPnl = mockTradingStats.todayPnl
  const todayPnlPercent = mockTradingStats.todayPnlPercent

  /** 最新净值 */

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="加载大盘数据中..." />
      </div>
    )
  }

  // 持仓表格列
  const positionColumns = [
    { title: '标的', dataIndex: 'name', key: 'name', render: (v: string, r: any) => (
      <span><strong>{v}</strong> <Text type="secondary" style={{ fontSize: 11 }}>{r.symbol}</Text></span>
    )},
    { title: '方向', dataIndex: 'side', key: 'side', render: (v: string) => (
      <Tag color={v === 'long' ? 'green' : 'red'}>{v === 'long' ? '多头' : '空头'}</Tag>
    )},
    { title: '数量', dataIndex: 'quantity', key: 'quantity', align: 'right' as const },
    { title: '成本价', dataIndex: 'entryPrice', key: 'entryPrice', align: 'right' as const, render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '现价', dataIndex: 'currentPrice', key: 'currentPrice', align: 'right' as const, render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '盈亏', dataIndex: 'unrealizedPnl', key: 'pnl', align: 'right' as const, render: (v: number) => (
      <Text style={{ color: pnlColor(v), fontWeight: 600 }}>{formatMoney(v)}</Text>
    )},
    { title: '盈亏%', dataIndex: 'unrealizedPnlPercent', key: 'pnlPct', align: 'right' as const, render: (v: number) => (
      <Text style={{ color: pnlColor(v) }}>{formatPercent(v)}</Text>
    )},
    { title: '权重', dataIndex: 'weight', key: 'weight', align: 'right' as const, render: (v: number) => `${v}%` },
  ]

  // 最新信号表格列
  const signalColumns = [
    { title: '等级', dataIndex: 'grade', key: 'grade', render: (v: string) => (
      <Tag color={gradeColor[v]} style={{ fontWeight: 'bold' }}>{v}级</Tag>
    )},
    { title: '标的', dataIndex: 'name', key: 'name', render: (v: string, r: any) => (
      <span><strong>{v}</strong> <Text type="secondary" style={{ fontSize: 11 }}>{r.symbol}</Text></span>
    )},
    { title: '方向', dataIndex: 'direction', key: 'direction', render: (v: string) => (
      <Tag color={v === 'LONG' ? '#FF5252' : '#4CAF50'}>{v === 'LONG' ? '📈 做多' : '📉 做空'}</Tag>
    )},
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', align: 'right' as const, render: (v: number) => (
      <Text style={{ color: v >= 0.8 ? '#FFD700' : '#4FC3F7', fontWeight: 600 }}>{(v * 100).toFixed(0)}%</Text>
    )},
    { title: '入场价', dataIndex: 'entryPrice', key: 'entryPrice', align: 'right' as const, render: (v: number) => `¥${v.toLocaleString()}` },
    { title: '风险收益比', dataIndex: 'riskReward', key: 'rr', align: 'right' as const, render: (v: number) => `1:${v}` },
    { title: '策略', dataIndex: 'strategyName', key: 'strategy', render: (v: string) => <Tag>{v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', render: (v: string) => {
      const c = v === 'active' ? 'green' : v === 'executed' ? 'blue' : 'default'
      const t = v === 'active' ? '生效中' : v === 'executed' ? '已执行' : '已过期'
      return <Tag color={c}>{t}</Tag>
    }},
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* ── 顶部统计 ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="总资产（CNY）"
              value={totalAssets}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="今日盈亏"
              value={todayPnl}
              precision={2}
              prefix={todayPnl >= 0 ? <RiseOutlined /> : <FallOutlined />}
              suffix={<Tag color={todayPnl >= 0 ? 'green' : 'red'}>{formatPercent(todayPnlPercent)}</Tag>}
              valueStyle={{ color: todayPnl >= 0 ? '#ff4d4f' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="累计收益"
              value={mockTradingStats.totalPnl}
              precision={2}
              prefix="¥"
              suffix={<Tag color="blue">{formatPercent(mockTradingStats.totalPnlPercent)}</Tag>}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="夏普比率"
              value={mockTradingStats.sharpeRatio}
              precision={2}
              prefix={<FundOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
            <div style={{ marginTop: 8 }}>
              <Badge status={wsConnected ? 'success' : 'error'} text={wsConnected ? '行情已连接' : '行情断开'} />
            </div>
          </Card>
        </Col>
      </Row>

      {/* ── 净值曲线 + 持仓分布 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card
            title="📈 净值曲线（近30日）"
            extra={<Text type="secondary">最大回撤: {Math.max(...netValueData.map(d => d.drawdown)).toFixed(2)}%</Text>}
          >
            <div style={{ height: 200, display: 'flex', alignItems: 'flex-end', gap: 2 }}>
              {netValueData.map((d, i) => {
                const minVal = Math.min(...netValueData.map(n => n.value))
                const maxVal = Math.max(...netValueData.map(n => n.value))
                const range = maxVal - minVal || 1
                const height = ((d.value - minVal) / range) * 180 + 20
                const isUp = i > 0 ? d.value >= netValueData[i - 1].value : true
                return (
                  <Tooltip key={i} title={`${d.date}: ¥${d.value.toLocaleString()} | 日盈亏: ¥${d.dailyPnl.toLocaleString()}`}>
                    <div
                      style={{
                        flex: 1,
                        height: Math.max(4, height),
                        background: isUp
                          ? 'linear-gradient(to top, #ff4d4f, #ff7875)'
                          : 'linear-gradient(to top, #52c41a, #95de64)',
                        borderRadius: '2px 2px 0 0',
                        minWidth: 4,
                      }}
                    />
                  </Tooltip>
                )
              })}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>{netValueData[0]?.date}</Text>
              <Text type="secondary" style={{ fontSize: 11 }}>{netValueData[netValueData.length - 1]?.date}</Text>
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="🥧 持仓分布">
            {positionDistribution.map((item) => (
              <div key={item.type} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <Text>{item.type}</Text>
                  <Text strong>{item.value}%</Text>
                </div>
                <Progress
                  percent={item.value}
                  showInfo={false}
                  strokeColor={
                    item.type === 'BTC' ? '#f7931a'
                    : item.type === 'ETH' ? '#627eea'
                    : item.type === 'A股' ? '#ff4d4f'
                    : item.type === '期权' ? '#722ed1'
                    : '#52c41a'
                  }
                  size="small"
                />
              </div>
            ))}
          </Card>
        </Col>
      </Row>

      {/* ── 持仓明细 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card
            title="📋 持仓明细"
            extra={<Text type="secondary">共 {mockPositions.length} 个持仓</Text>}
          >
            <Table
              dataSource={mockPositions}
              columns={positionColumns}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ x: 800 }}
            />
          </Card>
        </Col>
      </Row>

      {/* ── 最新信号 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card
            title="⚡ 最新信号"
            extra={<Text type="secondary">S级信号高亮显示</Text>}
          >
            <Table
              dataSource={mockSignals}
              columns={signalColumns}
              rowKey="id"
              size="small"
              pagination={false}
              scroll={{ x: 900 }}
              rowClassName={(record) => record.grade === 'S' ? 'signal-row-s' : ''}
            />
          </Card>
        </Col>
      </Row>

      {/* ── 风控 + AI研报 + 告警 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 风险仪表盘 */}
        <Col xs={24} lg={8}>
          <Card title="🛡️ 风控状态" extra={<SafetyOutlined />}>
            {mockRiskMetrics.map((r) => (
              <div
                key={r.name}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 0',
                  borderBottom: '1px solid #303030',
                }}
              >
                <Text>{r.name}</Text>
                <Space>
                  <Text type="secondary">{r.value}{r.unit}</Text>
                  <Tag color={r.status === 'normal' ? 'green' : r.status === 'warning' ? 'orange' : 'red'}>
                    {r.status === 'normal' ? '正常' : r.status === 'warning' ? '预警' : '危险'}
                  </Tag>
                </Space>
              </div>
            ))}
          </Card>
        </Col>

        {/* AI 研报摘要 */}
        <Col xs={24} lg={8}>
          <Card title="🤖 AI 研报摘要" extra={<FileTextOutlined />}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Text type="secondary">{aiReportSummary.date}</Text>
                <Tag color="blue">{aiReportSummary.sentiment}</Tag>
              </div>
              <Paragraph ellipsis={{ rows: 4 }} style={{ marginBottom: 0 }}>
                {aiReportSummary.summary}
              </Paragraph>
              <div>
                <Text type="secondary">置信度: </Text>
                <Progress
                  percent={aiReportSummary.confidence}
                  size="small"
                  style={{ width: 120, display: 'inline-block', marginLeft: 8 }}
                />
              </div>
            </Space>
          </Card>
        </Col>

        {/* 实时告警 */}
        <Col xs={24} lg={8}>
          <Card
            title="🚨 实时告警"
            extra={<AlertOutlined />}
            styles={{ body: { maxHeight: 260, overflow: 'auto' } }}
          >
            <List
              dataSource={mockAlerts}
              renderItem={(item) => (
                <List.Item style={{ padding: '6px 0' }}>
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Tag color={alertLevelColor[item.level]}>{item.level}危</Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>{item.time}</Text>
                    </div>
                    <Text style={{ fontSize: 13 }}>{item.msg}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      {/* ── 策略概览 ── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="📊 策略概览">
            <Row gutter={[16, 16]}>
              {mockStrategies.map((st) => (
                <Col xs={24} sm={12} lg={8} xl={6} key={st.id}>
                  <Card size="small" style={{ borderLeft: `3px solid ${st.enabled ? '#52c41a' : '#888'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <Text strong>{st.name}</Text>
                      <Badge status={st.enabled ? 'success' : 'default'} text={st.enabled ? '运行中' : '已暂停'} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <Text type="secondary">今日盈亏</Text>
                      <Text style={{ color: pnlColor(st.todayPnl) }}>{formatMoney(st.todayPnl)}</Text>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <Text type="secondary">累计盈亏</Text>
                      <Text style={{ color: pnlColor(st.totalPnl) }}>{formatMoney(st.totalPnl)}</Text>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <Text type="secondary">胜率</Text>
                      <Text>{(st.winRate * 100).toFixed(0)}%</Text>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <Text type="secondary">夏普</Text>
                      <Text>{st.sharpeRatio.toFixed(2)}</Text>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Text type="secondary">最大回撤</Text>
                      <Text style={{ color: '#faad14' }}>-{st.maxDrawdown}%</Text>
                    </div>
                  </Card>
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
