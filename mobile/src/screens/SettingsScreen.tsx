/**
 * ONE量化 · 设置页面
 * 交易所配置 · 通知开关 · 主题切换 · 关于
 */
import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Switch,
  Alert,
  Linking,
} from 'react-native';

// ── 类型 ──────────────────────────────────────────────────
type ThemeMode = 'dark' | 'light' | 'auto';

interface ExchangeConfig {
  id: string;
  name: string;
  icon: string;
  connected: boolean;
  account: string;
}

// ── 模拟交易所配置 ────────────────────────────────────────
const mockExchanges: ExchangeConfig[] = [
  { id: 'binance', name: 'Binance', icon: '🟡', connected: true, account: '****8842' },
  { id: 'sse', name: '上交所 (SSE)', icon: '🔴', connected: true, account: 'A123456789' },
  { id: 'szse', name: '深交所 (SZSE)', icon: '🔵', connected: true, account: '0123456789' },
  { id: 'hkex', name: '港交所 (HKEX)', icon: '🟢', connected: false, account: '' },
  { id: 'nasdaq', name: 'NASDAQ', icon: '🟣', connected: false, account: '' },
];

// ── 子组件 ────────────────────────────────────────────────
function SectionHeader({ title }: { title: string }) {
  return <Text style={styles.sectionHeader}>{title}</Text>;
}

function SettingRow({
  label,
  value,
  onPress,
  right,
}: {
  label: string;
  value?: string;
  onPress?: () => void;
  right?: React.ReactNode;
}) {
  return (
    <TouchableOpacity style={styles.settingRow} onPress={onPress} disabled={!onPress}>
      <Text style={styles.settingLabel}>{label}</Text>
      <View style={styles.settingRight}>
        {value && <Text style={styles.settingValue}>{value}</Text>}
        {right}
        {onPress && <Text style={styles.arrow}>›</Text>}
      </View>
    </TouchableOpacity>
  );
}

function ExchangeCard({ exchange }: { exchange: ExchangeConfig }) {
  return (
    <TouchableOpacity style={styles.exchangeCard}>
      <View style={styles.exchangeHeader}>
        <Text style={styles.exchangeIcon}>{exchange.icon}</Text>
        <View style={styles.exchangeInfo}>
          <Text style={styles.exchangeName}>{exchange.name}</Text>
          <Text style={[styles.exchangeStatus, { color: exchange.connected ? '#4CAF50' : '#888' }]}>
            {exchange.connected ? '已连接' : '未连接'}
          </Text>
        </View>
        {exchange.connected && (
          <Text style={styles.exchangeAccount}>{exchange.account}</Text>
        )}
      </View>
      {!exchange.connected && (
        <TouchableOpacity style={styles.connectButton}>
          <Text style={styles.connectButtonText}>连接</Text>
        </TouchableOpacity>
      )}
    </TouchableOpacity>
  );
}

