/**
 * K 线图 — TradingView Lightweight Charts 实现。
 * 无实时数据源时先渲染演示 K 线;接入行情后经 onTick 更新最后一根。
 */
import { useEffect, useRef } from 'react'
import {
  createChart, CandlestickSeries, HistogramSeries,
  type IChartApi, type ISeriesApi, type CandlestickData, type Time,
} from 'lightweight-charts'

export interface KLineChartProps {
  symbol: string
  /** 最新价(来自 WS ticker),更新最后一根 K 线 */
  lastPrice?: number
  height?: number
}

/** 生成演示 K 线(随机游走,基于 symbol 稳定种子) */
function genDemoKlines(symbol: string, n = 120): CandlestickData[] {
  let seed = Array.from(symbol).reduce((s, c) => s + c.charCodeAt(0), 0)
  const rand = () => {
    seed = (seed * 9301 + 49297) % 233280
    return seed / 233280
  }
  const base = symbol.startsWith('BTC') ? 41000 : symbol.startsWith('ETH') ? 2400 : 100
  const out: CandlestickData[] = []
  let close = base
  const now = Math.floor(Date.now() / 1000)
  for (let i = n; i > 0; i--) {
    const open = close
    const drift = (rand() - 0.5) * base * 0.012
    close = Math.max(base * 0.6, open + drift)
    const high = Math.max(open, close) * (1 + rand() * 0.004)
    const low = Math.min(open, close) * (1 - rand() * 0.004)
    out.push({ time: (now - i * 900) as Time, open, high, low, close })
  }
  return out
}

export default function KLineChart({ symbol, lastPrice, height = 360 }: KLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const lastBarRef = useRef<CandlestickData | null>(null)

  // 初始化图表
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const chart = createChart(el, {
      height,
      layout: { background: { color: '#0d1117' }, textColor: '#8c8c8c' },
      grid: {
        vertLines: { color: '#1c2128' },
        horzLines: { color: '#1c2128' },
      },
      timeScale: { timeVisible: true, borderColor: '#303030' },
      rightPriceScale: { borderColor: '#303030' },
      crosshair: { mode: 0 },
      localization: { locale: 'zh-CN' },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#f5222d', downColor: '#52c41a',       // 红涨绿跌(国内习惯)
      wickUpColor: '#f5222d', wickDownColor: '#52c41a',
      borderVisible: false,
    })
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    const data = genDemoKlines(symbol)
    candles.setData(data)
    volume.setData(
      data.map((d) => ({
        time: d.time,
        value: Math.abs(d.close - d.open) * 8000,
        color: d.close >= d.open ? 'rgba(245,34,45,0.35)' : 'rgba(82,196,26,0.35)',
      }))
    )
    chart.timeScale().fitContent()

    chartRef.current = chart
    seriesRef.current = candles
    lastBarRef.current = data[data.length - 1] ?? null

    const onResize = () => chart.applyOptions({ width: el.clientWidth })
    const ro = new ResizeObserver(onResize)
    ro.observe(el)
    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [symbol, height])

  // 实时价更新最后一根
  useEffect(() => {
    const series = seriesRef.current
    const last = lastBarRef.current
    if (!series || !last || !lastPrice || Number.isNaN(lastPrice)) return
    const updated: CandlestickData = {
      ...last,
      close: lastPrice,
      high: Math.max(last.high, lastPrice),
      low: Math.min(last.low, lastPrice),
    }
    lastBarRef.current = updated
    series.update(updated)
  }, [lastPrice])

  return <div ref={containerRef} style={{ width: '100%' }} />
}
