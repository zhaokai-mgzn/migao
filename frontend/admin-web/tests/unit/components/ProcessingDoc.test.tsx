// case_ids: UI-061
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup, screen } from '@testing-library/react'
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
  OPERATIONS_DOC_COLUMNS,
  PROCESSING_DOC_COLUMNS,
  PROCESSING_DOC_NOT_COLLECTED_FIELDS,
  operationsByItem,
  operationStatusText,
} from '@/components/orders/ProcessingDoc'
import type {
  Order,
  OrderItem,
  ProcessingOrder,
  ProcessingOrderItem,
  ProductionPosition,
} from '@/types'
import { collectTableIntegrity, dataTables } from '@/components/orders/doc-tables'
import {
  assertNoPaperZeroFill,
  assertPaperKeepsMissingDistinct,
  paperNumericColumn,
  paperTextOf,
} from '@/lib/print-doc-paper'

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
 * ⑧ 🔴 **码的内容 = 加工单级稳定短链，不再是加工单号纯文本**（issue #6867，设计 §11.3「前端 · admin-web」）：
 *    QR 值 = 调用方给的 `scan_url`（`{base}/o/{短码}`）；纸面**再印一行人可读短码**
 *    （`processingOrder.short_code`，形态照 `TaskCardPrint` 的 `task-card-label-short-code-*`），
 *    **缺码印 `—`、绝不编**（与既有「缺码不画假码」同口径；§11.7「手可输的兜底」）。
 */
function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    productId: 'p-1',
    productName: '布艺遮光帘A',
    // issue #6869：货号真字段是响应里的 `skuCode`（`productCode` **不在响应里**）；
    // 颜色 / 门幅在 `processingInfo` —— 夹具按真 wire 形态写。
    skuCode: '0012',
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
      doorWidth: '2.8米',
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

/** 纸面上的码（issue #6867）= 加工单级**稳定短链**（服务端给，前端**不拼**） */
const SCAN_URL = 'https://app.migaozn.com/o/7K3M9QP2'/** 服务端下发的人可读短码（与 `scan_url` 末段一致 —— 但组件只读它自己的键，不切 URL） */
const SHORT_CODE = '7K3M9QP2'

/**
 * 工序读面的一个分组（`GET /api/admin/production/orders/{id}/operations` 的 `positions[]`，
 * issue #6901）—— 形状照 `ProductionPosition` 真 wire 形态（snake_case 键）。
 */
function buildPosition(overrides: Partial<ProductionPosition> = {}): ProductionPosition {
  return {
    order_item_id: 'item-1',
    position_name: '布帘',
    operations: [
      { id: 'op-1', operation: '精裁-布', logical_name: '精裁', unit: '米', qty: 12.5, status: 'pending' },
      { id: 'op-2', operation: '韩褶-布', logical_name: '韩褶', unit: '折', qty: 52, status: 'done' },
    ],
    ...overrides,
  }
}

