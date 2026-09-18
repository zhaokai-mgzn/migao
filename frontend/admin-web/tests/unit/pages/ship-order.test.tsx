// case_ids: UI-040, UI-046

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 发货页（/orders/[id]/ship）— 渲染 + 发货人 + 发货单打印（issue #3768 / UI-040）
 *
 * ⚠️ 注意：页面内始终挂着一份**屏幕隐藏的纸质发货单**（`.shipment-print-area`，仅 @media print 显形）。
 * jsdom 不解析媒体查询 ⇒ 单据内容也在 DOM 里，收货人/商品名会在断言中命中多处。
 * 涉及与单据重复的文本请用 `getAllByText`（并保留下方注释），不要改回 `getByText` 触发
 * "Found multiple elements" 而误以为是回归。
 */

// Mock API
const mockGetOrder = vi.fn()
const mockUpdateLogistics = vi.fn()
const mockUpdateOrderStatus = vi.fn()
const mockGetCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    updateLogistics: (...args: any[]) => mockUpdateLogistics(...args),
    updateOrderStatus: (...args: any[]) => mockUpdateOrderStatus(...args),
  },
  // 客户常用物流档案带出（issue #4419 / UI-046）
  customerApi: {
    getCustomers: (...args: any[]) => mockGetCustomers(...args),
  },
}))

// Mock useRouteId
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'test-order-456',
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner
const mockToastError = vi.fn()
const mockToastSuccess = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: any[]) => mockToastSuccess(...args),
    error: (...args: any[]) => mockToastError(...args),
  },
}))

// 当前登录人（发货人默认值来源）：姓名经 name → nickname → username 兜底链解析
let mockUser: any = { id: 'u-1', name: '王五', nickname: 'wangwu', username: '13700137000' }
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => selector({ user: mockUser }),
}))

const mockOrder = {
  id: 'test-order-456',
  orderNo: 'MG202606002',
  status: 'pending_shipment',
  customerName: '李四',
  customerPhone: '13900139000',
  customerAddress: '上海市浦东新区',
  actualAmount: 3500,
  items: [
    {
      id: 'item2',
      productId: 'prod2',
      productName: '遮光窗帘',
      productCode: 'SKU-002',
      unitPrice: 175,
      quantity: 20,
      amount: 3500,
    },
  ],
  processingItems: [],
}

import ShipOrder from '@/app/(dashboard)/orders/[id]/ship/ShipOrder'

