import { useState, useMemo, useCallback } from 'react'
import {
  Card,
  Row,
  Col,
  Table,
  Button,
  Select,
  Space,
  Tag,
  Typography,
  InputNumber,
  Form,
  Modal,
  Tabs,
  Badge,
  message,
  Popconfirm,
  Divider,
} from 'antd'
import {
  LineChartOutlined,
  OrderedListOutlined,
  WalletOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { useAppStore } from '@/store'
import KLineChart from '@/components/KLineChart'
import type { Order } from '@/types'

const { Text } = Typography
const { Option } = Select

/** 模拟盘口数据 */
const generateOrderBook = () => {
  const basePrice = 68500
  const asks: Array<{ price: number; qty: number }> = []
  const bids: Array<{ price: number; qty: number }> = []
  for (let i = 0; i < 10; i++) {
    asks.push({
      price: +(basePrice + (i + 1) * (10 + Math.random() * 5)).toFixed(2),
      qty: +(Math.random() * 5 + 0.1).toFixed(4),
    })
    bids.push({
      price: +(basePrice - (i + 1) * (10 + Math.random() * 5)).toFixed(2),
      qty: +(Math.random() * 5 + 0.1).toFixed(4),
    })
  }
  return { asks: asks.reverse(), bids }
}

/** 模拟成交流水 */
const mockTrades = [
  { id: '1', time: '14:32:15', symbol: 'BTCUSDT', side: 'buy' as const, price: 68520.5, qty: 0.12, fee: 0.82 },
  { id: '2', time: '14:30:08', symbol: 'BTCUSDT', side: 'sell' as const, price: 68480.0, qty: 0.05, fee: 0.34 },
  { id: '3', time: '14:28:45', symbol: 'ETHUSDT', side: 'buy' as const, price: 3856.2, qty: 1.5, fee: 5.78 },
  { id: '4', time: '14:25:33', symbol: 'BTCUSDT', side: 'buy' as const, price: 68400.0, qty: 0.2, fee: 1.37 },
  { id: '5', time: '14:20:12', symbol: 'ETHUSDT', side: 'sell' as const, price: 3842.0, qty: 0.8, fee: 3.07 },
]

export default function TradingTerminal() {
  const tickers = useAppStore((s) => s.tickers)
  const orders = useAppStore((s) => s.orders)
  const positions = useAppStore((s) => s.positions)
  const addOrder = useAppStore((s) => s.addOrder)
  const updateOrder = useAppStore((s) => s.updateOrder)

  const [symbol, setSymbol] = useState('BTCUSDT')
  const [orderType, setOrderType] = useState<'limit' | 'market' | 'stop'>('limit')
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [price, setPrice] = useState<number>(68500)
  const [quantity, setQuantity] = useState<number>(0.1)
  const [stopPrice, setStopPrice] = useState<number>(67000)
  const [submitting, setSubmitting] = useState(false)

  const orderBook = useMemo(() => generateOrderBook(), [])
  const ticker = tickers[symbol]

  /** 提交订单 */
  const handleSubmitOrder = useCallback(async () => {
    Modal.confirm({
      title: '确认下单',
      content: (
        <div>
          <p><strong>标的：</strong>{symbol}</p>
          <p><strong>方向：</strong><Tag color={side === 'buy' ? 'green' : 'red'}>{side === 'buy' ? '买入' : '卖出'}</Tag></p>
          <p><strong>类型：</strong>{orderType === 'limit' ? '限价' : orderType === 'market' ? '市价' : '止损'}</p>
          {orderType !== 'market' && <p><strong>价格：</strong>{price}</p>}
          {orderType === 'stop' && <p><strong>触发价：</strong>{stopPrice}</p>}
          <p><strong>数量：</strong>{quantity}</p>
        </div>
      ),
      okText: '确认下单',
      cancelText: '取消',
      onOk: async () => {
        setSubmitting(true)
        try {
          const order = {
            client_order_id: `ORD-${Date.now()}`,
            symbol,
            market: 'crypto',
            side,
            order_type: orderType,
            quantity: String(quantity),
            price: orderType !== 'market' ? String(price) : null,
            status: 'pending',
            exchange: 'binance',
          }
          addOrder(order as any)
          message.success('订单已提交')
        } catch {
          message.error('下单失败，请重试')
        } finally {
          setSubmitting(false)
        }
      },
    })
  }, [symbol, side, orderType, price, quantity, stopPrice, addOrder])

  /** 撤单 */
  const handleCancelOrder = useCallback(
    (orderId: string) => {
      updateOrder(orderId, 'cancelled')
      message.success('订单已撤销')
    },
    [updateOrder]
  )

  /** 委托列表列定义 */
  const orderColumns = [
    { title: '时间', dataIndex: 'client_order_id', width: 100, render: () => new Date().toLocaleTimeString('zh-CN') },
    { title: '标的', dataIndex: 'symbol', width: 100 },
    {
      title: '方向',
      dataIndex: 'side',
      width: 70,
      render: (v: string) => (
        <Tag color={v === 'buy' ? 'green' : 'red'}>{v === 'buy' ? '买入' : '卖出'}</Tag>
      ),
    },
    { title: '类型', dataIndex: 'order_type', width: 70, render: (v: string) => v === 'limit' ? '限价' : v === 'market' ? '市价' : '止损' },
    { title: '价格', dataIndex: 'price', width: 100, render: (v: string) => v || '市价' },
    { title: '数量', dataIndex: 'quantity', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v: string) => {
        const m: Record<string, { color: string; text: string }> = {
          pending: { color: 'blue', text: '待成交' },
          filled: { color: 'green', text: '已成交' },
          cancelled: { color: 'default', text: '已撤销' },
          partial: { color: 'orange', text: '部分成交' },
        }
        const s = m[v] || { color: 'default', text: v }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '操作',
      width: 80,
      render: (_: any, record: Order) =>
        record.status === 'pending' ? (
          <Popconfirm title="确认撤销此订单？" onConfirm={() => handleCancelOrder(record.client_order_id)} okText="确认" cancelText="取消">
            <Button type="link" danger size="small">撤单</Button>
          </Popconfirm>
        ) : null,
    },
  ]

  /** 持仓列表列定义 */
  const positionColumns = [
    { title: '标的', dataIndex: 'symbol', width: 100 },
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
    { title: '数量', dataIndex: 'quantity', width: 80 },
    { title: '开仓均价', dataIndex: 'entry_price', width: 100 },
    {
      title: '浮动盈亏',
      dataIndex: 'unrealized_pnl',
      width: 100,
      render: (v: string) => {
        const n = parseFloat(v)
        return <Text style={{ color: n >= 0 ? '#52c41a' : '#ff4d4f' }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}</Text>
      },
    },
    {
      title: '已实现盈亏',
      dataIndex: 'realized_pnl',
      width: 100,
      render: (v: string) => {
        const n = parseFloat(v)
        return <Text style={{ color: n >= 0 ? '#52c41a' : '#ff4d4f' }}>{n >= 0 ? '+' : ''}{n.toFixed(2)}</Text>
      },
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Row gutter={[12, 12]}>
        {/* 左侧：K线区域 + 盘口 */}
        <Col xs={24} lg={16}>
          {/* K 线图占位 */}
          <Card
            title={
              <Space>
                <LineChartOutlined />
                <Text strong>{symbol}</Text>
                {ticker && (
                  <Text style={{ color: '#52c41a', fontSize: 18, fontWeight: 'bold' }}>
                    {parseFloat(ticker.last_price).toFixed(2)}
                  </Text>
                )}
              </Space>
            }
            size="small"
            style={{ marginBottom: 12 }}
          >
            <KLineChart
              symbol={symbol}
              lastPrice={ticker ? parseFloat(ticker.last_price) : undefined}
              height={360}
            />
          </Card>

          {/* 盘口 */}
          <Card title="📊 盘口（DOM）" size="small">
            <Row gutter={8}>
              <Col span={12}>
                <Text strong style={{ color: '#ff4d4f' }}>卖盘（Ask）</Text>
                <div style={{ marginTop: 4 }}>
                  {orderBook.asks.slice(0, 8).map((a, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '2px 4px',
                        background: `rgba(255,77,79,${0.05 + i * 0.02})`,
                        marginBottom: 1,
                        borderRadius: 2,
                        cursor: 'pointer',
                      }}
                      onClick={() => setPrice(a.price)}
                    >
                      <Text style={{ color: '#ff4d4f', fontFamily: 'monospace' }}>{a.price.toFixed(2)}</Text>
                      <Text type="secondary" style={{ fontFamily: 'monospace' }}>{a.qty.toFixed(4)}</Text>
                    </div>
                  ))}
                </div>
              </Col>
              <Col span={12}>
                <Text strong style={{ color: '#52c41a' }}>买盘（Bid）</Text>
                <div style={{ marginTop: 4 }}>
                  {orderBook.bids.slice(0, 8).map((b, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        padding: '2px 4px',
                        background: `rgba(82,196,26,${0.05 + i * 0.02})`,
                        marginBottom: 1,
                        borderRadius: 2,
                        cursor: 'pointer',
                      }}
                      onClick={() => setPrice(b.price)}
                    >
                      <Text style={{ color: '#52c41a', fontFamily: 'monospace' }}>{b.price.toFixed(2)}</Text>
                      <Text type="secondary" style={{ fontFamily: 'monospace' }}>{b.qty.toFixed(4)}</Text>
                    </div>
                  ))}
                </div>
              </Col>
            </Row>
          </Card>
        </Col>

        {/* 右侧：下单面板 */}
        <Col xs={24} lg={8}>
          <Card title="📝 下单面板" size="small">
            <Form layout="vertical" size="small">
              <Form.Item label="标的">
                <Select value={symbol} onChange={setSymbol}>
                  <Option value="BTCUSDT">BTCUSDT</Option>
                  <Option value="ETHUSDT">ETHUSDT</Option>
                  <Option value="SOLUSDT">SOLUSDT</Option>
                  <Option value="BNBUSDT">BNBUSDT</Option>
                </Select>
              </Form.Item>

              <Form.Item label="方向">
                <Space style={{ width: '100%' }}>
                  <Button
                    type={side === 'buy' ? 'primary' : 'default'}
                    style={{ flex: 1, background: side === 'buy' ? '#52c41a' : undefined, borderColor: '#52c41a' }}
                    onClick={() => setSide('buy')}
                  >
                    买入（做多）
                  </Button>
                  <Button
                    danger={side === 'sell'}
                    style={{ flex: 1 }}
                    onClick={() => setSide('sell')}
                  >
                    卖出（做空）
                  </Button>
                </Space>
              </Form.Item>

              <Form.Item label="订单类型">
                <Select value={orderType} onChange={setOrderType}>
                  <Option value="limit">限价单</Option>
                  <Option value="market">市价单</Option>
                  <Option value="stop">止损单</Option>
                </Select>
              </Form.Item>

              {orderType !== 'market' && (
                <Form.Item label="委托价格">
                  <InputNumber
                    value={price}
                    onChange={(v) => setPrice(v || 0)}
                    style={{ width: '100%' }}
                    step={0.01}
                    precision={2}
                  />
                </Form.Item>
              )}

              {orderType === 'stop' && (
                <Form.Item label="触发价格">
                  <InputNumber
                    value={stopPrice}
                    onChange={(v) => setStopPrice(v || 0)}
                    style={{ width: '100%' }}
                    step={0.01}
                    precision={2}
                  />
                </Form.Item>
              )}

              <Form.Item label="委托数量">
                <InputNumber
                  value={quantity}
                  onChange={(v) => setQuantity(v || 0)}
                  style={{ width: '100%' }}
                  step={0.01}
                  min={0.0001}
                />
              </Form.Item>

              <Divider style={{ margin: '12px 0' }} />

              <div style={{ marginBottom: 8 }}>
                <Text type="secondary">预估金额：</Text>
                <Text strong>
                  {orderType === 'market'
                    ? ticker
                      ? (parseFloat(ticker.last_price) * quantity).toFixed(2)
                      : '-'
                    : (price * quantity).toFixed(2)
                  } USDT
                </Text>
              </div>

              <Button
                type="primary"
                size="large"
                block
                loading={submitting}
                onClick={handleSubmitOrder}
                style={{
                  background: side === 'buy' ? '#52c41a' : '#ff4d4f',
                  borderColor: side === 'buy' ? '#52c41a' : '#ff4d4f',
                }}
              >
                {side === 'buy' ? '买入' : '卖出'} {orderType === 'limit' ? '限价' : orderType === 'market' ? '市价' : '止损'}
              </Button>
            </Form>
          </Card>
        </Col>
      </Row>

      {/* 底部 Tab */}
      <Card size="small" style={{ marginTop: 12 }}>
        <Tabs
          defaultActiveKey="orders"
          items={[
            {
              key: 'orders',
              label: <span><OrderedListOutlined /> 当前委托 <Badge count={orders.filter((o) => o.status === 'pending').length} size="small" /></span>,
              children: (
                <Table
                  dataSource={orders}
                  columns={orderColumns}
                  rowKey="client_order_id"
                  size="small"
                  pagination={false}
                  scroll={{ x: 700 }}
                  locale={{ emptyText: '暂无委托' }}
                />
              ),
            },
            {
              key: 'positions',
              label: <span><WalletOutlined /> 当前持仓</span>,
              children: (
                <Table
                  dataSource={positions}
                  columns={positionColumns}
                  rowKey="symbol"
                  size="small"
                  pagination={false}
                  scroll={{ x: 600 }}
                  locale={{ emptyText: '暂无持仓' }}
                />
              ),
            },
            {
              key: 'trades',
              label: <span><HistoryOutlined /> 成交流水</span>,
              children: (
                <Table
                  dataSource={mockTrades}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  scroll={{ x: 600 }}
                  locale={{ emptyText: '暂无成交' }}
                  columns={[
                    { title: '时间', dataIndex: 'time', width: 80 },
                    { title: '标的', dataIndex: 'symbol', width: 100 },
                    {
                      title: '方向',
                      dataIndex: 'side',
                      width: 70,
                      render: (v: string) => <Tag color={v === 'buy' ? 'green' : 'red'}>{v === 'buy' ? '买入' : '卖出'}</Tag>,
                    },
                    { title: '成交价', dataIndex: 'price', width: 100 },
                    { title: '数量', dataIndex: 'qty', width: 80 },
                    { title: '手续费', dataIndex: 'fee', width: 80 },
                  ]}
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
