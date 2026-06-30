/**
 * ONE量化 · 总览
 * 总资产、今日盈亏、持仓列表、最新S级信号、下拉刷新
 */
import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { useQuery } from '@tanstack/react-query';

// ── 类型 ──────────────────────────────────────────────────
interface PortfolioSummary {
  totalAssets: number;
  todayPnl: number;
  todayPnlPercent: number;
  availableCash: number;
}

interface Position {
  id: string;
  symbol: string;
  name: string;
  quantity: number;
  currentPrice: number;
  costPrice: number;
  pnl: number;
  pnlPercent: number;
}

interface Signal {
  id: string;
  symbol: string;
  name: string;
  direction: 'LONG' | 'SHORT';
  grade: 'S' | 'A' | 'B' | 'C';
  confidence: number;
  createdAt: string;
}

// ── 模拟数据（生产环境替换为 API 调用）──
const mockPortfolio: PortfolioSummary = {
  totalAssets: 1_256_800.5,
  todayPnl: 12_350.8,
  todayPnlPercent: 0.99,
  availableCash: 356_200.0,
};

const mockPositions: Position[] = [
  { id: '1', symbol: '600519', name: '贵州茅台', quantity: 100, currentPrice: 1680.0, costPrice: 1620.0, pnl: 6000, pnlPercent: 3.7 },
  { id: '2', symbol: '000858', name: '五粮液', quantity: 200, currentPrice: 152.5, costPrice: 148.0, pnl: 900, pnlPercent: 3.04 },
  { id: '3', symbol: '601318', name: '中国平安', quantity: 500, currentPrice: 48.2, costPrice: 50.1, pnl: -950, pnlPercent: -3.79 },
];

const mockSignals: Signal[] = [
  { id: 's1', symbol: '600519', name: '贵州茅台', direction: 'LONG', grade: 'S', confidence: 0.92, createdAt: '2026-06-30T10:30:00Z' },
  { id: 's2', symbol: '300750', name: '宁德时代', direction: 'LONG', grade: 'S', confidence: 0.88, createdAt: '2026-06-30T09:45:00Z' },
];

// ── 格式化 ────────────────────────────────────────────────
function formatMoney(n: number): string {
  return n.toLocaleString('zh-CN', { style: 'currency', currency: 'CNY' });
}

function formatPercent(n: number): string {
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

function pnlColor(n: number): string {
  if (n > 0) return '#FF5252';   // A股红涨
  if (n < 0) return '#4CAF50';   // 绿跌
  return '#888';
}

// ── 子组件 ────────────────────────────────────────────────
function PortfolioCard({ data }: { data: PortfolioSummary }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardLabel}>总资产</Text>
      <Text style={styles.totalAssets}>{formatMoney(data.totalAssets)}</Text>
      <View style={styles.pnlRow}>
        <Text style={styles.cardLabel}>今日盈亏</Text>
        <Text style={[styles.pnlText, { color: pnlColor(data.todayPnl) }]}>
          {formatMoney(data.todayPnl)} ({formatPercent(data.todayPnlPercent)})
        </Text>
      </View>
      <View style={styles.pnlRow}>
        <Text style={styles.cardLabel}>可用资金</Text>
        <Text style={styles.cashText}>{formatMoney(data.availableCash)}</Text>
      </View>
    </View>
  );
}

function PositionRow({ item }: { item: Position }) {
  return (
    <View style={styles.positionRow}>
      <View style={styles.positionInfo}>
        <Text style={styles.positionName}>{item.name}</Text>
        <Text style={styles.positionSymbol}>{item.symbol}</Text>
      </View>
      <View style={styles.positionPrices}>
        <Text style={styles.positionPrice}>{formatMoney(item.currentPrice)}</Text>
        <Text style={[styles.positionPnl, { color: pnlColor(item.pnl) }]}>
          {formatPercent(item.pnlPercent)}
        </Text>
      </View>
    </View>
  );
}

