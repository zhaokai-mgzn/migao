// case_ids: UI-062, UI-065
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup, within } from '@testing-library/react'
import type { ComponentProps } from 'react'

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
import { PROCESSING_TEXT_MISSING, processingPaperLine } from '@/lib/processing-item-text'
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
import type { Order, OrderItem } from '@/types'

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
 * ⑤ 🔴 **缺值可见 / 长名完整可见**：缺值显式占位 `—`；长名**折行印全文**（不裁字符串、
 *    也不上省略号 —— issue #7715：用户 2026-10-25 逐字「这里打印预览的文字要打印全，不能缩略」）；
 * ⑥ **纸面不印收款码**（issue #7589：用户 2026-10-24 逐字「销售单打印处右下角的二维码移除掉」）
 *    —— 页脚只留温馨提示、销售单也不再读收款码；打印隔离沿用 #4983 / #4965 范式（共享 `print-doc`）；
 * ⑧ **扫码报工码已迁到加工单纸面**（issue #7891，用户 2026-10-27 逐字「把销售单左上角的扫码
 *    报工二维码迁移到加工单打印上，这样设计才是合理的」）⇒ 本文件的判据**反向**：销售单纸面
 *    **不再出现**那块码（`sales-work-order-qr*` 一个都不许有，见 describe「⑬」），组件签名里
 *    也**不再吃** `processingOrder`（码值逐字取 `scan_url` / 缺码不画假码两条口径随码迁到
 *    `ProcessingDoc`，判据在 `ProcessingDoc.test.tsx`，本文件不复述）；
 * ⑨ **加工项绑商品**（issue #7891，用户同日逐字「销售单和报价单都缺了加工项」）：每个商品行之后
 *    一条子行（`sales-item-processing-{idx}`），文案**只**来自 `lib/processing-item-text.ts`；
 *    布料行 / 无加工项的行不出子行（见 describe「⑭」）；
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

/**
 * 纸面「缩略」判据（issue #7715）—— 返回命中的**裁切形态**，空集 = 合格。
 *
 * 用户 2026-10-25 逐字「这里打印预览的文字要打印全，不能缩略」：纸面是客户收货凭证，
 * 被省略号吃掉的正是「这是哪个花色」。⇒ 两件事一起判：
 * ① 样式里不许出现省略号 / `nowrap` / 旧形态 `.sales-cut`；
 * ② 承载长文本的单元格必须自己声明折行（`break-words`）。
 *
 * 抽成纯函数是刻意的：**红证与判据跑同一把尺子**（各写一份 ⇒ 红证证明不了判据）。
 */
function paperTruncationHits(styleText: string, cell: Element | null): string[] {
  const hits: string[] = []
  if (/text-overflow:\s*ellipsis/.test(styleText)) hits.push('text-overflow: ellipsis')
  if (/white-space:\s*nowrap/.test(styleText)) hits.push('white-space: nowrap')
  if (/\.sales-cut/.test(styleText)) hits.push('.sales-cut')
  if (!(cell?.className ?? '').includes('break-words')) hits.push('单元格未声明折行')
  return hits
}

const sheet = (): HTMLElement | null => document.querySelector('[data-testid="sales-sheet"]')
/**
 * 左上角作业单扫码报工码的块 —— issue #7891 起销售单**不再有**它（码迁到加工单纸面），
 * 故本文件的判据是**反向**的：这个查询必须恒为 `null`（修前那块码在这里查得到）。
 */
