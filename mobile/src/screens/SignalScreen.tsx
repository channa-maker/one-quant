/**
 * ONE量化 · 信号详情
 * 信号卡详情 · 一键跟单(过风控+二次确认) · 加入观察 · 👍👎 反馈
 */
import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

// ── 类型 ──────────────────────────────────────────────────
interface SignalDetail {
  id: string;
  symbol: string;
  name: string;
  direction: 'LONG' | 'SHORT';
  grade: 'S' | 'A' | 'B' | 'C';
  confidence: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  riskReward: number;
  reasoning: string;
  factors: string[];
  createdAt: string;
  expiresAt: string;
}

// ── 模拟数据 ──────────────────────────────────────────────
const mockSignal: SignalDetail = {
  id: 's1',
  symbol: '600519',
  name: '贵州茅台',
  direction: 'LONG',
  grade: 'S',
  confidence: 0.92,
  entryPrice: 1680.0,
  stopLoss: 1640.0,
  takeProfit: 1780.0,
  riskReward: 2.5,
  reasoning: '多因子模型综合研判：技术面突破关键压力位，资金面北向持续流入，基本面业绩超预期。三因子共振，形成 S 级做多信号。',
  factors: ['技术面突破', '北向资金流入', '业绩超预期', 'MACD金叉', '成交量放大'],
  createdAt: '2026-06-30T10:30:00Z',
  expiresAt: '2026-07-01T10:30:00Z',
};

