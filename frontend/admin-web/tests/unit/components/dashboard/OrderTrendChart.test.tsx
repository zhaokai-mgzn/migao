import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock recharts to avoid jsdom dimension issues
// Capture props on XAxis/YAxis/LineChart for assertions
vi.mock('recharts', () => ({
  LineChart: ({ children, margin }: any) => (
    <div data-testid="line-chart" data-margin={JSON.stringify(margin)}>{children}</div>
  ),
  Line: () => <div data-testid="line" />,
  XAxis: (props: any) => (
    <div data-testid="x-axis" data-tickformatter={props.tickFormatter ? 'present' : 'absent'} />
  ),
  YAxis: (props: any) => (
    <div
      data-testid="y-axis"
      data-domain={JSON.stringify(props.domain)}
      data-allowdecimals={String(props.allowDecimals ?? true)}
    />
  ),
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

  // #942: A5 — empty data should show 暂无数据, not empty chart
  it('shows 暂无数据 when data is empty and not loading', () => {
    render(<OrderTrendChart data={[]} loading={false} />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
    expect(screen.queryByTestId('responsive-container')).not.toBeInTheDocument()
  })

  // #942: A5 — loading spinner still shown even with empty data
  it('shows loading spinner even with empty data when loading=true', () => {
    render(<OrderTrendChart data={[]} loading={true} />)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
    expect(screen.queryByText('暂无数据')).not.toBeInTheDocument()
  })

  // #942: A4 — YAxis should have domain prop to prevent zero-data chart collapse
  it('YAxis has domain prop to prevent zero-data compression', () => {
    render(<OrderTrendChart data={mockData} />)
    const yAxis = screen.getByTestId('y-axis')
    const domain = JSON.parse(yAxis.getAttribute('data-domain') || 'null')
    expect(domain).toBeDefined()
    expect(Array.isArray(domain)).toBe(true)
  })

  // #942: A4 — YAxis should have allowDecimals=false for order counts
  it('YAxis has allowDecimals=false for integer order counts', () => {
    render(<OrderTrendChart data={mockData} />)
    const yAxis = screen.getByTestId('y-axis')
    expect(yAxis.getAttribute('data-allowdecimals')).toBe('false')
  })

  // #942: L4-006 — margin.left should not be negative
  it('chart margin.left is not negative', () => {
    render(<OrderTrendChart data={mockData} />)
    const chart = screen.getByTestId('line-chart')
    const margin = JSON.parse(chart.getAttribute('data-margin') || '{}')
    expect(margin.left).toBeGreaterThanOrEqual(0)
  })

  // #942: L4-007 — XAxis should have tickFormatter for MM-DD display
  it('XAxis has tickFormatter for date MM-DD format', () => {
    render(<OrderTrendChart data={mockData} />)
    const xAxis = screen.getByTestId('x-axis')
    expect(xAxis.getAttribute('data-tickformatter')).toBe('present')
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
})
