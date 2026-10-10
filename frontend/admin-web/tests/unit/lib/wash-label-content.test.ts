// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6656）：水洗唛**纸面内容**的单一真值（`frontend/admin-web/src/lib/wash-label-content.ts`）。
//
// 用户 2026-10-10 逐字：「**直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的**」
// ⇒ 两条打印通道（系统打印 `TaskCardPrint.tsx` / 免驱动直连 `lib/label-print/*`）改读**同一份**有序行清单。
// 本文件判的是**内容与行序**，不是排版（排版由各渲染器负责）。
//
// 逐条判据（都能判红）：
// ① 行序 = `WASH_LABEL_ROW_KEYS`（改序 ⇒ 必红）；
// ② 前缀（`客户 ` / `部位 ` / `色号 ` / `用料 ` / `宽高 ` / `加工方式 ` / `订单 ` / `交期 ` / `备注 `）
//    在**这一处**拼 —— 渲染器各自再拼一遍就是第二份真值；
// ③ **缺值不渲染，且判空看的是「值」不是「拼好的整行」**：`宽高 ` / `用料 ` 这种只剩前缀的空壳行
//    不得上纸（这条是改版时实测踩到的形态，故单列一条判据）；
// ④ 色号已含在件名里 ⇒ 不重复渲染（正反对照都钉）；
// ⑤ 套序走 `groupBySet`（与进度表同一份实现）；
// ⑥ 定型按行业措辞收成「定型 / 不定型」（值仍来自 `craft-display`）；
// ⑦ `toWashLabelInputs`：码 = `scan_url ?? part_token`、短码缺 ⇒ 「—」、按 `itemId` 对齐快照行、
//    0 部位 ⇒ 空数组（不造占位）。
import { describe, expect, it } from 'vitest'
import {
  WASH_LABEL_ROW_KEYS,
  toWashLabelInputs,
  washLabelRows,
  type WashLabelRowKey,
} from '@/lib/wash-label-content'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

const PROCESSING_ORDER_NO = 'JG-20260921-8237'
const ORDER_NO = '20260921973550001'
const CUSTOMER = '赵凯'
const DELIVERY = '2026-09-28'

const POSITION = {
  position_name: '布艺遮光帘A',
  position_kind: '布帘',
  order_item_id: 'item-1',
  set_no: `${PROCESSING_ORDER_NO}-001`,
  product_name: '2699系列雪尼尔窗帘面料',
  width: 3,
  height: 2.75,
  scan_url: 'https://app.migaozn.com/s/7K3M9QP2',
  part_token: 'tok-1',
  part_short_code: '7K3M9QP2',
} as unknown as ProductionPosition

const ITEM = {
  itemId: 'item-1',
  productName: '2699系列雪尼尔窗帘面料',
  colorName: '米白',
  craft: '韩褶',
  cuttingMode: '定高买宽',
  openCount: 2,
  isShaped: true,
  specialOptions: ['加logo条', '防翘扣'],
  fabric_meters: 6.3,
  remark: '加铅块',
  formula_text: '韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
} as unknown as ProcessingOrderItem

/** 全字段齐备的那张（真实工单形态） */
const fullRows = () =>
  washLabelRows({
    position: POSITION,
    item: ITEM,
    setNo: 1,
    setCount: 2,
    customerName: CUSTOMER,
    orderNo: ORDER_NO,
    expectedDeliveryDate: DELIVERY,
  })

const textOf = (rows: ReturnType<typeof washLabelRows>, key: WashLabelRowKey) =>
  rows.find((row) => row.key === key)?.text