// ── 格式化 ────────────────────────────────────────────────
function formatPrice(n: number): string {
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ── 信号等级颜色 ──────────────────────────────────────────
const GRADE_COLORS: Record<string, string> = {
  S: '#FFD700',
  A: '#FF6D00',
  B: '#4FC3F7',
  C: '#888',
};

// ── 主组件 ────────────────────────────────────────────────
export default function SignalScreen({ route }: any) {
  const signalId = route?.params?.signalId ?? 's1';
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);

  // 获取信号详情
  const { data: signal, isLoading } = useQuery({
    queryKey: ['signal', signalId],
    queryFn: async () => {
      // TODO: 替换为真实 API
      await new Promise((r) => setTimeout(r, 500));
      return mockSignal;
    },
  });

  // 一键跟单
  const followMutation = useMutation({
    mutationFn: async (signalId: string) => {
      // TODO: 调用后端跟单 API（会经过风控检查）
      await new Promise((r) => setTimeout(r, 1000));
      return { success: true, orderId: 'ORD-' + Date.now() };
    },
    onSuccess: (data) => {
      Alert.alert('跟单成功', `委托已提交，订单号：${data.orderId}`, [{ text: '确定' }]);
    },
    onError: (error: any) => {
      Alert.alert('跟单失败', error.message || '风控检查未通过', [{ text: '确定' }]);
    },
  });

  // 加入观察
  const watchMutation = useMutation({
    mutationFn: async (signalId: string) => {
      await new Promise((r) => setTimeout(r, 500));
      return { success: true };
    },
    onSuccess: () => {
      Alert.alert('已加入观察', '该信号已添加到您的观察列表', [{ text: '确定' }]);
    },
  });

  // 反馈
  const feedbackMutation = useMutation({
    mutationFn: async ({ signalId, type }: { signalId: string; type: 'up' | 'down' }) => {
      await new Promise((r) => setTimeout(r, 300));
      return { success: true };
    },
  });

  // ── 二次确认跟单 ──────────────────────────────────────
  const handleFollow = useCallback(() => {
    if (!signal) return;

    const directionText = signal.direction === 'LONG' ? '做多' : '做空';
    const message = [
      `标的：${signal.name}（${signal.symbol}）`,
      `方向：${directionText}`,
      `入场价：¥${formatPrice(signal.entryPrice)}`,
      `止损：¥${formatPrice(signal.stopLoss)}`,
      `止盈：¥${formatPrice(signal.takeProfit)}`,
      `风险收益比：1:${signal.riskReward}`,
      '',
      '确认提交委托？',
    ].join('\n');

    Alert.alert('⚠️ 确认跟单', message, [
      { text: '取消', style: 'cancel' },
      {
        text: '确认跟单',
        style: 'destructive',
        onPress: () => followMutation.mutate(signal.id),
      },
    ]);
  }, [signal, followMutation]);

  // ── 反馈处理 ──────────────────────────────────────────
  const handleFeedback = useCallback(
    (type: 'up' | 'down') => {
      if (!signal) return;
      setFeedback(type);
      feedbackMutation.mutate({ signalId: signal.id, type });
    },
    [signal, feedbackMutation],
  );

  // ── 加载中 ────────────────────────────────────────────
  if (isLoading || !signal) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#4FC3F7" />
        <Text style={styles.loadingText}>加载信号详情…</Text>
      </View>
    );
  }

  const directionText = signal.direction === 'LONG' ? '📈 做多' : '📉 做空';
  const gradeColor = GRADE_COLORS[signal.grade] ?? '#888';

  return (
    <ScrollView style={styles.container}>
      {/* 信号头部 */}
      <View style={styles.headerCard}>
        <View style={styles.headerRow}>
          <View style={[styles.gradeBadge, { backgroundColor: gradeColor }]}>
            <Text style={styles.gradeText}>{signal.grade} 级</Text>
          </View>
          <Text style={styles.directionText}>{directionText}</Text>
        </View>
        <Text style={styles.signalName}>{signal.name}</Text>
        <Text style={styles.signalSymbol}>{signal.symbol}</Text>
        <Text style={styles.confidenceText}>
          置信度：{(signal.confidence * 100).toFixed(0)}%
        </Text>
      </View>

      {/* 关键价格 */}
      <View style={styles.priceCard}>
        <View style={styles.priceRow}>
          <View style={styles.priceItem}>
            <Text style={styles.priceLabel}>入场价</Text>
            <Text style={styles.priceValue}>¥{formatPrice(signal.entryPrice)}</Text>
          </View>
          <View style={styles.priceItem}>
            <Text style={styles.priceLabel}>止损价</Text>
            <Text style={[styles.priceValue, { color: '#4CAF50' }]}>
              ¥{formatPrice(signal.stopLoss)}
            </Text>
          </View>
          <View style={styles.priceItem}>
            <Text style={styles.priceLabel}>止盈价</Text>
            <Text style={[styles.priceValue, { color: '#FF5252' }]}>
              ¥{formatPrice(signal.takeProfit)}
            </Text>
          </View>
        </View>
        <View style={styles.rrRow}>
          <Text style={styles.rrLabel}>风险收益比</Text>
          <Text style={styles.rrValue}>1 : {signal.riskReward}</Text>
        </View>
      </View>

      {/* 研判逻辑 */}
      <View style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>🧠 研判逻辑</Text>
        <Text style={styles.reasoningText}>{signal.reasoning}</Text>
      </View>

      {/* 因子标签 */}
      <View style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>📊 驱动因子</Text>
        <View style={styles.factorList}>
          {signal.factors.map((f, i) => (
            <View key={i} style={styles.factorTag}>
              <Text style={styles.factorText}>{f}</Text>
            </View>
          ))}
        </View>
      </View>

      {/* 有效期 */}
      <View style={styles.sectionCard}>
        <Text style={styles.sectionTitle}>⏰ 有效期</Text>
        <Text style={styles.metaText}>
          生成：{new Date(signal.createdAt).toLocaleString('zh-CN')}
        </Text>
        <Text style={styles.metaText}>
          过期：{new Date(signal.expiresAt).toLocaleString('zh-CN')}
        </Text>
      </View>

      {/* 操作按钮 */}
      <View style={styles.actionSection}>
        {/* 一键跟单 */}
        <TouchableOpacity
          style={[styles.followButton, followMutation.isPending && styles.disabledButton]}
          onPress={handleFollow}
          disabled={followMutation.isPending}
        >
          {followMutation.isPending ? (
            <ActivityIndicator color="#141414" />
          ) : (
            <Text style={styles.followButtonText}>⚡ 一键跟单</Text>
          )}
        </TouchableOpacity>

        {/* 加入观察 */}
        <TouchableOpacity
          style={styles.watchButton}
          onPress={() => signal && watchMutation.mutate(signal.id)}
          disabled={watchMutation.isPending}
        >
          <Text style={styles.watchButtonText}>👁 加入观察</Text>
        </TouchableOpacity>
      </View>

      {/* 反馈区 */}
      <View style={styles.feedbackSection}>
        <Text style={styles.feedbackTitle}>信号反馈</Text>
        <View style={styles.feedbackRow}>
          <TouchableOpacity
            style={[
              styles.feedbackButton,
              feedback === 'up' && styles.feedbackActiveUp,
            ]}
            onPress={() => handleFeedback('up')}
          >
            <Text style={styles.feedbackEmoji}>👍</Text>
            <Text style={styles.feedbackLabel}>有用</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.feedbackButton,
              feedback === 'down' && styles.feedbackActiveDown,
            ]}
            onPress={() => handleFeedback('down')}
          >
            <Text style={styles.feedbackEmoji}>👎</Text>
            <Text style={styles.feedbackLabel}>没用</Text>
          </TouchableOpacity>
        </View>
      </View>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

