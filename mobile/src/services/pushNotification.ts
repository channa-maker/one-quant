/**
 * ONE量化 · 推送通知服务
 * Expo Push Notifications
 * 推送分级：仅 S 级信号推送
 * 覆盖场景：强平预警 / 熔断 / 大额盈亏 / 研报就绪
 */
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

// ── 推送级别 ──────────────────────────────────────────────
export type PushLevel = 'S' | 'A' | 'B' | 'C';

// ── 推送场景 ──────────────────────────────────────────────
export type PushScenario =
  | 'LIQUIDATION_WARNING'   // 强平预警
  | 'CIRCUIT_BREAKER'       // 熔断触发
  | 'LARGE_PNL'             // 大额盈亏
  | 'REPORT_READY'          // 研报就绪
  | 'S_SIGNAL'              // S 级信号
  | 'RISK_BREACH';          // 风控突破

interface PushPayload {
  scenario: PushScenario;
  level: PushLevel;
  title: string;
  body: string;
  data?: Record<string, string>;
}

// ── 推送配置：仅 S 级推送 ─────────────────────────────────
const PUSH_ENABLED_LEVELS: Set<PushLevel> = new Set(['S']);

// 场景默认级别
const SCENARIO_LEVELS: Record<PushScenario, PushLevel> = {
  LIQUIDATION_WARNING: 'S',
  CIRCUIT_BREAKER: 'S',
  LARGE_PNL: 'S',
  REPORT_READY: 'A',
  S_SIGNAL: 'S',
  RISK_BREACH: 'S',
};

// ── 通知行为配置 ──────────────────────────────────────────
Notifications.setNotificationHandler({
  handleNotification: async (notification) => {
    const level = notification.request.content.data?.level as PushLevel | undefined;
    return {
      shouldShowAlert: level === 'S',
      shouldPlaySound: level === 'S',
      shouldSetBadge: true,
    };
  },
});

// ── 注册推送 ──────────────────────────────────────────────
let expoPushToken: string | null = null;

export async function registerPushNotifications(): Promise<string | null> {
  try {
    // 检查权限
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    if (existingStatus !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== 'granted') {
      console.warn('[推送] 用户未授权推送权限');
      return null;
    }

    // Android 需要通知渠道
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: '默认通知',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#FF5252',
      });

      await Notifications.setNotificationChannelAsync('emergency', {
        name: '紧急告警',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 500, 200, 500],
        lightColor: '#FF1744',
        sound: 'default',
      });
    }

    // 获取 Expo Push Token
    const tokenData = await Notifications.getExpoPushTokenAsync({
      projectId: 'your-project-id', // TODO: 替换为实际 project ID
    });
    expoPushToken = tokenData.data;

    console.log('[推送] 注册成功，Token:', expoPushToken);

    // TODO: 将 token 发送到后端注册
    // await api.registerPushToken(expoPushToken);

    return expoPushToken;
  } catch (error) {
    console.error('[推送] 注册失败:', error);
    return null;
  }
}

// ── 发送本地推送（测试用）──
export async function sendLocalPush(payload: PushPayload): Promise<void> {
  // 仅 S 级推送
  if (!PUSH_ENABLED_LEVELS.has(payload.level)) {
    console.log(`[推送] ${payload.level} 级推送已过滤，仅推送 S 级`);
    return;
  }

  await Notifications.scheduleNotificationAsync({
    content: {
      title: payload.title,
      body: payload.body,
      data: {
        scenario: payload.scenario,
        level: payload.level,
        ...payload.data,
      },
      sound: 'default',
      priority: Notifications.AndroidNotificationPriority.MAX,
    },
    trigger: null, // 立即发送
  });
}

// ── 预设推送模板 ──────────────────────────────────────────
export const PushTemplates = {
  /** 强平预警 */
  liquidationWarning(accountId: string, marginRatio: number): PushPayload {
    return {
      scenario: 'LIQUIDATION_WARNING',
      level: 'S',
      title: '🔴 强平预警',
      body: `账户保证金比例已降至 ${marginRatio.toFixed(1)}%，请立即处理！`,
      data: { accountId },
    };
  },

  /** 熔断触发 */
  circuitBreaker(strategyName: string, drawdown: number): PushPayload {
    return {
      scenario: 'CIRCUIT_BREAKER',
      level: 'S',
      title: '⚡ 熔断触发',
      body: `策略「${strategyName}」触发熔断，回撤 ${drawdown.toFixed(2)}%，已自动暂停`,
      data: { strategyName },
    };
  },

  /** 大额盈亏 */
  largePnl(amount: number, symbol: string): PushPayload {
    const sign = amount >= 0 ? '+' : '';
    return {
      scenario: 'LARGE_PNL',
      level: 'S',
      title: amount >= 0 ? '💰 大额盈利' : '📉 大额亏损',
      body: `${symbol} 当日盈亏 ${sign}${amount.toLocaleString('zh-CN')} 元`,
      data: { symbol, amount: String(amount) },
    };
  },

  /** S 级信号 */
  sSignal(symbol: string, name: string, direction: 'LONG' | 'SHORT'): PushPayload {
    const dirText = direction === 'LONG' ? '做多' : '做空';
    return {
      scenario: 'S_SIGNAL',
      level: 'S',
      title: '⭐ S 级信号',
      body: `${name}（${symbol}）${dirText}信号，置信度 ≥ 85%`,
      data: { symbol, direction },
    };
  },

  /** 研报就绪 */
  reportReady(title: string): PushPayload {
    return {
      scenario: 'REPORT_READY',
      level: 'A',
      title: '📄 研报就绪',
      body: `AI 研报《${title}》已生成完毕`,
      data: { reportTitle: title },
    };
  },
};

// ── 推送事件监听 ──────────────────────────────────────────
export function addPushListener(
  onReceive: (payload: PushPayload) => void,
  onTap?: (payload: PushPayload) => void,
): () => void {
  const receiveSub = Notifications.addNotificationReceivedListener((notification) => {
    const data = notification.request.content.data as unknown as PushPayload;
    if (data?.level === 'S') {
      onReceive(data);
    }
  });

  const responseSub = Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content.data as unknown as PushPayload;
    onTap?.(data);
  });

  return () => {
    receiveSub.remove();
    responseSub.remove();
  };
}

// ── 获取当前 Token ────────────────────────────────────────
export function getExpoPushToken(): string | null {
  return expoPushToken;
}