describe('washLabelRows — 纸面内容与行序（issue #6656）', () => {
  it('判据 ①：全字段齐备时，行序与行文本逐字 == 真实工单的纸面', () => {
    const rows = fullRows()

    // 行序是纸面契约（照真实工单：亿家纺织「成品定制」58mm 竖排小票的信息顺序）
    expect(rows.map((row) => row.key)).toEqual([...WASH_LABEL_ROW_KEYS])

    expect(textOf(rows, 'customer')).toBe(`客户 ${CUSTOMER}`)
    expect(textOf(rows, 'setNo')).toBe('第 1 套 / 共 2 套')
    expect(textOf(rows, 'positionKind')).toBe('部位 布帘')
    expect(textOf(rows, 'pieceName')).toBe('布艺遮光帘A')
    expect(textOf(rows, 'color')).toBe('色号 米白')
    expect(textOf(rows, 'meters')).toBe('用料 6.3米')
    expect(textOf(rows, 'size')).toBe('宽高 3×2.75米')
    expect(textOf(rows, 'craft')).toBe('加工方式 韩褶 · 定高买宽 · 双开 · 定型')
    expect(textOf(rows, 'orderNo')).toBe(`订单 ${ORDER_NO}`)
    expect(textOf(rows, 'delivery')).toBe(`交期 ${DELIVERY}`)
    // 备注 = 特殊选项 + 快照备注（拼接分隔符由 `craft-display` 定，本判据只钉「都在」）
    expect(textOf(rows, 'remark')).toContain('加logo条')
    expect(textOf(rows, 'remark')).toContain('加铅块')
    // 算料公式**不带前缀**（串本身就是 `韩褶公式：…`，再加前缀是重复）
    expect(textOf(rows, 'formula')).toBe('韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米')

    // 行数预算：可折行的四种给 2 行，其余单行（位图渲染器按它折行）
    expect(rows.filter((row) => row.maxLines === 2).map((row) => row.key)).toEqual([
      'pieceName',
      'craft',
      'remark',
      'formula',
    ])
  })

  it('判据 ③：缺值不渲染 —— 判空看**值**，不得留下只剩前缀的空壳行', () => {
    const bare = {
      position_name: '布艺遮光帘A',
      order_item_id: 'item-1',
      width: null,
      height: null,
    } as unknown as ProductionPosition

    const rows = washLabelRows({
      position: bare,
      item: null,
      setNo: 2,
      setCount: 3,
      orderNo: null,
      expectedDeliveryDate: null,
    })

    expect(rows.map((row) => row.key)).toEqual(['setNo', 'pieceName', 'orderNo', 'delivery'])
    expect(rows.map((row) => row.text)).toEqual(['第 2 套 / 共 3 套', '布艺遮光帘A', '订单 —', '交期 —'])
    // 🔴 正向拒绝：整行 trim 判空会把这些空壳印上纸（改版实测过的形态）
    expect(rows.some((row) => ['宽高', '用料', '色号', '部位', '加工方式', '备注', '客户'].includes(row.text))).toBe(
      false,
    )
  })

  it('判据 ③：宽高只有一边 ⇒ 不出宽高行（半个尺寸没有意义）', () => {
    const half = { ...POSITION, height: null } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: half, item: null }), 'size')).toBeUndefined()
    const none = { ...POSITION, width: null, height: null } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: none, item: null }), 'size')).toBeUndefined()
    // 正反对照：两值都在 ⇒ 该行必须出现（否则上面两条是空断言）
    expect(textOf(fullRows(), 'size')).toBe('宽高 3×2.75米')
  })

  it('判据 ④：色号已含在件名里 ⇒ 不重复渲染', () => {
    const named = { ...POSITION, position_name: '布艺遮光帘A（米白）' } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: named, item: ITEM }), 'color')).toBeUndefined()
    // 正反对照：件名不含色号 ⇒ 色号行必须在
    expect(textOf(fullRows(), 'color')).toBe('色号 米白')
  })

  it('判据 ⑤：套序来自调用方给的 `groupBySet` 读数（1 起）', () => {
    expect(textOf(washLabelRows({ position: POSITION, item: null, setNo: 3, setCount: 5 }), 'setNo')).toBe(
      '第 3 套 / 共 5 套',
    )
    // 缺读数 ⇒ 退化成「第 1 套 / 共 1 套」（不出现 NaN / undefined）
    expect(textOf(washLabelRows({ position: POSITION, item: null }), 'setNo')).toBe('第 1 套 / 共 1 套')
  })

  it('判据 ⑥：是否定型按行业措辞收成「定型 / 不定型」（不印「是否定型：是」）', () => {
    const unshaped = { ...ITEM, isShaped: false } as unknown as ProcessingOrderItem
    const craft = textOf(washLabelRows({ position: POSITION, item: unshaped }), 'craft')
    expect(craft).toBe('加工方式 韩褶 · 定高买宽 · 双开 · 不定型')
    expect(craft).not.toContain('是否定型')
    // 正反对照：定型 = 是 ⇒ 「定型」（判据可判别 —— 写死「定型」⇒ 不定型那条必红）
    expect(textOf(fullRows(), 'craft')).toBe('加工方式 韩褶 · 定高买宽 · 双开 · 定型')
  })

  it('件名与部位名全缺 ⇒ 件名行如实「—」（不编造、不空行）', () => {
    const anonymous = { order_item_id: 'item-9' } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: anonymous, item: null }), 'pieceName')).toBe('—')
  })

  it('无 position ⇒ 空清单（不在这里造占位行）', () => {
    expect(washLabelRows({ position: null, item: ITEM })).toEqual([])
    expect(washLabelRows({})).toEqual([])
  })
})