function SignalCard({ signal, onPress }: { signal: Signal; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.signalCard} onPress={onPress}>
      <View style={styles.signalHeader}>
        <View style={styles.gradeBadge}>
          <Text style={styles.gradeText}>{signal.grade}</Text>
        </View>
        <Text style={styles.signalName}>{signal.name}</Text>
        <Text style={styles.signalDirection}>
          {signal.direction === 'LONG' ? '📈 做多' : '📉 做空'}
        </Text>
      </View>
      <View style={styles.signalMeta}>
        <Text style={styles.signalConfidence}>
          置信度: {(signal.confidence * 100).toFixed(0)}%
        </Text>
        <Text style={styles.signalTime}>
          {new Date(signal.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </Text>
      </View>
    </TouchableOpacity>
  );
}

// ── 主组件 ────────────────────────────────────────────────
export default function DashboardScreen({ navigation }: any) {
  const [refreshing, setRefreshing] = useState(false);

  const { data: portfolio, refetch: refetchPortfolio } = useQuery({
    queryKey: ['portfolio'],
    queryFn: async () => {
      // TODO: 替换为真实 API
      await new Promise((r) => setTimeout(r, 300));
      return mockPortfolio;
    },
  });

  const { data: positions, refetch: refetchPositions } = useQuery({
    queryKey: ['positions'],
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 300));
      return mockPositions;
    },
  });

  const { data: signals, refetch: refetchSignals } = useQuery({
    queryKey: ['signals', 'latest'],
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 300));
      return mockSignals;
    },
  });

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([refetchPortfolio(), refetchPositions(), refetchSignals()]);
    setRefreshing(false);
  }, []);

  return (
    <FlatList
      style={styles.container}
      data={positions ?? []}
      keyExtractor={(item) => item.id}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor="#4FC3F7"
          colors={['#4FC3F7']}
        />
      }
      ListHeaderComponent={
        <>
          {/* 总资产卡片 */}
          {portfolio && <PortfolioCard data={portfolio} />}

          {/* 最新 S 级信号 */}
          {signals && signals.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>⚡ 最新信号</Text>
              {signals.map((s) => (
                <SignalCard
                  key={s.id}
                  signal={s}
                  onPress={() => navigation.navigate('SignalDetail', { signalId: s.id })}
                />
              ))}
            </View>
          )}

          {/* 持仓列表标题 */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>📋 当前持仓</Text>
          </View>
        </>
      }
      renderItem={({ item }) => <PositionRow item={item} />}
      ListEmptyComponent={
        <Text style={styles.emptyText}>暂无持仓</Text>
      }
    />
  );
}

// ── 样式 ──────────────────────────────────────────────────
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#141414',
  },
  card: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    padding: 20,
    margin: 16,
  },
  cardLabel: {
    color: '#888',
    fontSize: 13,
  },
  totalAssets: {
    color: '#E0E0E0',
    fontSize: 32,
    fontWeight: 'bold',
    marginTop: 4,
  },
  pnlRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 12,
  },
  pnlText: {
    fontSize: 16,
    fontWeight: '600',
  },
  cashText: {
    color: '#BDBDBD',
    fontSize: 16,
  },
  section: {
    paddingHorizontal: 16,
    marginTop: 8,
  },
  sectionTitle: {
    color: '#E0E0E0',
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  positionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    padding: 14,
    marginHorizontal: 16,
    marginBottom: 8,
  },
  positionInfo: {
    flex: 1,
  },
  positionName: {
    color: '#E0E0E0',
    fontSize: 15,
    fontWeight: '600',
  },
  positionSymbol: {
    color: '#666',
    fontSize: 12,
    marginTop: 2,
  },
  positionPrices: {
    alignItems: 'flex-end',
  },
  positionPrice: {
    color: '#E0E0E0',
    fontSize: 15,
  },
  positionPnl: {
    fontSize: 13,
    marginTop: 2,
  },
  signalCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    padding: 14,
    marginBottom: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#FFD700',
  },
  signalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  gradeBadge: {
    backgroundColor: '#FFD700',
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 2,
    marginRight: 10,
  },
  gradeText: {
    color: '#141414',
    fontWeight: 'bold',
    fontSize: 14,
  },
  signalName: {
    color: '#E0E0E0',
    fontSize: 15,
    fontWeight: '600',
    flex: 1,
  },
  signalDirection: {
    color: '#888',
    fontSize: 13,
  },
  signalMeta: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  signalConfidence: {
    color: '#4FC3F7',
    fontSize: 13,
  },
  signalTime: {
    color: '#666',
    fontSize: 12,
  },
  emptyText: {
    color: '#666',
    textAlign: 'center',
    marginTop: 32,
    fontSize: 14,
  },
});
