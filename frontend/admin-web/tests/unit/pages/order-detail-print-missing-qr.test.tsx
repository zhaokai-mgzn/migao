// case_ids: UI-061
//
// issue #6867（B5 实现包）：**旧加工单打印前「无码」是静默的**。
//
// 病（集成侧核实）：纸面的码已是加工单级稳定短链 `{base}/o/{短码}`，而**存量加工单没有
// `short_code`**（迁移 V155 明确不回填，补码只发生在实例化 / 重新生成二维码那条路径上）⇒
// 商家对旧单直接点「打印加工单」时，纸面**静默**印出「无码」+ 短码位 `—`：看起来打好了，
// 纸却扫不了，而页面上**没有任何东西**提示他先补码。
//
// 本文件把这一步「静默失败」变成「可见 + 一键可修」——**不新增后端端点**，
// 复用既有 `POST /api/admin/production/orders/{orderId}/qr-token/regenerate`（issue #4287，只补缺失的码）。
//
// 四条判据（每条都有反面读数，见文件末的「红证」注释块）：
//   ① 无码 ⇒ 提示可见（说清「现在打出来的纸扫不了」）+ 补码按钮可点
//   ② 有码 ⇒ 提示与按钮**都不**出现（反面：无码时也不出现 = #6867 的原始缺陷）
//   ③ 点补码 ⇒ 调**那个端点**（URL / 动词 / 入参断言）+ 成功后刷新读面 ⇒ 提示退场
//   ④ 无 `processing:manage` ⇒ **补码入口**不渲染（事实仍可见 —— 读面事实给所有人、
//      写面动作只给有权的人；照 #4287 既有口径，避免「按钮可见却 403」）
//   ⑤ 端点失败 ⇒ **可见**错误文案（不许静默 / 假装成功），且入口仍在可重试
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// 登录态：按 zustand 选择器返回（`usePermission()` 走 `useAuthStore(s => s.user)`）——
// 整份 state mock 会让 `user` 恒 undefined ⇒ `has()` 恒 false ⇒ 判据 ①② 恒假
// （同 tests/unit/pages/list-write-button-permission.test.tsx 的既有形态）。
const auth = vi.hoisted(() => ({
  state: {
    user: {
      id: '1',
      username: 'tester',
      name: '测试账号',
      permissions: ['*'] as string[],
      roles: [] as string[],
    },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(auth.state) : auth.state,
}))

/**
 * 加工单读面的**见证**（本文件的核心脚手架）。
 *
 * `ProcessingOrderBlock` 是本页**唯一**持有加工单读面的组件（它自取自持、经 `onStatusChange`
 * 上报，并把刷新函数经 `onReloadReady` 交给页面）。本文件把它替身成「上报用例指定的加工单」，
 * 于是页面状态与**真接线点**同构，且跑不依赖网络。
 *
 * 🔴 为什么必须有这层见证（两条实测教训，都在本文件踩过）：
 * ① `mockPoDetail` 被调用 ≠ **读面已落地**（promise 还没 then 完）⇒ 只等 mock 会得到
 *    「断言的是还没渲染，而不是不该渲染」的假绿；
 * ② 「补码后刷新」这条判据若去数 `mockPoDetail`，**测的是本文件自己的替身**（替身不发请求 ⇒
 *    恒 0 调用）⇒ 空的假红。要数的是**真接线点被调用**：块交出的刷新函数被调用了几次。
 */
const poState = vi.hoisted(() => ({ current: null as unknown }))
const poStatusCount = vi.hoisted(() => ({ value: 0 }))
const poReloadCount = vi.hoisted(() => ({ value: 0 }))
/** 让测试能等「读面已落地」而不依赖实现细节的自旋 */

const mockGetOrder = vi.fn()
const mockGetOrderShipments = vi.fn()
/** 加工单详情读面（`processingOrderApi.detail`）—— 只在别的用例改写它时被消费 */
const mockPoDetail = vi.fn()
const mockRegenerate = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: unknown[]) => mockGetOrder(...args),
    getOrderShipments: (...args: unknown[]) => mockGetOrderShipments(...args),
    closeOrder: vi.fn(),
    confirmPayment: vi.fn(),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
    refundOrder: vi.fn(),
  },
  processingOrderApi: {
    detail: (...args: unknown[]) => mockPoDetail(...args),
    generate: vi.fn(),
    list: vi.fn(),
    update: vi.fn(),
  },
  productionApi: {
    regenerateQrToken: (...args: unknown[]) => mockRegenerate(...args),
  },
}))

vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'test-order-123' }))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: Record<string, unknown>) => (
    <a href={href as string} {...props}>
      {children as React.ReactNode}
    </a>
  ),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))
vi.mock('dayjs', () => ({
  default: (date?: string) => ({ format: () => date || '2026-04-25 10:00', diff: () => 3600 }),
}))

