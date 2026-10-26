// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6656 建「纸面内容单一真值」→ **issue #7816 字段/份数改判**）：
// 水洗唛**纸面内容**的单一真值（`frontend/admin-web/src/lib/wash-label-content.ts`）。
//
// 用户 2026-10-26 逐字（issue #7816）：
// 「把订单号放到第一行，客户那一行上面，移除加工单号……移除交期字段」
// 「要体现出是否采用的韩褶公式以及韩褶的折数，用一个字段表示即可」
// 「如果订单是双开的要打印两份，单开的要打印1份，三开打印3份，4开打印4份」。
//
// 逐条判据（都能判红）：
// ① 行序 = `WASH_LABEL_ROW_KEYS`（订单号第一行；加工单号 / 交期**不在**清单里；改序 ⇒ 必红）；
// ② 前缀（`订单 ` / `客户 ` / `部位 ` / `颜色 ` / `门幅 ` / `用料 ` / `宽高 ` / `加工方式 ` / `褶法 ` /
//    `特殊选项 ` / `备注 `）在**这一处**拼 —— 渲染器各自再拼一遍就是第二份真值；
// ③ **缺值不渲染，且判空看的是「值」不是「拼好的整行」**：`宽高 ` / `用料 ` 这种只剩前缀的空壳行
//    不得上纸；订单号例外（缺值如实 `—`，它是「这张纸是给谁的」的最小可读集合）；
// ④ **褶法 = 是否韩褶公式 + 折数**（一个字段）：`韩褶 52折` / `韩褶`（无折数不编数）/ `倍数法` /
//    两者都判不出 ⇒ 不印（不猜）；
// ⑤ **份数 = 开数**（`washLabelCopies`）：1/2/3/4、表外 N、缺值/非法值 ⇒ 1；
// ⑥ `toWashLabelInputs`：码 = `scan_url ?? part_token`、按 `itemId` 对齐快照行、**按开数展开 N 条**、
//    0 部位 ⇒ 空数组（不造占位）。
import { describe, expect, it } from 'vitest'
import {
  WASH_LABEL_ROW_KEYS,
  toWashLabelInputs,
  washLabelCopies,
  washLabelPleats,
  washLabelRows,
  type WashLabelRowKey,
} from '@/lib/wash-label-content'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

const PROCESSING_ORDER_NO = 'JG-20260921-8237'
const ORDER_NO = '20260921973550001'
const CUSTOMER = '赵凯'

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
  doorWidth: '2.8米',
  craft: '韩褶',
  cuttingMode: '定高买宽',
  openCount: 2,
  isShaped: true,
  specialOptions: ['加logo条', '防翘扣'],
  fabric_meters: 6.3,
  remark: '加铅块',
  pleat_count: 52,
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
  })

const textOf = (rows: ReturnType<typeof washLabelRows>, key: WashLabelRowKey) =>
  rows.find((row) => row.key === key)?.text

