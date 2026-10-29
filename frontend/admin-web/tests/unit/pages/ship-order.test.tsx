// case_ids: UI-040, UI-047, OR-072

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { switchCarrier } from '@/lib/logistics'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

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
/** 原子发货端点替身（issue #6983）：发货页**唯一**的提交通道。 */
const mockShipOrder = vi.fn()
const mockGetCustomers = vi.fn()
const mockProcessingOrderDetail = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
  },
  // 生产 API（issue #6983）：`shipOrder` = 原子发货端点
  // （POST /api/admin/production/orders/{id}/ship，单事务 + 幂等 + 建发货单）。
  productionApi: {
    shipOrder: (...args: any[]) => mockShipOrder(...args),
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

/**
 * 幂等键序列（issue #6935）：`shipRequestId` 用 `crypto.randomUUID()`，
 * 这里替换成**可预测**的计数器 ⇒ 能判「重试复用同值 / 成功后换新值」。
 */
const requestIds: string[] = []
beforeEach(() => {
  requestIds.length = 0
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: {
      randomUUID: () => {
        const id = `req-${requestIds.length + 1}`
        requestIds.push(id)
        return id
      },
    },
  })
})

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
  // issue #7079 第 5 包：发货前置判据 = 读面键 `work_order_kind`（缺键/null = 无需要报工的作业）
  work_order_kind: null,
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
    mockShipOrder.mockResolvedValue({ data: { data: { status: 'shipped' } } })
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
      // issue #5271：组名随侧边栏 IA 改判（原「订单管理」→「交易管理」）
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      expect(screen.getByText('销售订单')).toBeInTheDocument()
    })
  })

  it('should render confirm goods section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认商品信息')).toBeInTheDocument()
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
  })

  // ===== 商品信息表：整表统一居中（issue #7590）=====
  // 发货页这份 `ProductTable` 是订单详情页的复制体，改前**同形态**混用左/中/右对齐。
  // 判据与详情页一致（两份必须同步收敛，否则「同一个商品表在两个页面长得不一样」）。
  it('商品信息表：每个表头与数据格都居中（issue #7590）', async () => {
    render(<ShipOrder />)
    const header = await screen.findByRole('columnheader', { name: '商品合计(元)' })
    const table = header.closest('table')!
    // 存在性断言要**触业务对象**（弱断言 `not.toBeNull` 会被 QA Growth Gate 判红）
    expect(table.tagName, '找不到「商品信息」表 ⇒ 判据在扫空气').toBe('TABLE')
    const cells = Array.from(table.querySelectorAll('th, td'))
    expect(cells.length, '表内单元格不足 8 个 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(8)
    const label = (c: Element) => `${c.tagName}「${(c.textContent || '').trim().slice(0, 10)}」`
    expect(
      cells.filter((c) => !c.className.split(/\s+/).includes('text-center')).map(label),
      '这些单元格没有居中（整表统一居中，见 issue #7590）'
    ).toEqual([])
    expect(
      cells.filter((c) => /\btext-(left|right)\b/.test(c.className)).map(label),
      '这些单元格同时带了 text-left / text-right ⇒ 会覆盖居中'
    ).toEqual([])
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

  /**
   * 🔴 判据 A（issue #6983）：确认发货 ⇒ 调**原子端点** `productionApi.shipOrder`，
   * 且请求带 `X-Client-Request-Id`（幂等键）。
   *
   * 红证：把提交改回 `orderApi.updateLogistics` + `orderApi.updateOrderStatus(shipped)` 两步 ⇒ 本条必红
   * （mockShipOrder 零调用，而那两个 mock 会各被调一次 —— 本条**不**再断言它们，
   * 由下一条类级元守卫扫源码判死）。
   */
  it('确认发货 ⇒ 调原子端点（带幂等键），不再走两步老路', async () => {
    const user = userEvent.setup()
    render(<ShipOrder />)

    const shipperInput = await screen.findByPlaceholderText('请输入实际发货人姓名')
    await user.clear(shipperInput)
    await user.type(shipperInput, '赵六')
    await user.type(screen.getByPlaceholderText('请输入快递单号'), 'SF20260915001')
    await user.click(screen.getByRole('button', { name: /确认发货/ }))

    await waitFor(() => expect(mockShipOrder).toHaveBeenCalledTimes(1))
    expect(mockShipOrder).toHaveBeenCalledWith(
      'test-order-456',
      expect.objectContaining({ trackingNo: 'SF20260915001', shipperName: '赵六' }),
      // 第三个参数 = 幂等键（由 api 层放进 `X-Client-Request-Id` 请求头，见 lib/api.ts）
      expect.stringMatching(/^req-\d+$/)
    )
  })

  /**
   * 🔴 判据 B（issue #6935）：失败后重试**复用同一个幂等键** —— 否则一次超时重试就是两次发货。
   * 成功后才换新键（下一件发货是一件新事）。
   */
  it('失败重试复用同一幂等键；成功后换新键', async () => {
    requestIds.length = 0
    const user = userEvent.setup()
    render(<ShipOrder />)

    await user.type(await screen.findByPlaceholderText('请输入快递单号'), 'SF-TIMEOUT-1')
    mockShipOrder.mockRejectedValueOnce(new Error('timeout'))
    await user.click(screen.getByRole('button', { name: /确认发货/ }))
    await waitFor(() => expect(mockShipOrder).toHaveBeenCalledTimes(1))
    expect(mockShipOrder.mock.calls[0][2]).toBe('req-1')

    // 重试（第二次点击）：仍是同一个键
    await user.click(screen.getByRole('button', { name: /确认发货/ }))
    await waitFor(() => expect(mockShipOrder).toHaveBeenCalledTimes(2))
    expect(mockShipOrder.mock.calls[1][2]).toBe('req-1')

    // 成功后：换新键（第三次点击是一件新的发货）
    await user.click(screen.getByRole('button', { name: /确认发货/ }))
    await waitFor(() => expect(mockShipOrder).toHaveBeenCalledTimes(3))
    expect(mockShipOrder.mock.calls[2][2]).toBe('req-2')
  })

  /**
   * 🔴 判据 C（issue #6983）· **类级元守卫**：发货写面不得再出现「先 updateLogistics
   * 再 updateOrderStatus(shipped)」那条两步老路。
   *
   * 为什么扫**源码**而不是再断言一次 mock：那两步的病灶是「不建发货单 + 非原子 + 无幂等键」，
   * 而 mock 面上「调没调」只能覆盖到当前这一条用例走的分支 —— 只要有人在别的分支
   * （如「无需物流」路径）把老路写回来，行为判据**看不见**。源码扫描是这条纪律的机械面：
   * 旧调用回潮 ⇒ 当场红并具名报出命中的那一处。
   *
   * 🔴 2026-10-28（issue #8013）扩面：发货写面从**一个**入口变成**两个** —— 整页发货页
   * `ShipOrder.tsx` 与销售订单列表的行内快捷发货 `InlineShipForm.tsx`。只扫其中一个 =
   * 「换个入口写回老路」照样绿 ⇒ 扫描面必须覆盖两个入口（新入口随本单一起进扫描面）。
   *
   * 判别力自证：把两条旧调用拼进内存字符串 ⇒ 同一份判据当场命中（证明它不是恒绿的空断言）。
   */
  it('类级守卫：发货写面（整页 + 行内）源码不得再出现两步老路（扫源码，回潮即红）', async () => {
    /** 发货写面的**全部**入口（新增入口必须登记到这里，否则它不受本判据约束） */
    const WRITE_SURFACES = [
      'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
      'src/components/orders/InlineShipForm.tsx',
    ]

    // 判据 = 两条**老端点的调用形态**（`orderApi.<方法>(`）—— 只认调用、不认散文：
    // 注释里可以解释这条纪律（那正是它被写下来的方式），但**代码里不许再出现调用**。
    const forbidden = [
      ['orderApi', 'updateLogistics('].join('.'),
      ['orderApi', 'updateOrderStatus('].join('.'),
    ]

    for (const rel of WRITE_SURFACES) {
      const source = readFileSync(join(process.cwd(), rel), 'utf8')
      // 前置条件（触发确认）：原子入口必须在场，否则「旧调用不在」是空跑
      expect(source, `${rel} 没有走原子发货端点`).toContain('productionApi.shipOrder(')
      const hits = forbidden.filter((needle) => source.includes(needle))
      expect(hits, `${rel} 出现两步老路：${hits.join(', ')}`).toEqual([])

      // 判别力自证：同一份判据对「把老路加回来」的文本当场命中（不是恒绿）
      const regressed = `${source}\n await orderApi.${'updateLogistics'}(order.id, {})`
      expect(forbidden.some((needle) => regressed.includes(needle))).toBe(true)
    }
  })

  it('发货人清空时拒绝提交（纸质单据不能没有经手人）', async () => {
    const user = userEvent.setup()
    render(<ShipOrder />)

    await user.clear(await screen.findByPlaceholderText('请输入实际发货人姓名'))
    await user.type(screen.getByPlaceholderText('请输入快递单号'), 'SF1')
    await user.click(screen.getByRole('button', { name: /确认发货/ }))

    await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('请输入发货人'))
    expect(mockShipOrder).not.toHaveBeenCalled()
  })

  it('本页**没有**打印入口（issue #7902：发货单退场，纸统一在销售订单详情出）', async () => {
    render(<ShipOrder />)
    // 稳态锚点：发货表单已就绪（不拿"打印按钮不存在"当锚点，否则判据会空跑）
    await screen.findByPlaceholderText('请输入实际发货人姓名')

    expect(screen.queryByRole('button', { name: /打印/ })).toBeNull()
    expect(document.querySelector('.shipment-print-area')).toBeNull()
    expect(screen.queryByTestId('print-preview')).toBeNull()
  })

  it('打印用例跑完后 window.print 必须已还原（否则泄漏到后续用例 ⇒「没打印」类断言恒真/恒假）', () => {
    expect(vi.isMockFunction(window.print)).toBe(false)
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

    await waitFor(() => expect(mockShipOrder).toHaveBeenCalledTimes(1))
    expect(mockShipOrder).toHaveBeenCalledWith(
      'test-order-456',
      expect.objectContaining({
        logisticsType: 'logistics',
        shippingMethod: 'logistics',
      }),
      expect.stringMatching(/^req-\d+$/)
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

  // ══════════════════════════════════════════════════════════════════════════
  // 承运商候选按物流类型收敛（issue #8079）
  //
  // 改前 `LOGISTICS_TYPES` 与 `LOGISTICS_COMPANIES` 是**两套互不相关的词表**：选「快递」照样
  // 能选「四季安物流」，选「物流/专线」照样全是快递公司 ⇒ 真机上「物流类型 = 快递 +
  // 物流公司 = 德邦快递」这种自相矛盾的组合还能提交。用户 2026-10-29：「全链路都要区分」。
  //
  // 与行内发货（`orders-inline-ship.test.tsx` 的 ⑧ 组）**同一组断言**（同一份词表函数）。
  // ══════════════════════════════════════════════════════════════════════════
  const companySelect = () => screen.getAllByRole('combobox')[0] as HTMLSelectElement
  const companyOptionValues = () => Array.from(companySelect().options).map((o) => o.value)
  const carrierTypeRadio = (label: string) => screen.getByRole('radio', { name: label })

  it('#8079 ① 选「物流/专线」⇒ 候选里不含任何快递公司（含顺丰速运）', async () => {
    render(<ShipOrder />)
    // 订单没记类型 ⇒ express + 快递第一家（既有默认值不回归）
    await waitFor(() => expect(companySelect()).toHaveValue('德邦快递'))
    fireEvent.click(carrierTypeRadio('物流/专线'))
    expect(companyOptionValues()).toEqual(['四季安物流'])
    expect(companyOptionValues()).not.toContain('顺丰速运')
  })

  it('#8079 ② 选「快递」⇒ 候选里不含专线承运商（四季安物流）', async () => {
    // 订单记的是专线 ⇒ 表单带出专线第一家；切回快递必须换成快递候选
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, logisticsType: 'logistics' } } })
    render(<ShipOrder />)
    await waitFor(() => expect(carrierTypeRadio('物流/专线')).toBeChecked())
    fireEvent.click(carrierTypeRadio('快递'))
    expect(companyOptionValues()).not.toContain('四季安物流')
    expect(companyOptionValues()).toEqual([
      '德邦快递',
      '顺丰速运',
      '中通快递',
      '圆通速递',
      '韵达快递',
      '申通快递',
    ])
  })

  it('#8079 ③ 从「快递-顺丰」切到「物流/专线」⇒ 承运商落到专线第一家，并给一次可见提示', async () => {
    render(<ShipOrder />)
    await waitFor(() => expect(companySelect()).toHaveValue('德邦快递'))
    fireEvent.change(companySelect(), { target: { value: '顺丰速运' } })
    expect(companySelect()).toHaveValue('顺丰速运')

    fireEvent.click(carrierTypeRadio('物流/专线'))

    // 不残留顺丰：落到专线第一家
    expect(companySelect()).toHaveValue('四季安物流')
    expect(companySelect()).not.toHaveValue('顺丰速运')
    // 可见提示（不是静默改）—— 文案唯一真值在 `lib/logistics.ts`，两处不各写一句会漂的话
    expect(screen.getByTestId('ship-carrier-notice')).toHaveTextContent(
      switchCarrier('顺丰速运', 'logistics').notice ?? '',
    )
    // 手改承运商 ⇒ 提示消失（不留一条过期提示）
    fireEvent.change(companySelect(), { target: { value: '四季安物流' } })
    expect(screen.queryByTestId('ship-carrier-notice')).toBeNull()
  })

  it('#8079 ④ 订单带 logisticsType=logistics 且没记承运商 ⇒ 默认取该类型第一家（不落成「专线 + 德邦快递」）', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, logisticsType: 'logistics' } } })
    render(<ShipOrder />)
    await waitFor(() => expect(carrierTypeRadio('物流/专线')).toBeChecked())
    expect(companySelect()).toHaveValue('四季安物流')
  })

  it('#8079 ④b 客户档案只记了物流类型（没记承运商）⇒ 承运商取该类型第一家', async () => {
    mockGetCustomers.mockResolvedValue({
      data: {
        data: {
          items: [{ id: 'c-hit', phone: '13900139000', defaultLogisticsType: 'logistics' }],
          total: 1,
        },
      },
    })
    render(<ShipOrder />)
    await waitFor(() => expect(mockGetCustomers).toHaveBeenCalled())
    await waitFor(() => expect(companySelect()).toHaveValue('四季安物流'))
    expect(carrierTypeRadio('物流/专线')).toBeChecked()
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
          // #7079：守卫读 `work_order_kind` ⇒ 含加工项单必须显式给 'processing'（不给就绕过守卫 = 假绿）
          work_order_kind: 'processing',
          items: [
            {
              ...mockOrder.items[0],
              processingFee: 37.5,
              processingInfo: { processingItems: [{ id: 'pr-1', name: '打孔', quantity: 12.5 }] },
            },
          ],
          processingItems: [{ id: 'pr-1', name: '打孔', quantity: 12.5 }],
        },
      },
    })
    render(<ShipOrder />)

    await screen.findAllByText('商品发货')
    expect(screen.queryByText(/须先完成加工单后再发货/)).toBeNull()

    // 屏幕侧的加工项表已随 #4882 退场（本页也不再挂纸质发货单 —— issue #7902）
    expect(screen.queryByText('加工合计')).toBeNull()
    expect(document.querySelector('.shipment-print-area')).toBeNull()
    // 反向自证（不是空跑）：页面确实渲染了发货表单与金额区
    expect(screen.getByPlaceholderText('请输入实际发货人姓名')).toBeInTheDocument()
    expect(document.body.textContent).toContain('订单实收款')
  })

  /**
   * issue #6664 第 6 条：**币符重复** —— `formatAmount` 已带 `¥`，调用处再拼「元」。
   *
   * 改前：`订单实收款：{formatAmount(order.actualAmount)}元` ⇒ 屏幕渲染成 `¥3,500.00元`，
   * 而**同一页的纸质发货单**与**订单详情页**都只写 `¥3,500.00` ⇒ 同一笔钱两个口径。
   *
   * 判据 = 对**真渲染结果**做形态检查（不是扫源码字符串）：
   * 全文不得出现「币符 + 数字 + 元」形态。
   * **注入式红证**：把 `元` 拼回去（`{formatAmount(order.actualAmount)}元`）⇒ 本条必红。
   */
  it('金额渲染不出现「币符 + 数字 + 元」形态（issue #6664 第 6 条）', async () => {
    render(<ShipOrder />)
    await screen.findAllByText('商品发货')

    const DUPLICATE_CURRENCY = /¥\s*[\d,]+\.\d{2}\s*元/
    const text = document.body.textContent ?? ''
    // 前置条件（触发确认）：页面上**确实**印了这笔钱（否则下面的零命中断言是空断言）
    expect(text).toContain('¥3,500.00')
    expect(text, `出现币符重复：${text.match(DUPLICATE_CURRENCY)?.[0] ?? ''}`).not.toMatch(DUPLICATE_CURRENCY)
    // 判别力自证：同一条正则对**改前**的字符串必命中
    expect(`订单实收款：¥3,500.00元`).toMatch(DUPLICATE_CURRENCY)
  })

  // ── 读失败 ≠ 不存在（issue #8057）──────────────────────────────────────────
  // 修前形态：`catch` 只 `toastRequestError`，`order` 留在 null ⇒ 本页印「订单不存在或已被删除」
  // —— 与销售订单详情同一种「把没读到说成单子没了」。
  it('读失败：常驻失败锚 + 重试出口，且不印「订单不存在或已被删除」（失败 ≠ 不存在）', async () => {
    mockGetOrder.mockRejectedValueOnce(new Error('boom'))
    render(<ShipOrder />)

    const anchor = await screen.findByTestId('ship-order-load-error')
    expect(anchor).toHaveTextContent('加载失败')
    expect(screen.queryByText('订单不存在或已被删除')).toBeNull()

    fireEvent.click(screen.getByTestId('ship-order-load-error-retry'))
    await waitFor(() => expect(mockGetOrder).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByTestId('ship-order-load-error')).toBeNull())
  })
})
