import React from 'react'
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
  List,
  Badge,
  Descriptions,
  Alert,
  Divider,
} from 'antd'
import {
  RobotOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  RiseOutlined,
  FallOutlined,
  BulbOutlined,
  BarChartOutlined,
  GlobalOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography

/** 模拟选股候选池 */
const stockCandidates = [
  {
    symbol: 'BTCUSDT',
    name: '比特币',
    score: 92,
    confidence: 85,
    direction: '做多' as const,
    reason: '链上数据表明巨鲸持续吸筹，技术面突破关键阻力位，资金费率健康',
    evidence: ['巨鲸地址净流入 +12,000 BTC', '突破 $68,000 阻力位', '资金费率 0.01%（健康）'],
  },
  {
    symbol: 'ETHUSDT',
    name: '以太坊',
    score: 85,
    confidence: 78,
    direction: '做多' as const,
    reason: 'ETH/BTC 汇率触底反弹迹象明显，DeFi TVL 持续增长',
    evidence: ['ETH/BTC 汇率 0.056 支撑有效', 'DeFi TVL 周增 8%', 'Layer2 交易量创新高'],
  },
  {
    symbol: 'NVDA',
    name: '英伟达',
    score: 78,
    confidence: 72,
    direction: '做多' as const,
    reason: 'AI 算力需求持续爆发，Q2 财报预期乐观，技术面回踩支撑',
    evidence: ['数据中心收入同比 +200%', '技术面回踩 50 日均线', '机构持仓持续增加'],
  },
  {
    symbol: 'SOLUSDT',
    name: 'Solana',
    score: 65,
    confidence: 58,
    direction: '做空' as const,
    reason: '短期涨幅过大，链上活跃度下降，面临获利回吐压力',
    evidence: ['7日涨幅 25%（过热）', '链上交易量下降 15%', '大户地址净流出'],
  },
  {
    symbol: 'TSLA',
    name: '特斯拉',
    score: 55,
    confidence: 45,
    direction: '做多' as const,
    reason: 'FSD 进展积极但估值偏高，建议观望等待更好的入场点',
    evidence: ['FSD v12 用户反馈积极', '估值 PE 60x（偏高）', '交付量符合预期'],
  },
]

/** 模拟情绪面板 */
const sentimentData = {
  overall: 68,
  label: '偏多',
  fearGreedIndex: 72,
  fearGreedLabel: '贪婪',
  socialSentiment: '积极',
  newsSentiment: '中性偏多',
  fundingRate: '0.012%',
  longShortRatio: 1.35,
  volatilityIndex: '中等',
}

/** 模拟宏观研判 */
const macroInsights = [
  {
    title: '美联储政策',
    impact: '中性',
    detail: '6 月议息会议维持利率不变，点阵图暗示年内降息 1 次。市场已充分定价，短期影响有限。',
    icon: <GlobalOutlined />,
  },
  {
    title: '加密货币监管',
    impact: '利多',
    detail: 'SEC 对以太坊 ETF 审批态度转暖，预计 7 月初有明确结果。若通过将带来大量增量资金。',
    icon: <ExperimentOutlined />,
  },
  {
    title: '科技股财报季',
    impact: '利多',
    detail: 'AI 相关公司财报预期乐观，半导体板块资金持续流入。关注 7 月中旬 FAANG 财报。',
    icon: <BarChartOutlined />,
  },
  {
    title: '地缘政治风险',
    impact: '利空',
    detail: '中东局势仍有不确定性，油价波动可能影响全球通胀预期。需关注避险情绪变化。',
    icon: <GlobalOutlined />,
  },
]

/** 模拟多空辩论 */
const debateReport = {
  bullArguments: [
    '链上数据显示长期持有者持续增持，市场底部信号明确',
    '美联储降息预期升温，流动性改善利好风险资产',
    '以太坊 ETF 预期将带来机构增量资金入场',
    '技术面突破关键阻力位，上升趋势确立',
  ],
  bearArguments: [
    '短期涨幅过大，技术面存在回调需求',
    '全球宏观经济仍有不确定性，衰退风险未完全消除',
    '加密货币监管政策仍存变数',
    '部分链上指标显示短期持有者获利了结意愿增强',
  ],
  verdict: '多头略占优势，建议维持中等仓位，逢低加仓。关注 68000 支撑位和 72000 阻力位。',
  bullScore: 65,
  bearScore: 35,
}

/** 模拟研报 */
const dailyReport = {
  date: new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }),
  title: '每日 AI 研报',
  summary: '今日市场整体偏多运行，BTC 在 68000 关键支撑上方企稳。链上数据显示巨鲸持续吸筹，以太坊 ETF 审批预期升温为主要催化剂。建议关注 ETH/BTC 汇率反弹机会，A 股半导体板块资金流入明显，可适当配置。',
  keyPoints: [
    'BTC 站稳 68000 支撑，短期目标 72000',
    '以太坊 ETF 预期升温，ETH/BTC 汇率有望反弹',
    'A 股半导体板块获北向资金持续流入',
    '美联储议息会议结果符合预期，市场已充分定价',
  ],
  riskWarnings: [
    '关注美联储后续政策指引变化',
    '中东地缘政治风险可能引发避险情绪',
    '加密货币杠杆率偏高，注意回调风险',
  ],
}

