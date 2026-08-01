import { useRef, useEffect, useCallback } from 'react'

export interface ChartDataPoint {
  time: string
  value: number
}

interface MiniChartProps {
  data: ChartDataPoint[]
  label: string
  color?: string
  height?: number
  showGrid?: boolean
  unit?: string
}

const COLORS = {
  green: { line: '#22c55e', fill: 'rgba(34, 197, 94, 0.1)' },
  blue: { line: '#3b82f6', fill: 'rgba(59, 130, 246, 0.1)' },
  orange: { line: '#f97316', fill: 'rgba(249, 115, 22, 0.1)' },
  purple: { line: '#a855f7', fill: 'rgba(168, 85, 247, 0.1)' },
  red: { line: '#ef4444', fill: 'rgba(239, 68, 68, 0.1)' },
}

function formatTimeLabel(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MiniChart({
  data,
  label,
  color = 'green',
  height = 160,
  showGrid = true,
  unit = '',
}: MiniChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const colorScheme = COLORS[color as keyof typeof COLORS] || COLORS.green

  // Filter out non-finite values up front so NaN/Infinity can never reach the
  // canvas math below (Math.min/max would propagate them into scale bounds).
  const points = data.filter(d => Number.isFinite(d.value))

  const drawChart = useCallback(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const dpr = window.devicePixelRatio || 1
    const rect = container.getBoundingClientRect()
    const width = rect.width

    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)

    const padding = { top: 8, right: 12, bottom: 24, left: 44 }
    const chartW = width - padding.left - padding.right
    const chartH = height - padding.top - padding.bottom

    if (points.length === 0) {
      ctx.fillStyle = '#6b7280'
      ctx.font = '13px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('No data yet', width / 2, height / 2)
      return
    }

    const n = points.length
    const values = points.map(d => d.value)
    let minVal = Math.min(...values)
    let maxVal = Math.max(...values)

    if (minVal === maxVal) {
      minVal = Math.max(0, minVal - 1)
      maxVal = maxVal + 1
    }

    const valRange = maxVal - minVal
    minVal = Math.max(0, minVal - valRange * 0.05)
    maxVal = maxVal + valRange * 0.05

    const toX = (i: number) => padding.left + (n === 1 ? chartW / 2 : (i / (n - 1)) * chartW)
    const toY = (v: number) => padding.top + chartH - ((v - minVal) / (maxVal - minVal)) * chartH

    // Grid lines
    if (showGrid) {
      ctx.strokeStyle = 'rgba(107, 114, 128, 0.15)'
      ctx.lineWidth = 1
      const gridLines = 4
      for (let i = 0; i <= gridLines; i++) {
        const y = padding.top + (i / gridLines) * chartH
        ctx.beginPath()
        ctx.moveTo(padding.left, y)
        ctx.lineTo(padding.left + chartW, y)
        ctx.stroke()

        const val = maxVal - (i / gridLines) * (maxVal - minVal)
        ctx.fillStyle = '#6b7280'
        ctx.font = '10px system-ui, sans-serif'
        ctx.textAlign = 'right'
        ctx.fillText(val.toFixed(val >= 100 ? 0 : 1), padding.left - 6, y + 3)
      }
    }

    // X-axis time labels
    ctx.fillStyle = '#6b7280'
    ctx.font = '10px system-ui, sans-serif'
    ctx.textAlign = 'center'
    const labelCount = Math.min(5, n)
    for (let i = 0; i < labelCount; i++) {
      const idx = labelCount === 1 ? 0 : Math.floor((i / (labelCount - 1)) * (n - 1))
      const x = toX(idx)
      ctx.fillText(formatTimeLabel(points[idx].time), x, height - 4)
    }

    // Filled area
    ctx.beginPath()
    ctx.moveTo(toX(0), toY(points[0].value))
    for (let i = 1; i < n; i++) {
      ctx.lineTo(toX(i), toY(points[i].value))
    }
    ctx.lineTo(toX(n - 1), padding.top + chartH)
    ctx.lineTo(toX(0), padding.top + chartH)
    ctx.closePath()
    ctx.fillStyle = colorScheme.fill
    ctx.fill()

    // Line
    ctx.beginPath()
    ctx.moveTo(toX(0), toY(points[0].value))
    for (let i = 1; i < n; i++) {
      ctx.lineTo(toX(i), toY(points[i].value))
    }
    ctx.strokeStyle = colorScheme.line
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    ctx.stroke()

    // Current value dot
    const lastIdx = n - 1
    const lx = toX(lastIdx)
    const ly = toY(points[lastIdx].value)

    ctx.beginPath()
    ctx.arc(lx, ly, 4, 0, Math.PI * 2)
    ctx.fillStyle = colorScheme.line
    ctx.fill()
    ctx.beginPath()
    ctx.arc(lx, ly, 2, 0, Math.PI * 2)
    ctx.fillStyle = '#ffffff'
    ctx.fill()
  }, [points, height, showGrid, colorScheme])

  useEffect(() => {
    drawChart()

    const handleResize = () => drawChart()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [drawChart])

  const currentValue = points.length > 0 ? points[points.length - 1].value : null

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between px-1">
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
        {currentValue !== null && (
          <span className="text-sm font-mono font-semibold" style={{ color: colorScheme.line }}>
            {currentValue.toFixed(currentValue >= 100 ? 0 : 1)}{unit}
          </span>
        )}
      </div>
      <div ref={containerRef} className="w-full">
        <canvas ref={canvasRef} className="w-full rounded-md" />
      </div>
    </div>
  )
}