describe('washLabelRows — 纸面内容与行序（issue #6656 → #7816）', () => {
  it('判据 ①：全字段齐备时，行序与行文本逐字 == 真实工单的纸面', () => {
    const rows = fullRows()

    // 行序是纸面契约：**订单号第一行**（2026-10-26 用户逐字「放到第一行，客户那一行上面」）
    expect(rows.map((row) => row.key)).toEqual([...WASH_LABEL_ROW_KEYS])
    expect(rows[0].key).toBe('orderNo')
    expect(rows[1].key).toBe('customer')

    expect(textOf(rows, 'orderNo')).toBe(`订单 ${ORDER_NO}`)
    expect(textOf(rows, 'customer')).toBe(`客户 ${CUSTOMER}`)
    expect(textOf(rows, 'setNo')).toBe('第 1 套 / 共 2 套')
    expect(textOf(rows, 'positionKind')).toBe('部位 布帘')
    expect(textOf(rows, 'color')).toBe('颜色 米白')
    expect(textOf(rows, 'doorWidth')).toBe('门幅 2.8米')
    expect(textOf(rows, 'meters')).toBe('用料 6.3米')
    expect(textOf(rows, 'size')).toBe('宽高 3×2.75米')
    expect(textOf(rows, 'craft')).toBe('加工方式 韩褶 · 定高买宽 · 双开 · 定型')
    // ④ 褶法 = 是否韩褶公式 + 折数（同一个字段，用户 2026-10-26 裁定）
    expect(textOf(rows, 'pleats')).toBe('褶法 韩褶 52折')
    expect(textOf(rows, 'specialOptions')).toBe('特殊选项 加logo条、防翘扣')
    expect(textOf(rows, 'remark')).toBe('备注 加铅块')
    // 反向判据：特殊选项**不得**再混进备注行（并回去 ⇒ 必红）
    expect(textOf(rows, 'remark')).not.toContain('加logo条')

    // 🔴 退场项一律不得回来：加工单号 / 交期 / 件名 / 算料公式（用户历次裁定）
    expect(rows.map((row) => row.key)).not.toContain('delivery')
    expect(rows.map((row) => row.key)).not.toContain('pieceName')
    expect(rows.map((row) => row.key)).not.toContain('formula')
    expect(rows.map((row) => row.text).join('｜')).not.toContain(PROCESSING_ORDER_NO)
    expect(rows.map((row) => row.text).join('｜')).not.toContain('交期')
    expect(rows.map((row) => row.text).join('｜')).not.toContain('韩褶公式')

    // 行数预算：订单号（17 位数字 + 前缀 > 版心）与三种长文本给 2 行，其余单行
    expect(rows.filter((row) => row.maxLines === 2).map((row) => row.key)).toEqual([
      'orderNo',
      'craft',
      'specialOptions',
      'remark',
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
    })

    // 订单号缺值如实 `—`（最小可读集合）；其余缺值行整行不出现
    expect(rows.map((row) => row.key)).toEqual(['orderNo', 'setNo'])
    expect(rows.map((row) => row.text)).toEqual(['订单 —', '第 2 套 / 共 3 套'])
    // 🔴 正向拒绝：整行 trim 判空会把这些空壳印上纸（改版实测过的形态）
    expect(
      rows.some((row) =>
        ['宽高', '用料', '颜色', '门幅', '部位', '加工方式', '褶法', '特殊选项', '备注', '客户'].includes(row.text)
      )
    ).toBe(false)
  })

  it('判据 ③：宽高只有一边 ⇒ 不出宽高行（半个尺寸没有意义）', () => {
    const half = { ...POSITION, height: null } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: half, item: null }), 'size')).toBeUndefined()
    const none = { ...POSITION, width: null, height: null } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: none, item: null }), 'size')).toBeUndefined()
    // 正反对照：两值都在 ⇒ 该行必须出现（否则上面两条是空断言）
    expect(textOf(fullRows(), 'size')).toBe('宽高 3×2.75米')
  })

  it('判据 ④：颜色**恒印**（件名退场后不再有「已含在件名里 ⇒ 去重」）', () => {
    const named = { ...POSITION, position_name: '布艺遮光帘A（米白）' } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: named, item: ITEM }), 'color')).toBe('颜色 米白')
    expect(textOf(fullRows(), 'color')).toBe('颜色 米白')
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

  it('门幅缺值 ⇒ 不出门幅行（不印空壳）；两种存量形态都补单位', () => {
    const anonymous = { order_item_id: 'item-9' } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: anonymous, item: null }), 'doorWidth')).toBeUndefined()
    const bare = { ...ITEM, doorWidth: '2.8' } as unknown as ProcessingOrderItem
    expect(textOf(washLabelRows({ position: POSITION, item: bare }), 'doorWidth')).toBe('门幅 2.8米')
  })

  it('无 position ⇒ 空清单（不在这里造占位行）', () => {
    expect(washLabelRows({ position: null, item: ITEM })).toEqual([])
    expect(washLabelRows({})).toEqual([])
  })
})

describe('washLabelPleats — 褶法 = 是否韩褶公式 + 折数（一个字段，2026-10-26 用户裁定）', () => {
  it('韩褶公式 + 折数 ⇒ 「韩褶 N折」（折数取自 `pleat_count`，不重算）', () => {
    expect(washLabelPleats(ITEM)).toBe('韩褶 52折')
    expect(washLabelPleats({ pleat_count: 36 } as ProcessingOrderItem)).toBe('韩褶 36折')
  })

  it('韩褶公式但折数缺失 ⇒ 只写「韩褶」（**不编数**）', () => {
    const noCount = { ...ITEM, pleat_count: undefined } as unknown as ProcessingOrderItem
    expect(washLabelPleats(noCount)).toBe('韩褶')
  })

  it('倍数法（褶倍数公式）⇒ 「倍数法」；即使残留 `pleat_count` 也以公式串为准', () => {
    expect(washLabelPleats({ formula_text: '褶倍数公式：(5.5÷2)×2 → 11.0米' } as ProcessingOrderItem)).toBe('倍数法')
    expect(
      washLabelPleats({
        formula_text: '褶倍数公式：(5.5÷2)×2 → 11.0米',
        pleat_count: 12,
      } as ProcessingOrderItem),
    ).toBe('倍数法')
  })

  it('两样都判不出 / 无 item ⇒ 空串（该行不印：不猜「没采用」也不猜「采用了」）', () => {
    expect(washLabelPleats(null)).toBe('')
    expect(washLabelPleats(undefined)).toBe('')
    expect(washLabelPleats({} as ProcessingOrderItem)).toBe('')
    // 对照：把 `pleat_count` 加上就判得出（判据可判别）
    expect(washLabelPleats({ pleat_count: 8 } as ProcessingOrderItem)).toBe('韩褶 8折')
  })
})

