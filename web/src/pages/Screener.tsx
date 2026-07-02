/**
 * 选股选币 — AI 候选池:ML 打分 + LLM 复核,输出 Top-N 带分数/理由/置信度。
 */
import { Card, Table, Tag, Typography, Row, Col, Statistic, Progress, Space, Alert } from 'antd'
import { RiseOutlined, FallOutlined, RobotOutlined } from '@ant-design/icons'
import { useApiData } from '@/hooks/useApiData'
import api from '@/utils/api'

const { Title, Text } = Typography

interface Candidate {
  symbol: string
  name: string
  market: string
  direction: '看多' | '看空' | '中性'
  ml_score: number
  llm_adjust: number
  final_score: number
  confidence: number
  reason: string
  factors: string[]
}

/** 演示数据(后端不可达时) */
const demoCandidates: Candidate[] = [
  { symbol: 'BTCUSDT', name: '比特币', market: '加密', direction: '看多', ml_score: 82, llm_adjust: 3, final_score: 85, confidence: 0.86, reason: 'CVD 背离修复 + 交易所净流出 + 资金费率转正,多头结构确认', factors: ['momentum_rsi_14', 'flow_cvd_1h', 'chain_netflow_24h'] },
  { symbol: 'ETHUSDT', name: '以太坊', market: '加密', direction: '看多', ml_score: 76, llm_adjust: 2, final_score: 78, confidence: 0.79, reason: '突破 20 日高点后回踩确认,链上活跃地址回升', factors: ['momentum_break_20d', 'chain_active_addr'] },
  { symbol: 'SOLUSDT', name: 'Solana', market: '加密', direction: '中性', ml_score: 58, llm_adjust: -4, final_score: 54, confidence: 0.61, reason: '动量尚可但临近大额解锁事件,LLM 复核降分', factors: ['momentum_rsi_14', 'event_unlock'] },
  { symbol: 'NVDA', name: '英伟达', market: '美股', direction: '看多', ml_score: 74, llm_adjust: 4, final_score: 78, confidence: 0.77, reason: '财报后动量延续,分析师上调目标价,资金净流入', factors: ['momentum_earnings_drift', 'flow_institutional'] },
  { symbol: 'DOGE', name: '狗狗币', market: '加密', direction: '看空', ml_score: 38, llm_adjust: -5, final_score: 33, confidence: 0.68, reason: '社媒情绪退潮 + 巨鲸地址派发,资金流出明显', factors: ['sentiment_social', 'chain_whale_flow'] },
]

const dirTag = (d: string) =>
  d === '看多' ? (
    <Tag color="red" icon={<RiseOutlined />}>看多</Tag>
  ) : d === '看空' ? (
    <Tag color="green" icon={<FallOutlined />}>看空</Tag>
  ) : (
    <Tag>中性</Tag>
  )

export default function Screener() {
  const { data, source, loading } = useApiData<Candidate[]>(
    () => api.get('/screener/candidates').then((r) => r.data),
    demoCandidates
  )

  const bullish = data.filter((c) => c.direction === '看多').length
  const bearish = data.filter((c) => c.direction === '看空').length

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }} align="center">
        <Title level={4} style={{ margin: 0 }}>
          <RobotOutlined /> AI 选股选币
        </Title>
        {source === 'demo' && <Tag color="orange">演示数据 · 后端未连接</Tag>}
      </Space>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Statistic title="候选总数" value={data.length} /></Card></Col>
        <Col span={6}><Card><Statistic title="看多" value={bullish} valueStyle={{ color: '#f5222d' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="看空" value={bearish} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card><Statistic title="平均置信度" value={(data.reduce((s, c) => s + c.confidence, 0) / Math.max(data.length, 1) * 100).toFixed(0)} suffix="%" /></Card></Col>
      </Row>

      <Card title="今日候选池(ML 打分 → LLM 复核 → 风险约束)">
        <Table<Candidate>
          dataSource={data}
          rowKey="symbol"
          loading={loading}
          size="small"
          pagination={false}
          columns={[
            { title: '标的', dataIndex: 'symbol', width: 110, render: (v, r) => (<Space direction="vertical" size={0}><Text strong>{v}</Text><Text type="secondary" style={{ fontSize: 12 }}>{r.name}</Text></Space>) },
            { title: '市场', dataIndex: 'market', width: 70, render: (v) => <Tag>{v}</Tag> },
            { title: '方向', dataIndex: 'direction', width: 90, render: dirTag },
            { title: 'ML 分', dataIndex: 'ml_score', width: 80 },
            { title: 'LLM 调整', dataIndex: 'llm_adjust', width: 90, render: (v: number) => (<Text style={{ color: v >= 0 ? '#f5222d' : '#52c41a' }}>{v >= 0 ? `+${v}` : v}</Text>) },
            { title: '综合分', dataIndex: 'final_score', width: 140, render: (v: number) => (<Progress percent={v} size="small" strokeColor={v >= 70 ? '#f5222d' : v >= 50 ? '#faad14' : '#52c41a'} format={(p) => `${p}`} />) },
            { title: '置信度', dataIndex: 'confidence', width: 80, render: (v: number) => `${(v * 100).toFixed(0)}%` },
            { title: '中文理由(LLM)', dataIndex: 'reason', ellipsis: true },
            { title: '因子', dataIndex: 'factors', width: 220, render: (fs: string[]) => (<Space size={4} wrap>{fs.map((f) => (<Tag key={f} style={{ fontSize: 11 }}>{f}</Tag>))}</Space>) },
          ]}
        />
      </Card>

      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        message="候选池仅为 AI 建议,进入交易仍需通过四层风控;单一证据源封顶中分,高分必须多源共振。"
      />
    </div>
  )
}