describe('toWashLabelInputs — 加工单 ⇒ 逐张输入（issue #6439 → #6656 扩字段）', () => {
  const twoPositions = [
    POSITION,
    { ...POSITION, order_item_id: 'item-2', position_name: '纱帘B', set_no: `${PROCESSING_ORDER_NO}-001` },
    { ...POSITION, order_item_id: 'item-3', position_name: '帘头C', set_no: `${PROCESSING_ORDER_NO}-002` },
  ] as ProductionPosition[]

  it('码 = scan_url ?? part_token；两者都没有 ⇒ null（不画假码）；短码缺 ⇒ 「—」', () => {
    const [withScan, withToken, noCode] = toWashLabelInputs({
      positions: [
        { scan_url: 'https://x/s/AAAAAAAA', part_token: 'tok-1', part_short_code: 'AAAAAAAA' },
        { scan_url: null, part_token: 'tok-2', part_short_code: 'BBBBBBBB' },
        { scan_url: null, part_token: null, part_short_code: null },
      ] as unknown as ProductionPosition[],
    })
    expect(withScan.qrValue).toBe('https://x/s/AAAAAAAA')
    expect(withToken.qrValue).toBe('tok-2')
    expect(noCode.qrValue).toBeNull()
    expect(noCode.shortCode).toBe('—')
  })

  it('🔴 每张都带上**完整纸面行清单**与表头（改动前只映射了 4 个键 ⇒ 直连打出来比预览少十行）', () => {
    const labels = toWashLabelInputs({
      processingOrderNo: PROCESSING_ORDER_NO,
      orderNo: ORDER_NO,
      customerName: CUSTOMER,
      expectedDeliveryDate: DELIVERY,
      positions: twoPositions,
      items: [ITEM, { itemId: 'item-3', colorName: '米灰', craft: '平板' } as unknown as ProcessingOrderItem],
    })

    expect(labels).toHaveLength(3)
    labels.forEach((label) => expect(label.processingOrderNo).toBe(PROCESSING_ORDER_NO))

    // 第 1 张：快照行齐备 ⇒ 与 `washLabelRows` 逐字一致（内容真值只有一处）
    expect(labels[0].rows?.map((row) => row.text)).toEqual(
      washLabelRows({
        position: twoPositions[0],
        item: ITEM,
        setNo: 1,
        setCount: 2,
        customerName: CUSTOMER,
        orderNo: ORDER_NO,
        expectedDeliveryDate: DELIVERY,
      }).map((row) => row.text),
    )
    expect(labels[0].rows?.length).toBeGreaterThan(5)
    expect(labels[0].rows?.map((row) => row.text)).toContain('用料 6.3米')

    // 第 3 张：不同套 ⇒ 套序逐张跟着走
    expect(labels[2].rows?.map((row) => row.text)).toContain('第 2 套 / 共 2 套')
  })

  it('空输入 ⇒ 空数组（不造占位：直连入口据此禁用，不是打一张空白纸）', () => {
    expect(toWashLabelInputs()).toEqual([])
    expect(toWashLabelInputs({ positions: null })).toEqual([])
    expect(toWashLabelInputs({ positions: [] })).toEqual([])
  })
})
