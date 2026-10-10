// case_ids: UI-086
// 类级元守卫·第二层（issue #6717）：**「关键决策列被挤到默认视口之外」的几何判据**。
//
// 为什么单开一个文件（与 `wide-table-action-column-guard.test.ts` 的分工）：
//   · 那个文件判的是**源码形态**（操作列有没有 `sticky right-0`）—— 零误报，但判不了「第几列」；
//   · 本文件判的是**几何**：用**真实渲染出来的列序**（真 `OrderTable` 的 DOM 顺序 —— 不看源码文本）
//     配一份**列宽模型**，照 `table-layout: auto` 的实际布局算一遍累积宽度，判「关键列落不落在
//     默认视口内」。**这就是本单缺陷的静态复现**：改前列序下「状态」在 1130px 处 ⇒ 越界。
//
// 🔴 为什么必须自己量（而不是只靠 E2E）：修前真机上量「状态列在不在视口里」是 E2E 的活
// （`tests/e2e/specs/orders/key-columns-reachability.spec.ts`，真实浏览器逐像素）——
// 但**那条 spec 不在 CI 的必跑集合里**（`pr-check.yml` 的 E2E 腿只跑一份**显式列表**的
// `specs/quality/*` + `specs/dashboard/dashboard.spec.ts`）⇒ 只靠它 = 「注册了但从不跑」。
// 所以本文件用 **jsdom 没有布局** 这一点反着用：把列宽当**显式模型**喂进去，
// 让「累积宽度越界」这件事在**每一次 PR** 上都能判红（成本 ~0、不依赖浏览器）。
//
// ## 判据
// 真实渲染 `/orders` 的 `OrderTable`（真组件、真列序）后：
//   ① 「状态」表头必须落在**前若干列**之内，且按列宽模型算出的 `left` 必须 < 默认视口宽
//      （1440×980 与 1280×800 两档都要成立）；
//   ② 末列（操作）的**数据格**必须带 `sticky` 且 `right-0`（否则它必然在视口外 —— 它与 ① 互为补充）；
//   ③ 列名集合逐字冻结（防「修可达性顺手改列」；顺序**允许**变化 —— 本单改的正是列序）。
//
// ## 列宽模型（`COLUMN_WIDTH_PX`）怎么来的 —— **有意取舍，照实登记**
// 模型值取自真机实测（issue #6717 正文的逐列 `getBoundingClientRect` 读数）+ 源码里的
// `min-w-[…]` / `max-w-[…]` 声明，取**偏大**的一侧（宁可把列算宽 ⇒ 判据更严，不易假绿）。
// 它**不是**浏览器布局的正确复刻：`table-layout: auto` 下列宽随内容浮动。
// ⇒ **边界**：本文件判的是「列序 + 宽度量级」这一层；**像素级真值仍以 E2E 那条为准**（两档视口实测读数）。
// 未登记的列宽 ⇒ 取 `DEFAULT_COLUMN_WIDTH_PX`（宽表里少见的列），**不会**因此假绿（越宽越容易越界）。
//
// ## 判别力自证
// 最后一组用例在**内存里**把列序改回改前的样子（状态移到末列之前）⇒ 本判据当场红
// —— 「改前红」这件事因此**可复算**，不依赖任何人记得当时的读数。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import OrderTable from '@/components/orders/OrderTable'
import type { Order } from '@/types'

/** 两档默认视口（与 issue #6717 的验收口径同源）。 */
const VIEWPORTS = [
  { label: '1440×980', width: 1440 },
  { label: '1280×800', width: 1280 },
] as const

/** 横向滚动容器的可视宽度（真机实测：1440 ⇒ 1044；1280 ⇒ 884 = 1044 − 160）。 */
const containerWidth = (viewport: number) => (viewport >= 1440 ? 1044 : 884)

/**
 * 列宽模型（px）。键 = 表头文本（`~` 表示复选框列）。值 = 该列的**宽度上界**估计。
 * 见文件头「列宽模型怎么来的」：真机读数 + `min-w`/`max-w` 声明，取偏大一侧。
 */
