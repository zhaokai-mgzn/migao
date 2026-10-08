// case_ids: PR-081
//
// PR-081（issue #5177）：智能派单**成批区**（排序渲染、预览、一键成批派单 UI）的可执行判据。
//
// 本文件的核心是**判据 5：排序是真实消费者** —— 服务端是排序的唯一口径
// （到货日升序 null 最后 → waitHours 降序 → waitingSince 升序 → orderId 升序），
// 页面必须**按接口给的数组顺序渲染**。所以这里的桩数据刻意让**任何**可能的客户端排序
// 都得出不同结果：
//
//   | DOM 位 | 单号       | 到货日     | waitHours |
//   |-------|-----------|-----------|-----------|
//   | 1     | MG-0009   | 2026-10-02 | 3         |   ← orderNo 最大、到货日居中、等待最短
//   | 2     | MG-0001   | 2026-09-30 | 50        |   ← orderNo 最小、到货日最早
//   | 3     | MG-0005   | null       | 120       |   ← 未指定到货日、等待最长
//
// ⇒ 按 orderNo 排会得到 0001/0005/0009；按到货日排会把第 1、2 行对调；按 waitHours 降序排会整段倒过来。
//   三者都与桩顺序不同 ⇒ **任何**在浏览器里补的排序器都会让断言红。
//
// 🔴 米数同理：预览桩里的 `savedMeters` **故意不自洽**（99 ≠ 10 − 6.5）——
//    前端一旦自己相减，断言就红（判据不会被自己的文案喂绿）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockGetBoard = vi.fn()
const mockPreview = vi.fn()
const mockDispatch = vi.fn()

