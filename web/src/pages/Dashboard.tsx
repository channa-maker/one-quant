import React, { useState, useEffect, useMemo } from 'react'
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
} from 'antd'
import {
  FundOutlined,
  SafetyOutlined,
  FileTextOutlined,
  AlertOutlined,
  PieChartOutlined,
} from '@ant-design/icons'
import { useAppStore } from '@/store'

const { Text, Paragraph } = Typography

/** 模拟净值数据点 */
const generateNetValueData = () => {
  const data: Array<{ date: string; value: number }> = []
  let val = 1.0
  for (let i = 30; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    val += (Math.random() - 0.45) * 0.02
    data.push({
      date: d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }),
      value: +val.toFixed(4),
    })
  }
  return data
}

/** 模拟持仓分布 */
const positionDistribution = [
  { type: 'BTC', value: 35 },
  { type: 'ETH', value: 25 },
  { type: 'A股', value: 20 },
  { type: '期权', value: 12 },
  { type: '现金', value: 8 },
]

/** 模拟风控层级 */
const riskLevels = [
  { level: 'L1', name: '日内限额', status: '正常', color: '#52c41a' },
  { level: 'L2', name: '策略限额', status: '正常', color: '#52c41a' },
  { level: 'L3', name: '账户限额', status: '预警', color: '#faad14' },
  { level: 'L4', name: '熔断机制', status: '正常', color: '#52c41a' },
]

/** 模拟 AI 研报 */
const aiReportSummary = {
  title: 'AI 每日研报摘要',
  date: new Date().toLocaleDateString('zh-CN'),
  summary: '市场情绪偏多，BTC 站稳 68000 关键支撑。建议关注 ETH/BTC 汇率反弹机会，A股半导体板块资金流入明显。风险提示：美联储议息会议临近，注意波动放大。',
  sentiment: '偏多',
  confidence: 78,
}

/** 模拟告警 */
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

export default function Dashboard() {
  const tickers = useAppStore((s) => s.tickers)
  const positions = useAppStore((s) => s.positions)
  const signals = useAppStore((s) => s.signals)
  const wsConnected = useAppStore((s) => s.wsConnected)

  const [loading, setLoading] = useState(true)
  const netValueData = useMemo(() => generateNetValueData(), [])

  useEffect(() => {
    const timer = setTimeout(() => setLoading(false), 500)
    return () => clearTimeout(timer)
  }, [])

  /** 计算总资产 */
  const totalAssets = useMemo(() => {
    const base = 1285632.45
    const tickerSum = Object.values(tickers).reduce(
      (sum, t) => sum + parseFloat(t.last_price || '0') * 0.01,
      0
    )
    return base + tickerSum
  }, [tickers])

  /** 今日盈亏 */
  const todayPnl = useMemo(() => {
    const base = 12580.32
    const rand = (Math.random() - 0.3) * 5000
    return base + rand
  }, [])

  /** 最新净值 */
  const latestNav = netValueData[netValueData.length - 1]?.value || 1.0

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="加载大盘数据中..." />
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部统计 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
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
          <Card>
            <Statistic
              title="今日盈亏"
              value={todayPnl}
              precision={2}
              prefix={todayPnl >= 0 ? '¥' : '-¥'}
              suffix={<Tag color={todayPnl >= 0 ? 'green' : 'red'}>{todayPnl >= 0 ? '盈利' : '亏损'}</Tag>}
              valueStyle={{ color: todayPnl >= 0 ? '#52c41a' : '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="最新净值"
              value={latestNav}
              precision={4}
              prefix={<FundOutlined />}
              valueStyle={{ color: latestNav >= 1 ? '#52c41a' : '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="实时持仓"
              value={positions.length || 5}
              suffix="个"
              prefix={<PieChartOutlined />}
            />
            <div style={{ marginTop: 8 }}>
              <Badge status={wsConnected ? 'success' : 'error'} text={wsConnected ? '行情已连接' : '行情断开'} />
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 净值曲线 */}
        <Col xs={24} lg={14}>
          <Card title="📈 净值曲线（近30日）">
            <div style={{ height: 200, display: 'flex', alignItems: 'flex-end', gap: 2 }}>
              {netValueData.map((d, i) => {
                const height = ((d.value - 0.95) / 0.15) * 180
                const isUp = d.value >= 1
                return (
                  <Tooltip key={i} title={`${d.date}: ${d.value}`}>
                    <div
                      style={{
                        flex: 1,
                        height: Math.max(4, height),
                        background: isUp
                          ? 'linear-gradient(to top, #52c41a, #95de64)'
                          : 'linear-gradient(to top, #ff4d4f, #ff7875)',
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

        {/* 持仓分布 */}
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

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 风险仪表盘 */}
        <Col xs={24} lg={8}>
          <Card title="🛡️ 风控状态" extra={<SafetyOutlined />}>
            {riskLevels.map((r) => (
              <div
                key={r.level}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 0',
                  borderBottom: '1px solid #303030',
                }}
              >
                <Space>
                  <Tag color={r.color}>{r.level}</Tag>
                  <Text>{r.name}</Text>
                </Space>
                <Tag color={r.status === '正常' ? 'green' : r.status === '预警' ? 'orange' : 'red'}>
                  {r.status}
                </Tag>
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
    </div>
  )
}
