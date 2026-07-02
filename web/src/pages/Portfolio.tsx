import { useEffect, useState } from 'react'
import { fetchPositions } from '@/utils/api'
import { Alert,
  Card,
  Row,
  Col,
  Typography,
  Tag,
  Table,
  Space,
  Tabs,
  Statistic,
  Descriptions,
  Badge,
  Select,
  Button,
  Tooltip,
} from 'antd'
import {
  WalletOutlined,
  FundOutlined,
  HistoryOutlined,
  BarChartOutlined,
  ReloadOutlined,
  ExportOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/** 账户列表 */
const accounts = [
  { key: 'binance', name: '币安主账户', market: '加密货币', balance: 856320.5, available: 256320.5, margin: 600000, currency: 'USDT' },
  { key: 'okx', name: 'OKX 子账户', market: '加密货币', balance: 320150.0, available: 120150.0, margin: 200000, currency: 'USDT' },
  { key: 'astock', name: 'A股账户', market: 'A股', balance: 180000.0, available: 50000.0, margin: 0, currency: 'CNY' },
  { key: 'option', name: '期权账户', market: '期权', balance: 95000.0, available: 45000.0, margin: 50000, currency: 'CNY' },
]

/** 模拟持仓数据 */
const allPositions = [
  { symbol: 'BTCUSDT', market: '加密货币', account: '币安主账户', side: 'long', qty: 2.5, entryPrice: 65800, currentPrice: 68520, unrealizedPnl: 6800, realizedPnl: 12500, margin: 164500 },
  { symbol: 'ETHUSDT', market: '加密货币', account: '币安主账户', side: 'long', qty: 15.0, entryPrice: 3720, currentPrice: 3856, unrealizedPnl: 2040, realizedPnl: 5600, margin: 55800 },
  { symbol: 'SOLUSDT', market: '加密货币', account: 'OKX 子账户', side: 'long', qty: 100, entryPrice: 145, currentPrice: 152, unrealizedPnl: 700, realizedPnl: -1200, margin: 14500 },
  { symbol: 'NVDA', market: 'A股', account: 'A股账户', side: 'long', qty: 50, entryPrice: 125, currentPrice: 132, unrealizedPnl: 350, realizedPnl: 800, margin: 0 },
  { symbol: 'BTC-28JUN-70000-C', market: '期权', account: '期权账户', side: 'long', qty: 10, entryPrice: 2800, currentPrice: 3200, unrealizedPnl: 4000, realizedPnl: 0, margin: 28000 },
  { symbol: 'BTC-28JUN-65000-P', market: '期权', account: '期权账户', side: 'short', qty: 5, entryPrice: 1500, currentPrice: 1200, unrealizedPnl: 1500, realizedPnl: 0, margin: 7500 },
]

/** 资金流水 */
const transactions = [
  { id: 1, time: '2024-06-30 14:30', type: '交易买入', account: '币安主账户', amount: -164500, symbol: 'BTCUSDT', status: '成功' },
  { id: 2, time: '2024-06-30 14:25', type: '交易卖出', account: '币安主账户', amount: +3420, symbol: 'BTCUSDT', status: '成功' },
  { id: 3, time: '2024-06-30 14:20', type: '交易买入', account: 'OKX 子账户', amount: -14500, symbol: 'SOLUSDT', status: '成功' },
  { id: 4, time: '2024-06-30 14:15', type: '资金划转', account: '币安→OKX', amount: -50000, symbol: '-', status: '成功' },
  { id: 5, time: '2024-06-30 14:00', type: '交易买入', account: 'A股账户', amount: -6250, symbol: 'NVDA', status: '成功' },
  { id: 6, time: '2024-06-30 13:50', type: '手续费', account: '币安主账户', amount: -82.5, symbol: '-', status: '扣除' },
  { id: 7, time: '2024-06-30 13:30', type: '交易卖出', account: '期权账户', amount: +7500, symbol: 'BTC-P', status: '成功' },
]

/** Greeks 聚合数据 */
const greeks = [
  { name: 'Delta', value: 12.5, description: '标的资产价格变动敏感度', unit: '' },
  { name: 'Gamma', value: 0.35, description: 'Delta 的变化率', unit: '' },
  { name: 'Theta', value: -185.0, description: '时间衰减（每日）', unit: 'CNY' },
  { name: 'Vega', value: 420.0, description: '波动率敏感度', unit: 'CNY' },
  { name: 'Rho', value: 28.5, description: '利率敏感度', unit: 'CNY' },
]

export default function Portfolio() {
  const [positions, setPositions] = useState(allPositions)
  const [live, setLive] = useState(false)

  // 挂载时尝试拉取后端真实持仓;不可达则保留演示数据
  useEffect(() => {
    fetchPositions()
      .then((res) => {
        const list = (res as { data?: unknown })?.data
        if (Array.isArray(list) && list.length > 0) {
          setPositions(
            list.map((it: Record<string, any>) => ({
              symbol: String(it.symbol ?? ''),
              market: String(it.market ?? ''),
              account: String(it.exchange ?? '默认账户'),
              side: it.side === 'short' ? 'short' : 'long',
              qty: Number(it.quantity ?? 0),
              entryPrice: Number(it.entry_price ?? 0),
              currentPrice: Number(it.current_price ?? it.entry_price ?? 0),
              unrealizedPnl: Number(it.unrealized_pnl ?? 0),
              realizedPnl: Number(it.realized_pnl ?? 0),
              margin: Number(it.margin ?? 0),
            }))
          )
          setLive(true)
        }
      })
      .catch(() => {/* 后端未连接:保留演示数据 */})
  }, [])

  const [selectedAccount, setSelectedAccount] = useState<string>('all')

  const filteredPositions = selectedAccount === 'all'
    ? positions
    : positions.filter((p) => p.account === accounts.find((a) => a.key === selectedAccount)?.name)

  /** 总资产 */
  const totalBalance = accounts.reduce((sum, a) => sum + a.balance, 0)
  const totalAvailable = accounts.reduce((sum, a) => sum + a.available, 0)
  const totalMargin = accounts.reduce((sum, a) => sum + a.margin, 0)
  const totalUnrealizedPnl = positions.reduce((sum, p) => sum + p.unrealizedPnl, 0)

  const positionColumns = [
    { title: '标的', dataIndex: 'symbol', width: 160, render: (v: string) => <Text strong>{v}</Text> },
    { title: '市场', dataIndex: 'market', width: 80, render: (v: string) => <Tag>{v}</Tag> },
    { title: '账户', dataIndex: 'account', width: 120 },
    {
      title: '方向',
      dataIndex: 'side',
      width: 70,
      render: (v: string) => (
        <Tag color={v === 'long' ? 'green' : v === 'short' ? 'red' : 'default'}>
          {v === 'long' ? '多头' : v === 'short' ? '空头' : '空仓'}
        </Tag>
      ),
    },
    { title: '数量', dataIndex: 'qty', width: 80 },
    {
      title: '开仓均价',
      dataIndex: 'entryPrice',
      width: 100,
      render: (v: number) => v.toLocaleString('zh-CN', { minimumFractionDigits: 2 }),
    },
    {
      title: '当前价',
      dataIndex: 'currentPrice',
      width: 100,
      render: (v: number) => v.toLocaleString('zh-CN', { minimumFractionDigits: 2 }),
    },
    {
      title: '浮动盈亏',
      dataIndex: 'unrealizedPnl',
      width: 110,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
          {v >= 0 ? '+' : ''}¥{v.toLocaleString()}
        </Text>
      ),
      sorter: (a: any, b: any) => a.unrealizedPnl - b.unrealizedPnl,
    },
    {
      title: '已实现盈亏',
      dataIndex: 'realizedPnl',
      width: 110,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? '+' : ''}¥{v.toLocaleString()}
        </Text>
      ),
    },
    {
      title: '占用保证金',
      dataIndex: 'margin',
      width: 100,
      render: (v: number) => v > 0 ? <Text>¥{v.toLocaleString()}</Text> : <Text type="secondary">-</Text>,
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {!live && (
        <Alert
          type="warning"
          showIcon
          message="当前为演示数据 · 后端连接后自动切换为实时持仓"
          style={{ marginBottom: 16 }}
        />
      )}
      {/* 账户总览 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="总资产"
              value={totalBalance}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="可用资金"
              value={totalAvailable}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="占用保证金"
              value={totalMargin}
              precision={2}
              prefix="¥"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="总浮动盈亏"
              value={totalUnrealizedPnl}
              precision={2}
              prefix={totalUnrealizedPnl >= 0 ? '+¥' : '-¥'}
              valueStyle={{ color: totalUnrealizedPnl >= 0 ? '#52c41a' : '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      <Tabs
        defaultActiveKey="positions"
        items={[
          {
            key: 'positions',
            label: <span><WalletOutlined /> 持仓明细</span>,
            children: (
              <Card
                extra={
                  <Space>
                    <Select
                      value={selectedAccount}
                      onChange={setSelectedAccount}
                      style={{ width: 160 }}
                      options={[
                        { value: 'all', label: '全部账户' },
                        ...accounts.map((a) => ({ value: a.key, label: a.name })),
                      ]}
                    />
                    <Button icon={<ReloadOutlined />}>刷新</Button>
                  </Space>
                }
              >
                <Table
                  dataSource={filteredPositions}
                  columns={positionColumns}
                  rowKey="symbol"
                  size="small"
                  scroll={{ x: 1100 }}
                  pagination={false}
                  summary={(data) => {
                    const totalUnrealized = data.reduce((s, r) => s + r.unrealizedPnl, 0)
                    const totalRealized = data.reduce((s, r) => s + r.realizedPnl, 0)
                    return (
                      <Table.Summary.Row>
                        <Table.Summary.Cell index={0} colSpan={7}>
                          <Text strong>合计</Text>
                        </Table.Summary.Cell>
                        <Table.Summary.Cell index={7}>
                          <Text strong style={{ color: totalUnrealized >= 0 ? '#52c41a' : '#ff4d4f' }}>
                            {totalUnrealized >= 0 ? '+' : ''}¥{totalUnrealized.toLocaleString()}
                          </Text>
                        </Table.Summary.Cell>
                        <Table.Summary.Cell index={8}>
                          <Text strong style={{ color: totalRealized >= 0 ? '#52c41a' : '#ff4d4f' }}>
                            {totalRealized >= 0 ? '+' : ''}¥{totalRealized.toLocaleString()}
                          </Text>
                        </Table.Summary.Cell>
                        <Table.Summary.Cell index={9} />
                      </Table.Summary.Row>
                    )
                  }}
                />
              </Card>
            ),
          },
          {
            key: 'accounts',
            label: <span><FundOutlined /> 账户概览</span>,
            children: (
              <Row gutter={[16, 16]}>
                {accounts.map((acc) => (
                  <Col xs={24} lg={12} key={acc.key}>
                    <Card title={acc.name} extra={<Tag>{acc.market}</Tag>}>
                      <Descriptions column={2} size="small" bordered>
                        <Descriptions.Item label="总余额">
                          <Text strong>{acc.currency === 'USDT' ? '$' : '¥'}{acc.balance.toLocaleString()}</Text>
                        </Descriptions.Item>
                        <Descriptions.Item label="可用资金">
                          <Text style={{ color: '#52c41a' }}>{acc.currency === 'USDT' ? '$' : '¥'}{acc.available.toLocaleString()}</Text>
                        </Descriptions.Item>
                        <Descriptions.Item label="占用保证金">
                          {acc.margin > 0 ? `${acc.currency === 'USDT' ? '$' : '¥'}${acc.margin.toLocaleString()}` : '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="资金使用率">
                          <Badge
                            status={((acc.balance - acc.available) / acc.balance) > 0.8 ? 'warning' : 'success'}
                            text={`${(((acc.balance - acc.available) / acc.balance) * 100).toFixed(1)}%`}
                          />
                        </Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
          {
            key: 'greeks',
            label: <span><BarChartOutlined /> Greeks 聚合</span>,
            children: (
              <Card title="📐 期权 Greeks 聚合（全账户）">
                <Row gutter={[16, 16]}>
                  {greeks.map((g) => (
                    <Col xs={12} sm={8} key={g.name}>
                      <Card size="small">
                        <Statistic
                          title={
                            <Tooltip title={g.description}>
                              <Text>{g.name}</Text>
                            </Tooltip>
                          }
                          value={g.value}
                          precision={2}
                          valueStyle={{
                            color: g.value >= 0 ? '#52c41a' : '#ff4d4f',
                            fontSize: 24,
                          }}
                        />
                      </Card>
                    </Col>
                  ))}
                </Row>
                <Alert
                  style={{ marginTop: 16 }}
                  message="Greeks 说明"
                  description="Delta: 标的价格敏感度 | Gamma: Delta 变化率 | Theta: 时间衰减 | Vega: 波动率敏感度 | Rho: 利率敏感度"
                  type="info"
                  showIcon
                />
              </Card>
            ),
          },
          {
            key: 'transactions',
            label: <span><HistoryOutlined /> 资金流水</span>,
            children: (
              <Card extra={<Button icon={<ExportOutlined />}>导出</Button>}>
                <Table
                  dataSource={transactions}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '时间', dataIndex: 'time', width: 150 },
                    { title: '类型', dataIndex: 'type', width: 100, render: (v: string) => <Tag>{v}</Tag> },
                    { title: '账户', dataIndex: 'account', width: 120 },
                    { title: '标的', dataIndex: 'symbol', width: 100 },
                    {
                      title: '金额',
                      dataIndex: 'amount',
                      width: 120,
                      render: (v: number) => (
                        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
                          {v >= 0 ? '+' : ''}¥{v.toLocaleString()}
                        </Text>
                      ),
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 80,
                      render: (v: string) => <Tag color={v === '成功' ? 'green' : 'orange'}>{v}</Tag>,
                    },
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
