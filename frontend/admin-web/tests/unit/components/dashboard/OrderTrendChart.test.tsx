import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Capture YAxis props for assertion
let lastYAxisProps: Record<string, any> = {}

// Mock recharts to avoid jsdom dimension issues
vi.mock('recharts', () => ({
  LineChart: ({ children, margin }: any) => (
    <div data-testid="line-chart" data-margin-left={margin?.left}>{children}</div>
  ),
  Line: () => <div data-testid="line" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: (props: any) => {
    lastYAxisProps = props
    return <div data-testid="y-axis" data-domain={JSON.stringify(props.domain)} />
  },
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ResponsiveContainer: ({ children }: any) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  Legend: () => <div data-testid="legend" />,
}))

import OrderTrendChart from '@/components/dashboard/OrderTrendChart'
import type { OrderTrendPoint } from '@/types'

const mockData: OrderTrendPoint[] = [
  { date: '06-15', orders: 12 },
  { date: '06-16', orders: 8 },
  { date: '06-17', orders: 15 },
]

describe('OrderTrendChart', () => {
  it('renders the chart title "订单趋势"', () => {
    render(<OrderTrendChart data={[]} />)
    expect(screen.getByText('订单趋势')).toBeInTheDocument()
  })

  it('shows loading spinner when loading=true', () => {
    render(<OrderTrendChart data={[]} loading={true} />)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('hides loading spinner when loading=false', () => {
    render(<OrderTrendChart data={mockData} loading={false} />)
    expect(document.querySelector('.animate-spin')).not.toBeInTheDocument()
  })

  it('renders chart container when not loading', () => {
    render(<OrderTrendChart data={mockData} />)
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument()
    expect(screen.getByTestId('line-chart')).toBeInTheDocument()
  })

  it('renders range toggle buttons 近7天 and 近30天', () => {
    render(<OrderTrendChart data={mockData} />)
    expect(screen.getByText('近7天')).toBeInTheDocument()
    expect(screen.getByText('近30天')).toBeInTheDocument()
  })

  it('defaults to 近7天 range active', () => {
    render(<OrderTrendChart data={mockData} />)
    const btn7 = screen.getByText('近7天')
    // Active button should have shadow-sm class
    expect(btn7.className).toContain('shadow-sm')
  })

  it('calls onRangeChange with 30 when clicking 近30天', async () => {
    const onRangeChange = vi.fn()
    const user = userEvent.setup()
    render(<OrderTrendChart data={mockData} onRangeChange={onRangeChange} />)

    await user.click(screen.getByText('近30天'))
    expect(onRangeChange).toHaveBeenCalledWith(30)
  })

  it('calls onRangeChange with 7 when clicking 近7天 after switching', async () => {
    const onRangeChange = vi.fn()
    const user = userEvent.setup()
    render(<OrderTrendChart data={mockData} onRangeChange={onRangeChange} />)

    // First switch to 30
    await user.click(screen.getByText('近30天'))
    // Then switch back to 7
    await user.click(screen.getByText('近7天'))
    expect(onRangeChange).toHaveBeenCalledTimes(2)
    expect(onRangeChange).toHaveBeenNthCalledWith(1, 30)
    expect(onRangeChange).toHaveBeenNthCalledWith(2, 7)
  })

  it('shows empty state when data array is empty', () => {
    render(<OrderTrendChart data={[]} />)
    expect(screen.getByText(/暂无数据/i)).toBeInTheDocument()
  })

  it('renders all recharts sub-components', () => {
    render(<OrderTrendChart data={mockData} />)
    expect(screen.getByTestId('line-chart')).toBeInTheDocument()
    expect(screen.getByTestId('cartesian-grid')).toBeInTheDocument()
    expect(screen.getByTestId('x-axis')).toBeInTheDocument()
    expect(screen.getByTestId('y-axis')).toBeInTheDocument()
    expect(screen.getByTestId('tooltip')).toBeInTheDocument()
    expect(screen.getByTestId('legend')).toBeInTheDocument()
    // Two Line components (orders + sessions)
    expect(screen.getAllByTestId('line').length).toBe(2)
  })

  // ── Bug #942 fix: YAxis domain / margin / empty state ──

  it('YAxis should have domain=[0, auto] to prevent data flattening', () => {
    render(<OrderTrendChart data={mockData} />)
    const yAxis = screen.getByTestId('y-axis')
    const domain = JSON.parse(yAxis.getAttribute('data-domain') || 'null')
    expect(domain).not.toBeNull()
    // domain[0] should be 0, domain[1] should be 'auto' for proper scaling
    expect(domain[0]).toBe(0)
    expect(domain[1]).toBe('auto')
  })

  it('should not have negative margin.left that clips Y-axis labels', () => {
    render(<OrderTrendChart data={mockData} />)
    const chart = screen.getByTestId('line-chart')
    const marginLeft = parseInt(chart.getAttribute('data-margin-left') || '0', 10)
    expect(marginLeft).toBeGreaterThanOrEqual(0)
  })

  it('should show empty state when all data values are zero', () => {
    const allZeroData = [
      { date: '06-15', orders: 0 },
      { date: '06-16', orders: 0 },
      { date: '06-17', orders: 0 },
    ]
    render(<OrderTrendChart data={allZeroData} />)
    // Should render empty hint text
    expect(screen.getByText(/暂无数据/i)).toBeInTheDocument()
  })

  it('should not show empty state when data has non-zero values', () => {
    render(<OrderTrendChart data={mockData} />)
    expect(screen.queryByText(/暂无数据/i)).not.toBeInTheDocument()
  })
})
