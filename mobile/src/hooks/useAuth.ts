/**
 * ONE量化 · 移动端鉴权 Hook
 * JWT + 生物识别 · Token 刷新 · 安全存储
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';

// ── 常量 ──────────────────────────────────────────────────
const STORAGE_KEYS = {
  ACCESS_TOKEN: 'onequant_access_token',
  REFRESH_TOKEN: 'onequant_refresh_token',
  USER_DATA: 'onequant_user_data',
  BIOMETRIC_ENABLED: 'onequant_biometric_enabled',
} as const;

const TOKEN_REFRESH_INTERVAL = 15 * 60 * 1000; // 15 分钟刷新一次

// ── 类型 ──────────────────────────────────────────────────
interface User {
  id: string;
  username: string;
  displayName: string;
  role: 'owner' | 'admin' | 'trader' | 'viewer';
  avatar?: string;
}

interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  tokens: AuthTokens | null;
  biometricEnabled: boolean;
  error: string | null;
}

interface UseAuthReturn extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  loginWithBiometric: () => Promise<void>;
  logout: () => Promise<void>;
  enableBiometric: () => Promise<boolean>;
  disableBiometric: () => Promise<void>;
  refreshToken: () => Promise<boolean>;
}

// ── 安全存储工具 ──────────────────────────────────────────
async function secureGet(key: string): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

async function secureSet(key: string, value: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(key, value);
  } catch (error) {
    console.error('[安全存储] 写入失败:', error);
  }
}

async function secureDelete(key: string): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(key);
  } catch (error) {
    console.error('[安全存储] 删除失败:', error);
  }
}

// ── API 调用（TODO: 替换为真实实现）──
async function apiLogin(
  username: string,
  password: string,
): Promise<{ user: User; tokens: AuthTokens }> {
  // 模拟登录
  await new Promise((r) => setTimeout(r, 800));

  if (username === 'demo' && password === 'demo') {
    return {
      user: {
        id: 'u1',
        username: 'demo',
        displayName: '演示用户',
        role: 'trader',
      },
      tokens: {
        accessToken: 'mock_access_token_' + Date.now(),
        refreshToken: 'mock_refresh_token_' + Date.now(),
        expiresAt: Date.now() + 60 * 60 * 1000, // 1 小时
      },
    };
  }

  throw new Error('用户名或密码错误');
}

async function apiRefreshToken(
  refreshToken: string,
): Promise<AuthTokens> {
  // 模拟刷新
  await new Promise((r) => setTimeout(r, 300));
  return {
    accessToken: 'mock_access_token_refreshed_' + Date.now(),
    refreshToken: refreshToken,
    expiresAt: Date.now() + 60 * 60 * 1000,
  };
}

// ── Hook ──────────────────────────────────────────────────
export function useAuth(): UseAuthReturn {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    user: null,
    tokens: null,
    biometricEnabled: false,
    error: null,
  });

  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 初始化：从安全存储恢复会话 ─────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const [accessJson, refreshJson, userJson, bioEnabled] = await Promise.all([
          secureGet(STORAGE_KEYS.ACCESS_TOKEN),
          secureGet(STORAGE_KEYS.REFRESH_TOKEN),
          secureGet(STORAGE_KEYS.USER_DATA),
          secureGet(STORAGE_KEYS.BIOMETRIC_ENABLED),
        ]);

        if (accessJson && refreshJson && userJson) {
          const tokens: AuthTokens = JSON.parse(accessJson);
          const user: User = JSON.parse(userJson);

          // 检查 token 是否过期
          if (tokens.expiresAt > Date.now()) {
            setState({
              isAuthenticated: true,
              isLoading: false,
              user,
              tokens,
              biometricEnabled: bioEnabled === 'true',
              error: null,
            });
          } else {
            // 尝试刷新
            const newTokens = await apiRefreshToken(tokens.refreshToken);
            await secureSet(STORAGE_KEYS.ACCESS_TOKEN, JSON.stringify(newTokens));
            setState({
              isAuthenticated: true,
              isLoading: false,
              user,
              tokens: newTokens,
              biometricEnabled: bioEnabled === 'true',
              error: null,
            });
          }
        } else {
          setState((prev) => ({ ...prev, isLoading: false }));
        }
      } catch {
        setState((prev) => ({ ...prev, isLoading: false }));
      }
    })();
  }, []);

  // ── Token 定时刷新 ─────────────────────────────────────
  useEffect(() => {
    if (!state.isAuthenticated || !state.tokens) return;

    const timeUntilRefresh = Math.max(
      state.tokens.expiresAt - Date.now() - 5 * 60 * 1000, // 提前 5 分钟刷新
      TOKEN_REFRESH_INTERVAL,
    );

    refreshTimerRef.current = setTimeout(async () => {
      const success = await refreshToken();
      if (!success) {
        console.warn('[鉴权] Token 刷新失败，需要重新登录');
      }
    }, timeUntilRefresh);

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [state.isAuthenticated, state.tokens]);

  // ── 登录 ────────────────────────────────────────────────
  const login = useCallback(async (username: string, password: string) => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const { user, tokens } = await apiLogin(username, password);

      await Promise.all([
        secureSet(STORAGE_KEYS.ACCESS_TOKEN, JSON.stringify(tokens)),
        secureSet(STORAGE_KEYS.REFRESH_TOKEN, tokens.refreshToken),
        secureSet(STORAGE_KEYS.USER_DATA, JSON.stringify(user)),
      ]);

      setState({
        isAuthenticated: true,
        isLoading: false,
        user,
        tokens,
        biometricEnabled: false,
        error: null,
      });
    } catch (error: any) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: error.message || '登录失败',
      }));
      throw error;
    }
  }, []);

  // ── 生物识别登录 ──────────────────────────────────────
  const loginWithBiometric = useCallback(async () => {
    const bioEnabled = await secureGet(STORAGE_KEYS.BIOMETRIC_ENABLED);
    if (bioEnabled !== 'true') {
      throw new Error('未启用生物识别');
    }

    const hasHardware = await LocalAuthentication.hasHardwareAsync();
    if (!hasHardware) {
      throw new Error('设备不支持生物识别');
    }

    const result = await LocalAuthentication.authenticateAsync({
      promptTitle: 'ONE量化 · 身份验证',
      promptMessage: '请验证身份以登录',
      cancelLabel: '取消',
      disableDeviceFallback: false,
    });

    if (!result.success) {
      throw new Error('生物识别验证失败');
    }

    // 从安全存储恢复会话
    const accessJson = await secureGet(STORAGE_KEYS.ACCESS_TOKEN);
    const userJson = await secureGet(STORAGE_KEYS.USER_DATA);
    const refreshJson = await secureGet(STORAGE_KEYS.REFRESH_TOKEN);

    if (accessJson && userJson && refreshJson) {
      const tokens: AuthTokens = JSON.parse(accessJson);
      const user: User = JSON.parse(userJson);

      // 检查是否需要刷新
      if (tokens.expiresAt <= Date.now()) {
        const newTokens = await apiRefreshToken(tokens.refreshToken);
        await secureSet(STORAGE_KEYS.ACCESS_TOKEN, JSON.stringify(newTokens));
        setState({
          isAuthenticated: true,
          isLoading: false,
          user,
          tokens: newTokens,
          biometricEnabled: true,
          error: null,
        });
      } else {
        setState({
          isAuthenticated: true,
          isLoading: false,
          user,
          tokens,
          biometricEnabled: true,
          error: null,
        });
      }
    } else {
      throw new Error('会话已过期，请使用密码登录');
    }
  }, []);

  // ── 登出 ────────────────────────────────────────────────
  const logout = useCallback(async () => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);

    await Promise.all([
      secureDelete(STORAGE_KEYS.ACCESS_TOKEN),
      secureDelete(STORAGE_KEYS.REFRESH_TOKEN),
      secureDelete(STORAGE_KEYS.USER_DATA),
    ]);

    setState({
      isAuthenticated: false,
      isLoading: false,
      user: null,
      tokens: null,
      biometricEnabled: false,
      error: null,
    });
  }, []);

  // ── 启用生物识别 ──────────────────────────────────────
  const enableBiometric = useCallback(async (): Promise<boolean> => {
    const hasHardware = await LocalAuthentication.hasHardwareAsync();
    if (!hasHardware) return false;

    const isEnrolled = await LocalAuthentication.isEnrolledAsync();
    if (!isEnrolled) return false;

    const result = await LocalAuthentication.authenticateAsync({
      promptTitle: '启用生物识别登录',
      promptMessage: '验证身份以启用快速登录',
    });

    if (result.success) {
      await secureSet(STORAGE_KEYS.BIOMETRIC_ENABLED, 'true');
      setState((prev) => ({ ...prev, biometricEnabled: true }));
      return true;
    }

    return false;
  }, []);

  // ── 禁用生物识别 ──────────────────────────────────────
  const disableBiometric = useCallback(async () => {
    await secureDelete(STORAGE_KEYS.BIOMETRIC_ENABLED);
    setState((prev) => ({ ...prev, biometricEnabled: false }));
  }, []);

  // ── 手动刷新 Token ────────────────────────────────────
  const refreshTokenFn = useCallback(async (): Promise<boolean> => {
    if (!state.tokens) return false;

    try {
      const newTokens = await apiRefreshToken(state.tokens.refreshToken);
      await secureSet(STORAGE_KEYS.ACCESS_TOKEN, JSON.stringify(newTokens));
      setState((prev) => ({ ...prev, tokens: newTokens }));
      return true;
    } catch (error) {
      console.error('[鉴权] Token 刷新失败:', error);
      await logout();
      return false;
    }
  }, [state.tokens, logout]);

  return {
    ...state,
    login,
    loginWithBiometric,
    logout,
    enableBiometric,
    disableBiometric,
    refreshToken: refreshTokenFn,
  };
}
