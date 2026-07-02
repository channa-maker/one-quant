/**
 * 数据获取 Hook:优先请求后端真实数据,失败时回退到本地演示数据。
 * source 字段告知页面当前数据来源,UI 据此展示"演示数据"标识。
 */
import { useEffect, useState } from 'react'

export interface ApiDataState<T> {
  data: T
  loading: boolean
  /** live=后端实时 · demo=本地演示(后端不可达) */
  source: 'live' | 'demo'
  refresh: () => void
}

export function useApiData<T>(
  fetcher: () => Promise<{ data?: T } | T>,
  fallback: T,
  deps: unknown[] = []
): ApiDataState<T> {
  const [data, setData] = useState<T>(fallback)
  const [loading, setLoading] = useState(true)
  const [source, setSource] = useState<'live' | 'demo'>('demo')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetcher()
      .then((res) => {
        if (cancelled) return
        const payload = (res as { data?: T })?.data ?? (res as T)
        if (payload !== undefined && payload !== null) {
          setData(payload)
          setSource('live')
        }
      })
      .catch(() => {
        if (!cancelled) setSource('demo')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps])

  return { data, loading, source, refresh: () => setTick((t) => t + 1) }
}