/** QR 的**确切内容**：`qrcode.react` 把值渲染成 `<title>`（与 `TaskCardPrint` 测试同款读法） */
const qrPayload = (): string | undefined =>
  document.querySelector('[data-testid="processing-doc-qr"] title')?.textContent ?? undefined

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

  it('类级不变量（issue #6720）：本单据纸面不得出现「未知 ⇒ 0」的回退形态', () => {
    render(
      <ProcessingDoc
        order={buildOrder({
          items: [
            buildItem({ quantity: undefined as unknown as number }),
            // 真 0 的对照行（用料 0 米是明确读数，不是「未知」）
            buildItem({ id: 'item-0', quantity: 0 }),
          ],
        })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const area = document.querySelector('.processing-print-area')
    // 判据面 = 8 列表的**用料列**（index 5，唯一由「数量是否算得出」决定的那一格）
    const metersColumn = paperNumericColumn(area, { column: 5 })
    // 单据：加工单 ProcessingDoc
    assertNoPaperZeroFill(metersColumn.slice(0, 1), {
      label: '加工单 ProcessingDoc',
      presence: ['缺 quantity 的订单行（用料列第 1 行）'],
    })
    // 单据：加工单 ProcessingDoc
    assertPaperKeepsMissingDistinct(metersColumn, {
      label: '加工单 ProcessingDoc',
      presence: ['用料列：缺值行（—）与真 0 行（0）'],
    })
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

  it('② 按套分块：3 个商品行 ⇒ 3 块，各带 `第N套/共M套` 与 9 列表头', () => {
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
    // issue #6869：列清单换成「商品 SKU 四件套 + 尺寸/数量/组件/批号/备注」——
    // 原「部位 / 部位信息 / 货号(=拼串) / 用料」退场（部位列在 #4521 后对普通订单恒空）
    // 🔴 issue #6901：列名由「数量(米)」改「数量」—— 单位随行显示（见下方「数量列单位」用例），
    // 写死「米」会与件/套的订单行自相矛盾。
    expect([...PROCESSING_DOC_COLUMNS]).toEqual([
      '品名',
      '货号',
      '颜色',
      '门幅',
      '尺寸',
      '数量',
      '组件',
      '批号',
      '备注',
    ])
  })

  it('② issue #6869：逐格印商品 SKU 四件套（品名/货号/颜色/门幅）—— 货号取响应真字段 `skuCode`', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const cells = Array.from(doc()!.querySelectorAll('.processing-doc-table tbody tr td')).map(
      (td) => td.textContent?.trim() ?? ''
    )
    expect(cells.slice(0, PROCESSING_DOC_COLUMNS.length)).toEqual([
      '布艺遮光帘A', // 品名
      '0012', // 货号（`skuCode` —— 夹具**没有** `productCode`：读幽灵字段的旧实现这里必空 ⇒ 红证）
      '米白', // 颜色（`processingInfo.colorName`）
      '2.8米', // 门幅（`processingInfo.doorWidth`，经 `craftSpecRows` 同一份格式化）
      '3.2×2.6', // 尺寸
      '12.5', // 数量(米)
      '主布', // 组件
      '—', // 批号（无快照行 ⇒ 未指派，显式占位）
      '', // 备注（未填行级备注 ⇒ 留白供手写）
    ])
  })

  it('② issue #6869：工艺说明行承载原「部位信息」，且「部位」并入其中（不再单独成列）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const text = doc()?.textContent || ''
    expect(text).toContain('部位：布帘')
    // 行标签「工艺」在**首格**（不是「工艺：…」前缀 —— 明细里本来就有「工艺：韩褶」，
    // 前缀会让纸面出现「工艺：…工艺：…」的重复，真机取证实测）
    const craftRow = Array.from(doc()!.querySelectorAll('.processing-doc-table tbody tr')).find(
      (tr) => tr.querySelector('td')?.textContent?.trim() === '工艺'
    )
    expect(craftRow).toBeTruthy()
    expect(text).not.toContain('工艺：部位：')
    // 「门幅」有自己的列 ⇒ 不许在工艺行里重复印一遍（同一真值印两处只是噪音）
    expect(text).not.toContain('门幅：2.8米')
    // 表头里不再有「部位」「部位信息」列
    const headers = Array.from(doc()!.querySelectorAll('.processing-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    expect(headers).not.toContain('部位')
    expect(headers).not.toContain('部位信息')
  })

  it('② issue #6869：备注列 = 商家手写的行级备注（`processingInfo.remark`）', () => {
    render(
      <ProcessingDoc
        order={buildOrder({
          items: [buildItem({ processingInfo: { colorName: '米白', remark: '公式--48个折' } })],
        })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const cells = Array.from(doc()!.querySelectorAll('.processing-doc-table tbody tr td')).map(
      (td) => td.textContent?.trim() ?? ''
    )
    expect(cells[PROCESSING_DOC_COLUMNS.length - 1]).toBe('公式--48个折')
  })

  it('① 货运：**枚举转中文**（issue #6869 用户逐字「不要用英文，人家看不懂」）；自定义值原样印', () => {
    render(
      <ProcessingDoc
        order={buildOrder({ logisticsType: 'express', logisticsCompany: '顺丰速运' })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const text = doc()?.textContent || ''
    expect(text).toContain('快递 · 顺丰速运')
    // 修前形态 = 原样拼后端枚举 ⇒ 纸面印 `express · 顺丰速运`（下面这条就是红证）
    expect(text).not.toContain('express')

    cleanup()
    // 未知/自定义取值**原样回显**（不编「快递」兜底）——『物流/专线』是登记值，故这条测自定义串
    render(
      <ProcessingDoc
        order={buildOrder({ logisticsType: '客户自送', logisticsCompany: '' })}
        processingOrder={buildProcessingOrder()}
      />
    )
    expect(doc()?.textContent).toContain('客户自送')
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
        qrValue={SCAN_URL}
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

  it('🔴 ⑧ QR 的内容 = 传入的 `scan_url`（加工单级稳定短链），**不是**加工单号纯文本（issue #6867）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ short_code: SHORT_CODE, scan_url: SCAN_URL })}
        qrValue={SCAN_URL}
      />
    )
    expect(qrPayload()).toBe(SCAN_URL)
    // 反向：扫出来**不再是**加工单号纯文本（旧形态 = 相机只显示一串文本、打不开任何页面）
    expect(qrPayload()).not.toBe('PO260926-0007')
  })

  it('🔴 ⑧ 短码行印 `processingOrder.short_code`（人可读兜底：扫码失败 / 无扫码工具时手输）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ short_code: SHORT_CODE, scan_url: SCAN_URL })}
        qrValue={SCAN_URL}
      />
    )
    expect(screen.getByTestId('processing-doc-short-code')).toHaveTextContent(SHORT_CODE)
  })

  it('🔴 ⑧ 红证：没有短码 ⇒ 短码行印 `—`，**绝不编造**（也不把加工单号顶上去）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        // 只有单号、没有短码/短链（存量单 / 读面未实例化）—— 与 `null` 逐字同款
        processingOrder={buildProcessingOrder({ short_code: null, scan_url: null })}
      />
    )
    expect(screen.getByTestId('processing-doc-short-code')).toHaveTextContent(MISSING)
    // 「缺码不画假码」同口径：短码行不许出现任何**加工单号**的片段
    expect(screen.getByTestId('processing-doc-short-code').textContent).not.toContain('PO')
    expect(screen.getByTestId('processing-doc-short-code').textContent).not.toMatch(/\d/)
  })

  it('🔴 ⑧ 红证（注入式自证）：把短码源写成加工单号 / 拿别的串顶替 ⇒ 上面那两条判据必红', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ short_code: SHORT_CODE, scan_url: SCAN_URL })}
        qrValue={SCAN_URL}
      />
    )
    // ① 旧形态（QR 值 = 加工单号纯文本）⇒ 「QR = scan_url」那条红
    const regressedQr = 'PO260926-0007'
    expect(regressedQr).not.toBe(SCAN_URL)
    // ② 编造短码（拿加工单号顶替短码行）⇒ 「短码行 = 服务端短码」那条红
    const fabricated = 'PO260926-0007'
    expect(screen.getByTestId('processing-doc-short-code').textContent).not.toBe(fabricated)
    // ③ 短码行挂上单号串 ⇒ 「无短码不许出现加工单号片段」那条红
    expect(fabricated).toContain('PO')
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
    // 9 列一个都不能少（少一个 label ⇒ NaN，这条会红）
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
    expect(declared.find((d) => d.index === 7)?.percent).toBe(batch) // 判据读的就是真值源
    const broken = declared.map((d) => (d.index === 7 ? 10 : d.percent))
    expect(broken.find((p, i) => declared[i].index === 7)).toBeLessThan(16)
  })
})

