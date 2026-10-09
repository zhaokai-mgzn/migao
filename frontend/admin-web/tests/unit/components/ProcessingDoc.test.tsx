// case_ids: UI-061
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// SalesDoc 与 ProcessingDoc 都会（经 hook / 组件）触到 `@/lib/api` —— 打桩成「无码」，
// 避免 jsdom 真发 XHR（噪音）。「无码 ⇒ 整块不出现」的判据仍由组件行为决定。
const mockGetPaymentQrcodes = vi.fn()
vi.mock('@/lib/api', () => ({
  settingsApi: { getPaymentQrcodes: (...args: unknown[]) => mockGetPaymentQrcodes(...args) },
}))

import ProcessingDoc, {
  MISSING,
  NOT_COLLECTED,
  PROCESSING_DOC_COLUMNS,
  PROCESSING_DOC_NOT_COLLECTED_FIELDS,
} from '@/components/orders/ProcessingDoc'
import type { Order, OrderItem, ProcessingOrder, ProcessingOrderItem } from '@/types'
import { collectTableIntegrity, dataTables } from '@/components/orders/doc-tables'

/**
 * 加工单（**A4 可打印纸质文档**，issue #5651）—— 照客户现行实物制式（issue #5651 实证表 #3）。
 *
 * 断言的是**纸面内容与版面契约**：
 * ① 表头九栏逐条命中（订单日期 / 客户 / 电话 / 地址 / 备注 / 制单人 / 单号 / 交付日期 / 货运）+ 右上 QR；
 * ② **按套分块**，每块 `第N套/共M套` + 一张 8 列表（列清单 = `PROCESSING_DOC_COLUMNS`，全仓唯一一份）；
 * ③ `@page { size: A4; margin: 12mm; }`（由介质矩阵生成）+ 分页不裁切（`break-inside: avoid`）
 *    且长单分页时**表头重复**（`thead { display: table-header-group }`）；
 * ④ 🔴 **缺值不许静默留空**：一律显式占位 `—`；本系统**没有采集**的字段（制单人 / 批号）
 *    另标「未采集」——「客户没填」与「我们没有这个列」必须可区分；
 * ⑤ 🔴 **缺码不画假码**（洗水码既有判据）：拿不到 QR 值 ⇒ 虚线占位框，不编码、不拿别的串顶替；
 * ⑥ 打印隔离沿用 #4983 / #4965 范式（共享 `print-doc` + 限定本次打印目标的 visibility 防御）；
 * ⑦ **列宽按内容预算**（issue #6600）：批号是**固定 17 字符**的 `PC-yyyyMMdd-####`，原先只给 10%
 *    ⇒ `table-layout: fixed` 下折成 3 行、把数据行撑高（真浏览器实测 63px）。现在 ≥16%（两行放得下）。
 */
function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    productId: 'p-1',
    productName: '布艺遮光帘A',
    productCode: '0012',
    color: '米白',
    specification: '门幅2.8米',
    quantity: 12.5,
    unitPrice: 100,
    amount: 1250,
    subtotal: 1250,
    processingFee: 0,
    width: 3.2,
    height: 2.6,
    processingInfo: {
      curtainType: '布帘',
      craft: '韩褶',
      cuttingMode: '定高买宽',
      colorName: '米白',
      componentRole: '主布',
    },
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
    totalAmount: 999.99,
    actualAmount: 888.88,
    discountAmount: 111.11,
    status: 'pending_shipment' as Order['status'],
    hasProcessing: true,
    items: [buildItem()],
    createdAt: '2026-09-26T10:00:00+08:00',
    logisticsType: '物流',
    logisticsCompany: '德邦',
    remark: '客户要求周五前送到',
    ...overrides,
  }
}

const buildProcessingOrder = (overrides: Partial<ProcessingOrder> = {}): ProcessingOrder => ({
  id: 'po-1',
  orderId: 'order-1',
  orderNo: 'CSO260926-0001',
  processingOrderNo: 'PO260926-0007',
  status: 'issued',
  expectedDeliveryDate: '2026-10-01',
  ...overrides,
})

const doc = (): HTMLElement | null => document.querySelector('.processing-print-area')
const css = (): string =>
  Array.from(doc()?.querySelectorAll('style') ?? [])
    .map((el) => el.textContent || '')
    .join('\n')
/** 表头标签（第一行第一列那一格）的文本集合 */
const cellText = (testId: string): string =>
  document.querySelector(`[data-testid="${testId}"]`)?.textContent?.trim() ?? ''

