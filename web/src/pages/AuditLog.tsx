/**
 * 审计日志 — 决策留痕检索:每笔订单/风控决策全生命周期回溯(只增不改)。
 */
import { useState } from 'react'
import { Card, Table, Tag, Typography, Input, Select, Space, DatePicker, Alert } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useApiData } from '@/hooks/useApiData'
import api from '@/utils/api'

const { Title, Text } = Typography

interface AuditEntry {
  id: string
  ts: string
  category: '订单' | '风控' | '策略' | '登录' | '配置'
  actor: string
  action: string
  decision?: string
  detail: string
  trace_id: string
}

const demoEntries: AuditEntry[] = [
  { id: 'a1', ts: '2026-07-01 12:31:05.412', category: '风控', actor: 'risk-engine', action: 'L2 敞口检查', decision: 'APPROVE', detail: 'BTCUSDT buy 0.5 名义 $20,500,总敞口 31% < 50%', trace_id: 'tr_8f2a' },
  { id: 'a2', ts: '2026-07-01 12:31:05.418', category: '订单', actor: 'oms', action: '订单提交', detail: 'BTCUSDT 限价买 0.5 @ 41,020(cid=ord_7b3f)', trace_id: 'tr_8f2a' },
  { id: 'a3', ts: '2026-07-01 12:31:06.101', category: '订单', actor: 'binance', action: '部分成交', detail: '成交 0.3/0.5 @ 41,018', trace_id: 'tr_8f2a' },
  { id: 'a4', ts: '2026-07-01 12:15:22.007', category: '风控', actor: 'risk-engine', action: 'L3 回撤检查', decision: 'REDUCE', detail: '回撤 12.4% 接近 15% 上限,要求减仓 30%', trace_id: 'tr_5c11' },
  { id: 'a5', ts: '2026-07-01 11:58:40.550', category: '策略', actor: 'scheduler', action: '策略启用', detail: 'smc_liquidity(灰度 5% 资金)审批人: owner', trace_id: 'tr_2a90' },
  { id: 'a6', ts: '2026-07-01 09:00:01.000', category: '登录', actor: 'admin', action: '登录成功', detail: 'IP 10.0.0.8 · 2FA 通过', trace_id: 'tr_0001' },
]

const decisionTag = (d?: string) => {
  if (!d) return null
  const color = d === 'APPROVE' ? 'success' : d === 'REJECT' ? 'error' : d === 'REDUCE' ? 'warning' : 'magenta'
  return <Tag color={color}>{d}</Tag>
}

export default function AuditLog() {
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState<string | undefined>()
  const { data, source, loading } = useApiData<AuditEntry[]>(
    () => api.get('/audit/logs').then((r) => r.data),
    demoEntries
  )

  const filtered = data.filter(
    (e) =>
      (!category || e.category === category) &&
      (!keyword || e.detail.includes(keyword) || e.trace_id.includes(keyword) || e.action.includes(keyword))
  )

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }} align="center" wrap>
        <Title level={4} style={{ margin: 0 }}>审计日志</Title>
        {source === 'demo' && <Tag color="orange">演示数据 · 后端未连接</Tag>}
      </Space>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="搜索 详情 / trace_id / 动作"
            prefix={<SearchOutlined />}
            style={{ width: 260 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            allowClear
          />
          <Select
            placeholder="类别"
            style={{ width: 120 }}
            allowClear
            value={category}
            onChange={setCategory}
            options={['订单', '风控', '策略', '登录', '配置'].map((c) => ({ value: c, label: c }))}
          />
          <DatePicker.RangePicker showTime />
        </Space>

        <Table<AuditEntry>
          dataSource={filtered}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
          columns={[
            { title: '时间(纳秒级)', dataIndex: 'ts', width: 200, render: (v) => <Text code style={{ fontSize: 12 }}>{v}</Text> },
            { title: '类别', dataIndex: 'category', width: 80, render: (v) => <Tag>{v}</Tag> },
            { title: '主体', dataIndex: 'actor', width: 110 },
            { title: '动作', dataIndex: 'action', width: 140 },
            { title: '决策', dataIndex: 'decision', width: 100, render: decisionTag },
            { title: '详情', dataIndex: 'detail', ellipsis: true },
            { title: '链路', dataIndex: 'trace_id', width: 90, render: (v) => <Text code style={{ fontSize: 12 }}>{v}</Text> },
          ]}
        />
      </Card>

      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        message="审计记录只增不改(不可篡改),含纳秒时间戳与全链路 trace_id,任意一笔交易可回溯到触发它的信号与风控决策。"
      />
    </div>
  )
}