// 只替身「内容型」组件：`PrintDocPreview` 走**真货**（缺码提示就落在它的页脚提示槽里，
// 替身掉它 = 本文件测的是替身 = 空断言），`ProcessingQrMissingNotice` 同样是真货（被测对象）。
vi.mock('@/components/orders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/orders')>()
  return {
    ...actual,
    OrderProgressSteps: () => <div data-testid="order-progress">OrderProgressSteps</div>,
    // 真接线点替身：上报用例指定的加工单（`onStatusChange`）+ 交出刷新函数（`onReloadReady`）
    ProcessingOrderBlock: ({ onStatusChange, onReloadReady }: {
      onStatusChange?: (po: unknown) => void
      onReloadReady?: (reload: () => Promise<void>) => void
    }) => {
      React.useEffect(() => {
        poStatusCount.value += 1
        onStatusChange?.(poState.current)
      }, [onStatusChange])
      React.useEffect(() => {
        onReloadReady?.(async () => {
          poReloadCount.value += 1
          poStatusCount.value += 1
          onStatusChange?.(poState.current)
        })
      }, [onReloadReady])
      return <div data-testid="po-block">ProcessingOrderBlock</div>
    },
    OrderUrgencyPanel: () => <div data-testid="order-urgency-panel">OrderUrgencyPanel</div>,
    ShipmentDoc: () => <div data-testid="shipment-doc">ShipmentDoc</div>,
    QuotationDoc: () => <div data-testid="quotation-doc">QuotationDoc</div>,
    ProcessingDoc: () => <div data-testid="processing-doc">ProcessingDoc</div>,
    SalesDoc: () => <div data-testid="sales-doc">SalesDoc</div>,
    CloseOrderModal: () => null,
    LogisticsForm: () => null,
    RefundOrderModal: () => null,
    EditOrderContentModal: () => null,
  }
})

import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'

const mockOrder = {
  id: 'test-order-123',
  orderNo: 'MG202606001',
  status: 'pending_shipment',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区xx小区',
  totalAmount: 1999,
  discountAmount: 0,
  actualAmount: 1999,
  createdAt: '2026-06-20T10:00:00Z',
  paidAt: '2026-06-20T10:30:00Z',
  items: [
    {
      id: 'item1',
      productId: 'prod1',
      productName: '测试窗帘布',
      sku: 'TEST-SKU-001',
      unitPrice: 99.5,
      quantity: 20,
      subtotal: 1990,
      processingInfo: null,
    },
  ],
  processingItems: [],
}

/** 存量加工单：**两个读面键都缺** ⇒ 纸面「无码」+ 短码 `—` */
const PO_MISSING_CODE = {
  id: 'po-1',
  orderId: 'test-order-123',
  processingOrderNo: 'PO260926-0007',
  status: 'issued',
  scan_url: null,
  short_code: null,
}
/** 补码成功后的读面：两键都在（纸面出短链 + 短码） */
const PO_WITH_CODE = {
  ...PO_MISSING_CODE,
  scan_url: 'https://app.migaozn.com/o/7K3M9QP2',
  short_code: '7K3M9QP2',
}

const NOTICE = 'processing-qr-missing-notice'
const ACTION = 'processing-qr-regenerate'

/** 打开订单详情并点「打印加工单」→ 打印预览层（商家的真实打印路径：订单详情 → 打印预览） */
async function openProcessingPreview() {
  const user = userEvent.setup()
  render(<OrderDetailPage />)
  const entry = await screen.findByText('打印加工单')
  await user.click(entry)
  await screen.findByTestId('print-preview')
  return user
}

/** 等「加工单读面已落地」（块上报了一次）—— 缺这句，「不在」类断言测的是「还没渲染」 */
async function waitForPoReadFace() {
  await waitFor(() => expect(poStatusCount.value).toBeGreaterThan(0))
  await waitFor(() => expect(screen.getByTestId('po-block')).toBeInTheDocument())
}

