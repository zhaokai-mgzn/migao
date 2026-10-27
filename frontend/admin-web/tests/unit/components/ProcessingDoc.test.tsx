// case_ids: UI-061
// @vitest-environment jsdom

import { describe, it, expect, vi } from 'vitest'
import { render, cleanup, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// ProcessingDoc 经 `useCompanyName` 触到 `@/lib/api`（企业名回落读面）—— 这里打一个**部分**替身，
// 让 jsdom 落到「取不到 ⇒ 空串」分支，避免真发 XHR（噪音）。
// （收款码与本单据无关：加工单纸面的码是**服务端下发的** `scan_url`（qrcode.react 纯 SVG，不取图）；
//  销售单自 issue #7589 起不印收款码。）
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
 * ② **按套分块**，每块 `第N套/共M套` + 一张 **6 列表**（列清单 = `PROCESSING_DOC_COLUMNS`，全仓唯一一份）；
 *    🔴 **两型同版式**（issue #7901 面料单 → issue #7909 加工单，用户 2026-10-27 两句裁定）：
 *    「品名」列 /「帘种」列 /「尺寸」列 /「工艺」行**都不再上纸**；
 * ③ `@page { size: A4; margin: 0; }`（由介质矩阵生成；边距 0 = 浏览器页眉页脚无处可画，
 *    版面内缩 12mm 由容器 padding 承担 —— issue #7309）+ 分页不裁切（`break-inside: avoid`）
 *    且长单分页时**表头重复**（`thead { display: table-header-group }`）；
 * ④ 🔴 **缺值不许静默留空**：一律显式占位 `—`；本系统**没有采集**的字段（制单人 / 批号）
 *    另标「未采集」——「客户没填」与「我们没有这个列」必须可区分；
 * ⑤ 🔴 **左上角扫码报工码**（issue #7891：由销售单迁入，用户 2026-10-27 逐字「把销售单左上角的
 *    扫码报工二维码迁移到加工单打印上」）—— 有码 ⇒ 出图且码值**逐字** = 服务端 `scan_url`、
 *    竖排「扫码报工」；无码 ⇒ 码 / 占位框 / 短码行三种形态**都不出现**；短码一律不上纸（issue #7608）；
 * ⑤b 🔴 **纸面标题按作业单两型**（issue #7891）：成品帘 ⇒「加工单」、面料单 ⇒「面料单」
 *    （用户逐字「面料单就叫面料单，不要叫裁剪单」）；缺键 ⇒ 加工单（存量单口径）；
 * ②b 🔴 **「工艺」行已整行退场**（issue #7909，用户 2026-10-27 逐字「加工单也要移除」）——
 *    原先是水洗唛式一行一条 `标签：值`（issue #7891）；现在两型纸面都不印工艺规格，
 *    车间认「定高买宽 / 双开 / 定型」看**水洗唛**或**屏幕**（生产明细页 / 加工单块）；
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

/** 纸面标题那一格（`tracking-[0.5em]` = 全单据唯一一处标题排版） */
const docTitle = (): string =>
  (
    Array.from(doc()?.querySelectorAll('div') ?? []).find((el) => el.className.includes('tracking-[0.5em]'))
      ?.textContent ?? ''
  ).trim()

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
    // 判据面 = 正文表的**数量列**（唯一由「数量是否算得出」决定的那一格）——
    // 下标**现取**列清单（issue #7901 / #7909 删了三列，写死 6 会指到别处 ⇒ 判据静默空跑）
    const metersColumn = paperNumericColumn(area, { column: PROCESSING_DOC_COLUMNS.indexOf('数量') })
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

  it('② 按套分块：3 个商品行 ⇒ 3 块，各带 `第N套/共M套` 与 6 列表头', () => {
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
    // issue #6869：列清单换成「商品身份 + 数量/批号/备注」；
    // 🔴 issue #6901：列名由「数量(米)」改「数量」—— 单位随行显示（见下方「数量列单位」用例），
    // 写死「米」会与件/套的订单行自相矛盾。
    // 🔴 issue #7901 / #7909（用户 2026-10-27 两句裁定）：品名 / 帘种 / 尺寸 三列退场 ⇒ 9 列变 6 列。
    expect([...PROCESSING_DOC_COLUMNS]).toEqual(['货号', '颜色', '门幅', '数量', '批号', '备注'])
  })

  it('② issue #6869：逐格印商品身份（货号 / 颜色 / 门幅）—— 货号取响应真字段 `skuCode`', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const cells = Array.from(doc()!.querySelectorAll('.processing-doc-table tbody tr td')).map(
      (td) => td.textContent?.trim() ?? ''
    )
    expect(cells.slice(0, PROCESSING_DOC_COLUMNS.length)).toEqual([
      '0012', // 货号（`skuCode` —— 夹具**没有** `productCode`：读幽灵字段的旧实现这里必空 ⇒ 红证）
      '米白', // 颜色（`processingInfo.colorName`）
      '2.8米', // 门幅（`processingInfo.doorWidth`，经 `craftSpecRows` 同一份格式化）
      '12.5', // 数量(米)
      '—', // 批号（无快照行 ⇒ 未指派，显式占位）
      '', // 备注（未填行级备注 ⇒ 留白供手写）
    ])
  })

  it('🔴 帘种不上纸（issue #7909）：帘种列退场 —— 表头没有「帘种」、纸面也不出现「纱帘」', () => {
    render(
      <ProcessingDoc
        order={buildOrder({
          items: [
            buildItem({
              id: 'item-sheer',
              processingInfo: { curtainType: '纱帘', colorName: '象牙白', doorWidth: '3.0米' },
            }),
          ],
        })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const headers = Array.from(doc()?.querySelectorAll('.processing-doc-table thead th') ?? []).map(
      (th) => th.textContent?.trim()
    )
    expect(headers).not.toContain('帘种')
    // 值也不许从别的格子漏出来（旧实现有独立的 `processing-doc-curtain-type` 格）
    expect(doc()?.textContent).not.toContain('纱帘')
    expect(document.querySelector('[data-testid="processing-doc-curtain-type"]')).toBeNull()
  })

  it('🔴 加工费组合行（issue #7833）：每套块内单列一行，逐字印快照 `processingItems[].name`（超高/倒幅）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={
          {
            ...buildProcessingOrder(),
            items: [
              {
                itemId: 'item-1',
                processingItems: [
                  { id: 'pi-1', name: '韩褶', quantity: 1 },
                  { id: 'pi-14', name: '超高', quantity: 1 },
                  { id: 'pi-16', name: '倒幅', quantity: 1 },
                  { id: 'pi-3', name: '定型', quantity: 1 },
                ],
              },
            ],
          } as unknown as ProcessingOrder
        }
      />
    )
    // 用户要的就是这半句：加工单上有超高/倒幅
    expect(cellText('processing-doc-combo')).toBe('韩褶、超高、倒幅、定型')
    const row = Array.from(doc()?.querySelectorAll('.processing-doc-table tr') ?? []).find(
      (tr) => tr.querySelector('td')?.textContent?.trim() === '加工费组合'
    )
    expect(row).toBeTruthy()
    // 长值由 DocTd 的 break-words 折行印全文（不裁切 —— 与「纸面不藏字」同口径）
    const valueCell = row!.querySelectorAll('td')[1]
    expect(valueCell?.className).toContain('break-words')
  })

  it('🔴 加工费组合缺值 ⇒ 整行不渲染（存量单没有快照项 ≠ 印一个空壳行）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(cellText('processing-doc-combo')).toBe('')
    expect(doc()?.textContent).not.toContain('加工费组合')
  })

  it('🔴 纸面不印「工艺」行（issue #7909，用户 2026-10-27 逐字「加工单也要移除」）', () => {
    // 🔴 改判说明：本组原先是**正面**判据（一行一条 `标签：值` / 特殊选项独立成行 / 取值源优先快照行）。
    // 工艺行退场后那三条正面断言会变成缺陷的守护者 ⇒ 整组改为**反向**：节点取不到 + 值一个字都不印。
    render(
      <ProcessingDoc
        order={buildOrder({
          items: [
            buildItem({
              processingInfo: { colorName: '米白', craft: '韩褶', specialOptions: ['防翘扣', '花边'] },
            }),
          ],
        })}
        processingOrder={buildProcessingOrder({
          items: [{ itemId: 'item-1', craft: '快照侧工艺' } as unknown as ProcessingOrderItem],
        })}
      />
    )
    expect(document.querySelector('[data-testid="processing-doc-craft"]')).toBeNull()
    // 快照行 / 订单行都带齐了工艺键，纸面仍一个字都不印
    expect(doc()?.textContent).not.toContain('加工方式')
    expect(doc()?.textContent).not.toContain('特殊选项')
    expect(doc()?.textContent).not.toContain('加工类型')
    expect(doc()?.textContent).not.toContain('韩褶')
    expect(doc()?.textContent).not.toContain('快照侧工艺')
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

  it('🔴 ⑤ 左上角扫码报工码（issue #7891：由销售单迁入）—— 有码 ⇒ 出图、码值逐字 = `scan_url`、竖排标签', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ short_code: SHORT_CODE, scan_url: SCAN_URL })}
      />
    )
    const qr = document.querySelector('[data-testid="processing-doc-qr"]')
    // 🔴 具体值断言（不是「存在即可」）：码块必须是**这一个** testid 的元素，
    // 且里面真的有一张 `QRCodeSVG`（弱断言 = 空判据，growth gate 会红）
    expect(qr?.getAttribute('data-testid')).toBe('processing-doc-qr')
    expect(qr?.querySelector('svg')).not.toBeUndefined()
    // 码值**逐字** = 服务端下发的 `scan_url`（qrcode.react 把 value 写进 `<svg><title>`；
    // 前端不拼域名 / 路径段 ⇒ 这里断言的是「印出来的就是服务端给的那一串」）
    expect(document.querySelector('[data-testid="processing-doc-qr-svg"] title')?.textContent).toBe(SCAN_URL)
    // 竖排「扫码报工」（issue #7608）：横向只占一行字宽 —— 竖排是**机制**，不是装饰
    const label = document.querySelector('[data-testid="processing-doc-qr-label"]') as HTMLElement | null
    expect(label?.textContent).toBe('扫码报工')
    expect(label?.style.writingMode).toBe('vertical-rl')
    // 位置 = **表头左上角**、与抬头并排：码块与标题栏是同一行的两个子块，码在前
    const headerBlock = qr?.parentElement
    expect(headerBlock?.children).toHaveLength(2)
    expect(headerBlock?.firstElementChild).toBe(qr)
    expect(headerBlock?.lastElementChild?.textContent).toContain('加工单')
    // 🔴 短码不上纸（issue #7608，用户 2026-10-24 逐字「不要在产品上体现短码了」）：
    // 判据面 = 纸面**可读文字**（`paperTextOf` 已剥掉 `<style>` / `<svg>` —— svg 里那串是码值本身）
    expect(paperTextOf(doc())).toContain('扫码报工')
    expect(paperTextOf(doc())).not.toContain(SHORT_CODE)
    // 起算点自证：这张纸真的画出来了（上面几条不是空跑）
    expect(doc()?.textContent).toContain('张三')
  })

  it('🔴 ⑤ 无 `scan_url` ⇒ 整块不出现（不画占位框、不印短码、不回落加工单号）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ short_code: SHORT_CODE, scan_url: null })}
      />
    )
    // 码 / 占位框 / 短码行三种形态**都不出现**（缺码不画假码：占位框会让人以为「扫得出来」）
    expect(document.querySelector('[data-testid="processing-doc-qr"]')).toBeNull()
    expect(document.querySelector('[data-testid="processing-doc-qr-placeholder"]')).toBeNull()
    expect(document.querySelector('[data-testid="processing-doc-short-code"]')).toBeNull()
    expect(doc()?.textContent).not.toContain('扫码报工')
    expect(paperTextOf(doc())).not.toContain(SHORT_CODE)
    // 起算点自证：纸面照旧渲染（不是「纸面整个没了」的空跑）
    expect(doc()?.textContent).toContain('PO260926-0007')

    // 没有作业单读面（存量 / 读面没取到）⇒ 同样不出现
    cleanup()
    render(<ProcessingDoc order={buildOrder()} processingOrder={null} />)
    expect(document.querySelector('[data-testid="processing-doc-qr"]')).toBeNull()
  })

  it('🔴 ⑤b 纸面标题按作业单两型：`order_kind=processing`（成品帘）⇒「加工单」', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ order_kind: 'processing' })}
      />
    )
    expect(docTitle()).toBe('加工单')
    expect(doc()?.textContent).not.toContain('面料单')
  })

  it('🔴 ⑤b 纸面标题：`order_kind=outbound`（面料单）⇒「面料单」（用户逐字「不要叫裁剪单」）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ order_kind: 'outbound' })}
      />
    )
    // 用户 2026-10-27 逐字「面料单就叫面料单，不要叫裁剪单」⇒ 纸名逐字判
    expect(docTitle()).toBe('面料单')
    expect(doc()?.textContent).not.toContain('裁剪单')
    // 也不能印成「加工单」（那是成品帘的纸名；同一份纸按两型给名，不是两个名字都能用）
    expect(docTitle()).not.toBe('加工单')
  })

  it('🔴 ⑤b 纸面标题：`order_kind` 缺键（存量单）⇒「加工单」（与 `orderKindOf` 同一把尺）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(docTitle()).toBe('加工单')
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
    // 6 列一个都不能少（少一个 label ⇒ NaN，这条会红）
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
    // 🔴 issue #7909：列序变了 ⇒ 批号的下标**现取**（写死 7 = 下次改列序时这条判据静默空跑）
    const batchIdx = PROCESSING_DOC_COLUMNS.indexOf('批号')
    expect(batchIdx).toBeGreaterThanOrEqual(0)
    expect(declared.find((d) => d.index === batchIdx)?.percent).toBe(batch) // 判据读的就是真值源
    const broken = declared.map((d) => (d.index === batchIdx ? 10 : d.percent))
    expect(broken.find((p, i) => declared[i].index === batchIdx)).toBeLessThan(16)
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
    // 起算点读**仍在上纸**的列（品名自 issue #7909 起不上纸 ⇒ 改读货号 / 颜色）
    expect(text).toContain('0012')
    expect(text).toContain('米白')
    expect(text).toContain('张三')
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

/**
 * 纸面列收敛：**两型同版式**（issue #7901 面料单 → issue #7909 加工单）。
 *
 * 用户 2026-10-27 先说「面料单移除红框的行列」（截图三处红框：品名列 / 帘种+尺寸两列 / 工艺行），
 * 看到结果后追加一句「**加工单也要移除**」⇒ 成品帘「加工单」与面料单现在**同一套 6 列**，
 * 都不印「工艺」行。理由（都不是「不好看」，是**在说假话 / 在重复**）：
 * - 「品名」：商品身份由「货号 + 颜色 + 门幅」承担（同族裁定：报价单 issue #7527）；
 * - 「帘种」：布料行恒 `—`；
 * - 「尺寸」：行内约定（`0×2.8`）不是成品尺寸，抄下来不能裁；
 * - 「工艺行」：面料单上只剩「加工费米数」，与「数量」列同一个数。
 * 🔴 加工单**有意接受**的信息收敛：车间认「定高买宽 / 双开 / 定型」看水洗唛或屏幕（issue #7909 已登记）。
 */
describe('纸面列收敛：两型同版式（issue #7901 / #7909）', () => {
  /** 正文表头标签（按渲染顺序） */
  const headers = (): (string | undefined)[] =>
    Array.from(doc()?.querySelectorAll('.processing-doc-table thead th') ?? []).map((th) =>
      th.textContent?.trim()
    )
  const EXPECTED = ['货号', '颜色', '门幅', '数量', '批号', '备注']

  it('🔴 加工单（order_kind=processing）6 列，不印品名 / 帘种 / 尺寸 / 工艺行', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(headers()).toEqual(EXPECTED)
    expect(doc()?.textContent).not.toContain('品名')
    expect(document.querySelector('[data-testid="processing-doc-curtain-type"]')).toBeNull()
    expect(document.querySelector('[data-testid="processing-doc-craft"]')).toBeNull()
    // 值也不许从别的格子漏出来
    expect(doc()?.textContent).not.toContain('布帘')
    expect(doc()?.textContent).not.toContain('3.2×2.6')
    expect(doc()?.textContent).not.toContain('加工方式')
  })

  it('🔴 面料单（order_kind=outbound）同一套 6 列（两型不许各印一套）', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={buildProcessingOrder({ order_kind: 'outbound' })}
      />
    )
    expect(headers()).toEqual(EXPECTED)
    expect(document.querySelector('[data-testid="processing-doc-craft"]')).toBeNull()
  })

  it('🔴 存量单（`order_kind` 缺键）也不退回 9 列 —— 列清单不随作业单类型分叉', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    expect(headers()).toEqual(EXPECTED)
    expect(headers()).toHaveLength(6)
  })

  it('🔴 表格列数不变量：每行 Σ(colSpan) = 6（少一格 ⇒ 备注列在数据行没边框，同 #6595 形态）', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const tables = collectTableIntegrity(dataTables(doc())) // 单据：加工单 ProcessingDoc
    expect(tables.length).toBeGreaterThan(0)
    for (const table of tables) {
      expect(table.columns).toBe(6)
      expect(table.rows.length).toBeGreaterThanOrEqual(2)
      expect(table.rows.every((n) => n === 6)).toBe(true)
    }
  })

  it('🔴 补位行（加工费组合）占满 6 列 —— `colSpan` 随列数走，不写死魔数', () => {
    render(
      <ProcessingDoc
        order={buildOrder()}
        processingOrder={
          buildProcessingOrder({
            items: [
              {
                itemId: 'item-1',
                processingItems: [{ id: 'pi-14', name: '超高', quantity: 1 }],
              } as unknown as ProcessingOrderItem,
            ],
          } as Partial<ProcessingOrder>)
        }
      />
    )
    // 起算点：那一行真的渲染了（否则这条会空跑通过）
    expect(cellText('processing-doc-combo')).toBe('超高')
    const tables = collectTableIntegrity(dataTables(doc()))
    for (const table of tables) expect(table.rows.every((n) => n === 6)).toBe(true)
  })

  it('② 多套单：3 个商品行 ⇒ 3 块，每块 6 列（用户报的那张多套单同形）', () => {
    render(
      <ProcessingDoc
        order={buildOrder({
          items: [buildItem(), buildItem({ id: 'item-2' }), buildItem({ id: 'item-3' })],
        })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const blocks = Array.from(document.querySelectorAll('.processing-set'))
    expect(blocks).toHaveLength(3)
    for (const block of blocks) {
      expect(block.querySelectorAll('thead th')).toHaveLength(6)
      expect(block.querySelectorAll('tbody tr')[0]?.querySelectorAll('td')).toHaveLength(6)
    }
  })
})
