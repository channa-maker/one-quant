import React, {  } from 'react'
import {
  Card,
  Row,
  Col,
  Typography,
  Tag,
  Table,
  Progress,
  Space,
  Tabs,
  Badge,
  Alert,
  Timeline,
  Tooltip,
  Switch,
} from 'antd'
import {
  SafetyOutlined,
  LockOutlined,
  AuditOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  HeatMapOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/** 四层风控状态 */
const riskLevels = [
  {
    level: 'L1',
    name: '日内限额',
    description: '单日亏损/交易次数/仓位比例限制',
    status: '正常' as const,
    color: '#52c41a',
    metrics: [
      { label: '日内亏损限额', value: '¥50,000', current: '¥12,580', usage: 25 },
      { label: '日内交易次数', value: '200 次', current: '67 次', usage: 34 },
      { label: '单标的仓位', value: '20%', current: '15.2%', usage: 76 },
    ],
  },
  {
    level: 'L2',
    name: '策略限额',
    description: '单策略最大仓位/亏损/回撤限制',
    status: '正常' as const,
    color: '#52c41a',
    metrics: [
      { label: '策略最大仓位', value: '¥500,000', current: '¥320,000', usage: 64 },
      { label: '策略最大亏损', value: '¥100,000', current: '¥28,500', usage: 29 },
      { label: '策略最大回撤', value: '15%', current: '5.2%', usage: 35 },
    ],
  },
  {
    level: 'L3',
    name: '账户限额',
    description: '账户总仓位/总亏损/净值回撤限制',
    status: '预警' as const,
    color: '#faad14',
    metrics: [
      { label: '账户总仓位', value: '¥2,000,000', current: '¥1,680,000', usage: 84 },
      { label: '账户总亏损', value: '¥200,000', current: '¥85,000', usage: 43 },
      { label: '净值最大回撤', value: '20%', current: '8.3%', usage: 42 },
    ],
  },
  {
    level: 'L4',
    name: '熔断机制',
    description: '极端行情下的紧急止损/平仓机制',
    status: '正常' as const,
    color: '#52c41a',
    metrics: [
      { label: '市场熔断', value: '单日跌幅 >10%', current: '未触发', usage: 0 },
      { label: '波动率熔断', value: '波动率 >3σ', current: '1.2σ', usage: 40 },
      { label: '流动性熔断', value: '滑点 >1%', current: '0.05%', usage: 5 },
    ],
  },
]

/** 熔断器状态 */
const circuitBreakers = [
  { name: '日内亏损熔断', threshold: '¥50,000', current: '¥12,580', status: '正常', triggered: false },
  { name: '单标的集中度熔断', threshold: '30%', current: '15.2%', status: '正常', triggered: false },
  { name: '波动率异常熔断', threshold: '3σ', current: '1.2σ', status: '正常', triggered: false },
  { name: '流动性枯竭熔断', threshold: '滑点 >1%', current: '0.05%', status: '正常', triggered: false },
  { name: '系统故障熔断', threshold: '心跳超时 30s', current: '正常', status: '正常', triggered: false },
]

/** 敞口热力图数据 */
const exposureData = [
  { market: 'BTC', long: 350000, short: 50000, net: 300000 },
  { market: 'ETH', long: 200000, short: 80000, net: 120000 },
  { market: 'SOL', long: 80000, short: 0, net: 80000 },
  { market: 'A股', long: 150000, short: 0, net: 150000 },
  { market: '期权', long: 50000, short: 30000, net: 20000 },
]

/** 限额展示 */
const limits = [
  { category: '单笔最大下单', value: '¥100,000', type: '硬约束', editable: false },
  { category: '日内最大亏损', value: '¥50,000', type: '硬约束', editable: false },
  { category: '单标的最大仓位', value: '20%', type: '硬约束', editable: false },
  { category: '策略最大同时运行', value: '10 个', type: '软约束', editable: true },
  { category: '最大杠杆倍数', value: '3x', type: '硬约束', editable: false },
  { category: '最小交易间隔', value: '100ms', type: '硬约束', editable: false },
]

/** 审计日志 */
const auditLogs = [
  { id: 1, time: '14:32:15', action: '风控放行', detail: 'BTCUSDT 买入 0.12 BTC，通过 L1-L4 检查', level: 'info' },
  { id: 2, time: '14:30:08', action: '风控拒绝', detail: 'ETHUSDT 买入 5 ETH 被 L1 日内限额拒绝', level: 'warning' },
  { id: 3, time: '14:28:45', action: '预警触发', detail: 'L3 账户仓位达 84%，触发预警', level: 'warning' },
  { id: 4, time: '14:25:33', action: '熔断检查', detail: '波动率熔断器例行检查，状态正常', level: 'info' },
  { id: 5, time: '14:20:12', action: '风控放行', detail: 'BTCUSDT 卖出 0.05 BTC，通过全部检查', level: 'info' },
  { id: 6, time: '14:15:00', action: '限额更新', detail: 'L2 策略限额由系统自动调整（基于波动率）', level: 'info' },
  { id: 7, time: '14:10:22', action: '风控拒绝', detail: 'SOLUSDT 买入请求被 L2 策略限额拒绝', level: 'error' },
  { id: 8, time: '14:05:00', action: '系统自检', detail: '四层风控系统自检完成，全部正常', level: 'success' },
]

const logLevelIcon: Record<string, React.ReactNode> = {
  info: <CheckCircleOutlined style={{ color: '#1677ff' }} />,
  warning: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
  error: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  success: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
}


export default function RiskCenter() {
  return (
    <div style={{ padding: 24 }}>
      <Tabs
        defaultActiveKey="levels"
        items={[
          {
            key: 'levels',
            label: <span><SafetyOutlined /> 四层风控</span>,
            children: (
              <Row gutter={[16, 16]}>
                {riskLevels.map((risk) => (
                  <Col xs={24} lg={12} key={risk.level}>
                    <Card
                      title={
                        <Space>
                          <Tag color={risk.color} style={{ fontSize: 14 }}>{risk.level}</Tag>
                          <Text strong>{risk.name}</Text>
                          <Badge
                            status={risk.status === '正常' ? 'success' : 'warning'}
                            text={risk.status}
                          />
                        </Space>
                      }
                      size="small"
                    >
                      <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                        {risk.description}
                      </Text>
                      {risk.metrics.map((m, i) => (
                        <div key={i} style={{ marginBottom: 8 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                            <Text>{m.label}</Text>
                            <Space>
                              <Text type="secondary">{m.current}</Text>
                              <Text>/</Text>
                              <Text strong>{m.value}</Text>
                            </Space>
                          </div>
                          <Progress
                            percent={m.usage}
                            showInfo={false}
                            strokeColor={
                              m.usage >= 80 ? '#ff4d4f' : m.usage >= 60 ? '#faad14' : '#52c41a'
                            }
                            size="small"
                          />
                        </div>
                      ))}
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
          {
            key: 'breakers',
            label: <span><ThunderboltOutlined /> 熔断器</span>,
            children: (
              <Card title="⚡ 熔断器状态">
                <Table
                  dataSource={circuitBreakers}
                  rowKey="name"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '熔断器名称', dataIndex: 'name', width: 180 },
                    { title: '触发阈值', dataIndex: 'threshold', width: 150 },
                    { title: '当前值', dataIndex: 'current', width: 100 },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 100,
                      render: (_v: string, r: any) => (
                        <Badge
                          status={r.triggered ? 'error' : 'success'}
                          text={r.triggered ? '已触发' : '正常'}
                        />
                      ),
                    },
                    {
                      title: '手动测试',
                      width: 100,
                      render: () => (
                        <Switch checkedChildren="测试" unCheckedChildren="正常" onChange={(c) => {
                          if (c) {
                            // Would trigger test mode
                          }
                        }} />
                      ),
                    },
                  ]}
                />
                <Alert
                  style={{ marginTop: 16 }}
                  message="熔断器说明"
                  description="熔断器在检测到异常条件时自动触发，会立即停止所有策略交易并平仓。手动测试模式不会实际触发熔断，仅用于验证逻辑。"
                  type="info"
                  showIcon
                />
              </Card>
            ),
          },
          {
            key: 'exposure',
            label: <span><HeatMapOutlined /> 敞口热力图</span>,
            children: (
              <Card title="🔥 敞口热力图">
                <Table
                  dataSource={exposureData}
                  rowKey="market"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '市场', dataIndex: 'market', width: 80 },
                    {
                      title: '多头敞口',
                      dataIndex: 'long',
                      width: 120,
                      render: (v: number) => (
                        <Text style={{ color: '#52c41a' }}>¥{v.toLocaleString()}</Text>
                      ),
                    },
                    {
                      title: '空头敞口',
                      dataIndex: 'short',
                      width: 120,
                      render: (v: number) => (
                        <Text style={{ color: '#ff4d4f' }}>¥{v.toLocaleString()}</Text>
                      ),
                    },
                    {
                      title: '净敞口',
                      dataIndex: 'net',
                      width: 120,
                      render: (v: number) => {
                        const maxNet = 300000
                        const ratio = Math.abs(v) / maxNet
                        return (
                          <div>
                            <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
                              ¥{v.toLocaleString()}
                            </Text>
                            <Progress
                              percent={ratio * 100}
                              showInfo={false}
                              strokeColor={ratio > 0.8 ? '#ff4d4f' : ratio > 0.5 ? '#faad14' : '#52c41a'}
                              size="small"
                            />
                          </div>
                        )
                      },
                    },
                    {
                      title: '热力图',
                      width: 200,
                      render: (_: any, r: any) => {
                        const maxVal = 350000
                        const longW = (r.long / maxVal) * 100
                        const shortW = (r.short / maxVal) * 100
                        return (
                          <div style={{ display: 'flex', gap: 2, height: 20 }}>
                            <Tooltip title={`多头: ¥${r.long.toLocaleString()}`}>
                              <div style={{ width: `${longW}%`, background: '#52c41a', borderRadius: 2, minWidth: 2 }} />
                            </Tooltip>
                            <Tooltip title={`空头: ¥${r.short.toLocaleString()}`}>
                              <div style={{ width: `${shortW}%`, background: '#ff4d4f', borderRadius: 2, minWidth: 2 }} />
                            </Tooltip>
                          </div>
                        )
                      },
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'limits',
            label: <span><LockOutlined /> 限额管理</span>,
            children: (
              <Card title="🔒 限额管理">
                <Table
                  dataSource={limits}
                  rowKey="category"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '限额类别', dataIndex: 'category', width: 200 },
                    { title: '限额值', dataIndex: 'value', width: 150 },
                    {
                      title: '类型',
                      dataIndex: 'type',
                      width: 100,
                      render: (v: string) => (
                        <Tag color={v === '硬约束' ? 'red' : 'blue'} icon={v === '硬约束' ? <LockOutlined /> : undefined}>
                          {v}
                        </Tag>
                      ),
                    },
                    {
                      title: '可编辑',
                      dataIndex: 'editable',
                      width: 80,
                      render: (v: boolean) => v ? <Tag color="green">可调</Tag> : <Tag>只读</Tag>,
                    },
                  ]}
                />
                <Alert
                  style={{ marginTop: 16 }}
                  message="硬约束说明"
                  description="标记为「硬约束」的限额不可通过界面修改，需联系系统管理员。这些限额是风控体系的核心防线。"
                  type="warning"
                  showIcon
                  icon={<LockOutlined />}
                />
              </Card>
            ),
          },
          {
            key: 'audit',
            label: <span><AuditOutlined /> 审计日志</span>,
            children: (
              <Card title="📋 风控审计日志">
                <Timeline
                  items={auditLogs.map((log) => ({
                    dot: logLevelIcon[log.level],
                    children: (
                      <div>
                        <Space>
                          <Text type="secondary" style={{ fontSize: 12 }}>{log.time}</Text>
                          <Tag color={
                            log.level === 'error' ? 'red'
                            : log.level === 'warning' ? 'orange'
                            : log.level === 'success' ? 'green'
                            : 'blue'
                          }>
                            {log.action}
                          </Tag>
                        </Space>
                        <div style={{ marginTop: 4 }}>
                          <Text>{log.detail}</Text>
                        </div>
                      </div>
                    ),
                  }))}
                />
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
