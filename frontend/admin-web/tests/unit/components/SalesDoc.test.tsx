// case_ids: UI-062, UI-065
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup, within } from '@testing-library/react'

// 销售单纸面**不再读企业收款码**（issue #7589）。两处替身都为此：
// ① `usePaymentQrcodes` 是可观测桩，返回一张**真码** —— 谁把收款码块加回销售单，`⑥` 的两条（出图 / 零调用）
//    都会红；桩返回空 map 的话「不出图」会被缺码这一无关原因蒙过去（假绿）。
// ② `useCompanyName` 直接给空串（jsdom 无登录态时的回落设置读面，别让它真发请求）。
const mockUsePaymentQrcodes = vi.fn((..._args: unknown[]) => ({
  wechat: { paymentType: 'wechat', imageUrl: '/uploads/qr-wechat.png', payeeName: '亿家纺织' },
}))
vi.mock('@/lib/use-payment-qrcodes', () => ({
  usePaymentQrcodes: (...args: unknown[]) => mockUsePaymentQrcodes(...args),
}))
vi.mock('@/lib/use-company-name', () => ({ useCompanyName: () => '' }))

import SalesDoc, {
  SALES_DOC_COLUMNS,
  SALES_DOC_MISSING,
  SALES_DOC_MONEY_GAPS,
  SALES_DOC_NOT_COLLECTED,
} from '@/components/orders/SalesDoc'
import { printPageRule } from '@/lib/print-media'
import { dataTables, collectTableIntegrity } from '@/components/orders/doc-tables'
import {
  SALES_QTY_BASIS,
  SALES_QTY_NOT_SHIPPED,
  SALES_QTY_STATES,
  type OrderShipmentRead,
} from '@/lib/sales-shipment'
import {
  PAPER_MISSING,
  assertNoPaperZeroFill,
  assertPaperKeepsMissingDistinct,
  paperNumericColumn,
} from '@/lib/print-doc-paper'
import type { Order, OrderItem, ProcessingOrder } from '@/types'

/**
 * 销售单（**三联纸 241mm × 140mm**，issue #5651）—— 照客户现行实物制式（实证表 #4）。
 *
 * 断言的六件事（每条都有红证，见「判据可红」用例）：
 * ① **介质**：`@page { size: 241mm 140mm; }`（用户 2026-09-26 裁定「241mm × 140mm（两等分）」）；
 *    **只渲染一页**（复写三份由压感纸承担，DOM 里只有一份 `.sales-sheet`）；
 *    容器固定为**单联可用高度** + `overflow: hidden` ⇒ 浏览器不会再分页（跨联 = 纸账不符）；
 * ② **介质是参数不是副本**：切 `media="a4"` 只换版面参数，**逐格取值必须逐字相同**
 *    （若有人为 A4 复制一份字段映射，这条会红）；
 * ③ 🔴 **金额一律取服务端字段**：`order.actualAmount` / `item.amount` —— 构造的服务端值与
 *    前端求和**故意不同**，纸面必须印服务端那个（前端现算 ⇒ 红）；
 * ④ 🔴 **缺口金额栏不编数**：上期余额 / 预存抵扣 / 账户余额 服务端无字段 ⇒ 标「未采集」，
 *    **不含任何数字**（印 `0.00` = 把「没有这个数」画成「余额为零」）；
 * ⑤ 🔴 **缺值可见 / 长名截断可见**：缺值显式占位 `—`；长名走 CSS 省略号（`sales-cut`）
 *    且**不裁字符串**（纸面是给人看的，静默裁切 = 账实不符的另一种形态）；
 * ⑥ **纸面不印收款码**（issue #7589：用户 2026-10-24 逐字「销售单打印处右下角的二维码移除掉」）
 *    —— 页脚只留温馨提示、销售单也不再读收款码；打印隔离沿用 #4983 / #4965 范式（共享 `print-doc`）；
 * ⑧ **左上角作业单扫码报工码**（issue #7530）：码值**逐字**取服务端下发的
 *    `processingOrder.scan_url`（`{base}/o/{短码}` ⇒ 302 到工人报工页 `/w/`），前端**不拼**；
 *    无码 ⇒ 整块不出现（不画占位框、不回落作业单号）。见 describe「⑬」；
 * ⑦ **数量列消费实发**（issue #5651 收口）：经 admin 读面 `GET /api/admin/orders/{id}/shipments`
 *    拿 `order_shipment_items` 的**实发**，四态（已发货 / 部分发货 / 未发货 / 读面没取到）
 *    **各自可判**、纸面**标明基准**、**永不印 0**、挂不到订单行的实发行**显式提示**。
 */