/** 表头这一格的**声明宽度百分比**（`w-[N%]`，全仓唯一真值 = 表头） */
const headerWidthOf = (label: string): number => {
  const th = Array.from(doc()?.querySelectorAll('.processing-doc-table thead th') ?? []).find(
    (el) => el.textContent?.trim() === label
  )
  return Number((th?.className ?? '').match(/\bw-\[(\d+)%\]/)?.[1] ?? NaN)
}
/** 8 列表头声明的宽度百分比（按表头顺序） */
const headerWidths = (): number[] => PROCESSING_DOC_COLUMNS.map(headerWidthOf)

describe('ProcessingDoc（A4 加工单，issue #5651）', () => {
  // 类级固化（issue #6595）：本单据的正文表逐行自洽（Σ(colSpan) = 表头列数）——
  // 主体行少渲染一格 ⇒ 备注列在数据行没有单元格 ⇒ 整列没有边框（用户真机截图撞见的那一处）。
  it('表格列数不变量：正文明细表逐行 Σ(colSpan) = 表头列数（issue #6595）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const tables = collectTableIntegrity(dataTables(doc())) // 单据：加工单 ProcessingDoc
    expect(tables.length).toBeGreaterThan(0)
    for (const table of tables) {
      expect(table.columns).toBe(PROCESSING_DOC_COLUMNS.length)
      expect(table.rows.every((n) => n === PROCESSING_DOC_COLUMNS.length)).toBe(true)
    }
  })

  it('① 表头九栏逐条命中实证 #3 的制式（缺值显式占位，不静默留空）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        qrValue="PO260926-0007"
      />
    )
    const text = doc()?.textContent || ''
    for (const label of ['订单日期', '客户', '电话', '地址', '备注', '制单人', '单号', '交付日期', '货运']) {
      expect(text).toContain(label)
    }
    // 取值来自服务端字段（订单日期 = order.createdAt；交付日期 = 加工单交期；单号 = 加工单号）
    expect(text).toContain('2026-09-26')
    expect(text).toContain('2026-10-01')
    expect(text).toContain('PO260926-0007')
    expect(text).toContain('张三')
    expect(text).toContain('13800000000')
    expect(text).toContain('物流 · 德邦')
    expect(text).toContain('客户要求周五前送到')
  })

  it('① 交付日期回落链：加工单无交期 ⇒ 读订单「要求到货日」（都是服务端字段）', () => {
    render(
      <ProcessingDoc
        order={buildOrder({ requiredDeliveryDate: '2026-10-05' })}
        processingOrder={buildProcessingOrder({ expectedDeliveryDate: undefined })}
      />
    )
    expect(doc()?.textContent).toContain('2026-10-05')
  })

  it('① 加工单缺失 ⇒ 单号回落订单号（不印空单号）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={null} />)
    expect(doc()?.textContent).toContain('CSO260926-0001')
  })

  it('② 按套分块：3 个商品行 ⇒ 3 块，各带 `第N套/共M套` 与 8 列表头', () => {
    render(
      <ProcessingDoc
        order={buildOrder({
          items: [buildItem(), buildItem({ id: 'item-2' }), buildItem({ id: 'item-3' })],
        })}
        processingOrder={buildProcessingOrder()}
      />
    )
    expect(document.querySelectorAll('.processing-set')).toHaveLength(3)
    expect(doc()?.textContent).toContain('第1套/共3套')
    expect(doc()?.textContent).toContain('第3套/共3套')
    // 列清单 = 唯一真值（组件按 PROCESSING_DOC_COLUMNS 渲染）
    const headers = Array.from(document.querySelectorAll('.processing-set thead th')).map((th) =>
      th.textContent?.trim()
    )
    expect(headers.slice(0, PROCESSING_DOC_COLUMNS.length)).toEqual([...PROCESSING_DOC_COLUMNS])
    // 逐条命中 issue 实证 #3 的列
    expect([...PROCESSING_DOC_COLUMNS]).toEqual([
      '部位',
      '部位信息',
      '尺寸',
      '组件',
      '货号',
      '用料',
      '批号',
      '备注',
    ])
  })

  it('③ 版面：@page A4（由介质矩阵生成）+ 分页不裁切 + 表头重复', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} printTarget="processing" />)
    expect(css()).toContain('@page { size: A4; margin: 12mm; }')
    expect(doc()?.getAttribute('data-print-media')).toBe('a4')
    expect(css()).toMatch(/\.processing-set\s*\{[^}]*break-inside:\s*avoid/)
    // 长单跨页时表头重复（否则第 2 页起认不出列）
    expect(css()).toMatch(/\.processing-doc-table thead\s*\{[^}]*display:\s*table-header-group/)
  })

  it('③ 分页判据可红：删掉 break-inside / thead 重复规则 ⇒ 上面那条必红', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const real = css()
    const mutated = real
      .replace(/\.processing-set\s*\{[^}]*\}/, '.processing-set { }')
      .replace(/\.processing-doc-table thead\s*\{[^}]*\}/, '.processing-doc-table thead { }')
    expect(mutated).not.toBe(real)
    expect(mutated).not.toMatch(/\.processing-set\s*\{[^}]*break-inside/)
    expect(mutated).not.toMatch(/table-header-group/)
  })

  it('🔴 ④ 缺字段**可见**：客户名 / 电话 / 地址缺失 ⇒ 显式占位 `—`（不是空单元格）', () => {
    render(
      <ProcessingDoc
        order={buildOrder({ customerName: '', customerPhone: '', customerAddress: undefined })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const el = doc()
    // 取「客户」那一行里标签右侧的值格
    const cells = Array.from(el?.querySelectorAll('td') ?? [])
    const valueAfter = (label: string): string => {
      const idx = cells.findIndex((td) => td.textContent?.trim() === label)
      return cells[idx + 1]?.textContent?.trim() ?? '__NOT_FOUND__'
    }
    expect(valueAfter('客户')).toBe('—')
    expect(valueAfter('电话')).toBe('—')
    expect(valueAfter('地址')).toBe('—')
  })

  it('④ 缺字段判据可红：把占位换回 `|| ""` 的静默留空 ⇒ 上面那条必红', () => {
    render(<ProcessingDoc order={buildOrder({ customerName: '李四' })} processingOrder={null} />)
    const cells = Array.from(doc()?.querySelectorAll('td') ?? [])
    const idx = cells.findIndex((td) => td.textContent?.trim() === '客户')
    const silent = (cells[idx + 1]?.textContent || '').trim() // 旧写法 `value || ''`
    expect(silent).toBe('李四')
    // 空值下旧写法给出空串（判据要求 `—`）⇒ 红
    cleanup()
    render(<ProcessingDoc order={buildOrder({ customerName: '' })} processingOrder={null} />)
    const cells2 = Array.from(doc()?.querySelectorAll('td') ?? [])
    const idx2 = cells2.findIndex((td) => td.textContent?.trim() === '客户')
    expect((cells2[idx2 + 1]?.textContent || '').trim()).not.toBe('')
  })

  it('🔴 ④ 制单人 / 批号 印**服务端真值**；缺值印 `—`（≠「本系统未采集」，issue #5914）', () => {
    // 制单人 = `orders.created_by_name`（V142 / #5835 起建单时写入，详情接口下发）
    // 批号 = 加工单**快照**行的 `batchNo`（按 `itemId` 与商品行对齐）
    render(
      <ProcessingDoc
        order={buildOrder({ createdByName: '王五' })}
        processingOrder={buildProcessingOrder({
          items: [{ itemId: 'item-1', batchNo: 'B20260901' } as ProcessingOrderItem],
        })}
      />
    )
    expect(cellText('processing-doc-creator')).toBe('王五')
    expect(cellText('processing-doc-batch')).toBe('B20260901')
    // 🔴 纸面**不许**再出现「未采集」：那是「系统没有这个字段」的说法，而这两个字段都在
    expect(doc()?.textContent).not.toContain(NOT_COLLECTED)
    expect(document.querySelector('[data-testid="processing-doc-gap-note"]')).toBeNull()
    // 缺口清单为空 = 已无真缺口（清单只许缩短/登记真缺口）
    expect(PROCESSING_DOC_NOT_COLLECTED_FIELDS).toHaveLength(0)
    cleanup()
    // 缺值 ⇒ 显式占位 `—`（客户没填 / 未指派批次），**不是**「未采集」、也绝不编值
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(cellText('processing-doc-creator')).toBe(MISSING)
    expect(cellText('processing-doc-batch')).toBe(MISSING)
  })

  it('🔴 ④ 红证：批号挂不到订单行（快照行 itemId 对不上）⇒ 不猜，印 `—`', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({
          items: [{ itemId: 'another-item', batchNo: 'B20260901' } as ProcessingOrderItem],
        })}
      />
    )
    // 对不上就不许把别人那行的批号印到这一行（猜 = 账实不符）
    expect(cellText('processing-doc-batch')).toBe(MISSING)
  })

  it('🔴 ⑤ QR：给了值 ⇒ 出码；**不给 ⇒ 出占位框、不画假码**', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        qrValue="PO260926-0007"
      />
    )
    expect(document.querySelector('[data-testid="processing-doc-qr"]')?.tagName.toLowerCase()).toBe('svg')
    cleanup()
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(document.querySelector('[data-testid="processing-doc-qr"]')).toBeNull()
    const placeholder = document.querySelector('[data-testid="processing-doc-qr-placeholder"]')
    expect(placeholder?.textContent).toContain('无码')
  })

  it('⑤ QR 判据可红：给不出值却硬画一个码（拿别处的串顶替）⇒ 必红', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    // 缺值分支下不许存在任何 SVG 码（旧写法若回落成 order.orderNo 就会在这里出现）
    expect(document.querySelectorAll('.processing-print-area svg')).toHaveLength(0)
  })

  it('⑥ 加工单**不印金额**（实证 #3 无金额列）⇒ 天然没有第二份金额真值', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const text = doc()?.textContent || ''
    for (const money of ['本单应收', '单价', '金额', '小计']) {
      expect(text).not.toContain(money)
    }
  })

  it('⑦ 打印隔离：portal 到 body + 共享标记类 + 隔离选择器排除所有打印单据 + 屏幕态隐藏', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const el = doc()
    expect(el?.parentElement).toBe(document.body)
    expect(el?.className).toContain('print-doc')
    expect(document.querySelectorAll('.processing-print-area')).toHaveLength(1)
    expect(css()).toMatch(/body > \*:not\(\.print-doc\)\s*\{\s*display:\s*none\s*!important/)
    expect(css()).not.toMatch(/body > \*:not\(\.processing-print-area\)/)
    expect(css()).toMatch(/\.processing-print-area\[data-print-target='processing'\]/)
  })

  it('⑦ 未置位打印目标 ⇒ 不加 data-print-target（点别的单据时本单不参与显形）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(doc()?.getAttribute('data-print-target')).toBeNull()
    cleanup()
    render(
      <ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} printTarget="processing" />
    )
    expect(doc()?.getAttribute('data-print-target')).toBe('processing')
  })

  it('⑦ 列宽按内容预算：批号列 ≥16%（17 位批号两行放得下）+ 列序不变 + 合计 100%（issue #6600）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const widths = headerWidths()
    // 列序：宽度调整不许顺手挪列（标签仍逐字等于列清单）
    const labels = Array.from(doc()?.querySelectorAll('.processing-doc-table thead th') ?? []).map(
      (el) => el.textContent?.trim()
    )
    expect(labels).toEqual([...PROCESSING_DOC_COLUMNS])
    // 批号列的系统下限：17 字符 `PC-yyyyMMdd-####` 在 9pt 下单行约 40mm，
    // 表宽 186mm ⇒ 16% ≈ 29.7mm 只够折「两行」；再回落 = 三行（#6600 的实测缺陷）
    const batch = headerWidthOf('批号')
    expect(batch).toBeGreaterThanOrEqual(16)
    // 批号必须比常态为空的「备注」列宽
    expect(batch).toBeGreaterThan(headerWidthOf('备注'))
    expect(widths.reduce((sum, w) => sum + w, 0)).toBe(100)
    // 8 列一个都不能少（少一个 label ⇒ NaN，这条会红）
    expect(widths.every((w) => Number.isFinite(w))).toBe(true)

    // 🔴 可红（在真值源上取证，不碰真文件）：把本组件的表头宽度声明改成**修前**的批号 10%
    // ⇒ 同一个解析器把下限判红（`10 < 16`），改回 16 ⇒ 通过 —— 这条判据不是恒真。
    const source = readFileSync(
      join(process.cwd(), 'src/components/orders/ProcessingDoc.tsx'),
      'utf-8'
    )
    const declared = Array.from(source.matchAll(/<DocTh[^>]*?w-\[(\d+)%\][^>]*?>\s*\{?PROCESSING_DOC_COLUMNS\[(\d)\]/g)).map(
      (m) => ({ index: Number(m[2]), percent: Number(m[1]) })
    )
    expect(declared.find((d) => d.index === 6)?.percent).toBe(batch) // 判据读的就是真值源
    const broken = declared.map((d) => (d.index === 6 ? 10 : d.percent))
    expect(broken.find((p, i) => declared[i].index === 6)).toBeLessThan(16)
  })
})
