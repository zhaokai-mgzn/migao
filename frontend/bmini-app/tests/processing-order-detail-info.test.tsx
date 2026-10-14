// case_ids: BM-040
/**
 * 「加工单详情」只读页的**商品身份 / 规格尺寸 / 加工信息**三块（issue #6901 包 B）。
 *
 * ## 治的形态（用户 2026-10-14 逐字）
 * 「加工单缺乏订单中的规格尺寸和加工信息，**工人需要这些信息+商品信息**来决定如何生产」
 * —— 本页原先只有「单号 + 工序进度 + 卡在哪」，工人看不到做的是哪一件、按什么规格做。
 *
 * ## 判据（红证 = 怎么让它单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | 1 | 商品身份 / 规格尺寸 / 加工信息**逐键钉值**（值逐字来自服务端会话，前端不重算） | 改任一处渲染口径（如自己 `toFixed` 另一套 / 换标签） ⇒ 值对不上 ⇒ 红 |
 * | 2 | 🔴 规格尺寸**两位小数 + 米**，且**只为在场的那一维**出数 | 缺高时仍印 `× 米` / 印 `NaN` ⇒ 红 |
 * | 3 | 🔴 **缺值不渲染该行**（且全页绝不出现 `undefined`/`null`/`NaN`） | 把缺键渲染成空行或占位 ⇒ 红 |
 * | 4 | 加工信息标签与 admin-web **单一真值同源**（`craftSpecRows`，非本页自造表） | 本页自拼标签表 ⇒ 与同源实现不一致 ⇒ 红 |
 * | 5 | 「部位 / 门幅」**不上屏两遍**（部位在商品身份组、门幅已有自己的行） | 不过滤 ⇒ 同一标签出现两次 ⇒ 红 |
 * | 6 | 派工**两键都在才显示**；只有批号 ⇒ 不渲染（缺键 = 未指派） | 单键也渲染 ⇒ 红 |
 * | 7 | 部位备注 `remark` 在场才渲染 | 缺键仍印「备注」行 ⇒ 红 |
 * | 8 | 🔴 **负控 · 纯只读零写请求**：源码无工人面记号，且整页只打 GET（`post`/`put`/`del` 零调用） | 注入一个写请求 ⇒ 红 |
 *
 * ## 展示口径不新造
 * 加工信息走 `src/utils/craft-display.ts::craftSpecRows()` —— 它与 admin-web / mini-app
 * **逐字同源**（守卫 `tests/unit_ci_workflows/test_craft_display_same_source.py` 判 C1 逐字节相等）
 * ⇒ 「标签表与 admin-web 单一真值漂移」在仓内进不来。售卖方式（内部键 `bulk_cut`/`full_roll`）
 * 同理走 `src/utils/selling-method.ts`，同源守卫见 `tests/selling-method-same-source.test.ts`。
 *
 * ## 夹具真相
 * 部位规格面的键集 = **服务端加工单快照的键名族**（`ProcessingOrderService#buildSnapshot`
 * 逐键透传：`sku`/`colorName`/`doorWidth`/`sellingMethod`/`unit`/`remark`/`formula`/`craftTier`/
 * `specialOptions`/`style`/`formula_text`/`processingMeters`/`componentRole`/`specialOptions`，
 * 加上 `ProductionService#orderSpecByItemId` 的 `product_name`/`width`/`height`/工艺列
 * 与 `CALC_OUTPUT_SNAPSHOT_KEYS`，以及 `stampBatchAssignments` 的 `batch_no`/`batch_meters`）。
 * 其中的商品身份键由**包 A** 在 `orderSpecByItemId` 补齐（本包不改后端，依赖顺序 A → B）；
 * 本文件因此**同时**覆盖「有值」与「缺席」两形态 ⇒ 在包 A 未合入的 base 上同样全绿，
 * 且 A 合入后行为正确。
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    getCurrentInstance: jest.fn(() => ({ router: { params: { orderId: 'order-1' } } })),
    navigateTo: jest.fn(),
    redirectTo: jest.fn(),
    getStorageSync: jest.fn(() => ''),
    setStorageSync: jest.fn(),
    removeStorageSync: jest.fn(),
    showToast: jest.fn(),
  },
  useDidShow: jest.fn(),
}))

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  del: jest.fn(),
}))

import { get, post, put, del } from '../src/utils/request'
import OrderDetailPage from '../src/pages/production/order-detail/index'
import { stripComments } from './helpers/h5PlatformLists'

const mockGet = get as unknown as jest.Mock
const mockPost = post as unknown as jest.Mock
const mockPut = put as unknown as jest.Mock
const mockDel = del as unknown as jest.Mock

const BRIEF = {
  success: true,
  data: {
    id: 'po-1',
    orderId: 'order-1',
    orderNo: 'SO-2026-001',
    processingOrderNo: 'MO-2026-001',
    customerName: '陈女士',
    expectedDeliveryDate: '2026-10-12',
  },
}

/**
 * 部位 A：**全键在场**（服务端把组合 1/2/3/5/6 都透传下来的形态）。
 *
 * 值全部逐字来自服务端会话 —— 判据 1 就是「屏幕上的串 == 这里的串」。
 */
