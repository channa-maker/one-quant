import React, { useState, useCallback } from 'react'
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
  Switch,
  Modal,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  message,
  Tabs,
  Progress,
  Tooltip,
  Badge,
  Row,
  Col,
  Statistic,
} from 'antd'
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  ExperimentOutlined,
  TrophyOutlined,
  ThunderboltOutlined,
  EditOutlined,
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography

/** 策略数据 */
interface Strategy {
  key: string
  name: string
  status: 'running' | 'paused' | 'error' | 'backtesting'
  type: string
  market: string
  pnl: number
  pnlRate: number
  winRate: number
  sharpe: number
  maxDrawdown: number
  trades: number
  champion: boolean
  params: Record<string, any>
  description: string
}

const initialStrategies: Strategy[] = [
  {
    key: '1',
    name: '趋势跟踪A',
    status: 'running',
    type: '趋势',
    market: 'BTC/ETH',
    pnl: 45680.5,
    pnlRate: 15.2,
    winRate: 62.5,
    sharpe: 1.85,
    maxDrawdown: -8.3,
    trades: 128,
    champion: true,
    params: { period: 20, atr_mult: 2.0, risk_per_trade: 0.02 },
    description: '基于均线和ATR的趋势跟踪策略，适合中长期持仓',
  },
  {
    key: '2',
    name: '均值回归B',
    status: 'running',
    type: '均值回归',
    market: 'ETH',
    pnl: 12350.2,
    pnlRate: 8.7,
    winRate: 71.3,
    sharpe: 2.12,
    maxDrawdown: -5.1,
    trades: 89,
    champion: false,
    params: { lookback: 50, z_entry: 2.0, z_exit: 0.5 },
    description: '基于布林带的均值回归策略，适合震荡行情',
  },
  {
    key: '3',
    name: '套利策略C',
    status: 'paused',
    type: '套利',
    market: 'BTC',
    pnl: -2150.0,
    pnlRate: -3.2,
    winRate: 45.0,
    sharpe: 0.35,
    maxDrawdown: -12.5,
    trades: 45,
    champion: false,
    params: { spread_threshold: 0.001, max_hold: 3600 },
    description: '跨交易所价差套利，当前市场条件不利已暂停',
  },
  {
    key: '4',
    name: '动量突破D',
    status: 'error',
    type: '动量',
    market: 'A股',
    pnl: 8920.0,
    pnlRate: 6.1,
    winRate: 55.8,
    sharpe: 1.23,
    maxDrawdown: -9.8,
    trades: 67,
    champion: false,
    params: { breakout_period: 20, volume_mult: 1.5 },
    description: '量价突破策略，当前因数据源异常暂停',
  },
  {
    key: '5',
    name: '挑战者E',
    status: 'backtesting',
    type: '趋势',
    market: 'BTC/ETH/SOL',
    pnl: 0,
    pnlRate: 0,
    winRate: 58.2,
    sharpe: 1.67,
    maxDrawdown: -7.2,
    trades: 0,
    champion: false,
    params: { period: 15, risk_per_trade: 0.015 },
    description: '新开发的趋势跟踪策略，正在回测验证中',
  },
]

const statusMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  running: { color: 'green', text: '运行中', icon: <PlayCircleOutlined /> },
  paused: { color: 'orange', text: '已暂停', icon: <PauseCircleOutlined /> },
  error: { color: 'red', text: '异常', icon: <ThunderboltOutlined /> },
  backtesting: { color: 'blue', text: '回测中', icon: <ExperimentOutlined /> },
}

