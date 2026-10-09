// case_ids: UI-095
// @vitest-environment jsdom
/**
 * 打印单据**表格列数不变量**（issue #6595）—— 实例判据 + 类级元守卫。
 *
 * 现场（用户真机截图 + 真浏览器读数）：加工单打印预览里，「备注」列**数据行整列没有边框**。
 * 根因不是样式，是 **DOM 缺格**：`ProcessingDoc` 主体行只渲染 7 格，而表头 8 列
 * ⇒ 第 8 列（备注）在数据行**没有任何单元格**，那一列的数据段自然没有边框。
 *
 * 本文件守两件事（`migao-dev-flow` §23「实例判据 + 类级元守卫」）：
 * ① **实例判据**：加工单每一行的 `Σ(colSpan)` 必须等于表头列数（= `PROCESSING_DOC_COLUMNS.length`）；
 * ② **类级元守卫**：**每一份打印单据的测试**都必须调同一条不变量（`assertDocTableIntegrity`）
 *    —— 未调用即红。否则「只修一处 = 没修」：同类缺陷换到报价单 / 销售单 / 发货单 / 任务卡
 *    不会有任何东西变红。
 *
 * 判别力自证：注入式对照（`doc-table-integrity-guard.test.tsx` 顶部注释的⑤条口径）在
 * 下面「判据可红」两条里用**内存 DOM** 落成 —— 少一格 ⇒ 必红；补齐 ⇒ 转绿。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// 组件会经 hook 触到 `@/lib/api`（收款码）⇒ 打桩成「无码」，避免 jsdom 真发 XHR（噪音）。
const mockGetPaymentQrcodes = vi.fn()
vi.mock('@/lib/api', () => ({
  settingsApi: { getPaymentQrcodes: (...args: unknown[]) => mockGetPaymentQrcodes(...args) },
}))

import ProcessingDoc, { PROCESSING_DOC_COLUMNS } from '@/components/orders/ProcessingDoc'
import {
  assertDocTableIntegrity,
  collectTableIntegrity,
  dataTables,
  type TableIntegrityResult,
} from '@/components/orders/doc-tables'
import type { Order, OrderItem, ProcessingOrder } from '@/types'

function buildItem(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    productId: 'p-1',
    productName: '布艺遮光帘A',
    productCode: '0012',
    color: '米白',
    specification: '',
    quantity: 12.5,
    unitPrice: 100,
    amount: 1250,
    subtotal: 1250,
    width: 3.2,
    height: 2.6,
    processingInfo: { curtainType: '布帘', craft: '韩褶', colorName: '米白', componentRole: '主布' },
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
    remark: '',
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

/** 判定用最小 HTML：表头 8 列 + 主体行（`cells` 格） */
const tableHtml = (cells: number): string =>
  '<table><thead><tr>' +
  Array.from({ length: 8 }, () => '<th></th>').join('') +
  '</tr></thead><tbody><tr>' +
  Array.from({ length: cells }, () => '<td></td>').join('') +
  '</tr></tbody></table>'

function parseTables(html: string): Element[] {
  const host = document.createElement('div')
  host.innerHTML = html
  return Array.from(host.querySelectorAll('table'))
}

// ───────────────────────── ① 判别力自证（判据可红 / 可绿） ─────────────────────────

describe('打印表格列数不变量 · 判别力自证', () => {
  it('🔴 少一格（历史形态：表头 8 列、数据行 7 格）⇒ 必红', () => {
    expect(() => collectTableIntegrity(parseTables(tableHtml(7)))).toThrow(/占 7 列，表头是 8 列/)
  })

  it('✅ 补齐第 8 格 ⇒ 转绿，且读数可复算', () => {
    expect(collectTableIntegrity(parseTables(tableHtml(8)))).toEqual([{ columns: 8, rows: [8, 8] }])
  })

  it('`colSpan` 计入：一格 span=8 的行与表头 8 列自洽（不是「格子数必须相等」）', () => {
    const html =
      '<table><thead><tr>' +
      Array.from({ length: 8 }, () => '<th></th>').join('') +
      '</tr></thead><tbody><tr><td colspan="8"></td></tr></tbody></table>'
    expect(collectTableIntegrity(parseTables(html))).toEqual([{ columns: 8, rows: [8, 8] }])
  })

  it('🔴 空集必须红：容器里一张表都没有 ⇒ 抛错（否则「单据没渲染」会被读成通过）', () => {
    expect(() => assertDocTableIntegrity(document.createElement('div'))).toThrow(/没有找到任何表格/)
  })
})

// ───────────────────────── ① 实例判据：加工单 ─────────────────────────

