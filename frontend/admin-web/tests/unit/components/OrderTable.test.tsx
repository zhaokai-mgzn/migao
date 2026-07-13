/**
 * OrderTable 组件测试
 * 覆盖：基本渲染、采购商品列、采购明细列、空状态、加载状态
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import OrderTable from '@/components/orders/OrderTable'
import type { Order } from '@/types'

const mockOrder = {
  id: 'order-001',
  orderNo: 'ORD-001',
  status: 'pending_shipment' as const,
  totalAmount: 299,
  actualAmount: 299,
  customerName: '测试客户',
  customerPhone: '13800000000',
  hasProcessing: false,
  createdAt: '2026-06-15T10:00:00Z',
  updatedAt: '2026-06-15T10:00:00Z',
  items: [
    {
      id: 'item-1',
      productId: 'prod-1',
      productName: '窗帘',
      productCode: 'CL-001',
      unitPrice: 99,
      quantity: 3,
      subtotal: 297,
      amount: 297,
    },
  ],
}

describe('OrderTable', () => {
  const defaultProps = {
    orders: [mockOrder],
    loading: false,
    selectedIds: [] as string[],
    onSelectChange: vi.fn(),
    onView: vi.fn(),
    onRemark: vi.fn(),
    onClose: vi.fn(),
    onShip: vi.fn(),
  }

  it('应渲染订单列表表头', () => {
    render(<OrderTable {...defaultProps} />)
    expect(screen.getByText('订单ID')).toBeTruthy()
    expect(screen.getByText('采购商品')).toBeTruthy()
    expect(screen.getByText('采购明细')).toBeTruthy()
    expect(screen.getByText('状态')).toBeTruthy()
  })

  it('应显示订单ID', () => {
    render(<OrderTable {...defaultProps} />)
    expect(screen.getByText('ORD-001')).toBeTruthy()
  })

  it('应显示采购商品名称和货号', () => {
    render(<OrderTable {...defaultProps} />)
    const names = screen.getAllByText('窗帘')
    expect(names.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/货号/)).toBeTruthy()
  })

  it('应显示采购明细（名称/单价×数量=金额）', () => {
    render(<OrderTable {...defaultProps} />)
    // 采购明细包含商品名称、单价、数量 — 使用 getAllByText 因为名称出现在两列
    const names = screen.getAllByText(/窗帘/)
    expect(names.length).toBeGreaterThanOrEqual(1)
  })

  it('采购明细分隔符应为 : 而非 /', () => {
    render(<OrderTable {...defaultProps} />)
    // 采购明细列在 min-w-[280px] 的 td 中，取该列文本验证分隔符
    const detailCells = document.querySelectorAll('td.min-w-\\[280px\\]')
    expect(detailCells.length).toBeGreaterThan(0)
    const cellText = detailCells[0].textContent || ''
    // 产品名后应紧跟 ' : 数字' 模式（如 窗帘 : 99元）
    expect(cellText).toMatch(/窗帘\s*:\s*\d/)
    // 不应出现 ' / 数字' 模式（在采购明细列上下文中）
    expect(cellText).not.toMatch(/窗帘\s*\/\s*\d/)
  })

  it('空列表显示"暂无数据"', () => {
    render(<OrderTable {...defaultProps} orders={[]} />)
    expect(screen.getByText('暂无数据')).toBeTruthy()
  })

  it('加载中显示"加载中..."', () => {
    render(<OrderTable {...defaultProps} orders={[]} loading={true} />)
    expect(screen.getByText('加载中…')).toBeTruthy()
  })

  it('应渲染复选框列', () => {
    render(<OrderTable {...defaultProps} />)
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes.length).toBeGreaterThan(0)
  })

  // #1290: 订单ID 行顶格 — 左侧无 padding
  it('订单ID 列 data cell 应为 pl-0（顶格）', () => {
    render(<OrderTable {...defaultProps} />)
    const orderIdCell = screen.getByText('ORD-001').closest('td')
    expect(orderIdCell).toBeTruthy()
    expect(orderIdCell!.className).toMatch(/\bpl-0\b/)
    expect(orderIdCell!.className).not.toMatch(/\bpx-4\b/)
  })

  // #1290: 商品货号行顶格 — 左侧无 padding
  it('采购商品列 data cell 应为 pl-0（顶格）', () => {
    render(<OrderTable {...defaultProps} />)
    const skuCell = screen.getByText(/货号/).closest('td')
    expect(skuCell).toBeTruthy()
    expect(skuCell!.className).toMatch(/\bpl-0\b/)
    expect(skuCell!.className).not.toMatch(/\bpx-4\b/)
  })

  // #1290: 订单ID 列 header 也应顶格，保证 header/data 对齐
  it('订单ID 列 header 应为 pl-0（顶格）', () => {
    render(<OrderTable {...defaultProps} />)
    const headerCell = screen.getByText('订单ID').closest('th')
    expect(headerCell).toBeTruthy()
    expect(headerCell!.className).toMatch(/\bpl-0\b/)
    expect(headerCell!.className).not.toMatch(/\bpx-4\b/)
  })
})
