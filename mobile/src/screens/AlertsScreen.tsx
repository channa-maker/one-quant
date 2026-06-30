/**
 * ONE量化 · 告警列表
 * 实时告警 · 分级标记(P0红/P1橙/P2黄/P3蓝) · 详情展开
 */
import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
} from 'react-native';
import { useQuery } from '@tanstack/react-query';

// ── 类型 ──────────────────────────────────────────────────
type AlertLevel = 'P0' | 'P1' | 'P2' | 'P3';

interface Alert {
  id: string;
  level: AlertLevel;
  title: string;
  detail: string;
  source: string;
  createdAt: string;
  acknowledged: boolean;
}

// ── 颜色映射 ──────────────────────────────────────────────
const LEVEL_COLORS: Record<AlertLevel, string> = {
  P0: '#FF1744',   // 红 - 最高
  P1: '#FF9100',   // 橙
  P2: '#FFD600',   // 黄
  P3: '#448AFF',   // 蓝
};

const LEVEL_LABELS: Record<AlertLevel, string> = {
  P0: '🔴 紧急',
  P1: '🟠 严重',
  P2: '🟡 警告',
  P3: '🔵 通知',
};

// ── 模拟数据 ──────────────────────────────────────────────
const mockAlerts: Alert[] = [
  {
    id: 'a1',
    level: 'P0',
    title: '强平预警',
    detail: '账户保证金比例已降至 112%，距离强平线（110%）仅差 2%。建议立即补充保证金或减仓。当前持仓：IF2407 多头 5 手。',
    source: '风控引擎',
    createdAt: '2026-06-30T11:58:00Z',
    acknowledged: false,
  },
  {
    id: 'a2',
    level: 'P1',
    title: '策略回撤超限',
    detail: '趋势跟踪策略当日回撤达 -3.2%，超过设定阈值 -3.0%。策略已自动暂停，等待人工确认后恢复。',
    source: '策略监控',
    createdAt: '2026-06-30T11:30:00Z',
    acknowledged: false,
  },
  {
    id: 'a3',
    level: 'P2',
    title: '大额委托提醒',
    detail: '检测到单笔委托金额超过 50 万元（阈值：50万）。标的：贵州茅台 600519，委托价：1685.00，数量：300 股。',
    source: '交易监控',
    createdAt: '2026-06-30T10:15:00Z',
    acknowledged: true,
  },
  {
    id: 'a4',
    level: 'P3',
    title: '研报就绪',
    detail: 'AI 研报《半导体行业深度分析》已生成完毕，共 42 页。包含行业趋势、核心标的、风险提示等章节。',
    source: '研报系统',
    createdAt: '2026-06-30T09:00:00Z',
    acknowledged: true,
  },
];

// ── 单条告警 ──────────────────────────────────────────────
function AlertCard({ alert }: { alert: Alert }) {
  const [expanded, setExpanded] = useState(false);
  const color = LEVEL_COLORS[alert.level];

  return (
    <TouchableOpacity
      style={[styles.alertCard, { borderLeftColor: color }]}
      onPress={() => setExpanded(!expanded)}
      activeOpacity={0.7}
    >
      {/* 头部 */}
      <View style={styles.alertHeader}>
        <View style={[styles.levelBadge, { backgroundColor: color }]}>
          <Text style={styles.levelText}>{alert.level}</Text>
        </View>
        <Text style={styles.alertTitle} numberOfLines={1}>
          {alert.title}
        </Text>
        {!alert.acknowledged && <View style={styles.unreadDot} />}
      </View>

      {/* 来源和时间 */}
      <View style={styles.alertMeta}>
        <Text style={styles.alertSource}>{alert.source}</Text>
        <Text style={styles.alertTime}>
          {new Date(alert.createdAt).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </Text>
      </View>

      {/* 展开详情 */}
      {expanded && (
        <View style={styles.alertDetailContainer}>
          <Text style={styles.alertDetail}>{alert.detail}</Text>
          {!alert.acknowledged && (
            <TouchableOpacity style={styles.ackButton}>
              <Text style={styles.ackButtonText}>确认已读</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* 展开提示 */}
      <Text style={styles.expandHint}>
        {expanded ? '▲ 收起' : '▼ 点击查看详情'}
      </Text>
    </TouchableOpacity>
  );
}

// ── 主组件 ────────────────────────────────────────────────
export default function AlertsScreen() {
  const [refreshing, setRefreshing] = useState(false);

  const { data: alerts, refetch } = useQuery({
    queryKey: ['alerts'],
    queryFn: async () => {
      // TODO: 替换为真实 API
      await new Promise((r) => setTimeout(r, 300));
      return mockAlerts;
    },
  });

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    await refetch();
    setRefreshing(false);
  }, []);

  const unackCount = (alerts ?? []).filter((a) => !a.acknowledged).length;

  return (
    <View style={styles.container}>
      {/* 统计栏 */}
      <View style={styles.statsBar}>
        <Text style={styles.statsText}>
          共 {(alerts ?? []).length} 条告警
        </Text>
        {unackCount > 0 && (
          <View style={styles.unackBadge}>
            <Text style={styles.unackText}>{unackCount} 条未读</Text>
          </View>
        )}
      </View>

      {/* 列表 */}
      <FlatList
        data={alerts ?? []}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <AlertCard alert={item} />}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#4FC3F7"
            colors={['#4FC3F7']}
          />
        }
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <Text style={styles.emptyText}>暂无告警 🎉</Text>
        }
      />
    </View>
  );
}

// ── 样式 ──────────────────────────────────────────────────
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#141414',
  },
  statsBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#2A2A2A',
  },
  statsText: {
    color: '#888',
    fontSize: 13,
  },
  unackBadge: {
    backgroundColor: '#FF1744',
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  unackText: {
    color: '#FFF',
    fontSize: 12,
    fontWeight: '600',
  },
  listContent: {
    padding: 16,
  },
  alertCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    padding: 14,
    marginBottom: 10,
    borderLeftWidth: 4,
  },
  alertHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  levelBadge: {
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    marginRight: 10,
  },
  levelText: {
    color: '#FFF',
    fontWeight: 'bold',
    fontSize: 12,
  },
  alertTitle: {
    color: '#E0E0E0',
    fontSize: 15,
    fontWeight: '600',
    flex: 1,
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#FF1744',
    marginLeft: 8,
  },
  alertMeta: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  alertSource: {
    color: '#666',
    fontSize: 12,
  },
  alertTime: {
    color: '#666',
    fontSize: 12,
  },
  alertDetailContainer: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#2A2A2A',
  },
  alertDetail: {
    color: '#BDBDBD',
    fontSize: 14,
    lineHeight: 22,
  },
  ackButton: {
    backgroundColor: '#2A2A2A',
    borderRadius: 6,
    paddingVertical: 8,
    paddingHorizontal: 16,
    alignSelf: 'flex-start',
    marginTop: 12,
  },
  ackButtonText: {
    color: '#4FC3F7',
    fontSize: 13,
    fontWeight: '600',
  },
  expandHint: {
    color: '#555',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 8,
  },
  emptyText: {
    color: '#666',
    textAlign: 'center',
    marginTop: 64,
    fontSize: 16,
  },
});
