'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { sampleTickIndices } from '@/lib/axis-sampling'

/**
 * 经营看板通用趋势图（织物质感）。
 *
 * 修复「横坐标没有铺满」的根因：旧实现用固定 viewBox（数据点 × 40 宽）配
 * preserveAspectRatio="meet"，容器更宽时图表被等比缩小、左右留白。
 * 本组件用 ResizeObserver 量取容器像素宽度，以「像素坐标系」渲染 SVG，
 * viewBox 宽 = 实际渲染宽，宽高比严格一致 → 曲线/面积/刻度天然铺满整卡宽度。
 */

export interface TrendSeriesDef {
  /** 数据点对象上的取值字段名 */
  key: string
  /** 图例名（tooltip / 图例） */
  name: string
  /** 主色 */
  color: string
  /** 是否渲染渐变面积（默认 false 仅折线） */
  area?: boolean
  /** 是否渲染数据点圆点（默认 true） */
  dots?: boolean
}

interface TrendChartProps {
  data: Array<Record<string, any>>
  series: TrendSeriesDef[]
  /** 轴标签格式化（如金额 1.2万） */
  formatValue?: (v: number) => string
  /** 图表高度（px），默认 240 */
  height?: number
  className?: string
}

/** 测试环境（jsdom）量不到宽度时使用的回退宽度，保证 SVG 几何可用 */
const FALLBACK_WIDTH = 560

/** 把数值向上取到「1/2/5 × 10^n」的整齐刻度 */
function niceCeil(value: number): number {
  if (value <= 0) return 10
  const pow = Math.pow(10, Math.floor(Math.log10(value)))
  const norm = value / pow
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  return nice * pow
}

