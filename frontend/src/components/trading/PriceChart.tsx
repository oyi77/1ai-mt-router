import { useEffect, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CandleData } from '@/api/trading'

interface PriceChartProps {
  data: CandleData[]
  symbol: string
}

export function PriceChart({ data, symbol }: PriceChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (!canvasRef.current || data.length === 0) return

    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    const prices = data.flatMap(d => [d.high, d.low])
    const minPrice = Math.min(...prices)
    const maxPrice = Math.max(...prices)
    const priceRange = maxPrice - minPrice
    const range = priceRange > 0 ? priceRange : 1
    const padding = range * 0.1

    const candleWidth = Math.max(1, (canvas.width - 60) / data.length)
    const chartHeight = canvas.height - 40

    data.forEach((candle, i) => {
      const x = 30 + i * candleWidth
      const openY = chartHeight - ((candle.open - minPrice + padding) / (range + padding * 2)) * chartHeight
      const closeY = chartHeight - ((candle.close - minPrice + padding) / (range + padding * 2)) * chartHeight
      const highY = chartHeight - ((candle.high - minPrice + padding) / (range + padding * 2)) * chartHeight
      const lowY = chartHeight - ((candle.low - minPrice + padding) / (range + padding * 2)) * chartHeight

      const isGreen = candle.close >= candle.open
      ctx.strokeStyle = isGreen ? '#22c55e' : '#ef4444'
      ctx.fillStyle = isGreen ? '#22c55e' : '#ef4444'

      ctx.beginPath()
      ctx.moveTo(x + candleWidth / 2, highY)
      ctx.lineTo(x + candleWidth / 2, lowY)
      ctx.stroke()

      const bodyHeight = Math.abs(closeY - openY) || 1
      ctx.fillRect(x + 2, Math.min(openY, closeY), Math.max(1, candleWidth - 4), bodyHeight)
    })

    ctx.fillStyle = '#888'
    ctx.font = '10px monospace'
    const step = range / 5
    const labelDigits = maxPrice >= 100 ? 2 : maxPrice >= 1 ? 4 : 5
    for (let i = 0; i <= 5; i++) {
      const price = minPrice + step * i
      const y = chartHeight - (i / 5) * chartHeight
      ctx.fillText(price.toFixed(labelDigits), 2, y + 3)
    }
  }, [data])

  return (
    <Card>
      <CardHeader>
        <CardTitle>{symbol} Price Chart</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">No candle data for {symbol}</p>
        ) : (
          <canvas ref={canvasRef} width={800} height={400} className="w-full" />
        )}
      </CardContent>
    </Card>
  )
}