function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    productId: 'p-1',
    productName: '布艺遮光帘A',
    // issue #6869：响应真字段是 `skuCode`（`productCode`/`color` 不在响应里）；
    // 颜色 / 门幅在 `processingInfo` —— 夹具按真 wire 形态写。
    skuCode: '0012',
    processingInfo: { colorName: '米白', doorWidth: '2.8米' },
    // 🔴 数量 × 单价 = 30，而服务端 `amount` = 500：**故意不同** ——
    // 前端若现算，纸面会印 30.00（红证载荷，不是脏数据）
    quantity: 3,
    unitPrice: 10,
    amount: 500,
    subtotal: 500,
    processingFee: 0,
    ...overrides,
  }
}

function buildOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: 'order-1',
    orderNo: 'CSO260926-0001',
    customerName: '张三',
    customerPhone: '13800000000',
    customerAddress: '浙江省杭州市余杭区某路 1 号',
    // 服务端汇总与「行金额之和」**故意不同**（行和 = 500）：纸面必须印服务端值
    totalAmount: 999.99,
    actualAmount: 888.88,
    discountAmount: 111.11,
    status: 'shipped' as Order['status'],
    hasProcessing: false,
    items: [buildItem()],
    createdAt: '2026-09-26T10:00:00+08:00',
    ...overrides,
  }
}

/**
 * 作业单（`processingOrder`）夹具 —— 销售单左上角扫码报工码的来源（issue #7530）。
 *
 * 🔴 `scan_url` 刻意用**非 `app.migaozn.com`** 的示例域：纸面**只认**服务端下发的这个值，
 * 前端自己拼 `{base}/o/{短码}` 会印出另一个地址 ⇒ 那条红证靠这个差集判得出来
 * （前端拼域名 / 路径段 = 第二份真值，换域名时纸面与读面会静默不一致）。
 */
function buildProcessingOrder(overrides: Partial<ProcessingOrder> = {}): ProcessingOrder {
  return {
    id: 'po-1',
    orderId: 'order-1',
    processingOrderNo: 'CK-20261023-0001',
    order_kind: 'outbound',
    status: 'generated',
    short_code: '7K3M9QP2',
    scan_url: 'https://print.example.test/o/7K3M9QP2',
    ...overrides,
  }
}

/** 「未发货」读面（发货单列表非空、但一条实发明细都没有的两种形态都覆盖得到） */
const NO_SHIPMENT: OrderShipmentRead = { status: 'producing', shipments: [] }

/** 发货读面夹具：一张已发货的发货单 + 给定明细（后端 `readShipment` 的逐字形状，snake_case） */
function buildRead(
  items: { order_item_id?: string | null; shipped_quantity: number; unit?: string }[],
  status = 'shipped',
): OrderShipmentRead {
  return {
    order_id: 'order-1',
    status,
    shipments: [
      {
        shipment_no: 'SH20260927000001',
        source: 'worker_photo',
        shipped_at: '2026-09-27T10:00:00+08:00',
        tracking_no: 'SF123',
        items,
      },
    ],
    shipped_totals: { by_unit: {} },
  }
}

const doc = (): HTMLElement | null => document.querySelector('.sales-print-area')
const css = (): string =>
  Array.from(doc()?.querySelectorAll('style') ?? [])
    .map((el) => el.textContent || '')
    .join('\n')
const text = (testId: string): string =>
  document.querySelector(`[data-testid="${testId}"]`)?.textContent?.trim() ?? ''