export default function TrendChart({
  data,
  series,
  formatValue,
  height = 240,
  className,
}: TrendChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const gradientIdBase = useId().replace(/:/g, '')

  // 量取容器像素宽度（ResizeObserver + resize 兜底）
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setWidth(el.getBoundingClientRect().width || 0)
    measure()
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(measure)
      ro.observe(el)
      return () => ro.disconnect()
    }
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  const W = width > 0 ? width : FALLBACK_WIDTH
  const H = height

  // 布局（像素坐标）
  const pad = { top: 16, right: 16, bottom: 34, left: 46 }
  const x0 = pad.left
  const x1 = W - pad.right
  const y0 = pad.top
  const y1 = H - pad.bottom
  const plotW = x1 - x0
  const plotH = y1 - y0

  const n = data.length

  const toX = useCallback(
    (i: number) => (n <= 1 ? (x0 + x1) / 2 : x0 + (i / (n - 1)) * plotW),
    [n, x0, x1, plotW]
  )

  // Y 轴值域：所有序列最大值上浮 15%，再取整齐刻度
  const rawMax = series.reduce((acc, s) => {
    for (const d of data) {
      const v = Number(d[s.key] ?? 0)
      if (Number.isFinite(v) && v > acc) acc = v
    }
    return acc
  }, 0)
  const chartMax = niceCeil(rawMax === 0 ? 1 : rawMax * 1.15)
  const toY = (v: number) => y1 - (v / chartMax) * plotH

  // Y 轴刻度：4 条水平网格线
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((r) => chartMax * r)

  // X 轴刻度降采样（≤7 个、间距 ≥64px 不重叠）
  const xTickIndices = sampleTickIndices(n, { width: plotW, maxTicks: 7, minGap: 64 })

  // 序列几何
  const seriesGeom = series.map((s) => {
    const points = data.map((d, i) => `${toX(i)},${toY(Number(d[s.key] ?? 0))}`).join(' ')
    const areaPath =
      points.length > 0
        ? `M ${toX(0)} ${y1} L ${points.replace(/ /g, ' L ')} L ${toX(n - 1)} ${y1} Z`
        : ''
    const gradientId = `${gradientIdBase}-${s.key}`
    return { ...s, points, areaPath, gradientId }
  })

  const hovered = hoverIndex !== null ? data[hoverIndex] : null

  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (n === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - rect.left
    // 将鼠标 x 折算回像素坐标（width 测量值可能与 getBoundingClientRect 有 1px 误差）
    const scale = W / (rect.width || 1)
    const px = mx * scale
    let best = 0
    let bestDist = Infinity
    for (let i = 0; i < n; i++) {
      const d = Math.abs(toX(i) - px)
      if (d < bestDist) {
        bestDist = d
        best = i
      }
    }
    setHoverIndex(best)
  }

  const tooltipLeft = hoverIndex !== null
    ? Math.min(Math.max(toX(hoverIndex) + 14, 10), W - 230)
    : 0

  return (
    <div
      ref={containerRef}
      className={cn('relative select-none', className)}
      style={{ height: H }}
    >
      <svg
        width="100%"
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="block"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
        role="img"
      >
        <defs>
          {seriesGeom.map((s) =>
            s.area ? (
              <linearGradient key={s.gradientId} id={s.gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color} stopOpacity="0.28" />
                <stop offset="100%" stopColor={s.color} stopOpacity="0.02" />
              </linearGradient>
            ) : null
          )}
        </defs>

        {/* 水平网格线 + Y 轴刻度 */}
        {yTicks.map((v, i) => {
          const y = toY(v)
          return (
            <g key={i}>
              <line x1={x0} y1={y} x2={x1} y2={y} stroke="#E6DFD3" strokeWidth="1" strokeDasharray={i === 0 ? undefined : '3 3'} />
              <text x={x0 - 8} y={y + 3.5} textAnchor="end" fontSize="10" fill="#B8AA94">
                {formatValue ? formatValue(v) : Math.round(v)}
              </text>
            </g>
          )
        })}

        {/* 面积（优先于折线，垫底） */}
        {seriesGeom.map((s) =>
          s.area && s.areaPath ? (
            <path key={`area-${s.key}`} d={s.areaPath} fill={`url(#${s.gradientId})`} />
          ) : null
        )}

        {/* 折线 */}
        {seriesGeom.map((s) =>
          s.points ? (
            <polyline
              key={`line-${s.key}`}
              fill="none"
              stroke={s.color}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={s.points}
            />
          ) : null
        )}

        {/* 数据点 */}
        {seriesGeom.map((s) =>
          (s.dots === undefined || s.dots) && n <= 40
            ? data.map((d, i) => (
                <circle
                  key={`dot-${s.key}-${i}`}
                  cx={toX(i)}
                  cy={toY(Number(d[s.key] ?? 0))}
                  r={hoverIndex === i ? 4 : 2.8}
                  fill={s.color}
                  stroke="#fff"
                  strokeWidth="1.5"
                  className="transition-all"
                />
              ))
            : null
        )}

        {/* X 轴刻度（y=225，位于数据基线下方，给日期标签留足空间） */}
        {xTickIndices.map((idx) => {
          const d = data[idx]
          const x = toX(idx)
          return (
            <text key={idx} x={x} y={225} textAnchor="middle" fontSize="10" fill="#9C8C72">
              {typeof d?.date === 'string' ? d.date.slice(5) : ''}
            </text>
          )
        })}

        {/* hover 十字线 */}
        {hoverIndex !== null && (
          <line
            x1={toX(hoverIndex)}
            y1={y0}
            x2={toX(hoverIndex)}
            y2={y1}
            stroke="#C6BDA9"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
        )}
      </svg>

      {/* hover Tooltip（HTML 覆盖层，格式自由） */}
      {hovered && (
        <div
          className="pointer-events-none absolute z-10 min-w-[180px] rounded-lg border border-neutral-200 bg-white/95 px-3 py-2 shadow-card backdrop-blur-sm animate-fade-in-up"
          style={{ left: tooltipLeft, top: 6 }}
        >
          <p className="mb-1 text-[11px] font-medium text-neutral-500">
            {typeof hovered.date === 'string' ? hovered.date : ''}
          </p>
          <div className="space-y-0.5">
            {series.map((s) => {
              const v = Number(hovered[s.key] ?? 0)
              return (
                <p key={s.key} className="flex items-center justify-between gap-3 text-xs">
                  <span className="flex items-center gap-1.5 text-neutral-500">
                    <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                    {s.name}
                  </span>
                  <span className="tnum font-semibold text-neutral-800">
                    {formatValue ? formatValue(v) : v}
                  </span>
                </p>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