// ── 样式 ──────────────────────────────────────────────────
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#141414',
  },
  loadingContainer: {
    flex: 1,
    backgroundColor: '#141414',
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingText: {
    color: '#888',
    marginTop: 12,
    fontSize: 14,
  },
  headerCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    padding: 20,
    margin: 16,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  gradeBadge: {
    borderRadius: 6,
    paddingHorizontal: 12,
    paddingVertical: 4,
    marginRight: 12,
  },
  gradeText: {
    color: '#141414',
    fontWeight: 'bold',
    fontSize: 16,
  },
  directionText: {
    color: '#E0E0E0',
    fontSize: 16,
    fontWeight: '600',
  },
  signalName: {
    color: '#E0E0E0',
    fontSize: 24,
    fontWeight: 'bold',
  },
  signalSymbol: {
    color: '#666',
    fontSize: 14,
    marginTop: 2,
  },
  confidenceText: {
    color: '#4FC3F7',
    fontSize: 14,
    marginTop: 8,
  },
  priceCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 16,
    marginBottom: 12,
  },
  priceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  priceItem: {
    alignItems: 'center',
    flex: 1,
  },
  priceLabel: {
    color: '#888',
    fontSize: 12,
    marginBottom: 4,
  },
  priceValue: {
    color: '#E0E0E0',
    fontSize: 18,
    fontWeight: 'bold',
  },
  rrRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 16,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#2A2A2A',
  },
  rrLabel: {
    color: '#888',
    fontSize: 14,
  },
  rrValue: {
    color: '#FFD700',
    fontSize: 16,
    fontWeight: 'bold',
  },
  sectionCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 16,
    marginBottom: 12,
  },
  sectionTitle: {
    color: '#E0E0E0',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 10,
  },
  reasoningText: {
    color: '#BDBDBD',
    fontSize: 14,
    lineHeight: 24,
  },
  factorList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  factorTag: {
    backgroundColor: '#2A2A2A',
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  factorText: {
    color: '#4FC3F7',
    fontSize: 13,
  },
  metaText: {
    color: '#888',
    fontSize: 13,
    marginBottom: 4,
  },
  actionSection: {
    paddingHorizontal: 16,
    marginTop: 8,
  },
  followButton: {
    backgroundColor: '#FFD700',
    borderRadius: 10,
    paddingVertical: 16,
    alignItems: 'center',
    marginBottom: 10,
  },
  followButtonText: {
    color: '#141414',
    fontSize: 18,
    fontWeight: 'bold',
  },
  disabledButton: {
    opacity: 0.6,
  },
  watchButton: {
    backgroundColor: '#2A2A2A',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#4FC3F7',
  },
  watchButtonText: {
    color: '#4FC3F7',
    fontSize: 16,
    fontWeight: '600',
  },
  feedbackSection: {
    paddingHorizontal: 16,
    marginTop: 20,
    alignItems: 'center',
  },
  feedbackTitle: {
    color: '#888',
    fontSize: 14,
    marginBottom: 12,
  },
  feedbackRow: {
    flexDirection: 'row',
    gap: 20,
  },
  feedbackButton: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 28,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#2A2A2A',
  },
  feedbackActiveUp: {
    borderColor: '#4CAF50',
    backgroundColor: '#1B3A1B',
  },
  feedbackActiveDown: {
    borderColor: '#FF5252',
    backgroundColor: '#3A1B1B',
  },
  feedbackEmoji: {
    fontSize: 28,
  },
  feedbackLabel: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
});
