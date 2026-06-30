import { useEffect, useRef, useCallback } from 'react'
import { useAppStore } from '@/store'

/** WebSocket 自动重连 Hook */
export function useWebSocket(channel: string = 'market') {
  const wsRef = useRef<WebSocket | null>(null)
  const setWsConnected = useAppStore((s) => s.setWsConnected)
  const setTicker = useAppStore((s) => s.setTicker)

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/${channel}`)

    ws.onopen = () => {
      setWsConnected(true)
      console.log(`WebSocket 已连接: ${channel}`)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.symbol && data.last_price) {
          setTicker(data)
        }
      } catch {}
    }

    ws.onclose = () => {
      setWsConnected(false)
      console.log('WebSocket 断开，3 秒后重连...')
      setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsRef.current = ws
  }, [channel, setWsConnected, setTicker])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [connect])
}
