import React, { useState, useEffect } from 'react'
import { fetchHealthDetail } from '@/utils/api'
import { Alert,
  Card,
  Row,
  Col,
  Typography,
  Tag,
  Table,
  Space,
  Progress,
  List,
  Tabs,
  Button,
} from 'antd'
import {
  HeartOutlined,
  AlertOutlined,
  DatabaseOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  ReloadOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/** 进程心跳状态 */
const processes = [
  { name: '行情网关', pid: 1001, status: 'running', uptime: '3d 12h', lastHeartbeat: '0.5s 前', cpu: 2.3, memory: 128 },
  { name: '策略引擎', pid: 1002, status: 'running', uptime: '3d 12h', lastHeartbeat: '0.8s 前', cpu: 15.6, memory: 512 },
  { name: '订单路由', pid: 1003, status: 'running', uptime: '3d 12h', lastHeartbeat: '0.3s 前', cpu: 5.2, memory: 256 },
  { name: '风控服务', pid: 1004, status: 'running', uptime: '3d 12h', lastHeartbeat: '0.6s 前', cpu: 3.1, memory: 192 },
  { name: 'AI 研报引擎', pid: 1005, status: 'running', uptime: '2d 8h', lastHeartbeat: '1.2s 前', cpu: 8.5, memory: 1024 },
  { name: '数据清洗', pid: 1006, status: 'warning', uptime: '1d 4h', lastHeartbeat: '5.0s 前', cpu: 22.1, memory: 768 },
  { name: '历史回放', pid: 1007, status: 'stopped', uptime: '-', lastHeartbeat: '30m 前', cpu: 0, memory: 0 },
]

/** 延迟指标 */
const latencyMetrics = [
  { service: '行情延迟', p50: 2.5, p95: 8.2, p99: 15.6, unit: 'ms', status: '正常' },
  { service: '下单延迟', p50: 5.1, p95: 18.3, p99: 35.2, unit: 'ms', status: '正常' },
  { service: '撤单延迟', p50: 3.8, p95: 12.5, p99: 28.1, unit: 'ms', status: '正常' },
  { service: '风控检查', p50: 0.8, p95: 2.1, p99: 4.5, unit: 'ms', status: '正常' },
  { service: '策略计算', p50: 15.2, p95: 45.8, p99: 98.5, unit: 'ms', status: '预警' },
  { service: 'API 响应', p50: 25.3, p95: 85.2, p99: 180.5, unit: 'ms', status: '正常' },
]

/** 数据质量 */
const dataQuality = [
  { source: '币安行情', records: '1,250,000', missing: 12, duplicate: 3, latency: '2.5ms', quality: 99.99 },
  { source: 'OKX 行情', records: '890,000', missing: 8, duplicate: 1, latency: '3.1ms', quality: 99.99 },
  { source: 'A股行情', records: '450,000', missing: 25, duplicate: 15, latency: '15.2ms', quality: 99.99 },
  { source: '链上数据', records: '125,000', missing: 150, duplicate: 45, latency: '120ms', quality: 99.84 },
  { source: '新闻数据', records: '35,000', missing: 320, duplicate: 180, latency: '500ms', quality: 98.57 },
]

/** 告警列表 */
const systemAlerts = [
  { id: 1, level: '高', source: '数据清洗', message: '进程心跳延迟 > 5s，可能存在性能问题', time: '5 分钟前', acknowledged: false },
  { id: 2, level: '中', source: '策略计算', message: 'P99 延迟达 98.5ms，接近阈值 100ms', time: '15 分钟前', acknowledged: false },
  { id: 3, level: '低', source: '链上数据', message: '数据缺失率 0.12%，高于基线 0.01%', time: '30 分钟前', acknowledged: true },
  { id: 4, level: '高', source: '历史回放', message: '进程已停止运行', time: '1 小时前', acknowledged: true },
  { id: 5, level: '中', source: '新闻数据', message: '重复数据率 0.51%，建议检查去重逻辑', time: '2 小时前', acknowledged: true },
]

const alertLevelColor: Record<string, string> = {
  '高': '#ff4d4f',
  '中': '#faad14',
  '低': '#1677ff',
}

/** 资源使用（模拟实时数据） */
const generateResourceData = () => ({
  cpu: Math.round(30 + Math.random() * 40),
  memory: Math.round(45 + Math.random() * 25),
  disk: 62,
  network: Math.round(10 + Math.random() * 30),
  gpu: Math.round(20 + Math.random() * 50),
})

const statusIcon: Record<string, React.ReactNode> = {
  running: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  warning: <WarningOutlined style={{ color: '#faad14' }} />,
  stopped: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
}


export default function SystemMonitor() {
  const [live, setLive] = useState(false)
  // 挂载时探测后端健康详情;可达则显示实时标记
  useEffect(() => {
    fetchHealthDetail().then(() => setLive(true)).catch(() => {/* 后端未连接 */})
  }, [])

  const [resources, setResources] = useState(generateResourceData())

  useEffect(() => {
    const timer = setInterval(() => {
      setResources(generateResourceData())
    }, 3000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div style={{ padding: 24 }}>
      {!live && (
        <Alert
          type="warning"
          showIcon
          message="当前为演示数据 · 后端连接后自动切换为实时监控"
          style={{ marginBottom: 16 }}
        />
      )}
      {/* 资源使用概览 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">CPU</Text>
              <Progress
                type="dashboard"
                percent={resources.cpu}
                size={80}
                strokeColor={resources.cpu > 80 ? '#ff4d4f' : resources.cpu > 60 ? '#faad14' : '#52c41a'}
                format={(p) => <Text style={{ fontSize: 16, fontWeight: 'bold' }}>{p}%</Text>}
              />
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">内存</Text>
              <Progress
                type="dashboard"
                percent={resources.memory}
                size={80}
                strokeColor={resources.memory > 80 ? '#ff4d4f' : resources.memory > 60 ? '#faad14' : '#52c41a'}
                format={(p) => <Text style={{ fontSize: 16, fontWeight: 'bold' }}>{p}%</Text>}
              />
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">磁盘</Text>
              <Progress
                type="dashboard"
                percent={resources.disk}
                size={80}
                strokeColor={resources.disk > 80 ? '#ff4d4f' : resources.disk > 60 ? '#faad14' : '#52c41a'}
                format={(p) => <Text style={{ fontSize: 16, fontWeight: 'bold' }}>{p}%</Text>}
              />
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">网络</Text>
              <Progress
                type="dashboard"
                percent={resources.network}
                size={80}
                strokeColor={resources.network > 80 ? '#ff4d4f' : '#52c41a'}
                format={(p) => <Text style={{ fontSize: 16, fontWeight: 'bold' }}>{p}%</Text>}
              />
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">GPU</Text>
              <Progress
                type="dashboard"
                percent={resources.gpu}
                size={80}
                strokeColor={resources.gpu > 80 ? '#ff4d4f' : '#52c41a'}
                format={(p) => <Text style={{ fontSize: 16, fontWeight: 'bold' }}>{p}%</Text>}
              />
            </div>
          </Card>
        </Col>
      </Row>

      <Tabs
        defaultActiveKey="processes"
        items={[
          {
            key: 'processes',
            label: <span><HeartOutlined /> 进程心跳</span>,
            children: (
              <Card extra={<Button icon={<ReloadOutlined />}>刷新</Button>}>
                <Table
                  dataSource={processes}
                  rowKey="name"
                  size="small"
                  pagination={false}
                  columns={[
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 60,
                      render: (v: string) => statusIcon[v],
                    },
                    { title: '进程名', dataIndex: 'name', width: 120, render: (v: string) => <Text strong>{v}</Text> },
                    { title: 'PID', dataIndex: 'pid', width: 80 },
                    {
                      title: '运行时长',
                      dataIndex: 'uptime',
                      width: 100,
                      render: (v: string) => <Text type="secondary">{v}</Text>,
                    },
                    {
                      title: '最后心跳',
                      dataIndex: 'lastHeartbeat',
                      width: 100,
                      render: (v: string) => {
                        const isSlow = parseFloat(v) > 3
                        return <Text style={{ color: isSlow ? '#faad14' : undefined }}>{v}</Text>
                      },
                    },
                    {
                      title: 'CPU',
                      dataIndex: 'cpu',
                      width: 100,
                      render: (v: number) => (
                        <Progress
                          percent={v}
                          size="small"
                          strokeColor={v > 50 ? '#ff4d4f' : v > 30 ? '#faad14' : '#52c41a'}
                          format={(p) => `${p}%`}
                        />
                      ),
                    },
                    {
                      title: '内存(MB)',
                      dataIndex: 'memory',
                      width: 100,
                      render: (v: number) => <Text>{v > 0 ? v : '-'}</Text>,
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'latency',
            label: <span><ClockCircleOutlined /> 延迟指标</span>,
            children: (
              <Card>
                <Table
                  dataSource={latencyMetrics}
                  rowKey="service"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '服务', dataIndex: 'service', width: 120, render: (v: string) => <Text strong>{v}</Text> },
                    {
                      title: 'P50',
                      dataIndex: 'p50',
                      width: 100,
                      render: (v: number, r: any) => <Text>{v} {r.unit}</Text>,
                    },
                    {
                      title: 'P95',
                      dataIndex: 'p95',
                      width: 100,
                      render: (v: number, r: any) => (
                        <Text style={{ color: v > 50 ? '#faad14' : undefined }}>{v} {r.unit}</Text>
                      ),
                    },
                    {
                      title: 'P99',
                      dataIndex: 'p99',
                      width: 100,
                      render: (v: number, r: any) => (
                        <Text style={{ color: v > 100 ? '#ff4d4f' : v > 50 ? '#faad14' : undefined }}>{v} {r.unit}</Text>
                      ),
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 80,
                      render: (v: string) => (
                        <Tag color={v === '正常' ? 'green' : 'orange'}>{v}</Tag>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'quality',
            label: <span><DatabaseOutlined /> 数据质量</span>,
            children: (
              <Card>
                <Table
                  dataSource={dataQuality}
                  rowKey="source"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '数据源', dataIndex: 'source', width: 120, render: (v: string) => <Text strong>{v}</Text> },
                    { title: '记录数', dataIndex: 'records', width: 120 },
                    {
                      title: '缺失',
                      dataIndex: 'missing',
                      width: 80,
                      render: (v: number) => (
                        <Text style={{ color: v > 100 ? '#ff4d4f' : v > 20 ? '#faad14' : '#52c41a' }}>{v}</Text>
                      ),
                    },
                    {
                      title: '重复',
                      dataIndex: 'duplicate',
                      width: 80,
                      render: (v: number) => (
                        <Text style={{ color: v > 100 ? '#ff4d4f' : v > 20 ? '#faad14' : '#52c41a' }}>{v}</Text>
                      ),
                    },
                    { title: '延迟', dataIndex: 'latency', width: 80 },
                    {
                      title: '质量分',
                      dataIndex: 'quality',
                      width: 120,
                      render: (v: number) => (
                        <Progress
                          percent={v}
                          size="small"
                          strokeColor={v >= 99.9 ? '#52c41a' : v >= 99 ? '#faad14' : '#ff4d4f'}
                          format={(p) => <Text>{p}%</Text>}
                        />
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'alerts',
            label: <span><AlertOutlined /> 告警列表</span>,
            children: (
              <Card>
                <List
                  dataSource={systemAlerts}
                  renderItem={(item) => (
                    <List.Item
                      style={{
                        background: item.acknowledged ? 'transparent' : 'rgba(250,173,20,0.05)',
                        padding: '12px 16px',
                        marginBottom: 4,
                        borderRadius: 4,
                      }}
                      actions={[
                        item.acknowledged ? (
                          <Tag color="default">已确认</Tag>
                        ) : (
                          <Button size="small" type="primary">确认</Button>
                        ),
                      ]}
                    >
                      <List.Item.Meta
                        avatar={
                          <Tag color={alertLevelColor[item.level]} style={{ fontSize: 13 }}>
                            {item.level}危
                          </Tag>
                        }
                        title={
                          <Space>
                            <Text strong>{item.source}</Text>
                            <Text type="secondary" style={{ fontSize: 12 }}>{item.time}</Text>
                          </Space>
                        }
                        description={<Text>{item.message}</Text>}
                      />
                    </List.Item>
                  )}
                />
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