const FULL_FIRST = {
  position_name: '布帘',
  order_item_id: 'item-1',
  // 组 1 商品身份（包 A 补齐的键族）
  product_name: '9231 遮光窗帘',
  sku: 'SKU-9231-A',
  colorName: '雾霾蓝',
  doorWidth: '2.8米',
  sellingMethod: 'bulk_cut',
  unit: '米',
  // 组 2 规格尺寸（order_items V63 列）
  width: 3.2,
  height: 2.75,
  // 组 3 加工信息（工艺列 + 快照键 + 算料输出）
  curtainType: '布帘',
  craft: '韩褶',
  cuttingMode: '定高买宽',
  openCount: 2,
  isShaped: true,
  style: '现代简约',
  formula: 'pleat',
  craftTier: 'standard',
  specialOptions: ['加铅线', '双褶'],
  pleat_count: 48,
  per_panel_pleats: 24,
  panels: 2,
  fullness: 2,
  fullness_actual: 2.1,
  fabric_meters: 6.4,
  processingMeters: 5.5,
  formula_text: '窗宽 3.2 ÷ 幅数 2 × 褶倍 2 = 3.2',
  hasPattern: true,
  patternRepeat: 0.32,
  // 组 5 派工（两键都在）
  batch_no: 'B-20261010-01',
  batch_meters: 6.4,
  // 组 6 部位备注
  remark: '公式--48个折',
  operations: [],
}

/** 部位 B：**缺键形态** —— 商品身份与加工信息键一个都不在（存量行 / 未透传） */
const ABSENT_SECOND = { position_name: '纱帘', order_item_id: 'item-2', operations: [] }
/** 部位 C：只有**一维**尺寸 + 只有批号（未指派米数）、没有备注 */
const MINIMAL_THIRD = {
  position_name: '帘头',
  order_item_id: 'item-3',
  width: 1.5,
  batch_no: 'B-20261011-02',
  operations: [],
}

function operationsResponse(positions: unknown[]) {
  return { success: true, data: { order_id: 'order-1', positions, progress: { total: 1, done: 0, percent: 0 } } }
}

function stub(operations: unknown) {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/api/admin/production/stuck-points')) {
      return Promise.resolve({ success: true, data: { stuck_total: 0, stuck: [] } })
    }
    if (url.includes('/api/admin/processing-orders/')) return Promise.resolve(BRIEF)
    if (url.includes('/operations')) return Promise.resolve(operations)
    return Promise.reject(new Error(`未桩住的端点：${url}`))
  })
}

/** 一个卡片内的「标签 → 值」逐行读出（`__row` 是既有的标签/值两列结构） */
function rowsOf(card: HTMLElement): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const row of Array.from(card.querySelectorAll('.order-detail__row'))) {
    const cells = row.querySelectorAll('.order-detail__label, .order-detail__value')
    if (cells.length !== 2) continue
    const label = cells[0].textContent ?? ''
    const value = cells[1].textContent ?? ''
    out[label] = [...(out[label] ?? []), value]
  }
  return out
}