export default function StrategyManagement() {
  const [strategies, setStrategies] = useState<Strategy[]>(initialStrategies)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null)
  const [form] = Form.useForm()

  /** 切换策略启停 */
  const toggleStrategy = useCallback(
    (key: string) => {
      setStrategies((prev) =>
        prev.map((s) => {
          if (s.key !== key) return s
          const newStatus = s.status === 'running' ? 'paused' : s.status === 'paused' ? 'running' : s.status
          if (newStatus === s.status) {
            message.warning('当前状态无法切换')
            return s
          }
          message.success(`策略「${s.name}」已${newStatus === 'running' ? '启动' : '暂停'}`)
          return { ...s, status: newStatus }
        })
      )
    },
    []
  )

  /** 编辑策略参数 */
  const openEdit = useCallback(
    (strategy: Strategy) => {
      setEditingStrategy(strategy)
      form.setFieldsValue({
        name: strategy.name,
        description: strategy.description,
        ...strategy.params,
      })
      setEditModalOpen(true)
    },
    [form]
  )

  const handleSaveParams = useCallback(() => {
    form.validateFields().then((values) => {
      const { name, description, ...params } = values
      setStrategies((prev) =>
        prev.map((s) =>
          s.key === editingStrategy?.key
            ? { ...s, name, description, params }
            : s
        )
      )
      setEditModalOpen(false)
      message.success('策略参数已更新')
    })
  }, [form, editingStrategy])

  /** 删除策略 */
  const deleteStrategy = useCallback(
    (key: string) => {
      setStrategies((prev) => prev.filter((s) => s.key !== key))
      message.success('策略已删除')
    },
    []
  )

  const columns = [
    {
      title: '策略名称',
      dataIndex: 'name',
      width: 150,
      render: (name: string, record: Strategy) => (
        <Space>
          {record.champion && (
            <Tooltip title="当前冠军策略">
              <TrophyOutlined style={{ color: '#faad14' }} />
            </Tooltip>
          )}
          <Text strong>{name}</Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '市场',
      dataIndex: 'market',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => {
        const s = statusMap[status]
        return (
          <Badge status={s.color as any} text={<Space>{s.icon}{s.text}</Space>} />
        )
      },
    },
    {
      title: '累计盈亏',
      dataIndex: 'pnl',
      width: 120,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
          {v >= 0 ? '+' : ''}{v.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
        </Text>
      ),
      sorter: (a: Strategy, b: Strategy) => a.pnl - b.pnl,
    },
    {
      title: '收益率',
      dataIndex: 'pnlRate',
      width: 90,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? '+' : ''}{v}%
        </Text>
      ),
      sorter: (a: Strategy, b: Strategy) => a.pnlRate - b.pnlRate,
    },
    {
      title: '胜率',
      dataIndex: 'winRate',
      width: 80,
      render: (v: number) => <Progress percent={v} size="small" style={{ width: 60 }} />,
      sorter: (a: Strategy, b: Strategy) => a.winRate - b.winRate,
    },
    {
      title: '夏普比',
      dataIndex: 'sharpe',
      width: 80,
      render: (v: number) => <Text>{v.toFixed(2)}</Text>,
      sorter: (a: Strategy, b: Strategy) => a.sharpe - b.sharpe,
    },
    {
      title: '最大回撤',
      dataIndex: 'maxDrawdown',
      width: 90,
      render: (v: number) => <Text style={{ color: '#ff4d4f' }}>{v}%</Text>,
    },
    {
      title: '交易次数',
      dataIndex: 'trades',
      width: 80,
    },
    {
      title: '操作',
      width: 200,
      render: (_: any, record: Strategy) => (
        <Space>
          <Switch
            checked={record.status === 'running'}
            checkedChildren="运行"
            unCheckedChildren="暂停"
            disabled={record.status === 'backtesting' || record.status === 'error'}
            onChange={() => toggleStrategy(record.key)}
          />
          <Tooltip title="编辑参数">
            <Button type="text" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Tooltip title="回测">
            <Button
              type="text"
              icon={<ExperimentOutlined />}
              disabled={record.status === 'backtesting'}
              onClick={() => message.info('回测功能开发中...')}
            />
          </Tooltip>
          <Popconfirm
            title="确定删除此策略？"
            description="删除后不可恢复"
            onConfirm={() => deleteStrategy(record.key)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  /** 冠军策略 */
  const champion = strategies.find((s) => s.champion)

  return (
    <div style={{ padding: 24 }}>
      {/* 冠军-挑战者状态 */}
      {champion && (
        <Card style={{ marginBottom: 16 }}>
          <Row gutter={16} align="middle">
            <Col>
              <TrophyOutlined style={{ fontSize: 32, color: '#faad14' }} />
            </Col>
            <Col flex="auto">
              <Text strong style={{ fontSize: 16 }}>冠军策略：{champion.name}</Text>
              <div style={{ marginTop: 4 }}>
                <Space>
                  <Tag color="green">运行中</Tag>
                  <Text>累计盈亏: <Text style={{ color: '#52c41a' }} strong>+{champion.pnl.toLocaleString()}</Text></Text>
                  <Text>夏普比: {champion.sharpe}</Text>
                  <Text>胜率: {champion.winRate}%</Text>
                </Space>
              </div>
            </Col>
            <Col>
              <Space>
                {strategies
                  .filter((s) => !s.champion && s.status !== 'error')
                  .slice(0, 2)
                  .map((s) => (
                    <Tag key={s.key} color="blue" icon={<ThunderboltOutlined />}>
                      挑战者: {s.name}
                    </Tag>
                  ))}
              </Space>
            </Col>
          </Row>
        </Card>
      )}

      <Card
        title="🧠 策略管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => message.info('刷新策略列表')}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('新建策略开发中...')}>
              新建策略
            </Button>
          </Space>
        }
      >
        <Table
          dataSource={strategies}
          columns={columns}
          rowKey="key"
          size="small"
          scroll={{ x: 1200 }}
          pagination={false}
          expandable={{
            expandedRowRender: (record) => (
              <div style={{ padding: '8px 0' }}>
                <Paragraph type="secondary">{record.description}</Paragraph>
                <Text strong>当前参数：</Text>
                <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 12 }}>
                  {Object.entries(record.params).map(([k, v]) => (
                    <Tag key={k} style={{ marginBottom: 4 }}>
                      {k}: {String(v)}
                    </Tag>
                  ))}
                </div>
              </div>
            ),
          }}
        />
      </Card>

      {/* 编辑参数弹窗 */}
      <Modal
        title={`编辑策略参数 - ${editingStrategy?.name}`}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSaveParams}
        okText="保存"
        cancelText="取消"
        width={500}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="策略名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="策略描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          {editingStrategy &&
            Object.entries(editingStrategy.params).map(([key, val]) => (
              <Form.Item key={key} name={key} label={key}>
                {typeof val === 'number' ? (
                  <InputNumber style={{ width: '100%' }} step={0.01} />
                ) : (
                  <Input />
                )}
              </Form.Item>
            ))}
        </Form>
      </Modal>
    </div>
  )
}
