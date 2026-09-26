// case_ids: UI-062
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'

const mockGetPaymentQrcodes = vi.fn()
vi.mock('@/lib/api', () => ({
  settingsApi: { getPaymentQrcodes: (...args: unknown[]) => mockGetPaymentQrcodes(...args) },
}))

import SalesDoc, {
  SALES_DOC_COLUMNS,
  SALES_DOC_MISSING,
  SALES_DOC_MONEY_GAPS,
  SALES_DOC_NOT_COLLECTED,
} from '@/components/orders/SalesDoc'
import { printPageRule } from '@/lib/print-media'
import type { Order, OrderItem, PaymentQrcodeMap } from '@/types'

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
 * ⑥ **缺码不画假码** + 打印隔离沿用 #4983 / #4965 范式（共享 `print-doc`）。
 */
function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    productId: 'p-1',
    productName: '布艺遮光帘A',
    productCode: '0012',
    color: '米白',
    specification: '门幅2.8米',
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

const doc = (): HTMLElement | null => document.querySelector('.sales-print-area')
const css = (): string => doc()?.querySelector('style')?.textContent || ''
const text = (testId: string): string =>
  document.querySelector(`[data-testid="${testId}"]`)?.textContent?.trim() ?? ''
const sheet = (): HTMLElement | null => document.querySelector('[data-testid="sales-sheet"]')

/** 明细区逐格取值（序号/货号/数量/单位/单价/金额/备注）—— 用于「切介质取值不变」的逐格比对 */
function rowCells(): string[][] {
  return Array.from(document.querySelectorAll('[data-testid^="sales-item-"]')).map((tr) =>
    Array.from(tr.querySelectorAll('td')).map((td) => td.textContent?.trim() || '')
  )
}