vi.mock('@/lib/api', () => ({
  poolBoardApi: {
    getBoard: (...a: unknown[]) => mockGetBoard(...a),
    preview: (...a: unknown[]) => mockPreview(...a),
    dispatch: (...a: unknown[]) => mockDispatch(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import ProductionPoolPage from '@/app/(dashboard)/production/pool/page'
import type { PoolBoard, PoolDispatchResult, PoolLine, PoolPreview } from '@/types'

const ok = (data: unknown) => ({ data: { data } })

const line = (over: Partial<PoolLine>): PoolLine => ({
  orderId: 'o1',
  orderNo: 'MG-0001',
  itemId: 'i1',
  productId: 'p1',
  productName: '遮光布',
  skuCode: '米白/2.8m',
  requiredMeters: 10,
  waitingSince: '2026-09-20T08:00:00+08:00',
  waitHours: 50,
  overdue: false,
  isUrgent: false,
  requiredDeliveryDate: null,
  deliveryDaysLeft: null,
  ...over,
})

// ⚠️ 数组顺序 = 服务端顺序（见文件头表）；**故意不是**任何客户端排序的结果
const L1 = line({
  orderId: 'o9',
  orderNo: 'MG-0009',
  itemId: 'i9',
  requiredDeliveryDate: '2026-10-02',
  deliveryDaysLeft: 7,
  waitHours: 3,
})
const L2 = line({
  orderId: 'o1',
  orderNo: 'MG-0001',
  itemId: 'i1',
  requiredDeliveryDate: '2026-09-30',
  deliveryDaysLeft: 5,
  waitHours: 50,
})
const L3 = line({
  orderId: 'o5',
  orderNo: 'MG-0005',
  itemId: 'i5',
  requiredDeliveryDate: null,
  deliveryDaysLeft: null,
  waitHours: 120,
  overdue: true,
})

const board = (over: Partial<PoolBoard> = {}): PoolBoard => ({
  maxWaitHours: 24,
  poolingEnabled: true,
  orderCount: 3,
  lineCount: 3,
  overdueCount: 0,
  urgentCount: 0,
  warnings: [],
  urgentLines: [],
  groups: [
    {
      materialKey: '遮光布 / 米白 / 2.8m',
      productId: 'p1',
      skuCode: '米白/2.8m',
      orderCount: 3,
      requiredMeters: 30,
      lines: [L1, L2, L3],
    },
  ],
  ...over,
})

const PREVIEW: PoolPreview = {
  orderCount: 2,
  assignmentRule: 'best-fit',
  formulaMeters: 10,
  pooledPlannedMeters: 6.5,
  // 🔴 故意不自洽：真实服务端会给 3.5（= 10 − 6.5）—— 前端自己相减 ⇒ 红
  savedMeters: 99,
  // ⚠️ 真值源 `ProductionPoolViews.Preview`：**五个米数字段全是 BigDecimal**（聚合）。
  // `perOrderPlannedMeters` 是**一个数**（逐单派的应领**合计**，对照读数），**不是** map。
  perOrderPlannedMeters: 8,
  poolingGainMeters: 1.5,
}

/** 成批区内**所有**订单行的单号（DOM 顺序） */
const renderedOrderNos = () =>
  Array.from(
    screen.getByTestId('pool-groups-section').querySelectorAll('[data-testid^="pool-line-"]'),
  ).map((el) => el.getAttribute('data-testid')!.replace('pool-line-', ''))

describe('智能派单 · 成批区（PR-081）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetBoard.mockResolvedValue(ok(board()))
    mockPreview.mockResolvedValue(ok(PREVIEW))
  })

  it('判据 5：按**接口给的数组顺序**渲染（本轮服务端口径），前端一处都不重排', async () => {
    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-groups-section')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('pool-line-o9')).toBeInTheDocument())

    // DOM 顺序逐字等于桩数组顺序 o9 → o1 → o5（= 到货日升序 null 最后 → waitHours 降序）
    expect(renderedOrderNos()).toEqual(['o9', 'o1', 'o5'])
    // 行内数字也来自服务端（等待时长按服务端 waitHours 渲染，不从 waitingSince 重算）
    expect(screen.getByTestId('pool-line-o9')).toHaveTextContent('3 小时')
    expect(screen.getByTestId('pool-line-o5')).toHaveTextContent('5 天')
    expect(screen.getByTestId('pool-line-o1')).toHaveTextContent('2026-09-30')
    expect(screen.getByTestId('pool-line-o5')).toHaveTextContent('未指定')
  })

  it('分组头显示物料键（商品 × 颜色 × 门幅）+ 订单数 + 需求米数（服务端值）', async () => {
    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-group-0')).toBeInTheDocument())

    const group = screen.getByTestId('pool-group-0')
    expect(group).toHaveTextContent('遮光布 / 米白 / 2.8m')
    expect(group).toHaveTextContent('3 单')
    expect(group).toHaveTextContent('30.00')
    // 空池提示不该同时出现（不是空壳页）
    expect(screen.queryByText('池内没有待派订单')).toBeNull()
  })

  it('勾选订单 ⇒ 自动调 /preview（pooled:true），并展示**五个服务端聚合米数**（逐字，不自己算）', async () => {
    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-line-o9')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('选择订单 MG-0009'))

    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1))
    // issue #6408：逐行带指派 + 显式 fifo —— 空指派 ⇒ 服务端一次都不扣料、省料恒 0
    expect(mockPreview).toHaveBeenCalledWith({
      orderIds: ['o9'],
      batches: [{ orderId: 'o9', itemId: 'i9' }],
      assignmentRule: 'fifo',
      pooled: true,
    })

    const preview = await screen.findByTestId('pool-preview')
    // 五行 = 服务端五个键，一个不少（**少一行就红** —— 例如把 perOrderPlannedMeters 当 map 处理
    // 时「对照·逐单派应领」整行会消失/变 `-`，那正是本单修掉的静默空转）
    expect(preview).toHaveTextContent('逐单公式米数（对照基线）')
    expect(preview).toHaveTextContent('10.00')
    expect(preview).toHaveTextContent('合并后预计领料米数')
    expect(preview).toHaveTextContent('6.50')
    // 🔴 服务端值逐字（99 而不是 10 − 6.5 = 3.50）⇒ 前端重算必红
    expect(preview).toHaveTextContent('预计节省')
    expect(preview).toHaveTextContent('99.00')
    // 对照读数（逐单派应领合计）—— **一个数**
    expect(preview).toHaveTextContent('对照·逐单派应领')
    expect(preview).toHaveTextContent('8.00')
    // 「池化**新增**收益」（= perOrder − pooled = 1.5）与「预计节省」（99）分开显示 ——
    // 把两者当同一个数渲染必红
    expect(preview).toHaveTextContent('合并新增收益')
    expect(preview).toHaveTextContent('1.50')
    // 预览 API **没有**逐单明细 ⇒ 不得凭空渲染一张「逐单计划米数」表
    expect(preview).not.toHaveTextContent('逐单计划米数')
  })

  it('「一键成批派单」未勾选时禁用；勾选后 ⇒ pooled:true + 逐单结果可见（成功给加工单号、失败给 message）', async () => {
    // 🔴 显式注解成 `PoolDispatchResult[]`：形状写错（例如把 `orderRef` 写成 `orderId`）⇒ **tsc 红**。
    // 若只走 `ok(data: unknown)`，错的形状照样编译通过而界面渲染成空白 —— 那正是
    // 「判据被自己的文案喂绿」的形态（本次实测踩到过：`perOrderPlannedMeters` 曾被写成 map）。
    const batchResults: PoolDispatchResult[] = [
        {
          orderRef: 'o9',
          processingOrderNo: 'JG-20260925-0001',
          success: true,
          message: null,
          code: null,
          suggestion: null,
        },
        {
          orderRef: 'o1',
          processingOrderNo: null,
          success: false,
          message: '该单缺少工艺路线，不能派单',
          code: 'NO_ROUTE',
          suggestion: '先到「工艺配置」给这个商品补路线',
        },
    ]
    mockDispatch.mockResolvedValue(ok(batchResults))

    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-dispatch-batch')).toBeInTheDocument())

    // 没勾选 ⇒ 按钮禁用（空批次派单是无效动作）
    expect(screen.getByTestId('pool-dispatch-batch')).toBeDisabled()

    fireEvent.click(screen.getByLabelText('选择订单 MG-0009'))
    fireEvent.click(screen.getByLabelText('选择订单 MG-0001'))
    // 勾选变化即触发一次预览（这里只要求「最后一次带的是两个订单」，不钉调用次数）
    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith({
        orderIds: ['o9', 'o1'],
        batches: [
          { orderId: 'o9', itemId: 'i9' },
          { orderId: 'o1', itemId: 'i1' },
        ],
        assignmentRule: 'fifo',
        pooled: true,
      }),
    )

    const btn = screen.getByTestId('pool-dispatch-batch')
    expect(btn).not.toBeDisabled()
    fireEvent.click(btn)

    await waitFor(() => expect(mockDispatch).toHaveBeenCalledTimes(1))
    expect(mockDispatch).toHaveBeenCalledWith({
      orderIds: ['o9', 'o1'],
      batches: [
        { orderId: 'o9', itemId: 'i9' },
        { orderId: 'o1', itemId: 'i1' },
      ],
      assignmentRule: 'fifo',
      pooled: true,
    })

    // **逐单结果可见**：成功那单显示加工单号；失败那单显示服务端 message（不是一句「派单失败」）
    await waitFor(() =>
      expect(screen.getByTestId('pool-result-o9')).toHaveTextContent('JG-20260925-0001'),
    )
    expect(screen.getByTestId('pool-result-o1')).toHaveTextContent('该单缺少工艺路线，不能派单')
    expect(screen.getByTestId('pool-result-o1')).toHaveTextContent('先到「工艺配置」给这个商品补路线')
  })

  it('「全选」一次勾上**全部料组**的成批候选（加急单不在候选内），再点一次清空', async () => {
    const URGENT = line({
      orderId: 'u1',
      orderNo: 'MG-URG-1',
      itemId: 'iu1',
      isUrgent: true,
      waitHours: 6,
    })
    const L7 = line({ orderId: 'o7', orderNo: 'MG-0007', itemId: 'i7' })
    mockGetBoard.mockResolvedValue(
      ok(
        board({
          orderCount: 4,
          lineCount: 4,
          urgentCount: 1,
          urgentLines: [URGENT],
          groups: [
            {
              materialKey: '遮光布 / 米白 / 2.8m',
              productId: 'p1',
              skuCode: '米白/2.8m',
              orderCount: 3,
              requiredMeters: 30,
              lines: [L1, L2, L3],
            },
            {
              materialKey: '遮光布 / 米白 / 3.2m',
              productId: 'p2',
              skuCode: '米白/3.2m',
              orderCount: 1,
              requiredMeters: 10,
              lines: [L7],
            },
          ],
        }),
      ),
    )

    render(<ProductionPoolPage />)
    const selectAll = await screen.findByTestId('pool-select-all')
    // 候选数 = **成批候选**（两个料组的行 3 + 1）—— 加急单 `u1` 不在其中
    expect(selectAll).toHaveTextContent('全选 4 单')

    fireEvent.click(selectAll)

    // 请求体逐行带指派（issue #6408）：勾中哪几行，请求里就是哪几行 —— 加急单**不在**里面
    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith({
        orderIds: ['o9', 'o1', 'o5', 'o7'],
        batches: [
          { orderId: 'o9', itemId: 'i9' },
          { orderId: 'o1', itemId: 'i1' },
          { orderId: 'o5', itemId: 'i5' },
          { orderId: 'o7', itemId: 'i7' },
        ],
        assignmentRule: 'fifo',
        pooled: true,
      }),
    )
    // 每一行**真的**被勾上（不是只改了计数文案）
    for (const orderNo of ['MG-0009', 'MG-0001', 'MG-0005', 'MG-0007']) {
      expect(screen.getByLabelText(`选择订单 ${orderNo}`)).toBeChecked()
    }
    expect(screen.getByTestId('pool-dispatch-batch')).not.toBeDisabled()
    // 加急行在插队区：**没有**勾选框（勾不到它，也就不会拿到 422 整批拒绝）
    expect(screen.queryByLabelText('选择订单 MG-URG-1')).toBeNull()
    expect(screen.getByText('MG-URG-1')).toBeInTheDocument()

    // 全选中 ⇒ 按钮变「取消全选」，点它清空（一键合并派单回到禁用）
    expect(screen.getByTestId('pool-select-all')).toHaveTextContent('取消全选')
    fireEvent.click(screen.getByTestId('pool-select-all'))
    await waitFor(() => expect(screen.getByLabelText('选择订单 MG-0009')).not.toBeChecked())
    expect(screen.getByLabelText('选择订单 MG-0007')).not.toBeChecked()
    expect(screen.getByTestId('pool-select-all')).toHaveTextContent('全选 4 单')
    expect(screen.getByTestId('pool-dispatch-batch')).toBeDisabled()
  })

  it('无成批候选 ⇒ 「全选」禁用（空批次不是有效动作）', async () => {
    mockGetBoard.mockResolvedValue(ok(board({ orderCount: 0, lineCount: 0, groups: [] })))

    render(<ProductionPoolPage />)
    const selectAll = await screen.findByTestId('pool-select-all')
    expect(selectAll).toBeDisabled()
  })

  it('超时未派告警：常驻只占**一行摘要**（逐单明细默认不在 DOM 里），点「查看明细」才展开、可收起', async () => {
    mockGetBoard.mockResolvedValue(
      ok(
        board({
          overdueCount: 2,
          warnings: [
            {
              orderId: 'o5',
              orderNo: 'MG-0005',
              waitHours: 120,
              message: '已超过最长等待 24 小时，请尽快成批或单独派单',
            },
            {
              orderId: 'o1',
              orderNo: 'MG-0001',
              waitHours: 30,
              message: '已超过最长等待 24 小时，请尽快成批或单独派单',
            },
          ],
        }),
      ),
    )

    render(<ProductionPoolPage />)
    const box = await screen.findByTestId('pool-warnings')

    // 摘要一行：条数 + 阈值 + 最久等待（数字全部来自服务端，前端只做格式化）
    expect(box).toHaveTextContent('2 单已超过最长等待 24 小时')
    expect(box).toHaveTextContent('最久已等 5 天')
    expect(screen.getByTestId('pool-status-overdue-count')).toHaveTextContent('2')

    // 🔴「不再占用大幅屏幕」的机械读数：默认折叠 ⇒ **逐单明细根本不在 DOM 里**
    expect(screen.queryByTestId('pool-warning-o5')).toBeNull()
    expect(screen.queryByTestId('pool-warning-o1')).toBeNull()

    // 展开 ⇒ 逐单明细：单号 / 已等待 / 服务端建议文案，一条不少
    fireEvent.click(screen.getByTestId('pool-warnings-toggle'))
    const warn = await screen.findByTestId('pool-warning-o5')
    expect(warn).toHaveTextContent('MG-0005')
    expect(warn).toHaveTextContent('5 天')
    expect(warn).toHaveTextContent('已超过最长等待 24 小时，请尽快成批或单独派单')
    expect(screen.getByTestId('pool-warning-o1')).toHaveTextContent('MG-0001')
    expect(screen.getByTestId('pool-warning-o1')).toHaveTextContent('1 天 6 小时')

    // 收起 ⇒ 明细消失（页面高度回到一行）
    fireEvent.click(screen.getByTestId('pool-warnings-toggle'))
    await waitFor(() => expect(screen.queryByTestId('pool-warning-o5')).toBeNull())
  })

  it('后端 `non_null` 序列化：缺席的键（到货日 / skuCode / warnings / urgentLines）按「未指定 / 空」渲染，不崩', async () => {
    // 后端 application.yml 配了 `default-property-inclusion: non_null` ⇒ 未指定的字段**整个键缺席**
    // （不是 `null`）⇒ 消费方必须把「缺席」与「null」当同一件事。本用例就是那个形态的桩。
    mockGetBoard.mockResolvedValue(
      ok({
        maxWaitHours: 24,
        poolingEnabled: false,
        orderCount: 1,
        lineCount: 1,
        overdueCount: 0,
        urgentCount: 0,
        // ⚠️ `warnings` / `urgentLines` 键**缺席**（不是空数组）
        groups: [
          {
            materialKey: '遮光布 / 米白 / 2.8m',
            productId: 'p1',
            orderCount: 1,
            requiredMeters: 10,
            lines: [
              {
                orderId: 'o1',
                orderNo: 'MG-0001',
                itemId: 'i1',
                productId: 'p1',
                productName: '遮光布',
                // ⚠️ `skuCode` / `requiredDeliveryDate` / `deliveryDaysLeft` 键**缺席**
                requiredMeters: 10,
                waitingSince: '2026-09-20T08:00:00+08:00',
                waitHours: 5,
                overdue: false,
                isUrgent: false,
              },
            ],
          },
        ],
      }),
    )

    render(<ProductionPoolPage />)
    const row = await screen.findByTestId('pool-line-o1')

    expect(row).toHaveTextContent('未指定') // 到货日缺席 ⇒ 未指定（不猜日期、不显示 undefined/NaN）
    expect(row).toHaveTextContent('不加急')
    expect(row).not.toHaveTextContent('undefined')
    expect(row).not.toHaveTextContent('NaN')
    // 键缺席 ⇒ 空态（不是崩溃、也不是把「没有」渲染成「有」）
    expect(screen.queryByTestId('pool-warnings')).toBeNull()
    expect(screen.getByText('当前没有加急待派订单')).toBeInTheDocument()
  })

  it('预览被拒（403/422）⇒ 拒绝文案在预览区可见（不静默留一个旧数字）', async () => {    mockPreview.mockRejectedValueOnce(new Error('没有权限执行此操作'))

    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-line-o9')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('选择订单 MG-0009'))

    await waitFor(() =>
      expect(screen.getByTestId('pool-preview-error')).toHaveTextContent('没有权限执行此操作'),
    )
    // 失败时不得残留上一次的米数（留着就是给商家一个假的「这批能省多少」）
    expect(within(screen.getByTestId('pool-preview')).queryByText('预计节省')).toBeNull()
  })
})
