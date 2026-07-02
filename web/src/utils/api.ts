/**
 * API 客户端:JWT 鉴权 + 写请求幂等键 + 401 统一跳登录。
 * 端点与后端 server/src/one_quant/api/routes 一一对齐。
 */
import axios from 'axios'
import type { ApiResponse } from '@/types'

const TOKEN_KEY = 'one_quant_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
})

/** 请求拦截:附加 Bearer Token;写请求自动生成幂等键(防网络重试重复下单) */
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const method = (config.method || 'get').toLowerCase()
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    config.headers['Idempotency-Key'] = crypto.randomUUID()
  }
  return config
})

/** 响应拦截:401 清票据并跳登录(登录接口本身除外) */
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    const url: string = err.config?.url || ''
    if (status === 401 && !url.includes('/auth/login')) {
      clearToken()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    console.error('API 错误:', err.response?.data || err.message)
    return Promise.reject(err)
  }
)

// ============ 认证 ============

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  username: string
  role: string
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await api.post<ApiResponse<LoginResult>>('/auth/login', { username, password })
  return res.data.data
}

// ============ 持仓 ============

export async function fetchPositions() {
  const res = await api.get<ApiResponse>('/positions/')
  return res.data
}

export async function fetchPnlSummary() {
  const res = await api.get<ApiResponse>('/positions/summary/pnl')
  return res.data
}

// ============ 策略 ============

export async function fetchStrategies() {
  const res = await api.get<ApiResponse>('/strategies/')
  return res.data
}

export async function toggleStrategy(name: string) {
  const res = await api.post<ApiResponse>(`/strategies/${name}/toggle`)
  return res.data
}

export async function fetchStrategyStats(name: string) {
  const res = await api.get<ApiResponse>(`/strategies/${name}/stats`)
  return res.data
}

// ============ 订单 ============

export async function submitOrder(order: Record<string, unknown>) {
  const res = await api.post<ApiResponse>('/orders/', order)
  return res.data
}

export async function cancelOrder(orderId: string) {
  const res = await api.delete<ApiResponse>(`/orders/${orderId}`)
  return res.data
}

// ============ 系统 ============

export async function fetchHealth() {
  const res = await api.get('/health')
  return res.data
}

export async function fetchHealthDetail() {
  const res = await api.get('/health/detail')
  return res.data
}

export default api