const COLUMN_WIDTH_PX: Record<string, number> = {
  '~': 40,
  订单ID: 190,
  状态: 100,
  加急: 100,
  '采购商品': 160,
  '采购明细(名称:单价×数量+加工费)': 320,
  '累计金额(元)': 110,
  '实收款(元)': 110,
  收货人信息: 200,
  下单时间: 130,
  制单人: 110,
  到货日: 130,
  备注: 160,
  操作: 250,
}
const DEFAULT_COLUMN_WIDTH_PX = 120

/** 改前（`origin/main`）的列序 —— 只用于「判别力自证」里做内存注入，**不**参与真判据。 */
const ORDER_COLUMNS_BEFORE = [
  '~',
  '订单ID',
  '采购商品',
  '采购明细(名称:单价×数量+加工费)',
  '累计金额(元)',
  '实收款(元)',
  '收货人信息',
  '下单时间',
  '制单人',
  '状态',
  '加急',
  '到货日',
  '备注',
  '操作',
]

/** 改后（本分支）的列序 —— 与真渲染出来的 DOM 顺序逐字比对。 */
const ORDER_COLUMNS_AFTER = [
  '~',
  '订单ID',
  '状态',
  '加急',
  '采购商品',
  '采购明细(名称:单价×数量+加工费)',
  '累计金额(元)',
  '实收款(元)',
  '收货人信息',
  '下单时间',
  '制单人',
  '到货日',
  '备注',
  '操作',
]

const ORDER: Order = {
  id: 'o1',
  orderNo: 'MG202610110001',
  customerName: '张先生',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市西湖区文三路 100 号',
  status: 'pending_shipment',
  totalAmount: 1280.5,
  actualAmount: 1280.5,
  createdAt: '2026-10-11T10:30:00+08:00',
  items: [
    {
      id: 'i1',
      productId: 'p1',
      productName: '北欧简约遮光窗帘',
      productCode: 'CL-GY-001',
      unitPrice: 256.1,
      quantity: 5,
      amount: 1280.5,
      subtotal: 1280.5,
    },
  ],
} as unknown as Order

const noop = () => {}

/** 渲染真组件，取「表头列名序列」与「每个单元格的 class」。 */
function renderOrderTable() {
  const { container } = render(
    <OrderTable
      orders={[ORDER]}
      loading={false}
      selectedIds={[]}
      onSelectChange={noop}
      onView={noop}
      onRemark={noop}
      onClose={noop}
      onShip={noop}
    />,
  )
  const table = container.querySelector('table') as HTMLTableElement
  const headerCells = Array.from(table.querySelectorAll('thead th')) as HTMLElement[]
  const bodyCells = Array.from(table.querySelectorAll('tbody tr:first-child td')) as HTMLElement[]
  const text = (el: HTMLElement) => (el.textContent ?? '').replace(/\s+/g, ' ').trim() || '~'
  return {
    columns: headerCells.map(text),
    headerCells,
    bodyCells,
  }
}

/**
 * 按**列宽模型**算一遍累积宽度（模拟 `table-layout: auto` 在给定列序下的横向布局）。
 * 返回每一列的 `[left, right]`（相对容器左缘）。
 */
function layout(columns: string[]): { text: string; left: number; right: number }[] {
  let x = 0
  return columns.map((text) => {
    const w = COLUMN_WIDTH_PX[text] ?? DEFAULT_COLUMN_WIDTH_PX
    const cell = { text, left: x, right: x + w }
    x += w
    return cell
  })
}

/**
 * 本判据的核心断言：给定列序与视口，**哪些关键列在默认视口内**。
 *
 * `keyColumns` = 必须在 `scrollLeft = 0` 时可被商家看到的「决策列」。
 * 纯函数（可内存注入 ⇒ 判别力自证）。
 */
export function offscreenKeyColumns(
  columns: string[],
  viewportWidth: number,
  keyColumns: string[],
): { text: string; left: number; right: number }[] {
  const box = layout(columns)
  const visible = containerWidth(viewportWidth)
  return box.filter((c) => keyColumns.includes(c.text) && c.right > visible + 0.5)
}

