// case_ids: UI-061
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// ProcessingDoc 经 `useCompanyName` 触到 `@/lib/api`（企业名回落读面）—— 这里打一个**部分**替身，
// 让 jsdom 落到「取不到 ⇒ 空串」分支，避免真发 XHR（噪音）。
// （收款码与本单据无关：加工单自 issue #7219 起不印二维码、销售单自 issue #7589 起不印收款码。）
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
 * ① 表头九栏逐条命中（订单日期 / 客户 / 电话 / 地址 / 备注 / 制单人 / 单号 / 交付日期 / 货运）；
 * ② **按套分块**，每块 `第N套/共M套` + 一张 **9 列表**（列清单 = `PROCESSING_DOC_COLUMNS`，全仓唯一一份）；
 * ③ `@page { size: A4; margin: 0; }`（由介质矩阵生成；边距 0 = 浏览器页眉页脚无处可画，
 *    版面内缩 12mm 由容器 padding 承担 —— issue #7309）+ 分页不裁切（`break-inside: avoid`）
 *    且长单分页时**表头重复**（`thead { display: table-header-group }`）；
 * ④ 🔴 **缺值不许静默留空**：一律显式占位 `—`；本系统**没有采集**的字段（制单人 / 批号）
 *    另标「未采集」——「客户没填」与「我们没有这个列」必须可区分；
 * ⑤ 🔴 **纸面不印 QR**（issue #7219：扫码入口不属于加工单）—— QR / 无码占位 / 可读短码行三种形态**都不出现**；
 * ⑥ 打印隔离沿用 #4983 / #4965 范式（共享 `print-doc` + 限定本次打印目标的 visibility 防御）；
 * ⑦ **列宽按内容预算**（issue #6600）：批号是**固定 17 字符**的 `PC-yyyyMMdd-####`，原先只给 10%
 *    ⇒ `table-layout: fixed` 下折成 3 行、把数据行撑高（真浏览器实测 63px）。现在 ≥16%（两行放得下）；
 * ⑧ 🔴 **纸面不印工序清单**（issue #7274）：工序细节不上纸（老调用方形态传进来的 `operations` 也不得渲染）——
 *    见文件尾「ProcessingDoc 纸面不印工序（issue #7274）」。
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
/** 9 列表头声明的宽度百分比（按表头顺序） */
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
    // 判据面 = 9 列表的**用料列**（index 5，唯一由「数量是否算得出」决定的那一格）
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
    // 🔴 issue #7309：A4 的 `@page` 边距是 **0**（浏览器把页眉页脚画在页边距里，够大就照画），
    // 版面内缩 12mm 由容器 padding 承担（下一行的断言）。
    expect(css()).toContain('@page { size: A4; margin: 0; }')
    expect(css()).toMatch(/\.processing-print-area\[data-print-target='processing'\]\s*\{[^}]*padding:\s*12mm/)
    // 内缩必须**逐页重复**（第 2 页起也留边；不 clone ⇒ 内容贴到纸边）
    expect(css()).toContain('box-decoration-break: clone')
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

  it('🔴 ⑤ 加工单**不再印 QR**（issue #7219：扫码入口不属于加工单）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ short_code: SHORT_CODE, scan_url: SCAN_URL })}
      />
    )
    // QR / 无码占位 / 短码行三种形态**都不出现**（移除是整块移除，不是隐藏）
    expect(document.querySelector('[data-testid="processing-doc-qr"]')).toBeNull()
    expect(document.querySelector('[data-testid="processing-doc-qr-placeholder"]')).toBeNull()
    expect(document.querySelector('[data-testid="processing-doc-short-code"]')).toBeNull()
  })

  it('加工单**不印金额**（实证 #3 无金额列）⇒ 天然没有第二份金额真值', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const text = doc()?.textContent || ''
    for (const money of ['本单应收', '单价', '金额', '小计']) {
      expect(text).not.toContain(money)
    }
  })

  it('⑥ 打印隔离：portal 到 body + 共享标记类 + 隔离选择器排除所有打印单据 + 屏幕态隐藏', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const el = doc()
    expect(el?.parentElement).toBe(document.body)
    expect(el?.className).toContain('print-doc')
    expect(document.querySelectorAll('.processing-print-area')).toHaveLength(1)
    expect(css()).toMatch(/body > \*:not\(\.print-doc\)\s*\{\s*display:\s*none\s*!important/)
    expect(css()).not.toMatch(/body > \*:not\(\.processing-print-area\)/)
    expect(css()).toMatch(/\.processing-print-area\[data-print-target='processing'\]/)
  })

  it('⑥ 未置位打印目标 ⇒ 不加 data-print-target（点别的单据时本单不参与显形）', () => {
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
 * 纸面**不印**工序清单（issue #7274，用户 2026-10-18 逐字「工序细节不用在打印单上，
 * 移除掉工序相关的表格信息」）。
 *
 * 判据形态 = **回归探针**：按 issue #6901 时代的调用方形态把 `operations` 传进来（TS 面上已退场），
 * 纸面必须**零**工序节点。若有人把工序块接回纸面 ⇒ 本文件立即红。
 */
describe('ProcessingDoc 纸面不印工序（issue #7274）', () => {
  it('🔴 旧调用方仍传工序实例 ⇒ 纸面也**零**工序表 / 工序行 / 工序文案', () => {
    // 旧 props 形态（issue #6901 的 `operations`）—— TS 面上已不存在，这里按旧调用方**照原样**传，
    // 让「重新接回纸面」这件事可被判红（而不是只靠注释约定）。
    const legacyCaller = { operations: [buildPosition()] } as unknown as Record<string, never>
    render(
      <ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} {...legacyCaller} />
    )
    const el = doc()
    expect(el?.querySelector('[data-testid="processing-doc-operations"]')).toBeNull()
    expect(el?.querySelectorAll('[data-testid="processing-doc-operation"]')).toHaveLength(0)
    const text = el?.textContent || ''
    // 工序实例里的显示名 / 状态 / 列标签一律不上纸（`韩褶` 是**工艺**值，纸面本该有，故不列）
    for (const forbidden of ['工序', '精裁', '应做', '待做']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('🔴 起算点自证：纸面正文照旧渲染（上面那条不是「纸面整个没了」的空跑）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const text = doc()?.textContent || ''
    expect(text).toContain('布艺遮光帘A')
    expect(text).toContain('工艺')
    expect(text).not.toContain('工序')
  })
})

/**
 * 数量列的单位随行（issue #6901）—— 列名与值**同出**
 * `frontend/admin-web/src/lib/order-item-sku.ts::orderItemQuantity()`（口径收敛一处）。
 */
describe('ProcessingDoc 数量列单位（issue #6901）', () => {
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
})
