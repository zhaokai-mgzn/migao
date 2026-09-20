// case_ids: UI-040, UI-047

import { describe, it, expect, vi, beforeEach } from 'vitest'
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
const mockProcessingOrderDetail = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    updateLogistics: (...args: any[]) => mockUpdateLogistics(...args),
    updateOrderStatus: (...args: any[]) => mockUpdateOrderStatus(...args),
  },
  // 客户常用物流档案带出（issue #4419 / UI-047）
  customerApi: {
    getCustomers: (...args: any[]) => mockGetCustomers(...args),
  },
  // 加工单前置守卫（issue #3889）：本文件多数用例的订单**不含加工项** ⇒ 该 effect 短路、不会调用它。
  // #4882 的用例给一个「已完成」的加工单，让含加工项订单能渲染出「商品信息」卡
  // （否则会被守卫拦在阻断页 —— 那样「加工项表不存在」的断言就成了空跑）。
  processingOrderApi: {
    detail: (...args: any[]) => mockProcessingOrderDetail(...args),
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
  // `window.print` 用 `vi.spyOn` 注入，并在**创建它的那个用例里** `printSpy.mockRestore()` 还原。
  //
  // 反例一（#4768 之前）：`window.print = vi.fn() as any` —— **直接赋值** jsdom 的 `window.print`
  // 且从不还原 ⇒ 泄漏到同文件后续用例，让「打印没被调用」这类断言恒真/恒假。
  // 🔴 反例二（#4768 的写法，**本单修的就是它**）：`afterEach(() => vi.restoreAllMocks())` ——
  // 它对**每一个**注册过的 mock 调 `mockRestore()`（= `mockReset()` + `state.restore()`），
  // 而 `mockReset()` 会 `implementation = undefined` ⇒ **本文件的 `vi.fn()` 替身
  // （mockGetOrder / mockGetCustomers / …）被清成「返回 undefined」**（不只是 `vi.spyOn`）。
  // 而 RTL 的 `cleanup()` 也在 `afterEach` 且**本文件先跑**（实测：那一刻
  // `document.body.children.length == 1`，组件**尚未卸载**）⇒ 存在「替身已清空、组件仍挂载」的窗口：
  // 组件的 effect 只要在这个窗口里再跑一次，`customerApi.getCustomers()` 就拿到 `undefined`
  // ⇒ `undefined.then` 同步抛 ⇒ 组件崩 ⇒ **本文件任意用例随机红**、**卡住前端部署**
  // （CI 实测：`ShipOrder.tsx:154`，`deploy-frontend.yml` 的「Unit tests」步）。
  // ⇒ 只还原**自己创建的那个 spy**，不做文件级清场（同一条根因 #4496 已诊断过一次，见 #4497；#4773 复发）。

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
    // 还原**只针对这一个 spy**（见 describe 头的反例二）：文件级 `restoreAllMocks()` 会连
    // `vi.fn()` 替身的实现一起清掉 ⇒ 组件 effect 命中 `undefined` ⇒ 本文件随机红、卡住部署。
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    try {
      const user = userEvent.setup()
      render(<ShipOrder />)

      await user.click(await screen.findByRole('button', { name: /打印发货单/ }))

      expect(printSpy).toHaveBeenCalledTimes(1)
    } finally {
      printSpy.mockRestore()
    }
  })

  it('打印用例跑完后 window.print 必须已还原（否则泄漏到后续用例 ⇒「没打印」类断言恒真/恒假）', () => {
    // 反向护栏：删掉上面那条用例的 `finally { printSpy.mockRestore() }` ⇒ 本判据必红。
    expect(vi.isMockFunction(window.print)).toBe(false)
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

  // ===== 客户常用物流档案带出（issue #4419 / UI-047）=====

  it('订单收货电话 = 客户档案「默认收货电话」（≠ 账户手机号）时同样带出（issue #4436）', async () => {
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: 'c-recv',
              // 账户手机号与订单收货电话**不同** —— 送到工地/仓库、联系人是另一人的常态
              phone: '13900139001',
              defaultReceiverPhone: '13900139000',
              defaultLogisticsType: 'logistics',
              defaultLogisticsCompany: '四季安物流',
            },
          ],
          total: 1,
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
      expect(screen.getAllByRole('combobox')[0]).toHaveValue('四季安物流')
    })
    expect(screen.getByRole('radio', { name: '物流/专线' })).toBeChecked()
  })

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

  // ══════════════════════════════════════════════════════════════════════════
  // 订单上的常用物流两列**优先**（issue #4874；后端 #4872 建单落库）
  //
  // 改动前：发货页只按订单收货手机号反查**客户档案**（#4419）。订单自己已经记了承运商
  // （下单页选客户时带出并落库）⇒ 应以订单为准；客户档案反查**保留**为
  // 「存量单 / 订单没记这一半」的兜底（**不删、不改成门禁**）。
  // ══════════════════════════════════════════════════════════════════════════
  it('#4874 订单两列有值 ⇒ 用订单值（**不**被客户档案反查覆盖）', async () => {
    // 注入式红证：让客户档案给出**另一组**值（快递 + 顺丰速运）。
    // 若实现把来源顺序调反（先档案、或档案无条件覆盖），界面会显示 顺丰速运 / 快递 ⇒ 本判据红。
    mockGetOrder.mockResolvedValue({
      data: {
        data: { ...mockOrder, logisticsType: 'logistics', logisticsCompany: '四季安物流' },
      },
    })
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: 'c-hit',
              phone: '13900139000',
              defaultLogisticsType: 'express',
              defaultLogisticsCompany: '顺丰速运',
            },
          ],
          total: 1,
        },
      },
    })
    render(<ShipOrder />)

    await waitFor(() => {
      expect(screen.getAllByRole('combobox')[0]).toHaveValue('四季安物流')
    })
    expect(screen.getByRole('radio', { name: '物流/专线' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '快递' })).not.toBeChecked()
    // 订单两半都齐 ⇒ **不发**反查请求（订单值就是权威来源）
    expect(mockGetCustomers).not.toHaveBeenCalled()
  })

  it('#4874 订单两列都缺（存量单）⇒ 回落客户档案反查（既有兜底不退化）', async () => {
    // mockOrder 本身没有 logisticsType / logisticsCompany（= 建单早于 #4872 的存量单）
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder } } })
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: 'c-hit',
              phone: '13900139000',
              defaultLogisticsType: 'logistics',
              defaultLogisticsCompany: '四季安物流',
            },
          ],
          total: 1,
        },
      },
    })
    render(<ShipOrder />)

    await waitFor(() => {
      expect(screen.getAllByRole('combobox')[0]).toHaveValue('四季安物流')
    })
    expect(screen.getByRole('radio', { name: '物流/专线' })).toBeChecked()
  })

  // ===== #4882：加工项表整表退场（与订单详情同款 A 方案）=====
  it('#4882 含加工项订单：屏幕上的加工项表（加工项 | 单价 | 数量 | 金额 | 加工合计）不再渲染', async () => {
    // 加工单已完成 ⇒ 守卫放行，发货表单与「商品信息」卡正常渲染
    mockProcessingOrderDetail.mockResolvedValue({ data: { data: { status: 'completed' } } })
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          hasProcessing: true,
          items: [{ ...mockOrder.items[0], processingFee: 37.5 }],
          // #4882：后端 `ProcessingItemBrief` 只剩 id / name / quantity
          processingItems: [{ id: 'pr-1', name: '打孔', quantity: 12.5 }],
        },
      },
    })
    render(<ShipOrder />)

    // 等发货表单落地（先确认没被守卫拦成阻断页 —— 否则下面的断言是空跑）
    await screen.findAllByText('商品发货')
    expect(screen.queryByText(/须先完成加工单后再发货/)).toBeNull()

    // 红证：`加工合计` 是那张退场表**独有**的表头
    // （保留下来的纸质发货单只有「加工费合计（元）：X」，没有「加工合计」）
    // ⇒ 把 `ProcessingTable`（定义或使用）加回来即红
    expect(screen.queryByText('加工合计')).toBeNull()

    // 退场的是「表」，不是「含加工项」语义：纸质单据照旧印名称 / 米数 / 加工费合计（行级落库值）
    expect(screen.getByText('加工费合计（元）：37.50')).toBeInTheDocument()
    expect(screen.getByText('打孔')).toBeInTheDocument()
    expect(screen.getByText('12.5')).toBeInTheDocument()
  })
})