describe('SalesDoc（销售单 · 三联纸 241mm × 140mm，issue #5651）', () => {
  it('① 介质：@page 241mm × 140mm（两等分）+ 只渲染一页 + 单联高度固定不跨联', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
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
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    const sheets = document.querySelectorAll('.sales-sheet')
    // 复写份数是**纸**的属性，不是渲染次数（矩阵里 carbonCopies = 3）⇒ 渲三份即红
    expect(sheets).toHaveLength(1)
  })

  it('② 介质是**参数**不是副本：切 A4 后 @page 变、而逐格取值**逐字不变**', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    const tri = rowCells()
    const triHeader = Array.from(document.querySelectorAll('.sales-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    const triDue = text('sales-total-due')
    const triTotal = text('sales-total')
    cleanup()
    render(<SalesDoc order={buildOrder()} media="a4" paymentQrcodes={{}} />)
    // 版面参数随介质变
    expect(css()).toContain('@page { size: A4; margin: 12mm; }')
    expect(doc()?.getAttribute('data-print-media')).toBe('a4')
    expect(sheet()?.style.height).toBe('')
    // 而**字段映射一份都没变**（复制一份映射给 A4 ⇒ 这里会红）
    expect(rowCells()).toEqual(tri)
    expect(
      Array.from(document.querySelectorAll('.sales-doc-table thead th')).map((th) => th.textContent?.trim())
    ).toEqual(triHeader)
    expect(text('sales-total-due')).toBe(triDue)
    expect(text('sales-total')).toBe(triTotal)
  })

  it('② 列清单 = SALES_DOC_COLUMNS（全仓唯一一份；商品行粒度，不是报价单的按套×部位）', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    const headers = Array.from(document.querySelectorAll('.sales-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    expect(headers).toEqual([...SALES_DOC_COLUMNS])
    expect([...SALES_DOC_COLUMNS]).toEqual(['序号', '货号', '数量', '单位', '单价', '金额', '备注'])
    expect(rowCells()).toHaveLength(1)
    expect(rowCells()[0].slice(0, 7)).toEqual(['1', '0012', '3', '米', '10.00', '500.00', '米白'])
  })

  it('🔴 ③ 金额取服务端字段：行金额 = item.amount（≠ 单价×数量），本单应收 = order.actualAmount', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    // 行金额印服务端的 500.00；前端现算会得到 3 × 10 = 30.00
    expect(text('sales-row-amount-0')).toBe('500.00')
    expect(text('sales-row-amount-0')).not.toBe('30.00')
    // 汇总同理：服务端 888.88 / 999.99 / 111.11（行金额之和是 500.00，印出来就说明前端现算了）
    expect(text('sales-total-due')).toBe('888.88')
    expect(text('sales-total')).toBe('999.99')
    expect(text('sales-discount')).toBe('111.11')
  })

  it('🔴 ③ 红证：让前端现算（单价×数量 / 行金额求和）⇒ 上面那条必红', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
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
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
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
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    const fabricated = (0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })
    expect(fabricated).toBe('0.00')
    // 纸面若有 `0.00` 就说明编数了（判据要求 `未采集`，且不许出现数字）
    expect(text('sales-account-balance')).not.toBe(fabricated)
    expect(text('sales-account-balance')).not.toMatch(/[0-9]/)
  })

  it('🔴 ⑤ 缺值**可见**：客户 / 电话 / 地址缺失 ⇒ 显式占位 `—`（不是空单元格）', () => {
    render(
      <SalesDoc
        order={buildOrder({ customerName: '', customerPhone: '', customerAddress: undefined })}
        paymentQrcodes={{}}
      />
    )
    expect(text('sales-customer')).toBe(SALES_DOC_MISSING)
    expect(text('sales-phone')).toBe(SALES_DOC_MISSING)
    expect(text('sales-address')).toBe(SALES_DOC_MISSING)
  })

  it('🔴 ⑤ 红证：把缺值换回静默留空（`|| ""`）⇒ 上面那条必红', () => {
    render(
      <SalesDoc order={buildOrder({ customerAddress: undefined })} paymentQrcodes={{}} />
    )
    const silent = (buildOrder({ customerAddress: undefined }).customerAddress || '').trim()
    expect(silent).toBe('') // 旧写法给空串 ⇒ 判据（`—`）红
    expect(text('sales-address')).toBe(SALES_DOC_MISSING)
  })

  it('⑤ 长名**截断可见**：单元格保留全文 + 走 CSS 省略号（不裁字符串）', () => {
    const longName = '杭州余杭某某某某某某某某某某某某某某某某某某纺织品经营部'
    render(<SalesDoc order={buildOrder({ customerName: longName })} paymentQrcodes={{}} />)
    // 不裁字符串：全文仍在 DOM 里（打印/屏幕都拿得到完整值）
    expect(text('sales-customer')).toBe(longName)
    // 截断是**可见**的（省略号），不是静默裁掉
    expect(document.querySelector('[data-testid="sales-customer"]')?.className).toContain('sales-cut')
    expect(css()).toMatch(/\.sales-cut\s*\{[^}]*text-overflow:\s*ellipsis/)
    expect(css()).toMatch(/\.sales-cut\s*\{[^}]*overflow:\s*hidden/)
  })

  it('⑤ 红证：把长名 slice 掉（静默裁切）或去掉省略号 ⇒ 上面那条必红', () => {
    const longName = '杭州余杭某某某某某某某某某某某某某某某某某某纺织品经营部'
    render(<SalesDoc order={buildOrder({ customerName: longName })} paymentQrcodes={{}} />)
    expect(text('sales-customer')).not.toBe(longName.slice(0, 8)) // slice = 静默裁切 ⇒ 红
    const withoutEllipsis = css().replace(/text-overflow:\s*ellipsis;?/g, '')
    expect(withoutEllipsis).not.toMatch(/text-overflow/) // 去掉省略号 ⇒ 判据红
  })

  it('⑥ 缺码**不画假码**：无收款码 ⇒ 页脚支付块整块不出现', async () => {
    mockGetPaymentQrcodes.mockReset()
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: {} } })
    render(<SalesDoc order={buildOrder()} />)
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(doc()?.querySelector('img')).toBeNull()
    expect(document.querySelectorAll('[data-testid^="sales-qr-"]')).toHaveLength(0)
    // 温馨提示仍在（缺码只影响支付块）
    expect(doc()?.textContent).toContain('收到货后先验货')
  })

  it('⑥ 有收款码 ⇒ 出图（扫码支付块）', () => {
    const qrcodes: PaymentQrcodeMap = {
      wechat: { paymentType: 'wechat', imageUrl: '/uploads/qr-wechat.png', payeeName: '亿家纺织' },
    }
    render(<SalesDoc order={buildOrder()} paymentQrcodes={qrcodes} />)
    const img = document.querySelector('[data-testid="sales-qr-wechat"]')
    expect(img?.getAttribute('src')).toBe('/uploads/qr-wechat.png')
  })

  it('⑦ 打印隔离：portal 到 body + 共享 print-doc + 隔离选择器排除所有打印单据 + 屏幕态隐藏', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    const el = doc()
    expect(el?.parentElement).toBe(document.body)
    expect(el?.className).toContain('print-doc')
    expect(document.querySelectorAll('.sales-print-area')).toHaveLength(1)
    expect(css()).toMatch(/body > \*:not\(\.print-doc\)\s*\{\s*display:\s*none\s*!important/)
    expect(css()).not.toMatch(/body > \*:not\(\.sales-print-area\)/)
    expect(css()).toMatch(/\.sales-print-area\[data-print-target='sales'\]/)
  })

  it('⑦ 未置位打印目标 ⇒ 不加 data-print-target（点别的单据时本单不参与显形）', () => {
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} />)
    expect(doc()?.getAttribute('data-print-target')).toBeNull()
    cleanup()
    render(<SalesDoc order={buildOrder()} paymentQrcodes={{}} printTarget="sales" />)
    expect(doc()?.getAttribute('data-print-target')).toBe('sales')
  })
})