// ── 主组件 ────────────────────────────────────────────────
export default function SettingsScreen() {
  const [pushEnabled, setPushEnabled] = useState(true);
  const [signalAlertEnabled, setSignalAlertEnabled] = useState(true);
  const [riskAlertEnabled, setRiskAlertEnabled] = useState(true);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [themeMode, setThemeMode] = useState<ThemeMode>('dark');
  const [colorMode, setColorMode] = useState<'red-up' | 'green-up'>('red-up');
  const [biometricEnabled, setBiometricEnabled] = useState(false);

  const themeLabels: Record<ThemeMode, string> = {
    dark: '深色模式',
    light: '浅色模式',
    auto: '跟随系统',
  };

  const handleThemeChange = () => {
    const modes: ThemeMode[] = ['dark', 'light', 'auto'];
    const currentIndex = modes.indexOf(themeMode);
    const nextMode = modes[(currentIndex + 1) % modes.length];
    setThemeMode(nextMode);
  };

  const handleColorModeToggle = () => {
    setColorMode(colorMode === 'red-up' ? 'green-up' : 'red-up');
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {/* ── 交易所配置 ── */}
      <SectionHeader title="🔗 交易所配置" />
      {mockExchanges.map((ex) => (
        <ExchangeCard key={ex.id} exchange={ex} />
      ))}

      {/* ── 通知设置 ── */}
      <SectionHeader title="🔔 通知设置" />
      <View style={styles.card}>
        <SettingRow
          label="推送通知"
          right={
            <Switch
              value={pushEnabled}
              onValueChange={setPushEnabled}
              trackColor={{ false: '#333', true: 'rgba(79, 195, 247, 0.3)' }}
              thumbColor={pushEnabled ? '#4FC3F7' : '#666'}
            />
          }
        />
        <View style={styles.divider} />
        <SettingRow
          label="信号提醒"
          right={
            <Switch
              value={signalAlertEnabled}
              onValueChange={setSignalAlertEnabled}
              trackColor={{ false: '#333', true: 'rgba(79, 195, 247, 0.3)' }}
              thumbColor={signalAlertEnabled ? '#4FC3F7' : '#666'}
            />
          }
        />
        <View style={styles.divider} />
        <SettingRow
          label="风控告警"
          right={
            <Switch
              value={riskAlertEnabled}
              onValueChange={setRiskAlertEnabled}
              trackColor={{ false: '#333', true: 'rgba(79, 195, 247, 0.3)' }}
              thumbColor={riskAlertEnabled ? '#4FC3F7' : '#666'}
            />
          }
        />
        <View style={styles.divider} />
        <SettingRow
          label="提示音"
          right={
            <Switch
              value={soundEnabled}
              onValueChange={setSoundEnabled}
              trackColor={{ false: '#333', true: 'rgba(79, 195, 247, 0.3)' }}
              thumbColor={soundEnabled ? '#4FC3F7' : '#666'}
            />
          }
        />
      </View>

      {/* ── 显示设置 ── */}
      <SectionHeader title="🎨 显示设置" />
      <View style={styles.card}>
        <SettingRow
          label="主题模式"
          value={themeLabels[themeMode]}
          onPress={handleThemeChange}
        />
        <View style={styles.divider} />
        <SettingRow
          label="涨跌颜色"
          value={colorMode === 'red-up' ? '红涨绿跌（A股）' : '绿涨红跌（美股）'}
          onPress={handleColorModeToggle}
        />
      </View>

      {/* ── 安全设置 ── */}
      <SectionHeader title="🔒 安全设置" />
      <View style={styles.card}>
        <SettingRow
          label="生物识别解锁"
          right={
            <Switch
              value={biometricEnabled}
              onValueChange={setBiometricEnabled}
              trackColor={{ false: '#333', true: 'rgba(79, 195, 247, 0.3)' }}
              thumbColor={biometricEnabled ? '#4FC3F7' : '#666'}
            />
          }
        />
        <View style={styles.divider} />
        <SettingRow
          label="修改密码"
          onPress={() => Alert.alert('提示', '密码修改功能开发中')}
        />
        <View style={styles.divider} />
        <SettingRow
          label="API 密钥管理"
          onPress={() => Alert.alert('提示', 'API 密钥管理功能开发中')}
        />
      </View>

      {/* ── 数据管理 ── */}
      <SectionHeader title="📦 数据管理" />
      <View style={styles.card}>
        <SettingRow
          label="清除缓存"
          value="12.3 MB"
          onPress={() => {
            Alert.alert('确认清除', '将清除本地缓存数据，不影响账户数据', [
              { text: '取消', style: 'cancel' },
              { text: '清除', style: 'destructive', onPress: () => Alert.alert('已完成', '缓存已清除') },
            ]);
          }}
        />
        <View style={styles.divider} />
        <SettingRow
          label="导出交易记录"
          onPress={() => Alert.alert('提示', '导出功能开发中')}
        />
      </View>

      {/* ── 关于 ── */}
      <SectionHeader title="ℹ️ 关于" />
      <View style={styles.card}>
        <SettingRow label="版本" value="1.0.0" />
        <View style={styles.divider} />
        <SettingRow
          label="用户协议"
          onPress={() => Linking.openURL('https://onequant.example.com/terms')}
        />
        <View style={styles.divider} />
        <SettingRow
          label="隐私政策"
          onPress={() => Linking.openURL('https://onequant.example.com/privacy')}
        />
        <View style={styles.divider} />
        <SettingRow
          label="联系我们"
          onPress={() => Linking.openURL('mailto:support@onequant.example.com')}
        />
        <View style={styles.divider} />
        <SettingRow label="开源许可" onPress={() => Alert.alert('开源许可', 'MIT License\n\n本项目使用了以下开源库：\n- React Native\n- React Navigation\n- React Query\n- Expo')} />
      </View>

      {/* 退出登录 */}
      <TouchableOpacity
        style={styles.logoutButton}
        onPress={() => {
          Alert.alert('确认退出', '退出后需要重新登录', [
            { text: '取消', style: 'cancel' },
            { text: '退出', style: 'destructive', onPress: () => {} },
          ]);
        }}
      >
        <Text style={styles.logoutText}>退出登录</Text>
      </TouchableOpacity>

      <Text style={styles.footer}>ONE量化 © 2026</Text>

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
  content: {
    padding: 16,
  },
  sectionHeader: {
    color: '#E0E0E0',
    fontSize: 16,
    fontWeight: 'bold',
    marginTop: 20,
    marginBottom: 12,
  },
  card: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    overflow: 'hidden',
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 16,
  },
  settingLabel: {
    color: '#E0E0E0',
    fontSize: 15,
  },
  settingRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  settingValue: {
    color: '#888',
    fontSize: 14,
  },
  arrow: {
    color: '#555',
    fontSize: 20,
  },
  divider: {
    height: 1,
    backgroundColor: '#2A2A2A',
    marginLeft: 16,
  },
  exchangeCard: {
    backgroundColor: '#1E1E1E',
    borderRadius: 10,
    padding: 14,
    marginBottom: 8,
  },
  exchangeHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  exchangeIcon: {
    fontSize: 24,
    marginRight: 12,
  },
  exchangeInfo: {
    flex: 1,
  },
  exchangeName: {
    color: '#E0E0E0',
    fontSize: 15,
    fontWeight: '600',
  },
  exchangeStatus: {
    fontSize: 12,
    marginTop: 2,
  },
  exchangeAccount: {
    color: '#666',
    fontSize: 12,
  },
  connectButton: {
    backgroundColor: '#4FC3F7',
    borderRadius: 6,
    paddingVertical: 8,
    paddingHorizontal: 20,
    alignSelf: 'flex-end',
    marginTop: 10,
  },
  connectButtonText: {
    color: '#141414',
    fontSize: 13,
    fontWeight: '600',
  },
  logoutButton: {
    backgroundColor: 'rgba(255, 82, 82, 0.1)',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 24,
    borderWidth: 1,
    borderColor: '#FF5252',
  },
  logoutText: {
    color: '#FF5252',
    fontSize: 16,
    fontWeight: '600',
  },
  footer: {
    color: '#444',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 16,
  },
});