describe('加工单 · 表格列数不变量（issue #6595）', () => {
  it('🔴 主体行（品名规格为空 ⇒ 没有补位行）每一行都必须占满 8 列 —— 备注列才有边框', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const tables = collectTableIntegrity(dataTables(doc()))
    // 每套一张 8 列表（1 个商品行 = 1 张正文表；抬头那几张信息表因不带 `<thead>` 不在此面内）
    expect(tables.length).toBeGreaterThan(0)
    for (const table of tables) {
      expect(table.columns).toBe(PROCESSING_DOC_COLUMNS.length)
      // 主体行必须与表头同列数 —— 这正是「备注列在数据行没有格子」的判据
      expect(table.rows.length).toBeGreaterThanOrEqual(2)
      expect(table.rows.every((n) => n === PROCESSING_DOC_COLUMNS.length)).toBe(true)
    }
  })

  it('品名规格有值 ⇒ 多一条整行补位（`colSpan` 计入后仍逐行自洽）', () => {
    render(
      <ProcessingDoc
        order={buildOrder({ items: [buildItem({ specification: '门幅2.8米' })] })}
        processingOrder={buildProcessingOrder()}
      />
    )
    const tables = collectTableIntegrity(dataTables(doc()))
    expect(tables[0].rows).toEqual([8, 8, 8])
  })

  it('抬头信息表（`tbody`-only、行内不等列）不被误判 —— 判别依据是 `<thead>`', () => {
    render(<ProcessingDoc order={buildOrder()} processingOrder={buildProcessingOrder()} />)
    const all = Array.from(doc()?.querySelectorAll('table') ?? [])
    // 语料自证：容器里既有抬头表也有正文表（否则「过滤」这条判据自己就空跑）
    expect(all.length).toBeGreaterThan(dataTables(doc()).length)
    // 正文表（带 `<thead>`）逐行自洽；不在面内的表是抬头那种
    expect(dataTables(doc()).every((table) => table.querySelector('thead') !== null)).toBe(true)
  })
})

// ───────────────────────── ② 类级元守卫：每份单据的测试都调用同一判据 ─────────────────────────

interface DocGuard {
  /** 单据名（报红时点得出是哪一个） */
  label: string
  /** 测试文件（相对 `frontend/admin-web`） */
  file: string
}

/** 语料：打印单据 → 它的测试文件（新增单据时必须同步登记） */
const DOC_GUARDS: DocGuard[] = [
  { label: '加工单 ProcessingDoc', file: 'tests/unit/components/ProcessingDoc.test.tsx' },
  { label: '报价单 QuotationDoc', file: 'tests/unit/components/QuotationDoc.test.tsx' },
  { label: '销售单 SalesDoc', file: 'tests/unit/components/SalesDoc.test.tsx' },
  { label: '发货单 ShipmentDoc', file: 'tests/unit/components/ShipmentDoc.test.tsx' },
  { label: '任务卡 TaskCardPrint', file: 'tests/unit/components/TaskCardPrint.test.tsx' },
]

const REPO_ADMIN_WEB = process.cwd()

/**
 * 扫一个文件里对「表格列数不变量」的登记（供判据 2/3 复用；纯函数，可内存取证）。
 *
 * 登记形态 = **同一行**既有不变量调用、又有单据标识 `单据：<label>`
 * （如 `collectTableIntegrity(dataTables(doc())) // 单据：加工单 ProcessingDoc`）——
 * 「变量名 ≈ 单据名」这种约定太脆（`doc()` 在五份单据里同名），显式标识才判得准。
 */
function guardRegistrations(source: string, labels: readonly string[]): string[] {
  const found: string[] = []
  for (const label of labels) {
    const pattern = new RegExp(`^.*单据：${label}.*collectTableIntegrity.*$|^.*collectTableIntegrity.*单据：${label}.*$`, 'm')
    if (pattern.test(source)) found.push(label)
  }
  return found
}

describe('类级元守卫 · 每份打印单据都挂同一条表格不变量', () => {
  it('🔴 未调用即红：任一单据的测试没有挂 `assertDocTableIntegrity` ⇒ 具名报出', () => {
    const missing = DOC_GUARDS.filter((guard) => {
      const source = readFileSync(join(REPO_ADMIN_WEB, guard.file), 'utf-8')
      return guardRegistrations(source, [guard.label]).length === 0
    })
    expect(
      missing.map((guard) => `${guard.label}（${guard.file}）`),
      '这些打印单据没有把「行/列数不变量」挂进自己的测试 —— 同类缺陷（少渲染一格 ⇒ 整列无边框）换到它们的纸面上不会有任何东西变红'
    ).toEqual([])
  })

  it('语料不许空转：登记的单据数下限 + 每个文件必须真实存在（扫空气 ⇒ 红）', () => {
    expect(DOC_GUARDS.length).toBeGreaterThanOrEqual(5)
    for (const guard of DOC_GUARDS) {
      expect(readFileSync(join(REPO_ADMIN_WEB, guard.file), 'utf-8').length).toBeGreaterThan(0)
    }
  })

  it('判别力自证：把某份单据的调用删掉 ⇒ 上面那条必红（内存对照，不动真文件）', () => {
    const fake = 'it("x", () => { /* 这里什么判据都没有 */ })'
    expect(guardRegistrations(fake, ['加工单 ProcessingDoc'])).toEqual([])
    // 有调用但没有单据标识 ⇒ 不认（否则靠变量名撞运气）
    expect(guardRegistrations('collectTableIntegrity(dataTables(doc()))', ['加工单 ProcessingDoc'])).toEqual([])
    expect(
      guardRegistrations('collectTableIntegrity(dataTables(doc())) // 单据：加工单 ProcessingDoc', [
        '加工单 ProcessingDoc',
      ])
    ).toEqual(['加工单 ProcessingDoc'])
  })
})

// `collectTableIntegrity` 的读数类型在测试里逐处复算用得到（避免 any）
const _typed: (tables: readonly Element[]) => TableIntegrityResult[] = collectTableIntegrity
void _typed
void cleanup