const impactColor: Record<string, string> = {
  '利多': '#52c41a',
  '利空': '#ff4d4f',
  '中性': '#1677ff',
}

export default function AIResearch() {
  return (
    <div style={{ padding: 24 }}>
      <Tabs
        defaultActiveKey="report"
        items={[
          {
            key: 'report',
            label: <span><FileTextOutlined /> 每日研报</span>,
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={16}>
                  <Card title={`🤖 ${dailyReport.title} · ${dailyReport.date}`}>
                    <Paragraph style={{ fontSize: 15 }}>{dailyReport.summary}</Paragraph>
                    <Divider />
                    <Title level={5}>📌 核心要点</Title>
                    <List
                      dataSource={dailyReport.keyPoints}
                      renderItem={(item) => (
                        <List.Item style={{ padding: '4px 0', border: 'none' }}>
                          <Space>
                            <ThunderboltOutlined style={{ color: '#1677ff' }} />
                            <Text>{item}</Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                    <Divider />
                    <Title level={5}>⚠️ 风险提示</Title>
                    <List
                      dataSource={dailyReport.riskWarnings}
                      renderItem={(item) => (
                        <List.Item style={{ padding: '4px 0', border: 'none' }}>
                          <Space>
                            <Badge status="warning" />
                            <Text type="warning">{item}</Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Card>
                </Col>
                <Col xs={24} lg={8}>
                  {/* 情绪面板 */}
                  <Card title="😊 市场情绪面板" style={{ marginBottom: 16 }}>
                    <div style={{ textAlign: 'center', marginBottom: 16 }}>
                      <Progress
                        type="dashboard"
                        percent={sentimentData.fearGreedIndex}
                        format={(p) => (
                          <div>
                            <div style={{ fontSize: 24, fontWeight: 'bold' }}>{p}</div>
                            <div style={{ fontSize: 12 }}>{sentimentData.fearGreedLabel}</div>
                          </div>
                        )}
                        strokeColor={{
                          '0%': '#ff4d4f',
                          '50%': '#faad14',
                          '100%': '#52c41a',
                        }}
                      />
                    </div>
                    <Descriptions column={1} size="small" bordered>
                      <Descriptions.Item label="综合情绪">
                        <Tag color="green">{sentimentData.label}</Tag> {sentimentData.overall}分
                      </Descriptions.Item>
                      <Descriptions.Item label="社交媒体">{sentimentData.socialSentiment}</Descriptions.Item>
                      <Descriptions.Item label="新闻情绪">{sentimentData.newsSentiment}</Descriptions.Item>
                      <Descriptions.Item label="资金费率">{sentimentData.fundingRate}</Descriptions.Item>
                      <Descriptions.Item label="多空比">{sentimentData.longShortRatio}</Descriptions.Item>
                      <Descriptions.Item label="波动率">{sentimentData.volatilityIndex}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'candidates',
            label: <span><BulbOutlined /> 选股候选池</span>,
            children: (
              <Card>
                <Table
                  dataSource={stockCandidates}
                  rowKey="symbol"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '标的', dataIndex: 'symbol', width: 100, render: (v: string, r: any) => <Text strong>{v}</Text> },
                    { title: '名称', dataIndex: 'name', width: 80 },
                    {
                      title: '方向',
                      dataIndex: 'direction',
                      width: 80,
                      render: (v: string) => (
                        <Tag color={v === '做多' ? 'green' : 'red'}>{v}</Tag>
                      ),
                    },
                    {
                      title: '评分',
                      dataIndex: 'score',
                      width: 120,
                      render: (v: number) => (
                        <Progress
                          percent={v}
                          size="small"
                          strokeColor={v >= 80 ? '#52c41a' : v >= 60 ? '#faad14' : '#ff4d4f'}
                          format={(p) => <Text strong>{p}</Text>}
                        />
                      ),
                      sorter: (a: any, b: any) => a.score - b.score,
                      defaultSortOrder: 'descend' as const,
                    },
                    {
                      title: '置信度',
                      dataIndex: 'confidence',
                      width: 80,
                      render: (v: number) => <Text>{v}%</Text>,
                    },
                    {
                      title: '研判理由',
                      dataIndex: 'reason',
                      ellipsis: true,
                    },
                    {
                      title: '关键证据',
                      dataIndex: 'evidence',
                      width: 300,
                      render: (evidence: string[]) => (
                        <Space direction="vertical" size={2}>
                          {evidence.map((e, i) => (
                            <Text key={i} style={{ fontSize: 12 }}>• {e}</Text>
                          ))}
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: 'macro',
            label: <span><GlobalOutlined /> 宏观研判</span>,
            children: (
              <Row gutter={[16, 16]}>
                {macroInsights.map((item, i) => (
                  <Col xs={24} lg={12} key={i}>
                    <Card>
                      <Space align="start">
                        <div style={{ fontSize: 24, color: impactColor[item.impact] }}>{item.icon}</div>
                        <div>
                          <Space>
                            <Text strong style={{ fontSize: 15 }}>{item.title}</Text>
                            <Tag color={impactColor[item.impact]}>{item.impact}</Tag>
                          </Space>
                          <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{item.detail}</Paragraph>
                        </div>
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
          {
            key: 'debate',
            label: <span><ExperimentOutlined /> 多空辩论</span>,
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={12}>
                  <Card
                    title={<Space><RiseOutlined style={{ color: '#52c41a' }} /> 多头论据</Space>}
                    style={{ borderColor: '#52c41a' }}
                  >
                    <List
                      dataSource={debateReport.bullArguments}
                      renderItem={(item) => (
                        <List.Item style={{ padding: '6px 0', border: 'none' }}>
                          <Text>✅ {item}</Text>
                        </List.Item>
                      )}
                    />
                    <Divider />
                    <div style={{ textAlign: 'center' }}>
                      <Progress
                        percent={debateReport.bullScore}
                        strokeColor="#52c41a"
                        format={(p) => <Text strong style={{ color: '#52c41a', fontSize: 18 }}>{p}分</Text>}
                      />
                    </div>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card
                    title={<Space><FallOutlined style={{ color: '#ff4d4f' }} /> 空头论据</Space>}
                    style={{ borderColor: '#ff4d4f' }}
                  >
                    <List
                      dataSource={debateReport.bearArguments}
                      renderItem={(item) => (
                        <List.Item style={{ padding: '6px 0', border: 'none' }}>
                          <Text>❌ {item}</Text>
                        </List.Item>
                      )}
                    />
                    <Divider />
                    <div style={{ textAlign: 'center' }}>
                      <Progress
                        percent={debateReport.bearScore}
                        strokeColor="#ff4d4f"
                        format={(p) => <Text strong style={{ color: '#ff4d4f', fontSize: 18 }}>{p}分</Text>}
                      />
                    </div>
                  </Card>
                </Col>
                <Col span={24}>
                  <Card title="📋 综合研判">
                    <Alert
                      message="综合结论"
                      description={debateReport.verdict}
                      type="info"
                      showIcon
                      icon={<RobotOutlined />}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
        ]}
      />
    </div>
  )
}