const workOrderQr = (): Element | null => document.querySelector('[data-testid="sales-work-order-qr"]')

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
    // 🔴 2026-10-25 收口：`@page` 边距改 0（浏览器页眉页脚画在边距里），版面内缩 6mm 12mm
    // 改由容器 padding 承担 ⇒ DOM 上仍是 `padding: 6mm 12mm`（见 SalesDoc 的打印样式）
    expect(css()).toContain('@page { size: 241mm 140mm; margin: 0; }')
    expect(css()).toContain('padding: 6mm 12mm')
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
        printTarget="sales"
      />
    )
    const tri = rowCells()
    const triHeader = Array.from(document.querySelectorAll('.sales-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    const triDue = text('sales-total-due')
    const triTotal = text('sales-total')
    cleanup()
    render(
      <SalesDoc
        order={buildOrder()}
        shipments={NO_SHIPMENT}
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
    // 逐格取值 / 表头 / 金额汇总 一律逐字相同
    expect(rowCells()).toEqual(tri)
    expect(
      Array.from(document.querySelectorAll('.sales-doc-table thead th')).map((th) => th.textContent?.trim())
    ).toEqual(triHeader)
    expect(text('sales-total-due')).toBe(triDue)
    expect(text('sales-total')).toBe(triTotal)
    // 切介质也不许把已迁走的扫码报工码带回来（issue #7891）
    expect(workOrderQr()).toBeNull()
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
    // 🔴 issue #7625（用户 2026-10-24「给所有打印预览表格都加一列用来区分是布帘还是纱帘」）：
    // 「门幅」后插入「帘种」⇒ 8 列变 9 列（帘种紧跟门幅，与其余三张纸面同一相对位置）。
    expect([...SALES_DOC_COLUMNS]).toEqual([
      '序号',
      '货号',
      '颜色',
      '门幅',
      '帘种',
      '数量',
      '单位',
      '单价',
      '金额',
    ])
    expect(rowCells()).toHaveLength(1)
    // 🔴 货号取响应真字段 `skuCode` —— 夹具**没有** `productCode`（幽灵字段）：
    // 旧实现（`productCode || productName`）在这一格印的是品名 ⇒ 本判据即红证
    // 帘种第 5 格：夹具 `processingInfo` 没写 `curtainType`（写侧口径「主帘缺省即布帘」）⇒ 布帘
    expect(rowCells()[0]).toEqual(['1', '0012', '米白', '2.8米', '布帘', '3', '米', '10.00', '500.00'])
    // 🔴 品名**整列退场**：纸面任何一处都不再印商品名（去掉表头却留着单元格 = 串列）
    expect(doc()?.textContent).not.toContain('布艺遮光帘A')
  })

  it('帘种列（issue #7625）：显式 `curtainType=纱帘` ⇒ 印「纱帘」；布料单（无帘）⇒ 占位 `—`', () => {
    render(
      <SalesDoc
        order={buildOrder({
          items: [
            buildItem({
              id: 'item-sheer',
              productName: '纱帘B',
              processingInfo: { colorName: '象牙白', doorWidth: '3.0米', curtainType: '纱帘' },
            }),
            buildItem({
              id: 'item-fabric',
              processingInfo: { colorName: '米白', doorWidth: '2.8米', saleForm: '布料' },
            }),
          ],
        })}
        shipments={NO_SHIPMENT}
      />
    )
    const cellsOf = (idx: number): string[] =>
      Array.from(document.querySelectorAll(`[data-testid="sales-item-${idx}"] td`)).map(
        (td) => td.textContent ?? ''
      )
    // 帘种列 index = 4（序号0 货号1 颜色2 门幅3 帘种4）
    // 🔴 注入式红证：纱帘行回落「布帘」/ 布料单被默认成「布帘」⇒ 下面两条必红
    expect(cellsOf(0)[4]).toBe('纱帘')
    expect(cellsOf(1)[4]).toBe(SALES_DOC_MISSING)
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
    // 金额列 index = 8（issue #7625 起 9 列表：序号0 货号1 颜色2 门幅3 帘种4 数量5 单位6 单价7 金额8）
    const amountColumn = paperNumericColumn(doc(), { column: 8 })
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

  it('⑤ 长名**完整可见**：单元格折行印全文（不缩略 / 不裁字符串）', () => {
    const longName = '杭州余杭某某某某某某某某某某某某某某某某某某纺织品经营部'
    render(<SalesDoc order={buildOrder({ customerName: longName })} shipments={NO_SHIPMENT} />)
    // 不裁字符串：全文仍在 DOM 里（打印/屏幕都拿得到完整值）
    expect(text('sales-customer')).toBe(longName)
    // 🔴 纸面**不缩略**（issue #7715）：折行印全文 —— 省略号 / nowrap / `.sales-cut` 一处都不许有
    expect(paperTruncationHits(css(), document.querySelector('[data-testid="sales-customer"]'))).toEqual([])
  })

  it('⑤ 颜色列**折行印全**（用户截图指的就是这一格）：长色名不进省略号', () => {
    // 真机形态：颜色 = 货号前缀 + 色名（实测「2659-08 月落雾…」被省略号吃掉后半截）
    const longColor = '2659-08 月落雾灰蓝拼接加长款'
    render(
      <SalesDoc
        order={buildOrder({
          items: [
            buildItem({
              skuCode: '2659',
              processingInfo: { colorName: longColor, doorWidth: '2.8米' },
            }),
          ],
        })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(text('sales-code-0')).toBe('2659')
    expect(text('sales-color-0')).toBe(longColor)
    expect(paperTruncationHits(css(), document.querySelector('[data-testid="sales-color-0"]'))).toEqual([])
  })

  it('⑤ 红证：把省略号裁切写回来 / slice 掉长名 ⇒ 上面那条必红', () => {
    const longName = '杭州余杭某某某某某某某某某某某某某某某某某某纺织品经营部'
    render(<SalesDoc order={buildOrder({ customerName: longName })} shipments={NO_SHIPMENT} />)
    expect(text('sales-customer')).not.toBe(longName.slice(0, 8)) // slice = 静默裁切 ⇒ 红
    const cell = document.querySelector('[data-testid="sales-customer"]')
    // ⚠️ 不写存在性弱断言（`not.toBeNull()` —— QA Growth Gate 的 TS 弱断言面会判红）：
    //    下面那把尺子本身就会对「格子缺失」报「未声明折行」⇒ 判据照样红，不需要额外一行。
    expect(cell?.getAttribute('data-testid')).toBe('sales-customer')
    // 射程自证：把**旧形态**（issue #5651 的 `.sales-cut`：省略号 + nowrap）摆进同一把尺子 ⇒ 必须命中。
    // 这条若不命中，上面的「不许缩略」就是空断言（判据根本没在看那件事）。
    const legacyCss = '.sales-cut { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }'
    expect(paperTruncationHits(css() + legacyCss, cell)).toEqual(
      expect.arrayContaining(['.sales-cut', 'text-overflow: ellipsis', 'white-space: nowrap'])
    )
    // 负控：同一把尺子量真产物 ⇒ 空集（判据不是恒命中）
    expect(paperTruncationHits(css(), cell)).toEqual([])
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
    //    最后声明的那条赢 ⇒ 非目标单据发表纸型 = 把兄弟单据的纸型顶掉，实测打废纸）。
    // ⚠️ 判据钉的是**规则**（`@page {`），不是「@page」这个词：打印样式的注释里正常会提到
    //    @page（解释「页眉页脚画在 @page 边距里」），按词判定会把说明文字判成违规（假红）。
    expect(css()).not.toMatch(/@page\s*\{/)
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
  // ⑬ 扫码报工码**已迁到加工单**（issue #7891，用户 2026-10-27 逐字「把销售单左上角的扫码报工
  //    二维码迁移到加工单打印上，这样设计才是合理的」）—— 判据因此**反向**：
  //    销售单纸面**不再出现**那块码，组件也**不再吃** `processingOrder` prop。
  // ══════════════════════════════════════════════════════════════════════════════

  it('⑬ 销售单纸面**不再出现**扫码报工码（码已迁到加工单纸面）', () => {
    render(<SalesDoc order={buildOrder()} shipments={NO_SHIPMENT} />)
    // 三个锚点一个都不许有（修前分别查得到块 / svg / 竖排标签）
    expect(workOrderQr()).toBeNull()
    expect(document.querySelector('[data-testid="sales-work-order-qr-svg"]')).toBeNull()
    expect(document.querySelector('[data-testid="sales-work-order-qr-label"]')).toBeNull()
    // 纸面上连一张图 / 一个 `<svg>` 都没有（收款码 #7589 已退场、报工码 #7891 已迁走）
    expect(doc()?.querySelectorAll('img')).toHaveLength(0)
    expect(doc()?.querySelectorAll('svg')).toHaveLength(0)
    expect(doc()?.textContent).not.toContain('扫码报工')
    // 射程自证（负判据不许是「选择器打错字」）：把 **issue #7530 的那块码**摆进同一批选择器
    // ⇒ 必须查得到；移走后再回到空集（证明判据既不恒真、也不对着空 DOM 恒假）。
    const probe = document.createElement('div')
    probe.innerHTML =
      '<div data-testid="sales-work-order-qr">' +
      '<svg data-testid="sales-work-order-qr-svg"></svg>' +
      '<div data-testid="sales-work-order-qr-label">扫码报工</div></div>'
    document.body.appendChild(probe)
    expect(document.querySelectorAll('[data-testid="sales-work-order-qr"]')).toHaveLength(1)
    expect(document.querySelectorAll('[data-testid="sales-work-order-qr-svg"]')).toHaveLength(1)
    expect(document.querySelectorAll('[data-testid="sales-work-order-qr-label"]')).toHaveLength(1)
    expect(probe.querySelectorAll('svg')).toHaveLength(1)
    expect(probe.textContent).toContain('扫码报工')
    probe.remove()
    expect(document.querySelectorAll('[data-testid="sales-work-order-qr"]')).toHaveLength(0)
  })

  it('⑬ 组件签名里已没有 `processingOrder`（类型面：删 prop 才算迁完）', () => {
    // 类型级红证：谁把 `processingOrder` 加回 props ⇒ 下面的 `false` 赋值当场 TS 报错。
    type HasProcessingOrder = 'processingOrder' extends keyof ComponentProps<typeof SalesDoc>
      ? true
      : false
    const hasProcessingOrder: HasProcessingOrder = false
    expect(hasProcessingOrder).toBe(false)
  })

  it('⑬ 遗留调用点若仍传 `processingOrder` ⇒ 也不会把码带回来（防御）', () => {
    // 组件签名已无该 prop（调用点那一包同批删掉了两处传参）。这里**从类型外**注入，
    // 证明遗留 / 回退的调用点即使还传这个多余 prop，也**不会**复活那块码。
    const staleProps = {
      order: buildOrder(),
      shipments: NO_SHIPMENT,
      processingOrder: {
        id: 'po-1',
        orderId: 'order-1',
        processingOrderNo: 'CK-20261023-0001',
        short_code: '7K3M9QP2',
        scan_url: 'https://print.example.test/o/7K3M9QP2',
      },
    } as unknown as ComponentProps<typeof SalesDoc>
    render(<SalesDoc {...staleProps} />)
    expect(workOrderQr()).toBeNull()
    expect(doc()?.querySelectorAll('svg')).toHaveLength(0)
    // 短码 / 作业单号也不上纸（内部标识不上随货单据，issue #7608 的口径不变）
    expect(doc()?.textContent).not.toContain('7K3M9QP2')
    expect(doc()?.textContent).not.toContain('CK-20261023-0001')
  })

  // ══════════════════════════════════════════════════════════════════════════════
  // ⑭ 加工项**绑商品**（issue #7891，用户 2026-10-27 逐字「销售单和报价单都缺了加工项」+
  //    「发货单的加工项需要和商品绑定…都放在加工项那一栏里面」）
  //    子行 = 商品行之后的一条 `colSpan` 子行；文案**只**来自 `lib/processing-item-text.ts`
  // ══════════════════════════════════════════════════════════════════════════════

  /** 第 `idx` 个商品行的加工项子行（没有 ⇒ `null`）与其纸面文本 */
  const processingRow = (idx: number): Element | null =>
    document.querySelector(`[data-testid="sales-item-processing-${idx}"]`)
  const processingText = (idx: number): string => processingRow(idx)?.textContent?.trim() ?? ''

  it('⑭ 数量全等 ⇒ 「各」只说一遍数字（`定型、韩褶 各 6.3`）', () => {
    const info = {
      colorName: '米白',
      doorWidth: '2.8米',
      processingItems: [
        { name: '定型', quantity: 6.3 },
        { name: '韩褶', quantity: 6.3 },
      ],
    }
    render(
      <SalesDoc
        order={buildOrder({ items: [buildItem({ processingInfo: info })] })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(processingText(0)).toBe('加工项：定型、韩褶 各 6.3')
    // 文案**只**来自共享构建器（组件里另拼一份 ⇒ 这两条会在同一次改动里分叉）
    expect(processingText(0)).toBe(processingPaperLine(info))
    // 子行与商品行**同一张表**、单格跨全表列数（不新增列 ⇒ C5 的列清单真值不动）
    const row = processingRow(0)
    expect(row?.closest('table')).toBe(document.querySelector('.sales-doc-table'))
    expect(row?.closest('tbody')?.getAttribute('data-testid')).toBe('sales-doc-body')
    expect(row?.querySelectorAll('td')).toHaveLength(1)
    expect(row?.querySelector('td')?.getAttribute('colspan')).toBe(String(SALES_DOC_COLUMNS.length))
    expect(document.querySelectorAll('.sales-doc-table thead th')).toHaveLength(SALES_DOC_COLUMNS.length)
    // 单行紧凑（三联纸单联可用高只有 128mm）：0.85em + 折行不裁（issue #7715）
    expect(row?.querySelector('td')?.className).toContain('text-[0.85em]')
    expect(row?.querySelector('td')?.className).toContain('break-words')
    // 行/列自洽交给类级不变量：子行 Σ(colSpan) 必须等于表头列数（issue #6595）
    expect(dataTables(doc()).every((table) => collectTableIntegrity([table]).length === 1)).toBe(true) // 单据：销售单 SalesDoc
  })

  it('⑭ 数量不等 ⇒ 逐项印各自的数（`定型 6.3 + 韩褶 2`，不提公因子）', () => {
    const info = {
      processingItems: [
        { name: '定型', quantity: 6.3 },
        { name: '韩褶', quantity: 2 },
      ],
    }
    render(
      <SalesDoc
        order={buildOrder({ items: [buildItem({ processingInfo: info })] })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(processingText(0)).toBe('加工项：定型 6.3 + 韩褶 2')
    expect(processingText(0)).not.toContain('各')
    expect(processingText(0)).toBe(processingPaperLine(info))
  })

  it('⑭ 缺数量 ⇒ 该项印缺值占位 `—`（`打孔 —`，不静默吞掉、不摊成 0）', () => {
    const info = { processingItems: [{ name: '打孔' }] }
    render(
      <SalesDoc
        order={buildOrder({ items: [buildItem({ processingInfo: info })] })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(processingText(0)).toBe(`加工项：打孔 ${PROCESSING_TEXT_MISSING}`)
    expect(processingText(0)).not.toContain('打孔 0')
  })

  it('⑭ 特殊选项**同一栏**上纸（`加工项：… · 特殊选项：拼2次-布`）', () => {
    const info = {
      processingItems: [{ name: '定型', quantity: 6.3 }],
      specialOptions: ['拼2次-布'],
    }
    render(
      <SalesDoc
        order={buildOrder({ items: [buildItem({ processingInfo: info })] })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(processingText(0)).toBe('加工项：定型 6.3 · 特殊选项：拼2次-布')
    expect(processingText(0)).toBe(processingPaperLine(info))
  })

  it('⑭ **绑定**：A 行的加工项不出现在 B 行子行（不串行），且子行紧跟自己的商品行', () => {
    render(
      <SalesDoc
        order={buildOrder({
          items: [
            buildItem({
              id: 'item-a',
              skuCode: '0012',
              processingInfo: { processingItems: [{ name: '定型', quantity: 3 }] },
            }),
            buildItem({
              id: 'item-b',
              skuCode: '0013',
              quantity: 4,
              processingInfo: { processingItems: [{ name: '打孔', quantity: 4 }] },
            }),
          ],
        })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(processingText(0)).toBe('加工项：定型 3')
    expect(processingText(1)).toBe('加工项：打孔 4')
    // 反向：A 行子行里没有 B 行的加工项，B 行也没有 A 行的（跨行串味 = 把别人的活印在这行下面）
    expect(processingText(0)).not.toContain('打孔')
    expect(processingText(1)).not.toContain('定型')
    // 位置：子行紧跟**自己**那一行的商品行之后
    expect(processingRow(0)?.previousElementSibling?.getAttribute('data-testid')).toBe('sales-item-0')
    expect(processingRow(1)?.previousElementSibling?.getAttribute('data-testid')).toBe('sales-item-1')
  })

  it('⑭ 布料行 / 无加工项的行 ⇒ 不出子行（不印空行、不印「加工项：—」）', () => {
    render(
      <SalesDoc
        order={buildOrder({
          items: [
            // 布料行：`processingInfo` 只有颜色 / 门幅 + saleForm，没有加工项数组
            buildItem({ id: 'item-fabric', processingInfo: { colorName: '米白', saleForm: '布料' } }),
            // 存量单：整行没有 `processingInfo` 键
            buildItem({ id: 'item-legacy', skuCode: '0014', processingInfo: undefined }),
            // 有加工项的成品帘行（对照：子行只在它下面出）
            buildItem({
              id: 'item-curtain',
              skuCode: '0015',
              processingInfo: { curtainType: '布帘', processingItems: [{ name: '定型', quantity: 6 }] },
            }),
          ],
        })}
        shipments={NO_SHIPMENT}
      />
    )
    expect(processingRow(0)).toBeNull()
    expect(processingRow(1)).toBeNull()
    expect(processingText(2)).toBe('加工项：定型 6')
    // 子行总数 = 1（不多出空行），纸面也不出现「加工项：—」这种空值形态
    expect(document.querySelectorAll('[data-testid^="sales-item-processing-"]')).toHaveLength(1)
    expect(doc()?.textContent).not.toContain(`加工项：${PROCESSING_TEXT_MISSING}`)
  })
})
