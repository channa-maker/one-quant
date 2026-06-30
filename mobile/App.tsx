/**
 * ONE量化 - 移动端入口
 * 深色主题 · 全中文菜单 · React Navigation
 */
import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Text, View, StyleSheet } from 'react-native';

import DashboardScreen from './src/screens/DashboardScreen';
import AlertsScreen from './src/screens/AlertsScreen';
import SignalScreen from './src/screens/SignalScreen';
import { useAuth } from './src/hooks/useAuth';
import { registerPushNotifications } from './src/services/pushNotification';

// ── 深色主题 ──────────────────────────────────────────────
const DarkTheme = {
  ...DefaultTheme,
  dark: true,
  colors: {
    ...DefaultTheme.colors,
    primary: '#4FC3F7',
    background: '#141414',
    card: '#1E1E1E',
    text: '#E0E0E0',
    border: '#2A2A2A',
    notification: '#FF5252',
  },
};

// ── 导航类型 ──────────────────────────────────────────────
type TabParamList = {
  '总览': undefined;
  '信号': { signalId?: string };
  '告警': undefined;
};

type RootStackParamList = {
  Main: undefined;
  SignalDetail: { signalId: string };
};

const Tab = createBottomTabNavigator<TabParamList>();
const Stack = createNativeStackNavigator<RootStackParamList>();

// ── Tab 图标（文字 emoji 替代，生产环境换真实图标）──
function TabIcon({ name, color, size }: { name: string; color: string; size: number }) {
  const icons: Record<string, string> = {
    '总览': '📊',
    '信号': '⚡',
    '告警': '🔔',
  };
  return <Text style={{ fontSize: size, color }}>{icons[name] ?? '📱'}</Text>;
}

// ── 底部 Tab 导航 ─────────────────────────────────────────
function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ color, size }) => (
          <TabIcon name={route.name} color={color} size={size} />
        ),
        tabBarActiveTintColor: '#4FC3F7',
        tabBarInactiveTintColor: '#666',
        tabBarStyle: {
          backgroundColor: '#1E1E1E',
          borderTopColor: '#2A2A2A',
        },
        headerStyle: { backgroundColor: '#1E1E1E' },
        headerTintColor: '#E0E0E0',
      })}
    >
      <Tab.Screen
        name="总览"
        component={DashboardScreen}
        options={{ title: '总览', headerTitle: 'ONE量化 · 总览' }}
      />
      <Tab.Screen
        name="信号"
        component={SignalScreen}
        options={{ title: '信号', headerTitle: 'ONE量化 · 信号' }}
      />
      <Tab.Screen
        name="告警"
        component={AlertsScreen}
        options={{ title: '告警', headerTitle: 'ONE量化 · 告警' }}
      />
    </Tab.Navigator>
  );
}

// ── 查询客户端 ─────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
    },
  },
});

// ── 登录占位 ──────────────────────────────────────────────
function LoginPlaceholder() {
  return (
    <View style={styles.loginContainer}>
      <Text style={styles.loginTitle}>ONE量化</Text>
      <Text style={styles.loginSubtitle}>请先登录</Text>
    </View>
  );
}

// ── 根组件 ────────────────────────────────────────────────
export default function App() {
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (isAuthenticated) {
      registerPushNotifications();
    }
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <View style={styles.loginContainer}>
        <Text style={styles.loginTitle}>加载中…</Text>
      </View>
    );
  }

  if (!isAuthenticated) {
    return (
      <NavigationContainer theme={DarkTheme}>
        <StatusBar style="light" />
        <LoginPlaceholder />
      </NavigationContainer>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <NavigationContainer theme={DarkTheme}>
        <StatusBar style="light" />
        <Stack.Navigator screenOptions={{ headerShown: false }}>
          <Stack.Screen name="Main" component={MainTabs} />
          <Stack.Screen
            name="SignalDetail"
            component={SignalScreen}
            options={{
              headerShown: true,
              title: '信号详情',
              headerStyle: { backgroundColor: '#1E1E1E' },
              headerTintColor: '#E0E0E0',
            }}
          />
        </Stack.Navigator>
      </NavigationContainer>
    </QueryClientProvider>
  );
}

const styles = StyleSheet.create({
  loginContainer: {
    flex: 1,
    backgroundColor: '#141414',
    alignItems: 'center',
    justifyContent: 'center',
  },
  loginTitle: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#4FC3F7',
  },
  loginSubtitle: {
    fontSize: 16,
    color: '#888',
    marginTop: 12,
  },
});