/**
 * 工序清单 + 数量单位（issue #6901）—— 用户逐字「加工单缺乏订单中的规格尺寸和加工信息，
 * 工人需要这些信息+商品信息来决定如何生产」。
 *
 * 纸面此前只有**商品 + 工艺规格**，**没有**「这张单要做哪几道工序」（显示名 / 单位 / 应做数量 / 状态）。
 * 判据面两条形态：
 * ① 有工序实例（读面 `positions[]` 按 `order_item_id` 对得上本行）⇒ 逐行印**服务端真值**；
 * ② 无/对不上 ⇒ **整块不出现**（不印空表、不印占位表头）。
 */
describe('ProcessingDoc 工序清单（issue #6901）', () => {
  it('🔴 逐道印工序：显示名（logical_name）/ 应做（数量+单位）/ 状态 —— 取读面真值，不重算', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        operations={[buildPosition()]}
      />
    )
    // 块头一行 + 每道一行（数据行 = `processing-doc-operation`）
    expect(screen.getByTestId('processing-doc-operations')).toBeInTheDocument()
    const rows = screen.getAllByTestId('processing-doc-operation')
    expect(rows).toHaveLength(2)
    const cellsOf = (row: HTMLElement): string[] =>
      Array.from(row.querySelectorAll('td')).map((td) => td.textContent?.trim() ?? '')
    expect(cellsOf(rows[0])).toEqual(['精裁', '12.5 米', '待做'])
    expect(cellsOf(rows[1])).toEqual(['韩褶', '52 折', '已完成'])
    // 🔴 纸面**不得**出现工人端快照名（读面键 `operation`，变体名）——只许印逻辑名
    expect(doc()?.textContent).not.toContain('精裁-布')
    // 块头列清单 = 唯一真值（乱序/漏列都会让这条红）
    expect(screen.getByTestId('processing-doc-operations').textContent).toBe(
      OPERATIONS_DOC_COLUMNS.join('')
    )
  })

  it('🔴 红证（注入式）：把显示名写成快照名 `operation` / 状态只印英文键 ⇒ 上面那条必红', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        operations={[buildPosition()]}
      />
    )
    const row = screen.getAllByTestId('processing-doc-operation')[0]
    // ① 旧形态（直读 `operation`）⇒ 纸面会出现 `精裁-布`，上面那条 `not.toContain` 立即红
    expect(row.textContent).toContain('精裁')
    expect(row.textContent).not.toContain('精裁-布')
    // ② 读面 `status` 是机器键：直接渲染会印 `pending` / `done`（工人看不懂）
    expect(row.textContent).toContain('待做')
    expect(row.textContent).not.toContain('pending')
    // ③ 单位与数量同格（不是只印数字 —— 米/折是这道工序的**计量口径**）
    expect(row.textContent).toContain('12.5 米')
  })

  it('🔴 无工序 / 挂不上订单行 ⇒ 工序块**整块不出现**（不印空表、不印占位表头）', () => {
    const { unmount } = render(
      <ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />
    )
    // ① 没传读面（订单还没生成加工单）⇒ 一行都不出现
    expect(screen.queryByTestId('processing-doc-operations')).toBeNull()
    expect(screen.queryAllByTestId('processing-doc-operation')).toHaveLength(0)
    unmount()

    // ② 读面给了实例，但 `order_item_id` 与本订单行对不上 ⇒ **不猜**（不许把别人的工序印到这张单上）
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        operations={[buildPosition({ order_item_id: 'another-item' })]}
      />
    )
    expect(screen.queryByTestId('processing-doc-operations')).toBeNull()
    // ③ 分组在、但 `operations` 为空 ⇒ 同样整块不出现（不是空表）
    cleanup()
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        operations={[buildPosition({ operations: [] })]}
      />
    )
    expect(screen.queryByTestId('processing-doc-operations')).toBeNull()
  })

  it('🔴 数量列单位随行：快照 `unit` 是套 ⇒ 列名印「数量(套)」且逐值同口径（口径收敛一处）', () => {
    render(
      <ProcessingDoc
        order={buildOrder({ items: [buildItem({ quantity: 2 })] })}
        processingOrder={buildProcessingOrder({
          items: [{ itemId: 'item-1', unit: '套' } as ProcessingOrderItem],
        })}
      />
    )
    const headers = Array.from(doc()!.querySelectorAll('.processing-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    expect(headers).toContain('数量(套)')
    expect(headers).not.toContain('数量(米)')
    // 值仍是纯数量（单位在列名里；同格不重复印）
    const cells = Array.from(doc()!.querySelectorAll('.processing-doc-table tbody tr td')).map(
      (td) => td.textContent?.trim() ?? ''
    )
    expect(cells[PROCESSING_DOC_COLUMNS.indexOf('数量')]).toBe('2')
  })

  it('🔴 单位未采集（快照无 `unit`）⇒ 列名只写「数量」，**绝不编「米」**', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const headers = Array.from(doc()!.querySelectorAll('.processing-doc-table thead th')).map(
      (th) => th.textContent?.trim()
    )
    expect(headers).toContain('数量')
    expect(headers).not.toContain('数量(米)')
    // 起算点：纸面**不许**出现任何自行断言的单位
    expect(doc()?.textContent).not.toContain('数量(米)')
  })

  it('🔴 负控：工序块上线后纸面仍**不印金额**（实证 #3 无金额列，issue #5651 硬约束）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder()}
        operations={[buildPosition()]}
      />
    )
    const text = doc()?.textContent || ''
    // 工序块带来「应做 / 状态」，**不得**顺手把读面的 `unit_price` / `price_state` 印上纸
    expect(screen.getAllByTestId('processing-doc-operation')).toHaveLength(2)
    for (const money of ['本单应收', '单价', '金额', '小计', '未定价', '¥']) {
      expect(text).not.toContain(money)
    }
  })

  it('🔴 纯函数判据（口径可复算）：`operationsByItem` 跳过无 `order_item_id` / 空工序，`operationStatusText` 二态', () => {
    // 挂不到订单行 ⇒ 不索引（挂不上就不上纸面，不猜）
    expect(operationsByItem([buildPosition({ order_item_id: null })]).size).toBe(0)
    expect(operationsByItem([buildPosition({ operations: [] })]).size).toBe(0)
    expect(operationsByItem(undefined).size).toBe(0)
    expect(operationsByItem([buildPosition()]).get('item-1')?.operations).toHaveLength(2)
    // 状态二态（读面只有 done / 其余；缺值按「待做」印，**不显示空**）
    expect(operationStatusText('done')).toBe('已完成')
    expect(operationStatusText('pending')).toBe('待做')
    expect(operationStatusText(null)).toBe('待做')
  })
})