describe('ShipOrder', () => {
  let printSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    mockUser = { id: 'u-1', name: '王五', nickname: 'wangwu', username: '13700137000' }
    mockGetOrder.mockResolvedValue({
      data: { data: mockOrder },
    })
    mockUpdateLogistics.mockResolvedValue({ data: { data: null } })
    mockUpdateOrderStatus.mockResolvedValue({ data: { data: null } })
    // 默认：查不到客户档案（不覆盖发货页既有默认值「德邦快递」）
    mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    printSpy = vi.fn()
    window.print = printSpy as any
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should show loading state initially', () => {
    render(<ShipOrder />)
    expect(screen.getByText('加载订单详情...')).toBeInTheDocument()
  })

  it('should render page title after loading', async () => {
    render(<ShipOrder />)
    // 页面标题 "商品发货" 在 h1 和面包屑中都会出现
    const headings = await screen.findAllByText('商品发货')
    expect(headings.length).toBeGreaterThanOrEqual(1)
  })

  it('should render breadcrumb navigation', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('首页')).toBeInTheDocument()
      expect(screen.getByText('订单管理')).toBeInTheDocument()
    })
  })

  it('should render confirm goods section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认商品信息')).toBeInTheDocument()
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
  })

  it('should render confirm shipping info section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认收货信息')).toBeInTheDocument()
      // 「收货信息」同时是屏幕区块标题与纸质单据区块标题 → 命中多处是预期
      expect(screen.getAllByText('收货信息').length).toBeGreaterThanOrEqual(1)
      // 收货人「李四」同时出现在屏幕区块与纸质单据（屏幕隐藏副本）→ 命中多处是预期
      expect(screen.getAllByText('李四').length).toBeGreaterThanOrEqual(1)
    })
  })

  it('should render logistics section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认物流')).toBeInTheDocument()
    })
  })

  it('should render shipping method options', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('物流发货')).toBeInTheDocument()
      expect(screen.getByText('无需物流')).toBeInTheDocument()
    })
  })

  it('should render confirm and cancel buttons', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认发货')).toBeInTheDocument()
      expect(screen.getByText('取消发货')).toBeInTheDocument()
    })
  })

  it('should show not-allowed state for non-shippable order', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed' } },
    })
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('当前订单状态不允许发货')).toBeInTheDocument()
    })
  })

  // ===== 发货人 + 发货单打印（UI-040）=====

  it('发货人默认预填当前登录人姓名（不是手机号/账号）', async () => {
    render(<ShipOrder />)

    const input = await screen.findByPlaceholderText('请输入实际发货人姓名')
    expect(input).toHaveValue('王五')
  })

  it('登录用户信息晚到：仅回填尚未被手工改过的字段', async () => {
    mockUser = null
    const { rerender } = render(<ShipOrder />)

    const input = await screen.findByPlaceholderText('请输入实际发货人姓名')
    expect(input).toHaveValue('')

    mockUser = { id: 'u-1', name: '王五' }
    rerender(<ShipOrder />)

    await waitFor(() =>
      expect(screen.getByPlaceholderText('请输入实际发货人姓名')).toHaveValue('王五')
    )
  })

  it('改成实际发货人后确认发货：payload 带 shipperName 且订单流转 shipped', async () => {
    const user = userEvent.setup()
    render(<ShipOrder />)

    const shipperInput = await screen.findByPlaceholderText('请输入实际发货人姓名')
    await user.clear(shipperInput)
    await user.type(shipperInput, '赵六')
    await user.type(screen.getByPlaceholderText('请输入快递单号'), 'SF20260915001')
    await user.click(screen.getByRole('button', { name: /确认发货/ }))

    await waitFor(() => expect(mockUpdateLogistics).toHaveBeenCalledTimes(1))
    expect(mockUpdateLogistics).toHaveBeenCalledWith(
      'test-order-456',
      expect.objectContaining({ trackingNo: 'SF20260915001', shipperName: '赵六' })
    )
    await waitFor(() =>
      expect(mockUpdateOrderStatus).toHaveBeenCalledWith('test-order-456', { status: 'shipped' })
    )
  })

  it('发货人清空时拒绝提交（纸质单据不能没有经手人）', async () => {
    const user = userEvent.setup()
    render(<ShipOrder />)

    await user.clear(await screen.findByPlaceholderText('请输入实际发货人姓名'))
    await user.type(screen.getByPlaceholderText('请输入快递单号'), 'SF1')
    await user.click(screen.getByRole('button', { name: /确认发货/ }))

    await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('请输入发货人'))
    expect(mockUpdateLogistics).not.toHaveBeenCalled()
  })

  it('发货前可打印发货单：点击真的触发 window.print', async () => {
    const user = userEvent.setup()
    render(<ShipOrder />)

    await user.click(await screen.findByRole('button', { name: /打印发货单/ }))

    expect(printSpy).toHaveBeenCalledTimes(1)
  })

  it('发货单在 DOM 中就绪（屏幕隐藏、打印显形），内容含订单号/收货人/明细/发货人', async () => {
    render(<ShipOrder />)

    await screen.findByPlaceholderText('请输入实际发货人姓名')

    const doc = document.querySelector('.shipment-print-area')
    expect(doc).not.toBeNull()
    expect(doc!.textContent).toContain('发货单')
    expect(doc!.textContent).toContain('MG202606002')
    expect(doc!.textContent).toContain('李四')
    expect(doc!.textContent).toContain('遮光窗帘')
    // 发货人 = 当前输入值（尚未保存也要能印在纸面）
    expect(doc!.textContent).toContain('王五')
  })

  // ===== 客户常用物流档案带出（issue #4419 / UI-046）=====

  it('按订单手机号精确查客户档案，带出常用物流方式与公司', async () => {
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [
            // 关键词模糊命中但手机号不同 ⇒ 不得采用（防带错客户）
            { id: 'c-other', phone: '13900139001', defaultLogisticsType: 'express', defaultLogisticsCompany: '顺丰速运' },
            { id: 'c-hit', phone: '13900139000', defaultLogisticsType: 'logistics', defaultLogisticsCompany: '四季安物流' },
          ],
          total: 2,
        },
      },
    })
    render(<ShipOrder />)

    await waitFor(() => {
      expect(mockGetCustomers).toHaveBeenCalledWith(
        expect.objectContaining({ keyword: '13900139000' })
      )
    })
    await waitFor(() => {
      const selects = screen.getAllByRole('combobox')
      expect(selects[0]).toHaveValue('四季安物流')
    })
    // 物流方式带出为「物流/专线」（express 是后端列默认，不是客户档案里的值）
    expect(screen.getByRole('radio', { name: '物流/专线' })).toBeChecked()
  })

  it('常用公司是预置列表之外的自定义承运商时，下拉里补出该选项（否则显示不出已存值）', async () => {
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [{ id: 'c-hit', phone: '13900139000', defaultLogisticsCompany: '本地专线·老王' }],
          total: 1,
        },
      },
    })
    render(<ShipOrder />)

    await waitFor(() => {
      expect(screen.getAllByRole('combobox')[0]).toHaveValue('本地专线·老王')
    })
    expect(screen.getByRole('option', { name: '本地专线·老王' })).toBeInTheDocument()
  })

  it('用户已手动改过物流公司后，档案带出不再覆盖手工输入', async () => {
    const user = userEvent.setup()
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [{ id: 'c-hit', phone: '13900139000', defaultLogisticsCompany: '四季安物流' }],
          total: 1,
        },
      },
    })
    render(<ShipOrder />)

    const companySelect = (await screen.findAllByRole('combobox'))[0]
    await user.selectOptions(companySelect, '顺丰速运')
    // 等档案请求的 then 落地（若实现会覆盖，这里就会被打回四季安物流）
    await waitFor(() => expect(mockGetCustomers).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 0))
    expect(companySelect).toHaveValue('顺丰速运')
  })

  it('确认发货时 payload 携带物流方式（此前 admin-web 从不设置 logistics_type）', async () => {
    const user = userEvent.setup()
    render(<ShipOrder />)

    await screen.findByPlaceholderText('请输入实际发货人姓名')
    await user.click(screen.getByRole('radio', { name: '物流/专线' }))
    await user.type(screen.getByPlaceholderText('请输入快递单号'), 'SF20260919001')
    await user.click(screen.getByRole('button', { name: /确认发货/ }))

    await waitFor(() => expect(mockUpdateLogistics).toHaveBeenCalledTimes(1))
    expect(mockUpdateLogistics).toHaveBeenCalledWith(
      'test-order-456',
      expect.objectContaining({ logisticsType: 'logistics' })
    )
  })
})
