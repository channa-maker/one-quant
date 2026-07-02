import React, { useState } from 'react'
import { Card, Tag, Descriptions, Progress, Button, Modal, Typography, Space, Tooltip } from 'antd'
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ExclamationCircleOutlined,
  SoundOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography

/** 信号级别 */
type SignalGrade = 'S' | 'A' | 'B' | 'C'

/** 信号卡属性 */
export interface SignalCardData {
  id: string
  symbol: string
  name?: string
  side: 'buy' | 'sell'
  compositeScore: number
  confidenceLow: number
  confidenceHigh: number
  grade: SignalGrade
  riskLevel: '低' | '中' | '高' | '极高'
  suggestedStopLoss: number
  riskRewardRatio: number
  reasonCn: string
  evidence: Array<{ label: string; value: string; weight: number }>
  strategyName: string
  timestamp: number
}

interface SignalCardProps {
  signal: SignalCardData
  colorMode?: 'red-up' | 'green-up'
  onAction?: (signal: SignalCardData, action: string) => void
}

/** 级别颜色映射 */
const gradeColorMap: Record<SignalGrade, string> = {
  S: '#ff4d4f',
  A: '#fa8c16',
  B: '#1677ff',
  C: '#8c8c8c',
}

/** 级别标签文字 */
const gradeTextMap: Record<SignalGrade, string> = {
  S: 'S 级 · 强烈',
  A: 'A 级 · 推荐',
  B: 'B 级 · 关注',
  C: 'C 级 · 记录',
}

/** 风险颜色 */
const riskColorMap: Record<string, string> = {
  '低': '#52c41a',
  '中': '#faad14',
  '高': '#ff7a45',
  '极高': '#ff4d4f',
}

export const SignalCard: React.FC<SignalCardProps> = ({ signal, colorMode = 'red-up', onAction }) => {
  const [detailOpen, setDetailOpen] = useState(false)

  const isBuy = signal.side === 'buy'
  const directionColor = colorMode === 'red-up'
    ? (isBuy ? '#52c41a' : '#ff4d4f')
    : (isBuy ? '#1677ff' : '#ff4d4f')

  const directionIcon = isBuy ? <ArrowUpOutlined /> : <ArrowDownOutlined />
  const directionText = isBuy ? '做多' : '做空'

  /** 信号卡整体边框样式 */
  const borderColor = gradeColorMap[signal.grade]

  return (
    <>
      <Card
        hoverable
        size="small"
        style={{
          borderLeft: `4px solid ${borderColor}`,
          marginBottom: 8,
          background: signal.grade === 'S' ? 'rgba(255,77,79,0.05)' : undefined,
        }}
        title={
          <Space>
            {signal.grade === 'S' && (
              <SoundOutlined style={{ color: '#ff4d4f', fontSize: 16 }} />
            )}
            <Tag color={borderColor}>{gradeTextMap[signal.grade]}</Tag>
            <Text strong>{signal.symbol}</Text>
            {signal.name && <Text type="secondary">{signal.name}</Text>}
          </Space>
        }
        extra={
          <Tag
            icon={directionIcon}
            color={directionColor}
            style={{ fontSize: 14, padding: '2px 12px' }}
          >
            {directionText}
          </Tag>
        }
        actions={[
          <Button
            key="detail"
            type="link"
            size="small"
            onClick={() => setDetailOpen(true)}
          >
            查看详情
          </Button>,
          onAction && signal.grade !== 'C' && (
            <Button
              key="follow"
              type="link"
              size="small"
              onClick={() => onAction(signal, 'follow')}
            >
              跟踪信号
            </Button>
          ),
        ].filter(Boolean)}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>综合评分</Text>
            <div>
              <Progress
                percent={signal.compositeScore}
                size="small"
                strokeColor={signal.compositeScore >= 80 ? '#52c41a' : signal.compositeScore >= 60 ? '#faad14' : '#ff4d4f'}
                format={(p) => <span style={{ fontWeight: 'bold' }}>{p}</span>}
              />
            </div>
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>置信区间</Text>
            <div style={{ fontWeight: 'bold' }}>
              {signal.confidenceLow}% ~ {signal.confidenceHigh}%
            </div>
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>风险等级</Text>
            <div>
              <Tag color={riskColorMap[signal.riskLevel]}>{signal.riskLevel}</Tag>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Tooltip title="建议止损价位">
            <Text type="secondary">
              <ExclamationCircleOutlined /> 止损: <Text strong>{signal.suggestedStopLoss}</Text>
            </Text>
          </Tooltip>
          <Tooltip title="盈亏比">
            <Text type="secondary">
              盈亏比: <Text strong style={{ color: '#1677ff' }}>1:{signal.riskRewardRatio}</Text>
            </Text>
          </Tooltip>
        </div>

        <Paragraph
          ellipsis={{ rows: 2 }}
          type="secondary"
          style={{ fontSize: 12, marginBottom: 0 }}
        >
          {signal.reasonCn}
        </Paragraph>
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title={
          <Space>
            <Tag color={borderColor}>{gradeTextMap[signal.grade]}</Tag>
            <span>{signal.symbol} 信号详情</span>
          </Space>
        }
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={600}
      >
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="标的">{signal.symbol}</Descriptions.Item>
          <Descriptions.Item label="名称">{signal.name || '-'}</Descriptions.Item>
          <Descriptions.Item label="方向">
            <Tag color={directionColor} icon={directionIcon}>{directionText}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="级别">
            <Tag color={borderColor}>{gradeTextMap[signal.grade]}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="综合评分">{signal.compositeScore}</Descriptions.Item>
          <Descriptions.Item label="置信区间">
            {signal.confidenceLow}% ~ {signal.confidenceHigh}%
          </Descriptions.Item>
          <Descriptions.Item label="风险等级">
            <Tag color={riskColorMap[signal.riskLevel]}>{signal.riskLevel}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="盈亏比">1:{signal.riskRewardRatio}</Descriptions.Item>
          <Descriptions.Item label="建议止损">{signal.suggestedStopLoss}</Descriptions.Item>
          <Descriptions.Item label="策略来源">{signal.strategyName}</Descriptions.Item>
          <Descriptions.Item label="中文研判" span={2}>
            {signal.reasonCn}
          </Descriptions.Item>
        </Descriptions>

        <div style={{ marginTop: 16 }}>
          <Text strong>📊 证据明细</Text>
          <div style={{ marginTop: 8 }}>
            {signal.evidence.map((ev, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '6px 0',
                  borderBottom: '1px solid #f0f0f0',
                }}
              >
                <Text>{ev.label}</Text>
                <Space>
                  <Text strong>{ev.value}</Text>
                  <Tag>{(ev.weight * 100).toFixed(0)}%</Tag>
                </Space>
              </div>
            ))}
          </div>
        </div>
      </Modal>
    </>
  )
}

export default SignalCard