afterEach(() => cleanup())

describe('宽表关键列几何判据（issue #6717）', () => {
  it('① 真渲染出来的列序 = 本分支冻结的列序（几何判据的坐标系不许漂）', () => {
    const { columns } = renderOrderTable()
    expect(columns, '真实渲染的列序与冻结清单不一致 ⇒ 下面的几何读数没有意义').toEqual(ORDER_COLUMNS_AFTER)
  })

  it('② 两档默认视口下「状态」必须落在可视区内（列宽模型下的累积宽度）', () => {
    const { columns } = renderOrderTable()
    for (const vp of VIEWPORTS) {
      const bad = offscreenKeyColumns(columns, vp.width, ['状态'])
      expect(
        bad,
        `${vp.label}：scrollLeft=0 时「状态」列按列宽模型落在 left=${bad[0]?.left} 处 ` +
          `（> 可视宽 ${containerWidth(vp.width)}）⇒ 商家要横滚才看得到订单状态（issue #6717 的现场形态）`,
      ).toEqual([])
    }
  })

  it('③ 末列（操作）的数据格必须右缘冻结 —— 否则它在任何默认视口下都在视口外', () => {
    const { columns, headerCells, bodyCells } = renderOrderTable()
    const idx = columns.indexOf('操作')
    expect(idx, '找不到「操作」列').toBeGreaterThanOrEqual(0)
    const headerCls = headerCells[idx].className
    const bodyCls = bodyCells[idx].className
    expect(headerCls, '「操作」列表头必须 sticky + right-0').toMatch(/\bsticky\b/)
    expect(headerCls, '「操作」列表头必须 sticky + right-0').toMatch(/\bright-0\b/)
    expect(bodyCls, '「操作」列数据格必须 sticky + right-0（否则行按钮滚出视口）').toMatch(/\bsticky\b/)
    expect(bodyCls, '「操作」列数据格必须 sticky + right-0（否则行按钮滚出视口）').toMatch(/\bright-0\b/)
    // 背景必须**不是**透明的：`bg-inherit` 依赖 `<tr>` 显式声明背景，这里只判「有背景来源」
    // （模型层的完整判定 = 真渲染行的背景声明，见下一条）。
    expect(
      bodyCls + ' ' + (bodyCells[idx].parentElement?.className ?? ''),
      '「操作」列数据格与其行必须有背景来源（bg-inherit / bg-*）—— 否则滚动时横向内容会**穿透**',
    ).toMatch(/bg-(inherit|white|neutral-50)/)
  })

  it('④ 列名集合逐字冻结（顺序允许变化 —— 本单改的正是列序）', () => {
    const { columns } = renderOrderTable()
    expect(new Set(columns)).toEqual(new Set(ORDER_COLUMNS_AFTER))
    expect(columns.length).toBe(ORDER_COLUMNS_AFTER.length)
  })

  it('⑤ 判别力自证：把列序改回改前的样子 ⇒ 本判据在内存里当场红（改前红可复算）', () => {
    for (const vp of VIEWPORTS) {
      const bad = offscreenKeyColumns(ORDER_COLUMNS_BEFORE, vp.width, ['状态'])
      expect(
        bad.map((c) => c.text),
        `${vp.label}：改前列序下「状态」必须被判成出屏（否则本判据没有判别力）`,
      ).toEqual(['状态'])
      // 反向对照：改后列序在同一模型 / 同一视口下**不**出屏
      expect(offscreenKeyColumns(ORDER_COLUMNS_AFTER, vp.width, ['状态'])).toEqual([])
    }
    // 边界：列宽模型本身也能红（把「状态」列宽抬到超过可视宽 ⇒ 判红），说明判据不是恒绿
    const fat = COLUMN_WIDTH_PX['状态']
    COLUMN_WIDTH_PX['状态'] = containerWidth(1280) + 1
    expect(offscreenKeyColumns(ORDER_COLUMNS_AFTER, 1280, ['状态']).map((c) => c.text)).toEqual(['状态'])
    COLUMN_WIDTH_PX['状态'] = fat
  })
})