/** 某个部位那一块的「标签 → 值」（按 `position_name` 锚定，槽点在同名部位上也不串） */
function positionRows(name: string): Record<string, string[]> {
  const blocks = Array.from(document.querySelectorAll('[data-testid="order-detail-position-spec"]'))
  const hit = blocks.find((block) => block.querySelector('.order-detail__position-name')?.textContent === name)
  if (!hit) throw new Error(`取不到部位 ${name} 的信息块（选择器/结构漂了？）`)
  return rowsOf(hit as HTMLElement)
}

async function renderPage(operations: unknown) {
  stub(operations)
  render(<OrderDetailPage />)
  await waitFor(() => expect(screen.getByTestId('order-detail-specs')).toBeTruthy())
}

describe('加工单详情页 · 商品身份 / 规格尺寸 / 加工信息（issue #6901 包 B）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('判据 1：商品身份逐键钉值（品名 / 货号 / 颜色 / 门幅 / 售卖方式 / 单位）', async () => {
    await renderPage(operationsResponse([FULL_FIRST]))
    const rows = positionRows('布帘')

    expect(rows['品名']).toEqual(['9231 遮光窗帘'])
    expect(rows['货号']).toEqual(['SKU-9231-A'])
    expect(rows['颜色']).toEqual(['雾霾蓝'])
    // 门幅走 craft-display 的同一份米数解析（`2.8米` ⇒ 原样两位口径一致）
    expect(rows['门幅']).toEqual(['2.8米'])
    // 售卖方式落库是内部键 ⇒ 上屏必须是展示名（不是 `bulk_cut`）
    expect(rows['售卖方式']).toEqual(['散剪'])
    expect(rows['单位']).toEqual(['米'])
  })

  it('判据 2：规格尺寸 = 宽 × 高（两位小数 + 米）；只有一维时只印一维，缺维度不出现空槽', async () => {
    await renderPage(operationsResponse([FULL_FIRST, MINIMAL_THIRD]))

    expect(positionRows('布帘')['规格尺寸']).toEqual(['3.20 × 2.75 米'])
    // 只给了宽 ⇒ 只印宽（绝不出现 `1.50 × 米` / `NaN`）
    expect(positionRows('帘头')['规格尺寸']).toEqual(['1.50 米'])
  })

  it('判据 3：加工信息逐键钉值，且缺值行**一行都不渲染**、全页无 undefined/null/NaN', async () => {
    await renderPage(operationsResponse([FULL_FIRST, ABSENT_SECOND, MINIMAL_THIRD]))
    const rows = positionRows('布帘')

    // 工艺 / 加工类型 / 打开方式 / 是否定型 / 款式 / 用料公式 / 档位 / 特殊选项
    expect(rows['工艺']).toEqual(['韩褶'])
    expect(rows['加工类型']).toEqual(['定高买宽'])
    expect(rows['打开方式']).toEqual(['双开'])
    expect(rows['是否定型']).toEqual(['是'])
    expect(rows['款式']).toEqual(['现代简约'])
    expect(rows['用料公式']).toEqual(['韩褶公式（褶数法）'])
    expect(rows['档位']).toEqual(['标准工艺'])
    expect(rows['特殊选项']).toEqual(['加铅线、双褶'])
    // 算料输出：总褶数 / 每片褶数 / 幅数 / 理论褶倍 / 实际褶倍 / 面料米数 / 算料公式 / 对花 / 花距
    expect(rows['总褶数']).toEqual(['48'])
    expect(rows['褶数（每片）']).toEqual(['24'])
    expect(rows['幅数']).toEqual(['2'])
    expect(rows['理论褶倍']).toEqual(['2 倍'])
    expect(rows['实际褶倍']).toEqual(['2.1 倍'])
    expect(rows['面料米数']).toEqual(['6.4米'])
    expect(rows['加工费米数']).toEqual(['5.5米'])
    expect(rows['算料公式']).toEqual(['窗宽 3.2 ÷ 幅数 2 × 褶倍 2 = 3.2'])
    expect(rows['是否对花']).toEqual(['是'])
    expect(rows['花距']).toEqual(['0.32米'])

    // 缺键形态：纱帘那块的**加工信息与商品身份一行都不在**
    const absent = positionRows('纱帘')
    for (const label of [
      '品名', '货号', '颜色', '门幅', '售卖方式', '单位', '规格尺寸',
      '工艺', '加工类型', '打开方式', '是否定型', '总褶数', '面料米数',
    ]) {
      expect({ label, present: label in absent }).toEqual({ label, present: false })
    }

    // 全页绝不出现未格式化/未定义的痕迹（判据 3 的机器读数）
    const text = document.body.textContent ?? ''
    expect(text).not.toContain('undefined')
    expect(text).not.toContain('NaN')
    // `null` 只可能来自我们主动摆的占位 —— 本页没有占位，因此一次都不许出现
    expect(text).not.toContain('null')
  })

  it('判据 4+5：加工信息标签与 admin-web 单一真值同源；部位/门幅当且仅当印一遍', async () => {
    await renderPage(operationsResponse([FULL_FIRST]))
    const rows = positionRows('布帘')

    // 同源的机器读数：渲染出的加工信息标签 == `craftSpecRows`（三端逐字同源的那份）的标签
    const { craftSpecRows } = require('../src/utils/craft-display')
    const expected = craftSpecRows(FULL_FIRST)
      .filter((row: { label: string }) => row.label !== '部位')
      .map((row: { label: string }) => row.label)
    const rendered = Object.keys(rows).filter((label) => expected.includes(label))
    expect(rendered).toEqual(expected)

    // 判据 5：`门幅` 恰好一次（它是工人要核的尺寸，不许被「去重」去掉）
    expect(rows['门幅']).toHaveLength(1)
    // `部位` = 本块的**标题**（`position_name`）⇒ 不再重复印一行（同屏同一真值至多一处）
    expect({ present: '部位' in rows }).toEqual({ present: false })
    expect({ header: document.querySelectorAll('.order-detail__position-name')[0]?.textContent }).toEqual({
      header: '布帘',
    })
  })

  it('判据 6：派工**两键都在才显示**；只有批号（未指派米数）⇒ 不渲染', async () => {
    await renderPage(operationsResponse([FULL_FIRST, MINIMAL_THIRD]))

    expect(positionRows('布帘')['派工']).toEqual(['B-20261010-01 · 6.4 米'])
    // 两键缺一 = 未指派（口径见 `stampBatchAssignments`）
    expect({ present: '派工' in positionRows('帘头') }).toEqual({ present: false })
  })

  it('判据 7：部位备注在场才渲染', async () => {
    await renderPage(operationsResponse([FULL_FIRST, ABSENT_SECOND, MINIMAL_THIRD]))

    expect(positionRows('布帘')['备注']).toEqual(['公式--48个折'])
    expect({ present: '备注' in positionRows('纱帘') }).toEqual({ present: false })
    expect({ present: '备注' in positionRows('帘头') }).toEqual({ present: false })
  })

  it('判据 8（负控）：整页只打 GET —— 无任何写请求（post / put / del 零调用）', async () => {
    await renderPage(operationsResponse([FULL_FIRST]))
    // 该打的读面都打了（反空跑：否则「没调写接口」可能只是**什么都没发生**）
    const urls = mockGet.mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('/operations'))).toBe(true)
    expect(urls.some((url) => url.includes('/api/admin/processing-orders/'))).toBe(true)
    expect(mockPost).not.toHaveBeenCalled()
    expect(mockPut).not.toHaveBeenCalled()
    expect(mockDel).not.toHaveBeenCalled()
  })

  it('判据 8（源码面）：去注释后仍无任何工人面记号', () => {
    const src = stripComments(
      fs.readFileSync(path.join(__dirname, '../src/pages/production/order-detail/index.tsx'), 'utf8'),
    )
    ;[
      '扫一扫',
      '去登录工人身份',
      'scanResolve',
      'completeByScan',
      'getWorkerOrderOperations',
      'hasWorkerSession',
      'WORKER_TAB_LOGIN_ROUTE',
      'PRODUCTION_WORKER_LOGIN_REQUIRED',
      'workerSessionHeaders',
      'reportOperationFree',
    ].forEach((token) => {
      expect({ token, present: src.includes(token) }).toEqual({ token, present: false })
    })
    // 反向自证：源码里**确实**在消费只读读面与同源展示口径（否则上面那串「都没出现」是空跑）
    expect(src).toContain('getProcessingOrderBrief(')
    expect(src).toContain('getOrderOperations(')
    expect(src).toContain('craftSpecRows(')
  })
})
