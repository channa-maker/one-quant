/**
 * 期权中心 — 期权链 / Greeks 看板 / IV 曲面 / 组合策略构建。
 */
import { useState } from 'react'
import { Card, Table, Tag, Typography, Row, Col, Statistic, Select, Space, Tabs, Alert } from 'antd'
import { useApiData } from '@/hooks/useApiData'
import IVSurface from '@/components/monitoring/IVSurface'
import api from '@/utils/api'

const { Title, Text } = Typography

interface OptionRow {
  strike: number
  call_bid: number; call_ask: number; call_iv: number; call_delta: number; call_gamma: number; call_oi: number
  put_bid: number; put_ask: number; put_iv: number; put_delta: number; put_gamma: number; put_oi: number
}

/** 演示期权链(BTC 40000 附近) */
const demoChain: OptionRow[] = [38000, 39000, 40000, 41000, 42000, 43000, 44000].map((k, i) => {
  const atm = Math.abs(k - 41000) / 1000
  return {
    strike: k,
    call_bid: Math.max(50, 3200 - i * 520), call_ask: Math.max(60, 3260 - i * 520),
    call_iv: 52 + atm * 1.8, call_delta: Math.max(0.05, 0.9 - i * 0.14), call_gamma: 0.00012 - atm * 0.00001, call_oi: 1200 - i * 120,
    put_bid: Math.max(40, 200 + i * 480), put_ask: Math.max(50, 260 + i * 480),
    put_iv: 54 + atm * 2.1, put_delta: -Math.max(0.05, 0.1 + i * 0.13), put_gamma: 0.00011 - atm * 0.00001, put_oi: 900 + i * 100,
  }
})

const demoPortfolioGreeks = { delta: 12.6, gamma: 0.0021, vega: 8_400, theta: -1_250, margin_used: 186_000 }

/** 演示 IV 曲面数据:3 个到期 × 7 个行权价 */
const demoIVData = (['2026-07-25', '2026-08-29', '2026-09-26'] as const).flatMap((expiry, ei) =>
  [38000, 39000, 40000, 41000, 42000, 43000, 44000].map((strike) => ({
    expiry,
    expiryDays: 24 + ei * 35,
    strike,
    iv: 0.5 + Math.abs(strike - 41000) / 100000 + ei * 0.02,
    callPut: (strike >= 41000 ? 'call' : 'put') as 'call' | 'put',
  }))
)

export default function OptionsCenter() {
  const [underlying, setUnderlying] = useState('BTC')
  const [expiry, setExpiry] = useState('2026-07-25')
  const { data: chain, source, loading } = useApiData<OptionRow[]>(
    () => api.get(`/options/chain?underlying=${underlying}&expiry=${expiry}`).then((r) => r.data),
    demoChain,
    [underlying, expiry]
  )

  const g = demoPortfolioGreeks

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }} align="center" wrap>
        <Title level={4} style={{ margin: 0 }}>期权中心</Title>
        <Select value={underlying} onChange={setUnderlying} style={{ width: 100 }}
          options={[{ value: 'BTC' }, { value: 'ETH' }].map((o) => ({ ...o, label: o.value }))} />
        <Select value={expiry} onChange={setExpiry} style={{ width: 140 }}
          options={['2026-07-25', '2026-08-29', '2026-09-26'].map((d) => ({ value: d, label: d }))} />
        {source === 'demo' && <Tag color="orange">演示数据 · 后端未连接</Tag>}
      </Space>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}><Card size="small"><Statistic title="组合 Delta" value={g.delta} precision={1} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="组合 Gamma" value={g.gamma} precision={4} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="组合 Vega" value={g.vega} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="组合 Theta" value={g.theta} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="保证金占用 (USDT)" value={g.margin_used} /></Card></Col>
      </Row>

      <Tabs
        items={[
          {
            key: 'chain',
            label: '期权链',
            children: (
              <Card>
                <Table<OptionRow>
                  dataSource={chain}
                  rowKey="strike"
                  loading={loading}
                  size="small"
                  pagination={false}
                  columns={[
                    { title: 'Call 买/卖', width: 130, render: (_, r) => <Text>{r.call_bid} / {r.call_ask}</Text> },
                    { title: 'Call IV%', dataIndex: 'call_iv', width: 90, render: (v: number) => v.toFixed(1) },
                    { title: 'Δ', dataIndex: 'call_delta', width: 70, render: (v: number) => v.toFixed(2) },
                    { title: '持仓量', dataIndex: 'call_oi', width: 90 },
                    { title: '行权价', dataIndex: 'strike', width: 110, align: 'center', render: (v) => <Tag color="blue" style={{ fontSize: 13 }}>{v}</Tag> },
                    { title: '持仓量', dataIndex: 'put_oi', width: 90 },
                    { title: 'Δ', dataIndex: 'put_delta', width: 70, render: (v: number) => v.toFixed(2) },
                    { title: 'Put IV%', dataIndex: 'put_iv', width: 90, render: (v: number) => v.toFixed(1) },
                    { title: 'Put 买/卖', width: 130, render: (_, r) => <Text>{r.put_bid} / {r.put_ask}</Text> },
                  ]}
                />
              </Card>
            ),
          },
          { key: 'iv', label: 'IV 曲面(3D)', children: <Card><IVSurface data={demoIVData} /></Card> },
          {
            key: 'builder',
            label: '组合策略构建器',
            children: (
              <Card>
                <Alert type="info" showIcon message="支持:垂直价差 / 跨式 / 宽跨式 / 铁鹰 / 日历价差 / 领口 — 组合下单前经组合层 Greeks 限额与四层风控校验。" />
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