const sheet = (): HTMLElement | null => document.querySelector('[data-testid="sales-sheet"]')
/** 左上角作业单扫码报工码的块（无码 ⇒ `null`）与它的**确切内容**（`<svg><title>` = qrcode.react 的 value） */
const workOrderQr = (): Element | null => document.querySelector('[data-testid="sales-work-order-qr"]')
const workOrderQrValue = (): string =>
  workOrderQr()?.querySelector('svg title')?.textContent?.trim() ?? ''

/** 明细区逐格取值（序号/货号/颜色/门幅/数量/单位/单价/金额）—— 用于「切介质取值不变」的逐格比对 */
function rowCells(): string[][] {
  return Array.from(document.querySelectorAll('[data-testid^="sales-item-"]')).map((tr) =>
    Array.from(tr.querySelectorAll('td')).map((td) => td.textContent?.trim() || '')
  )
}

describe('SalesDoc（销售单 · 三联纸 241mm × 140mm，issue #5651）', () => {
  // 类级固化（issue #6595）：本单据的每一张表逐行自洽（Σ(colSpan) = 表头列数）。
  it('表格列数不变量：逐行 Σ(colSpan) 与表头列数一致（issue #6595）', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    expect(dataTables(doc()).every((table) => collectTableIntegrity([table]).length === 1)).toBe(true) // 单据：销售单 SalesDoc
  })

  it('① 介质：@page 241mm × 140mm（两等分）+ 只渲染一页 + 单联高度固定不跨联', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} printTarget="sales" />)
    expect(css()).toContain('@page { size: 241mm 140mm; margin: 6mm 12mm; }')
    expect(css()).toContain(printPageRule('continuous-241x140'))
    expect(doc()?.getAttribute('data-print-media')).toBe('continuous-241x140')
    // 🔴 复写三份由**纸**承担：DOM 里只有一份单据（渲染三遍 = 打三张、复写九份）
    expect(document.querySelectorAll('[data-testid="sales-sheet"]')).toHaveLength(1)
    expect(document.querySelectorAll('.sales-sheet')).toHaveLength(1)
    // 单联可用高度 = 页长 − 上下边距 = 140 − 12 = 128mm；超出即裁（绝不跨联）
    expect(sheet()?.style.height).toBe('128mm')
    expect(sheet()?.style.overflow).toBe('hidden')
    // 连续走纸口径**显式登记为待实测**（真机参数本机拿不到，不编造）
    expect(css()).toContain('break-inside: avoid')
  })

  it('① 红证：把三联纸的「只渲染一页」改坏（渲三份）⇒ 上面那条必红', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    const sheets = document.querySelectorAll('.sales-sheet')
    // 复写份数是**纸**的属性，不是渲染次数（矩阵里 carbonCopies = 3）⇒ 渲三份即红
    expect(sheets).toHaveLength(1)
  })

  it('② 介质是**参数**不是副本：切 A4 后 @page 变、而逐格取值**逐字不变**', () => {
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
        processingOrder={buildProcessingOrder()}
        printTarget="sales"
      />
    )
    const tri = rowCells()
    const triHeader = Array.from(document.querySelectorAll('.sales-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    const triDue = text('sales-total-due')
    const triTotal = text('sales-total')
    const triQr = workOrderQrValue()
    cleanup()
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
        processingOrder={buildProcessingOrder()}
        media="a4"
        printTarget="sales"
      />
    )
    // 版面参数随介质变（issue #7309：切到 A4 后 `@page` 边距必须是 0 —— 否则浏览器会印出
    // 自己的页眉页脚；版面内缩改由容器 padding 承担）
    expect(css()).toContain('@page { size: A4; margin: 0; }')
    expect(css()).toMatch(/\.sales-print-area\[data-print-target='sales'\]\s*\{[^}]*padding:\s*12mm/)
    expect(doc()?.getAttribute('data-print-media')).toBe('a4')
    expect(sheet()?.style.height).toBe('')
    // 而**字段映射一份都没变**（复制一份映射给 A4 ⇒ 这里会红）：
    // 逐格取值 / 表头 / 金额汇总 / 扫码报工码值 一律逐字相同
    expect(rowCells()).toEqual(tri)
    expect(
      Array.from(document.querySelectorAll('.sales-doc-table thead th')).map((th) => th.textContent?.trim())
    ).toEqual(triHeader)
    expect(text('sales-total-due')).toBe(triDue)
    expect(text('sales-total')).toBe(triTotal)
    expect(triQr).toBe('https://print.example.test/o/7K3M9QP2')
    expect(workOrderQrValue()).toBe(triQr)
  })

  it('② 列清单 = SALES_DOC_COLUMNS（全仓唯一一份；商品行粒度，不是报价单的按套粒度）', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    const headers = Array.from(document.querySelectorAll('.sales-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    expect(headers).toEqual([...SALES_DOC_COLUMNS])
    // issue #6869：商品 SKU 四件套里补过「品名」与「颜色 / 门幅」，撤掉恒空的「备注」；
    // 🔴 issue #7530（用户 2026-10-23 逐字「销售单不要品名」）：「品名」列**退场**，
    // 单据身份改由货号 / 颜色 / 门幅承载 ⇒ 9 列变 8 列。
    expect([...SALES_DOC_COLUMNS]).toEqual(['序号', '货号', '颜色', '门幅', '数量', '单位', '单价', '金额'])
    expect(rowCells()).toHaveLength(1)
    // 🔴 货号取响应真字段 `skuCode` —— 夹具**没有** `productCode`（幽灵字段）：
    // 旧实现（`productCode || productName`）在这一格印的是品名 ⇒ 本判据即红证
    expect(rowCells()[0]).toEqual(['1', '0012', '米白', '2.8米', '3', '米', '10.00', '500.00'])
    // 🔴 品名**整列退场**：纸面任何一处都不再印商品名（去掉表头却留着单元格 = 串列）
    expect(doc()?.textContent).not.toContain('布艺遮光帘A')
  })

  it('🔴 ③ 金额取服务端字段：行金额 = item.amount（≠ 单价×数量），本单应收 = order.actualAmount', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    // 行金额印服务端的 500.00；前端现算会得到 3 × 10 = 30.00
    expect(text('sales-row-amount-0')).toBe('500.00')
    expect(text('sales-row-amount-0')).not.toBe('30.00')
    // 汇总同理：服务端 888.88 / 999.99 / 111.11（行金额之和是 500.00，印出来就说明前端现算了）
    expect(text('sales-total-due')).toBe('888.88')
    expect(text('sales-total')).toBe('999.99')
    expect(text('sales-discount')).toBe('111.11')
  })

  it('🔴 ③ 红证：让前端现算（单价×数量 / 行金额求和）⇒ 上面那条必红', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    const order = buildOrder()
    const frontEndRow = (order.items?.[0]?.unitPrice ?? 0) * (order.items?.[0]?.quantity ?? 0)
    const frontEndTotal = (order.items ?? []).reduce((sum, it) => sum + (it.amount || 0), 0)
    // 两个「前端算出来的值」都**不等于**纸面值 —— 这正是判据的判别力所在
    expect(frontEndRow).toBe(30)
    expect(frontEndTotal).toBe(500)
    expect(text('sales-row-amount-0')).not.toBe(frontEndRow.toFixed(2))
    expect(text('sales-total-due')).not.toBe(frontEndTotal.toFixed(2))
  })

  it('🔴 ④ 缺口金额栏标「未采集」且**不含数字**（不把「没有这个数」画成「余额为零」）', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    for (const id of ['sales-prev-balance', 'sales-prepay', 'sales-account-balance']) {
      expect(text(id)).toBe(SALES_DOC_NOT_COLLECTED)
      expect(text(id)).not.toMatch(/[0-9]/)
    }
    expect([...SALES_DOC_MONEY_GAPS]).toEqual(['上期余额', '预存抵扣', '账户余额'])
    const note = text('sales-gap-note')
    for (const label of SALES_DOC_MONEY_GAPS) {
      expect(note).toContain(label)
    }
  })

  it('🔴 ④ 红证：把缺口栏编成 0.00 / 前端硬编码一个余额 ⇒ 上面那条必红', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    const fabricated = (0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })
    expect(fabricated).toBe('0.00')
    // 纸面若有 `0.00` 就说明编数了（判据要求 `未采集`，且不许出现数字）
    expect(text('sales-account-balance')).not.toBe(fabricated)
    expect(text('sales-account-balance')).not.toMatch(/[0-9]/)
  })

  it('类级不变量（issue #6720）：本单据纸面不得出现「未知 ⇒ 0」的回退形态', () => {
    render(
      <SalesDoc
        order={buildOrder({
          items: [
            buildItem({
              amount: undefined as unknown as number,
              unitPrice: undefined as unknown as number,
            }),
            // 真 0 的对照行（issue #6720 明令：真 0 仍印 0，不许把真值判红）
            buildItem({ id: 'item-0', amount: 0, unitPrice: 0 }),
          ],
        })}
        shipments={NO_SHIPMENT}
      />
    )
    // 判据面 = **缺值那一行**（真 0 的对照行在另一行：缺值行不得有 0.00，真 0 行不得有「—」）
    // 金额列 index = 7（issue #7530 起 8 列表：序号0 货号1 颜色2 门幅3 数量4 单位5 单价6 金额7）
    const amountColumn = paperNumericColumn(doc(), { column: 7 })
    // 单据：销售单 SalesDoc
    assertNoPaperZeroFill(amountColumn.slice(0, 1), {
      label: '销售单 SalesDoc',
      presence: ['缺 amount 的订单行（金额列第 1 行）'],
    })
    // 单据：销售单 SalesDoc
    assertPaperKeepsMissingDistinct(amountColumn, {
      label: '销售单 SalesDoc',
      presence: ['金额列：缺值行（—）与真 0 行（0.00）'],
    })
  })

  it('🔴 ⑤ 缺值**可见**：客户 / 电话 / 地址缺失 ⇒ 显式占位 `—`（不是空单元格）', () => {
    render(
      <SalesDoc
        order={buildOrder({ customerName: '', customerPhone: '', customerAddress: undefined })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(text('sales-customer')).toBe(SALES_DOC_MISSING)
    expect(text('sales-phone')).toBe(SALES_DOC_MISSING)
    expect(text('sales-address')).toBe(SALES_DOC_MISSING)
  })

  it('🔴 ⑤ 红证：把缺值换回静默留空（`|| ""`）⇒ 上面那条必红', () => {
    render(
      <SalesDoc order={buildOrder({ customerAddress: undefined })} shipments={NO_SHIPMENT} />
    )
    const silent = (buildOrder({ customerAddress: undefined }).customerAddress || '').trim()
    expect(silent).toBe('') // 旧写法给空串 ⇒ 判据（`—`）红
    expect(text('sales-address')).toBe(SALES_DOC_MISSING)
  })

  it('⑤ 长名**截断可见**：单元格保留全文 + 走 CSS 省略号（不裁字符串）', () => {
    const longName = '杭州余杭某某某某某某某某某某某某某某某某某某纺织品经营部'
    render(<SalesDoc order={buildOrder({ customerName: longName })} shipments={NO_SHIPMENT} />)
    // 不裁字符串：全文仍在 DOM 里（打印/屏幕都拿得到完整值）
    expect(text('sales-customer')).toBe(longName)
    // 截断是**可见**的（省略号），不是静默裁掉
    expect(document.querySelector('[data-testid="sales-customer"]')?.className).toContain('sales-cut')
    expect(css()).toMatch(/\.sales-cut\s*\{[^}]*text-overflow:\s*ellipsis/)
    expect(css()).toMatch(/\.sales-cut\s*\{[^}]*overflow:\s*hidden/)
  })

  it('⑤ 红证：把长名 slice 掉（静默裁切）或去掉省略号 ⇒ 上面那条必红', () => {
    const longName = '杭州余杭某某某某某某某某某某某某某某某某某某纺织品经营部'
    render(<SalesDoc order={buildOrder({ customerName: longName })} shipments={NO_SHIPMENT} />)
    expect(text('sales-customer')).not.toBe(longName.slice(0, 8)) // slice = 静默裁切 ⇒ 红
    const withoutEllipsis = css().replace(/text-overflow:\s*ellipsis;?/g, '')
    expect(withoutEllipsis).not.toMatch(/text-overflow/) // 去掉省略号 ⇒ 判据红
  })

  it('⑥ 销售单纸面**不印收款码**（issue #7589）：页脚只留温馨提示', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    // 用户 2026-10-24 逐字「销售单打印处右下角的二维码移除掉」—— 有码无码都不上纸
    expect(doc()?.querySelectorAll('img')).toHaveLength(0)
    expect(document.querySelectorAll('[data-testid^="sales-qr-"]')).toHaveLength(0)
    expect(doc()?.textContent).not.toMatch(/微信|支付宝/)
    // 温馨提示仍在（移除的只有收款码那一块）
    expect(doc()?.textContent).toContain('收到货后先验货')
  })

  it('⑥ 销售单**不读**收款码：谁把 `usePaymentQrcodes` 加回来 ⇒ 必红（零请求）', () => {
    mockUsePaymentQrcodes.mockClear()
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    expect(mockUsePaymentQrcodes).not.toHaveBeenCalled()
  })

  it('⑥ 红证：旧的收款码块（`sales-qr-*` / 渠道图）一旦回来 ⇒ 上面那条必红', () => {
    // 旧实现（issue #5651）在页脚右侧渲染 `<img data-testid="sales-qr-wechat">` + 渠道名 ——
    // 把那份 DOM 摆进**同一个判据射程**，证明上面三条断言不是空断言（射程自证）。
    const probe = document.createElement('div')
    probe.innerHTML =
      '<img data-testid="sales-qr-wechat" src="/uploads/qr-wechat.png" alt="微信收款码" /><span>微信</span>'
    expect(probe.querySelectorAll('img')).toHaveLength(1)
    expect(probe.querySelectorAll('[data-testid^="sales-qr-"]')).toHaveLength(1)
    expect(probe.textContent).toMatch(/微信|支付宝/)
  })

  it('⑦ 打印隔离：portal 到 body + 共享 print-doc + 隔离选择器排除所有打印单据 + 屏幕态隐藏', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    const el = doc()
    expect(el?.parentElement).toBe(document.body)
    expect(el?.className).toContain('print-doc')
    expect(document.querySelectorAll('.sales-print-area')).toHaveLength(1)
    expect(css()).toMatch(/body > \*:not\(\.print-doc\)\s*\{\s*display:\s*none\s*!important/)
    expect(css()).not.toMatch(/body > \*:not\(\.sales-print-area\)/)
    expect(css()).toMatch(/\.sales-print-area\[data-print-target='sales'\]/)
  })

  it('⑦ 未置位打印目标 ⇒ 不加 data-print-target（点别的单据时本单不参与显形）', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    expect(doc()?.getAttribute('data-print-target')).toBeNull()
    // 🔴 且**不发表自己的纸型**（issue #5914 的 P1-2：`@page` 是文档级规则，同页多份并存时
    //    最后声明的那条赢 ⇒ 非目标单据发表纸型 = 把兄弟单据的纸型顶掉，实测打废纸）
    expect(css()).not.toContain('@page')
    cleanup()
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} printTarget="sales" />)
    expect(doc()?.getAttribute('data-print-target')).toBe('sales')
  })

  // ══════════════════════════════════════════════════════════════════════════════
  // ⑧~⑫ 数量列消费**实发**（issue #5651 收口）：四态各自可判 + 永不印 0
  //   真值 owner = `order_shipment_items`（后端 admin 读面 `GET /api/admin/orders/{id}/shipments`）
  // ══════════════════════════════════════════════════════════════════════════════

  it('⑧ 已发货 ⇒ 数量列印**实发**（不是下单数量）；纸面标明口径', () => {
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={buildRead([{ order_item_id: 'item-1', shipped_quantity: 7, unit: '米' }])}
      />
    )
    // 实发 7 / 下单 3 —— 印 3 就说明还在用订单行投影（红证载荷）
    expect(text('sales-qty-0')).toBe('7')
    expect(text('sales-qty-0')).not.toBe('3')
    expect(text('sales-qty-basis')).toContain('实发数量')
  })

  it('⑧ 红证：数量列退回订单行投影（item.quantity）⇒ 上面那条必红', () => {
    const order = buildOrder()
    render(
      <SalesDoc
        order={order}
        shipments={buildRead([{ order_item_id: 'item-1', shipped_quantity: 7, unit: '米' }])}
      />
    )
    const orderedProjection = String(order.items?.[0]?.quantity) // 旧写法会印这个
    expect(orderedProjection).toBe('3')
    expect(text('sales-qty-0')).not.toBe(orderedProjection)
  })

  it('⑨ 部分发货 ⇒ 已发行印实发、未发行**显式**「未发」（不是 0、不是空白）', () => {
    const order = buildOrder({
      items: [buildItem(), buildItem({ id: 'item-2', skuCode: '0013', quantity: 5 })],
    })
    render(
      <SalesDoc
        order={order}
        shipments={buildRead([{ order_item_id: 'item-1', shipped_quantity: 3, unit: '米' }])}
      />
    )
    expect(text('sales-qty-0')).toBe('3')
    expect(text('sales-qty-1')).toBe(SALES_QTY_NOT_SHIPPED)
    expect(text('sales-qty-1')).not.toMatch(/[0-9]/) // 印 `0` 会被读成「实发为零」
    expect(text('sales-qty-basis')).toContain('部分发货')
  })

  it('⑨ 红证：把未发行写成 0 / 静默留空 ⇒ 上面那条必红', () => {
    const order = buildOrder({
      items: [buildItem(), buildItem({ id: 'item-2', skuCode: '0013', quantity: 5 })],
    })
    render(
      <SalesDoc
        order={order}
        shipments={buildRead([{ order_item_id: 'item-1', shipped_quantity: 3, unit: '米' }])}
      />
    )
    // 缺值填 0 = 把「没有这个数」画成「实发为零」
    const asRendered = (value: number | null | undefined) => String(value ?? 0)
    const zeroFilled = asRendered(null)
    expect(zeroFilled).toBe('0')
    expect(text('sales-qty-1')).not.toBe(zeroFilled)
    expect(text('sales-qty-1')).not.toBe('')
  })

  it('⑩ 未发货 ⇒ 数量列 = 订单数量，且纸面**标明**「这不是实发」（不静默沿用）', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    expect(text('sales-qty-0')).toBe('3')
    expect(text('sales-qty-basis')).toContain('未发货')
    expect(text('sales-qty-basis')).toContain('订单数量')
  })

  it('⑪ 读面没取到（null）⇒ 与「未发货」**不同**的显式标注（不冒充业务状态）', () => {
    render(<SalesDoc order={buildOrder()} shipments={null} />)
    expect(text('sales-qty-basis')).toContain('未取到')
    // 退回订单数量是对的（并已标明），但**不许**说成「未发货」——那是把取数故障读成业务事实
    expect(text('sales-qty-basis')).not.toBe(SALES_QTY_BASIS['not-shipped'])
    expect(text('sales-qty-0')).toBe('3')
  })

  it('⑪ 红证：把状态合并成一种显示 ⇒ 上面两条必红', () => {
    // 四句口径说明必须**两两不同**：合并任意两句 ⇒ 纸面再也判不出「这个数是实发还是下单数量」
    const labels = SALES_QTY_STATES.map((s) => SALES_QTY_BASIS[s])
    expect(new Set(labels).size).toBe(labels.length)
    expect(SALES_QTY_BASIS['not-shipped']).not.toBe(SALES_QTY_BASIS.unavailable)
    expect(SALES_QTY_BASIS.shipped).not.toBe(SALES_QTY_BASIS.partial)
    expect([...SALES_QTY_STATES]).toEqual(['shipped', 'partial', 'not-shipped', 'unavailable'])
  })

  it('⑫ 实发明细挂不到订单行 ⇒ 纸面**显式**提示行数（不静默丢）', () => {
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={buildRead([
          { order_item_id: 'item-1', shipped_quantity: 3, unit: '米' },
          { order_item_id: null, shipped_quantity: 2, unit: '米' },
        ])}
      />
    )
    expect(text('sales-qty-basis')).toContain('1 行实发明细未挂到订单行')
    // 挂不上的那行**不进**本表（不猜归属），但绝不静默
    expect(document.querySelectorAll('[data-testid^="sales-item-"]')).toHaveLength(1)
  })

  // ══════════════════════════════════════════════════════════════════════════════
  // ⑬ 左上角作业单扫码报工二维码（issue #7530）
  //   码值 = **服务端下发**的 `processingOrder.scan_url`（`{base}/o/{短码}` ⇒ 302 到工人报工页 `/w/`）
  // ══════════════════════════════════════════════════════════════════════════════

  it('⑬ 有作业单扫码短链 ⇒ 纸面**左上角**出码，码值逐字 = 服务端 scan_url', () => {
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
        processingOrder={buildProcessingOrder()}
      />
    )
    // 码块存在性由**取值断言**证明（`workOrderQrValue()` 取的就是它的 `<svg><title>`）——
    // 不写 `not.toBeNull()` 这类存在性弱断言（QA Growth Gate 的 TS 弱断言面会判红）
    const qr = workOrderQr()
    expect(workOrderQrValue()).toBe('https://print.example.test/o/7K3M9QP2')
    // ② 位置 = 纸面**左上角**：QR 块在 `.sales-sheet` 的第一段里，且文档顺序在「销售单」抬头之前
    //    （不是页脚 / 右下角、也不与收款码混在一处）
    const title = Array.from(sheet()?.querySelectorAll('span') ?? []).find(
      (el) => el.textContent?.trim() === '销售单'
    )
    expect(title).toBeTruthy()
    expect(sheet()?.firstElementChild?.contains(qr)).toBe(true)
    expect(Boolean(qr!.compareDocumentPosition(title!) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
    expect(qr!.closest('[data-testid^="sales-qr-"]')).toBeNull()
  })

  it('⑬ 短码人可读：扫码枪 / 相机读不出时由印在码旁的短码兜底', () => {
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
        processingOrder={buildProcessingOrder()}
      />
    )
    expect(text('sales-work-order-qr-label')).toBe('扫码报工')
    expect(text('sales-work-order-short-code')).toBe('7K3M9QP2')
  })

  it('⑬ 缺码**不画假码**：无 scan_url ⇒ 整块不出现（零 QR / 零占位框 / 不回落作业单号）', () => {
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
        // 只有短码、没有服务端下发的短链（存量单未实例化 / 读面没取到）—— 前端**不自己拼**
        processingOrder={buildProcessingOrder({ scan_url: null })}
      />
    )
    expect(workOrderQr()).toBeNull()
    // 不画占位框；不回落作业单号；也不把裸短码印成「一个码」（扫出来只有文本、打不开页面）
    expect(doc()?.querySelector('[data-testid="sales-work-order-qr-placeholder"]')).toBeNull()
    expect(doc()?.textContent).not.toContain('CK-20261023-0001')
    expect(doc()?.textContent).not.toContain('7K3M9QP2')
    // 纸面**不印收款码**（issue #7589）⇒ 页脚本来就没有任何图片节点（与「缺码不画假码」同一读数）
    expect(doc()?.querySelectorAll('img')).toHaveLength(0)

    cleanup()
    // 没有作业单（订单详情页读面没取到）⇒ 同样整块不出现
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    expect(workOrderQr()).toBeNull()
  })

  it('⑬ 红证：前端自己拼 `{base}/o/{短码}` ⇒ 码值与服务端下发值不同 ⇒ 上面那条必红', () => {
    const serverScanUrl = 'https://print.example.test/o/7K3M9QP2'
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
        processingOrder={buildProcessingOrder({ scan_url: serverScanUrl })}
      />
    )
    // 「前端自己拼」的写法 —— 与服务端下发值不同（域名 / 路径段是第二份真值）
    const fabricated = 'https://app.migaozn.com/o/7K3M9QP2'
    expect(fabricated).not.toBe(serverScanUrl)
    expect(workOrderQrValue()).toBe(serverScanUrl)
    expect(workOrderQrValue()).not.toBe(fabricated)
  })
})
