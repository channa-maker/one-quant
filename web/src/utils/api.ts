import axios from 'axios'
import type { ApiResponse } from '@/types'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error('API 错误:', err.response?.data || err.message)
    return Promise.reject(err)
  }
)

export async function fetchPositions() {
  const res = await api.get<ApiResponse>('/positions')
  return res.data
}

export async function fetchStrategies() {
  const res = await api.get<ApiResponse>('/strategies')
  return res.data
}

export async function submitOrder(order: any) {
  const res = await api.post<ApiResponse>('/orders', order)
  return res.data
}

export async function cancelOrder(orderId: string) {
  const res = await api.delete<ApiResponse>(`/orders/${orderId}`)
  return res.data
}

export async function fetchHealth() {
  const res = await api.get('/health')
  return res.data
}

export default api