describe('washLabelCopies — 份数 = 打开方式开数（2026-10-26 用户裁定）', () => {
  it('单开 1 / 双开 2 / 三开 3 / 四开 4 逐值', () => {
    expect(washLabelCopies({ openCount: 1 } as ProcessingOrderItem)).toBe(1)
    expect(washLabelCopies({ openCount: 2 } as ProcessingOrderItem)).toBe(2)
    expect(washLabelCopies({ openCount: 3 } as ProcessingOrderItem)).toBe(3)
    expect(washLabelCopies({ openCount: 4 } as ProcessingOrderItem)).toBe(4)
  })

  it('开数是**正整数**不是固定枚举（issue #4387）⇒ 表外开数如实 N 份', () => {
    expect(washLabelCopies({ openCount: 6 } as ProcessingOrderItem)).toBe(6)
  })

  it('缺值 / 非法值 ⇒ 1 份（不印 0 份、不印负数、不印 NaN 份）', () => {
    for (const bad of [undefined, null, 0, -2, Number.NaN, Number.POSITIVE_INFINITY, '', 'abc']) {
      expect(washLabelCopies({ openCount: bad } as unknown as ProcessingOrderItem)).toBe(1)
    }
    expect(washLabelCopies(null)).toBe(1)
    expect(washLabelCopies(undefined)).toBe(1)
    // 存量 / 透传形态：以字符串承载的数字仍要读出来（读不出 ⇒ 静默只打 1 份，比报错更难发现）
    expect(washLabelCopies({ openCount: '2' } as unknown as ProcessingOrderItem)).toBe(2)
  })
})

describe('toWashLabelInputs — 加工单 ⇒ 逐张输入（#6439 → #6656 → #7816 份数展开）', () => {
  const twoPositions = [
    POSITION,
    {
      ...POSITION,
      order_item_id: 'item-2',
      position_name: '纱帘B',
      scan_url: 'https://app.migaozn.com/s/QW8Z2N4B',
      set_no: `${PROCESSING_ORDER_NO}-002`,
    },
  ] as ProductionPosition[]

  it('码 = scan_url ?? part_token；两者都没有 ⇒ null（不画假码）', () => {
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
    // 短码不再进纸面输入（2026-10-26 用户逐字「移除……短码文字」）
    expect(Object.keys(noCode)).not.toContain('shortCode')
  })

  it('🔴 份数 = 开数：双开部位出 2 条、三开出 3 条、缺开数出 1 条', () => {
    const labels = toWashLabelInputs({
      orderNo: ORDER_NO,
      customerName: CUSTOMER,
      positions: twoPositions,
      items: [ITEM, { itemId: 'item-2', openCount: 3, colorName: '米灰' } as unknown as ProcessingOrderItem],
    })
    // item-1 = 双开 2 份 + item-2 = 三开 3 份
    expect(labels).toHaveLength(5)
    // 同开数的几张内容逐字相同（同一部位重复出纸），但码仍取自本部位
    expect(labels[0].rows?.map((row) => row.text)).toEqual(labels[1].rows?.map((row) => row.text))
    expect(labels[0].qrValue).toBe(labels[1].qrValue)
    // 第 3 张起是第二个部位（三开）
    expect(labels[2].qrValue).toBe(labels[3].qrValue)
    expect(labels[2].qrValue).toBe(labels[4].qrValue)
    expect(labels[1].qrValue).not.toBe(labels[2].qrValue)
    // 缺开数 ⇒ 1 份（不印 0 份）
    const single = toWashLabelInputs({ positions: [twoPositions[1]], items: [] })
    expect(single).toHaveLength(1)
  })

  it('🔴 每张都带上**完整纸面行清单**（改动前只映射了 4 个键 ⇒ 直连打出来比预览少十行）', () => {
    const labels = toWashLabelInputs({
      orderNo: ORDER_NO,
      customerName: CUSTOMER,
      positions: [POSITION],
      items: [ITEM],
    })

    // 双开 ⇒ 2 张
    expect(labels).toHaveLength(2)
    labels.forEach((label) => expect(label.qrValue).toBe(POSITION.scan_url))

    // 内容 = `washLabelRows`（内容真值只有一处）
    expect(labels[0].rows?.map((row) => row.text)).toEqual(
      washLabelRows({
        position: POSITION,
        item: ITEM,
        // 单个部位 ⇒ 套数 = 1（走 `groupBySet`，与页面同一份实现）
        setNo: 1,
        setCount: 1,
        customerName: CUSTOMER,
        orderNo: ORDER_NO,
      }).map((row) => row.text),
    )
    expect(labels[0].rows?.length).toBeGreaterThan(5)
    expect(labels[0].rows?.map((row) => row.text)).toContain('用料 6.3米')
    expect(labels[0].rows?.map((row) => row.text)).toContain('褶法 韩褶 52折')
  })

  it('空输入 ⇒ 空数组（不造占位：直连入口据此禁用，不是打一张空白纸）', () => {
    expect(toWashLabelInputs()).toEqual([])
    expect(toWashLabelInputs({ positions: null })).toEqual([])
    expect(toWashLabelInputs({ positions: [] })).toEqual([])
  })
})