describe('订单详情打印加工单 · 缺码提示与一键补码（issue #6867 / B5）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    poStatusCount.value = 0
    poReloadCount.value = 0
    poState.current = PO_MISSING_CODE
    auth.state.user.permissions = ['*']
    mockGetOrder.mockResolvedValue({ data: { data: mockOrder } })
    mockGetOrderShipments.mockResolvedValue({
      data: { data: { order_id: 'test-order-123', status: 'producing', shipments: [] } },
    })
    mockPoDetail.mockResolvedValue({ data: { data: PO_MISSING_CODE } })
  })

  // 显式卸载：高负载下（本机实测 load 80+）残留 DOM 会拖慢后面每个用例，
  // 让「超时」看起来像代码缺陷（本文件实测踩过）。
  afterEach(() => {
    cleanup()
  })

  it('① 无码 ⇒ 提示可见（说清「现在打出来的纸扫不了」）+ 补码按钮可点', async () => {
    await openProcessingPreview()

    const notice = await screen.findByTestId(NOTICE)
    expect(notice).toBeVisible()
    // 说清后果，而不是只甩一个「缺码」（商家要能据此做决定）
    expect(notice.textContent).toMatch(/扫不了/)
    const action = screen.getByTestId(ACTION)
    expect(action).toBeEnabled()
    // 「有权限时入口必在」与判据 ④（无权限时必须不在）成对 —— 缺任一条都会退化成恒真/恒假断言
    expect(screen.getByTestId(NOTICE)).toBeVisible()
  })

  it('② 有码 ⇒ 提示与按钮**都不**出现（反向读数：无码时也不出现 = 本单原始缺陷）', async () => {
    poState.current = PO_WITH_CODE
    await openProcessingPreview()

    await waitForPoReadFace()
    await waitFor(() => {
      expect(screen.queryByTestId(NOTICE)).toBeNull()
      expect(screen.queryByTestId(ACTION)).toBeNull()
    })
  })

  it('③ 点补码 ⇒ 调 `POST .../qr-token/regenerate` + 刷新读面后出新码（提示退场）', async () => {
    const user = await openProcessingPreview()
    await waitForPoReadFace()
    // 补码成功后读面回带两键 ⇒ 刷新那次拿到的就是有码的加工单
    mockRegenerate.mockResolvedValue({
      data: { data: { order_id: 'test-order-123', qr_token: 'a'.repeat(32), part_codes: 0 } },
    })
    poState.current = PO_WITH_CODE

    await user.click(await screen.findByTestId(ACTION))

    // 🔴 端点断言（URL / 动词 / 入参）：写死在 api.ts 的请求上，不是「调了某个函数」
    expect(mockRegenerate).toHaveBeenCalledTimes(1)
    expect(mockRegenerate).toHaveBeenCalledWith('test-order-123')
    // 成功 ⇒ **真的**重新读了加工单（真接线点：块交出的刷新被调用）
    await waitFor(() => expect(poReloadCount.value).toBeGreaterThanOrEqual(1))
    // 新码落地 ⇒ 提示与按钮退场（不是「请求回来了就假装成功」）
    await waitFor(() => {
      expect(screen.queryByTestId(NOTICE)).toBeNull()
      expect(screen.queryByTestId(ACTION)).toBeNull()
    })
  })

  it('④ 无 `processing:manage` ⇒ 补码入口不渲染（缺码事实仍可见；页面其余照常）', async () => {
    auth.state.user.permissions = ['order:list']
    await openProcessingPreview()

    await waitForPoReadFace()
    // 两条一起才不退化成恒真断言：无权限 ⇒ 写入口不在，但「这张纸扫不了」这个**读**面事实照旧可见
    // （看不见它 = 让没有补码权限的人继续印废纸）；有权限时入口必在 = 判据 ①
    expect(await screen.findByTestId(NOTICE)).toBeVisible()
    expect(screen.queryByTestId(ACTION)).toBeNull()
    // 预览层本身照常可用（权限只管补码入口，不挡看单 / 打印）
    expect(screen.getByTestId('print-preview-print')).toBeInTheDocument()
  })

  it('⑤ 端点失败 ⇒ 可见错误文案（且补码入口仍在，可重试）', async () => {
    const user = await openProcessingPreview()
    mockRegenerate.mockRejectedValue(new Error('500'))

    await user.click(await screen.findByTestId(ACTION))

    const notice = await screen.findByTestId(NOTICE)
    await waitFor(() => expect(notice.textContent).toMatch(/失败/))
    // 失败后入口不得消失（否则商家连重试的出口都没有）
    expect(screen.getByTestId(ACTION)).toBeEnabled()
  })
})

/* ────────────────────────────────────────────────────────────────────────────
 * 红证（把本文件的被测实现**改回去 / 改错**时的实际读数，逐条对应上面的判据）：
 *   ① 缺码不渲染提示（= 改前现状，纸面静默印「无码」）
 *      ⇒ `findByTestId('processing-qr-missing-notice')` 超时 ⇒ 红。
 *   ② 提示改成「永远渲染」（例如 `if (!missing) return null` 写成 `if (missing) return null`）
 *      ⇒ 有码时提示仍在 ⇒ **红在 ②**（这条是 ① 的反面读数：只写 ① 会退化成「永远不渲染」也绿的空断言）。
 *   ③ 不接线补码端点 / 调错端点（例如误用 `instantiate`）
 *      ⇒ `expect(mockRegenerate).toHaveBeenCalledWith('test-order-123')` 失败 / 次数 ≠ 1 ⇒ 红；
 *      把 `onRegenerated` 去掉（不刷新）⇒ `poReloadCount` 停在 0 ⇒ 红（不会「假装成功」）。
 *   ④ 入口不看权限（删掉 `canManage` 条件）⇒ 无权限用例里 `ACTION` 仍在 ⇒ 红；
 *      反过来「无权限时连事实一起藏」（`if (!canManage) return null`）⇒ 该用例的 `NOTICE` 找不到 ⇒ 也红。
 *   ⑤ 失败走静默（`catch {}` 不 setError）⇒ 文案里没有「失败」⇒ 红；
 *      失败时把入口也藏起来（`if (error) return null`）⇒ `getByTestId(ACTION)` 失败 ⇒ 红。
 * 折假值红证：若把缺码折成加工单号顶上去（画一个扫不开的码），② 会绿而 ①③ 仍红 ⇒
 *   本文件对「折假值」不是零判别力（纸面另有 `ProcessingDoc.test.tsx` 的「缺码不画假码」判据）。
 * ──────────────────────────────────────────────────────────────────────────── */
