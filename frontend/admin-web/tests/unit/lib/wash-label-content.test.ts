// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6656 建「纸面内容单一真值」→ #7816 字段/份数 → **issue #7833 单号/加工费组合/印全文**）：
// 水洗唛**纸面内容**的单一真值（`frontend/admin-web/src/lib/wash-label-content.ts`）。
//
// 用户 2026-10-26 逐字（issue #7833）：
// 「JG-20261026-8172 这个加工单有超高倒幅，但是在加工单的各个环节都没有体现出来，打印的洗水唛中
//   也需要体现加工费组合中的信息」「加工方式这几个字可以移除」「打印后的结果出现了文字缩写」
// 「把定高买宽和定宽买高的工艺规格信息不要展示在洗水唛上」「订单号是否可以短一些…只留加工单号，删掉订单行」。
//
// 逐条判据（都能判红）：
// ① 行序 = `WASH_LABEL_ROW_KEYS`（**单号 = 加工单号**第一行；订单号 / 加工单号以外的号 / 交期**不在**
//    清单里；改序 ⇒ 必红）；
// ② 前缀（`单号 ` / `客户 ` / `货号 ` / `帘种 ` / `安装小区 ` / `安装位置 ` / `门幅 ` / `用料 ` /
//    `宽高 ` / `特殊选项 ` / `备注 ` / `布料批次 `）在**这一处**拼 —— 渲染器各自再拼一遍就是第二份真值；
//    🔴 **「加工方式」前缀已退场**（用户逐字「可以移除」）⇒ 加工行只印值；
//    🔴 issue #7872（用户 2026-10-26 逐字「这里的颜色文案改成货号，右侧的内容不要变化了，再加一个布料批次号，
//    放在最下面，布料批次：xxx」）：前缀 `颜色` → **`货号`**（值仍是 `colorName` 原样、一字不动）、
//    行清单**末位新增 `布料批次`**（值 = 快照键 `batchNo`）；
// ③ **缺值不渲染，且判空看的是「值」不是「拼好的整行」**：`宽高 ` / `用料 ` 这种只剩前缀的空壳行
//    不得上纸；单号例外（缺值如实 `—`，它是「这张纸是给谁的」的最小可读集合）；
// ④ **褶法 = 是否韩褶公式 + 折数**（一个字段）：`韩褶公式 52折` / `韩褶公式`（无折数不编数）/ `倍数法` /
//    两者都判不出 ⇒ 不印（不猜）；
// ⑤ **份数 = 开数**（`washLabelCopies`）：1/2/3/4、表外 N、缺值/非法值 ⇒ 1；
// ⑥ `toWashLabelInputs`：码 = `scan_url ?? part_token`、按 `itemId` 对齐快照行、**按开数展开 N 条**、
//    0 部位 ⇒ 空数组（不造占位）；
// ⑦ **张序 = 每套连续**（issue #8074，用户 2026-10-29 逐字「每套连续排版，不要拆开」）：
//    `washLabelSheets` 按套聚合 —— 每套先常规唛（部位序 × 开数）、再本套专属唛；套间不交叉。
//    改前 = 全部常规唛在前、全部专属唛追加在最后（多套时同套的纸被拆到两处）。
import { describe, expect, it } from 'vitest'
import {
  WASH_LABEL_OPTION_MEDIA,
  WASH_LABEL_OPTION_ROW_KEYS,
  WASH_LABEL_REGULAR_MEDIA,
  WASH_LABEL_ROW_KEYS,
  toWashLabelInputs,
  washLabelCopies,
  washLabelDocNo,
  washLabelOptionGroupsOf,
  washLabelPleats,
  washLabelRows,
  washLabelSheets,
  washLabelSubtitle,
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
  sku: '0012',
  colorName: '米白',
  // 布料批次（快照键 `batchNo`，派工指派批次时写入）—— 纸面**末行**（issue #7872）
  batchNo: 'PC-20261026-0001',
  // 安装去向（issue #7856）：小区 = 订单级、位置 = 件级；只印，不参与任何计算
  installCommunity: '春江花园 3栋2单元',
  installRoom: '主卧',
  doorWidth: '2.8米',
  craft: '韩褶',
  cuttingMode: '定高买宽',
  openCount: 2,
  isShaped: true,
  // 加工费组合键（= `processingItems[].name` 的集合）：超高 / 倒幅 在这里（issue #7833）
  processingItems: [
    { id: 'pi-1', name: '韩褶', quantity: 1 },
    { id: 'pi-14', name: '超高', quantity: 1 },
    { id: 'pi-16', name: '倒幅', quantity: 1 },
    { id: 'pi-3', name: '定型', quantity: 1 },
  ],
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
    processingOrderNo: PROCESSING_ORDER_NO,
  })

const textOf = (rows: ReturnType<typeof washLabelRows>, key: WashLabelRowKey) =>
  rows.find((row) => row.key === key)?.text

describe('washLabelRows — 纸面内容与行序（issue #6656 → #7816 → #7833）', () => {
  it('判据 ①：全字段齐备时，行序与行文本逐字 == 真实工单的纸面', () => {
    const rows = fullRows()

    // 行序是纸面契约：**单号（加工单号）第一行**（用户 2026-10-26「放到第一行，客户那一行上面」；
    // issue #7833 起该位置印加工单号、17 位订单号退出纸面）
    expect(rows.map((row) => row.key)).toEqual([...WASH_LABEL_ROW_KEYS])
    expect(rows[0].key).toBe('docNo')
    expect(rows[1].key).toBe('customer')

    // issue #7839：纸面单号**去 `JG-` 前缀**（系统里的编号不变）
    expect(textOf(rows, 'docNo')).toBe('单号: 20260921-8237')
    expect(textOf(rows, 'customer')).toBe(`客户: ${CUSTOMER}`)
    expect(textOf(rows, 'setNo')).toBe('第 1 套 / 共 2 套')
    expect(textOf(rows, 'positionKind')).toBe('帘种: 布帘')
    // issue #7856：该行的**值** = `colorName`（不是 `sku`）；
    // 🔴 issue #7872（2026-10-26 用户逐字「这里的颜色文案改成货号，右侧的内容不要变化了」）
    //    ⇒ 前缀由 `颜色` 改 **`货号`**、值一字不动（`米白` 原样）
    expect(textOf(rows, 'color')).toBe('货号: 米白')
    // issue #7856：安装去向（小区 = 订单级、位置 = 件级）—— 都印。
    // 🔴 **issue #7986（2026-10-28 用户逐字「把安装小区和安装位置放置到客户那一行下面」）**
    //    ⇒ 紧跟在**客户**之后（改回「帘种之后」⇒ 下面两条绝对位次断言必红）
    expect(textOf(rows, 'installCommunity')).toBe('安装小区: 春江花园 3栋2单元')
    expect(textOf(rows, 'installRoom')).toBe('安装位置: 主卧')
    const order = rows.map((row) => row.key)
    expect(order.indexOf('installCommunity')).toBe(order.indexOf('customer') + 1)
    expect(order.indexOf('installRoom')).toBe(order.indexOf('installCommunity') + 1)
    // 绝对位次（纸面第 3、4 行；第 1 = 单号、第 2 = 客户）
    expect(rows[2].key).toBe('installCommunity')
    expect(rows[3].key).toBe('installRoom')
    // 其余行的相对顺序不动：套序仍在安装行之后、帘种仍在货号之后
    expect(order.indexOf('setNo')).toBeGreaterThan(order.indexOf('installRoom'))
    expect(order.indexOf('positionKind')).toBe(order.indexOf('color') + 1)
    expect(textOf(rows, 'doorWidth')).toBe('门幅: 2.8米')
    expect(textOf(rows, 'meters')).toBe('用料: 6.3米')
    expect(textOf(rows, 'size')).toBe('宽高: 3×2.75米')
    // 加工行（issue #7833）：**无「加工方式」前缀**、**不印加工类型**、**并入加工费组合项**
    // （韩褶来自工艺、超高/倒幅/定型来自组合键；定型与工艺字段同义 ⇒ 只印一次，落在末尾）
    expect(textOf(rows, 'craft')).toBe('韩褶 · 超高 · 倒幅 · 双开 · 定型')
    // ⑤ 褶法 = 是否韩褶公式 + 折数（同一个字段，用户 2026-10-26 裁定）
    //    🔴 issue #7856：**无「褶法」前缀**（用户逐字「褶法：去掉，只保留后面的文字，和工艺一样」）
    expect(textOf(rows, 'pleats')).toBe('韩褶公式 52折')
    expect(textOf(rows, 'specialOptions')).toBe('特殊选项: 加logo条、防翘扣')
    expect(textOf(rows, 'remark')).toBe('备注: 加铅块')
    // 🔴 布料批次 = 纸面**末行**（issue #7872 用户逐字「放在最下面，布料批次：xxx」）——
    // 位置也是判据：插到别处（例如紧跟颜色）⇒ 本条必红
    expect(textOf(rows, 'batchNo')).toBe('布料批次: PC-20261026-0001')
    expect(rows[rows.length - 1].key).toBe('batchNo')
    // 反向判据：特殊选项**不得**再混进备注行（并回去 ⇒ 必红）
    expect(textOf(rows, 'remark')).not.toContain('加logo条')

    // 🔴 退场项一律不得回来：订单号 / 交期 / 件名 / 算料公式（用户历次裁定）
    expect(rows.map((row) => row.key)).not.toContain('delivery')
    expect(rows.map((row) => row.key)).not.toContain('pieceName')
    expect(rows.map((row) => row.key)).not.toContain('formula')
    const paper = rows.map((row) => row.text).join('｜')
    expect(paper).not.toContain(ORDER_NO) // 17 位订单号退出纸面（issue #7833）
    expect(paper).not.toContain('交期')
    expect(paper).not.toContain('韩褶公式：') // 算料公式行退场（褶法行里的「韩褶公式」是字段值，不是那一行）
    expect(paper).not.toContain('加工方式') // 前缀退场（用户逐字「可以移除」）
    expect(paper).not.toContain('定高买宽') // 加工类型不上纸（用户逐字）
    expect(paper).not.toContain('定宽买高')

    // 🔴 行里**没有**行数预算（issue #7833：有预算就有省略号）—— 只带 key + text
    expect(Object.keys(rows[0]).sort()).toEqual(['key', 'text'])
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
      processingOrderNo: null,
    })

    // 单号缺值如实 `—`（最小可读集合）；其余缺值行整行不出现
    expect(rows.map((row) => row.key)).toEqual(['docNo', 'setNo'])
    expect(rows.map((row) => row.text)).toEqual(['单号: —', '第 2 套 / 共 3 套'])
    // 🔴 正向拒绝：整行 trim 判空会把这些空壳印上纸（改版实测过的形态）
    expect(
      rows.some((row) =>
        ['宽高', '用料', '货号', '门幅', '帘种', '安装小区', '安装位置', '特殊选项', '备注', '客户', '布料批次'].includes(row.text)
      )
    ).toBe(false)
  })

  it('判据 ③：宽高只有一边 ⇒ 不出宽高行（半个尺寸没有意义）', () => {
    const half = { ...POSITION, height: null } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: half, item: null }), 'size')).toBeUndefined()
    const none = { ...POSITION, width: null, height: null } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: none, item: null }), 'size')).toBeUndefined()
    // 正反对照：两值都在 ⇒ 该行必须出现（否则上面两条是空断言）
    expect(textOf(fullRows(), 'size')).toBe('宽高: 3×2.75米')
  })

  it('判据 ④：`货号` 行的**值** = `colorName`（issue #7872：只改文案、值不变）；缺值 ⇒ 该行不出现', () => {
    expect(textOf(fullRows(), 'color')).toBe('货号: 米白')
    // 缺 `colorName`（存量快照）⇒ 不出该行；**不拿 sku 顶替**（issue #7856 用户「不要展示sku」仍有效）
    const noColor = { ...ITEM, colorName: undefined } as unknown as ProcessingOrderItem
    expect(textOf(washLabelRows({ position: POSITION, item: noColor }), 'color')).toBeUndefined()
    // sku 不上纸（改前印「货号: 0012」⇒ 本条必红）
    expect(fullRows().map((row) => row.text).join('｜')).not.toContain('0012')
    // 🔴 旧文案 `颜色` 不得残留（issue #7872 用户逐字「这里的颜色文案改成货号」）
    expect(fullRows().map((row) => row.text).join('｜')).not.toContain('颜色')
  })

  it('🔴 判据 ⑦：布料批次 = 快照 `batchNo`；未指派 ⇒ 如实 `—`；无快照行 ⇒ 该行不出现（issue #7872）', () => {
    expect(textOf(fullRows(), 'batchNo')).toBe('布料批次: PC-20261026-0001')
    // 未指派批次（快照行在、`batchNo` 缺）= 该行**未指派**（≠「本系统没有这个字段」）⇒ 如实 `—`
    // （口径登记在 `frontend/admin-web/src/types/index.ts` 的 `ProcessingOrderItem.batchNo`）
    const noBatch = { ...ITEM, batchNo: undefined } as unknown as ProcessingOrderItem
    expect(textOf(washLabelRows({ position: POSITION, item: noBatch }), 'batchNo')).toBe('布料批次: —')
    // 空串 / 纯空格按缺值处理（不印「布料批次: 」这种空壳）
    const blank = { ...ITEM, batchNo: '   ' } as unknown as ProcessingOrderItem
    expect(textOf(washLabelRows({ position: POSITION, item: blank }), 'batchNo')).toBe('布料批次: —')
    // 没有快照行 ⇒ 不猜（与其它快照派生行同一条口径：整行不出现，不印 `—`）
    expect(textOf(washLabelRows({ position: POSITION, item: null }), 'batchNo')).toBeUndefined()
  })

  it('判据 ④-b：**帘种紧跟在颜色下面**（用户 2026-10-26「再加个帘种，放到货号下面」）', () => {
    // 有颜色行时：颜色 → 帘种 相邻且顺序固定
    const keys = fullRows().map((row) => row.key)
    expect(keys.indexOf('positionKind')).toBe(keys.indexOf('color') + 1)
    // 颜色缺值时，帘种仍在（两条判据互不依赖 —— 否则「相邻」会被缺值掩盖）
    const noColor = { ...ITEM, colorName: undefined } as unknown as ProcessingOrderItem
    const rows = washLabelRows({ position: POSITION, item: noColor })
    expect(rows.map((row) => row.key)).toContain('positionKind')
    expect(rows.map((row) => row.key)).not.toContain('color')
    // `position_kind` 缺值时回落到快照 `curtainType`（同一条取值链，不另做推导）
    const barePosition = { ...POSITION, position_kind: undefined } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: barePosition, item: { ...ITEM, curtainType: '纱帘' } as ProcessingOrderItem }), 'positionKind')).toBe('帘种: 纱帘')
  })

  it('判据 ④-c：安装信息缺值 ⇒ 整行不印（不印「安装小区: —」占纸，issue #7856）', () => {
    const rows = washLabelRows({ position: POSITION, item: { ...ITEM, installCommunity: '', installRoom: undefined } as ProcessingOrderItem })
    expect(rows.map((row) => row.key)).not.toContain('installCommunity')
    expect(rows.map((row) => row.key)).not.toContain('installRoom')
  })

  it('判据 ⑤：套序来自调用方给的 `groupBySet` 读数（1 起）', () => {
    expect(textOf(washLabelRows({ position: POSITION, item: null, setNo: 3, setCount: 5 }), 'setNo')).toBe(
      '第 3 套 / 共 5 套',
    )
    // 缺读数 ⇒ 退化成「第 1 套 / 共 1 套」（不出现 NaN / undefined）
    expect(textOf(washLabelRows({ position: POSITION, item: null }), 'setNo')).toBe('第 1 套 / 共 1 套')
  })

  it('判据 ⑥：是否定型按行业措辞收成「定型 / 不定型」（不印「是否定型：是」）', () => {
    // 这一条用**没有组合项**的快照：只判「是否定型」这一格映射（组合项并入见上一条判据 ①）
    const plain = { ...ITEM, processingItems: undefined } as unknown as ProcessingOrderItem
    const unshaped = { ...plain, isShaped: false } as unknown as ProcessingOrderItem
    const craft = textOf(washLabelRows({ position: POSITION, item: unshaped }), 'craft')
    expect(craft).toBe('韩褶 · 双开 · 不定型')
    expect(craft).not.toContain('是否定型')
    // 正反对照：定型 = 是 ⇒ 「定型」（判据可判别 —— 写死「定型」⇒ 不定型那条必红）
    expect(textOf(washLabelRows({ position: POSITION, item: plain }), 'craft')).toBe('韩褶 · 双开 · 定型')
  })

  it('🔴 加工费组合项并入加工行；「定型」不印两遍；组合项顺序 = 后端数组序（issue #7833）', () => {
    const rows = fullRows()
    const craft = textOf(rows, 'craft') || ''
    // 组合项逐字上纸（这正是「加工单有超高倒幅…没有体现出来」的修复落点）
    for (const name of ['超高', '倒幅']) expect(craft).toContain(name)
    // 同义项只印一次：组合里的「定型」与是否定型同义 ⇒ 只出现一次（末尾格）
    expect(craft.split('定型').length - 1).toBe(1)
    // 顺序：工艺 → 组合项（保序）→ 打开方式 → 定型
    expect(craft.indexOf('韩褶')).toBeLessThan(craft.indexOf('超高'))
    expect(craft.indexOf('超高')).toBeLessThan(craft.indexOf('倒幅'))
    expect(craft.indexOf('倒幅')).toBeLessThan(craft.indexOf('双开'))
    expect(craft.trimEnd().endsWith('定型')).toBe(true)
    // 没有组合项 ⇒ 只剩工艺 / 打开方式 / 定型（不编「组合为空」之类的占位）
    const noCombo = { ...ITEM, processingItems: [] } as unknown as ProcessingOrderItem
    expect(textOf(washLabelRows({ position: POSITION, item: noCombo }), 'craft')).toBe('韩褶 · 双开 · 定型')
  })

  it('加工类型不上纸（定高买宽 / 定宽买高都不印）—— 用户 2026-10-26 逐字', () => {
    for (const cuttingMode of ['定高买宽', '定宽买高', 'fixed_height_pleats']) {
      const item = { ...ITEM, cuttingMode } as unknown as ProcessingOrderItem
      const craft = textOf(washLabelRows({ position: POSITION, item }), 'craft') || ''
      expect(craft).not.toContain('定高买宽')
      expect(craft).not.toContain('定宽买高')
      expect(craft).not.toContain('fixed_height')
    }
  })

  it('门幅缺值 ⇒ 不出门幅行（不印空壳）；两种存量形态都补单位', () => {
    const anonymous = { order_item_id: 'item-9' } as unknown as ProductionPosition
    expect(textOf(washLabelRows({ position: anonymous, item: null }), 'doorWidth')).toBeUndefined()
    const bare = { ...ITEM, doorWidth: '2.8' } as unknown as ProcessingOrderItem
    expect(textOf(washLabelRows({ position: POSITION, item: bare }), 'doorWidth')).toBe('门幅: 2.8米')
  })

  it('无 position ⇒ 空清单（不在这里造占位行）', () => {
    expect(washLabelRows({ position: null, item: ITEM })).toEqual([])
    expect(washLabelRows({})).toEqual([])
  })
})

describe('washLabelDocNo — 纸面单号去 `JG-` 前缀（issue #7839，用户「简约点」）', () => {
  it('只剥开头那一个 `JG-`（大小写不敏感）；其余形态原样返回', () => {
    expect(washLabelDocNo('JG-20261026-8172')).toBe('20261026-8172')
    expect(washLabelDocNo('jg-20261026-8172')).toBe('20261026-8172')
    // 前后空白先 trim（后端历史脏数据）
    expect(washLabelDocNo('  JG-20261026-8172  ')).toBe('20261026-8172')
    // 只剥开头：中间出现的「JG-」不动（不是全局替换）
    expect(washLabelDocNo('2026-JG-8172')).toBe('2026-JG-8172')
    // 其它编号形态不猜、不改（存量单 / 手工单）
    expect(washLabelDocNo('PO260926-0007')).toBe('PO260926-0007')
    expect(washLabelDocNo('202610268172')).toBe('202610268172')
  })

  it('空值 / 缺值 ⇒ 空串（调用方按「缺值 ⇒ —」处理，不编造）', () => {
    expect(washLabelDocNo(undefined)).toBe('')
    expect(washLabelDocNo(null)).toBe('')
    expect(washLabelDocNo('   ')).toBe('')
    expect(washLabelDocNo('JG-')).toBe('')
  })
})

describe('washLabelPleats — 褶法 = 是否韩褶公式 + 折数（一个字段，2026-10-26 用户裁定）', () => {
  it('韩褶公式 + 折数 ⇒ 「韩褶公式 N折」（折数取自 `pleat_count`，不重算）', () => {
    expect(washLabelPleats(ITEM)).toBe('韩褶公式 52折')
    expect(washLabelPleats({ pleat_count: 36 } as ProcessingOrderItem)).toBe('韩褶公式 36折')
  })

  it('韩褶公式但折数缺失 ⇒ 只写「韩褶公式」（**不编数**）', () => {
    const noCount = { ...ITEM, pleat_count: undefined } as unknown as ProcessingOrderItem
    expect(washLabelPleats(noCount)).toBe('韩褶公式')
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
    expect(washLabelPleats({ pleat_count: 8 } as ProcessingOrderItem)).toBe('韩褶公式 8折')
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
      processingOrderNo: PROCESSING_ORDER_NO,
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
      processingOrderNo: PROCESSING_ORDER_NO,
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
        processingOrderNo: PROCESSING_ORDER_NO,
      }).map((row) => row.text),
    )
    expect(labels[0].rows?.length).toBeGreaterThan(5)
    expect(labels[0].rows?.map((row) => row.text)).toContain('用料: 6.3米')
    expect(labels[0].rows?.map((row) => row.text)).toContain('韩褶公式 52折')
  })

  it('空输入 ⇒ 空数组（不造占位：直连入口据此禁用，不是打一张空白纸）', () => {
    expect(toWashLabelInputs()).toEqual([])
    expect(toWashLabelInputs({ positions: null })).toEqual([])
    expect(toWashLabelInputs({ positions: [] })).toEqual([])
  })
})

describe('专属唛 —— 余料带回 / 绑带 每套一张（issue #8002）', () => {
  const optionItem = (specialOptions: string[]) =>
    ({ ...ITEM, specialOptions } as unknown as ProcessingOrderItem)
  const twoPositions = [
    POSITION,
    {
      ...POSITION,
      order_item_id: 'item-2',
      position_name: '纱帘B',
      set_no: `${PROCESSING_ORDER_NO}-002`,
      scan_url: 'https://app.migaozn.com/s/QW8Z2N4B',
    },
  ] as ProductionPosition[]

  it('类别：选项名逐字命中；「余料做绑带 / 余料做帘头」不触发；副标题 = 语义名（**去**「成品定制」前缀）', () => {
    expect(washLabelOptionGroupsOf(optionItem(['余料带回-布']))).toEqual([
      { label: '余料带回', options: ['余料带回-布'] },
    ])
    expect(washLabelOptionGroupsOf(optionItem(['加logo条', '布绑带']))).toEqual([
      { label: '绑带', options: ['布绑带'] },
    ])
    // 同一部位两类都勾（参考工单）⇒ 2 张，按类别顺序
    expect(washLabelOptionGroupsOf(optionItem(['布绑带', '余料带回-布']))).toEqual([
      { label: '余料带回', options: ['余料带回-布'] },
      { label: '绑带', options: ['布绑带'] },
    ])
    // 不产生「交还客户的那袋东西」的选项不触发
    expect(washLabelOptionGroupsOf(optionItem(['余料做绑带', '余料做帘头', '加logo条']))).toEqual([])
    expect(washLabelOptionGroupsOf(undefined)).toEqual([])
    // 🔴 2026-10-29（用户逐字「洗水唛的副标题 成品定制.余料带回 改成余料带回，移除前面的成品定制」）：
    // 专属唛副标题**只印语义名**；常规唛仍是 `成品定制`（一字未改）
    expect(washLabelSubtitle('余料带回')).toBe('余料带回')
    expect(washLabelSubtitle('绑带')).toBe('绑带')
    expect(washLabelSubtitle(null)).toBe('成品定制')
    expect(washLabelSubtitle('')).toBe('成品定制')
    // 反向：专属唛的副标题里不得再出现前缀（改回 `成品定制 · X` ⇒ 必红）
    expect(washLabelSubtitle('余料带回')).not.toContain('成品定制')
    expect(washLabelSubtitle('绑带')).not.toContain('成品定制')
  })

  it('张数：常规唛 = 开数；专属唛 = 每套每类别 1 张（不乘开数）、排在常规唛之后', () => {
    const sheets = washLabelSheets({ positions: [POSITION], items: [optionItem(['余料带回-布', '布绑带'])] })
    // 双开 ⇒ 常规 2 张 + 专属 2 张
    expect(sheets).toHaveLength(4)
    expect(sheets.map((sheet) => sheet.optionLabel)).toEqual([null, null, '余料带回', '绑带'])
    expect(sheets.map((sheet) => sheet.subtitle)).toEqual([
      '成品定制',
      '成品定制',
      '余料带回',
      '绑带',
    ])
    // 专属唛：码 / 套序 / 快照行都沿用该部位（不另造内容）
    expect(sheets[2].qrValue).toBe(POSITION.scan_url)
    expect(sheets[2].position).toBe(POSITION)
    expect(sheets[2].item?.itemId).toBe('item-1')
    expect(sheets[2].setNo).toBe(1)
    // 没有命中选项 ⇒ 零专属唛（常规唛原样）
    const plain = washLabelSheets({ positions: [POSITION], items: [ITEM] })
    expect(plain).toHaveLength(2)
    expect(plain.every((sheet) => sheet.optionLabel === null)).toBe(true)
  })

  it('一套一张：两套各自出自己那一张（套序 / 类别各自独立，且**每套连续**——issue #8074）', () => {
    const sheets = washLabelSheets({
      positions: twoPositions,
      items: [optionItem(['余料带回-布']), { itemId: 'item-2', openCount: 1, specialOptions: ['纱绑带'] } as unknown as ProcessingOrderItem],
    })
    // 常规 = 双开 2 + 单开 1；专属 = 第 1 套的余料 + 第 2 套的绑带
    expect(sheets).toHaveLength(5)
    // 🔴 用户 2026-10-29「每套连续排版，不要拆开」：第 1 套常规 2 张 → 第 1 套专属 1 张
    // → 第 2 套常规 1 张 → 第 2 套专属 1 张（改前 = 全部常规在前、专属整体追加到最后）
    expect(sheets.map((sheet) => sheet.optionLabel)).toEqual([null, null, '余料带回', null, '绑带'])
    expect(sheets.map((sheet) => sheet.setNo)).toEqual([1, 1, 1, 2, 2])
    expect(sheets[2].qrValue).toBe(POSITION.scan_url)
    expect(sheets[4].qrValue).toBe(twoPositions[1].scan_url)
  })

  it('🔴 多套交叉入参 ⇒ 出纸仍「每套连续」（issue #8074）', () => {
    // 真实读面顺序：后端 `listOperations` 按 `position_name` 升序 ⇒ 多套同商品同色号时
    // 「第 1 套布 / 第 2 套布 / 第 1 套纱 / 第 2 套纱」交叉进来。
    const crossed = [
      { ...POSITION, order_item_id: 'item-1', set_no: `${PROCESSING_ORDER_NO}-001`, scan_url: 'scan-1-bu' },
      { ...POSITION, order_item_id: 'item-2', set_no: `${PROCESSING_ORDER_NO}-002`, scan_url: 'scan-2-bu' },
      { ...POSITION, order_item_id: 'item-3', set_no: `${PROCESSING_ORDER_NO}-001`, scan_url: 'scan-1-sha' },
      { ...POSITION, order_item_id: 'item-4', set_no: `${PROCESSING_ORDER_NO}-002`, scan_url: 'scan-2-sha' },
    ] as ProductionPosition[]
    const sheets = washLabelSheets({
      positions: crossed,
      items: [
        { itemId: 'item-1', openCount: 2, specialOptions: ['余料带回-布'] },
        { itemId: 'item-2', openCount: 1, specialOptions: [] },
        { itemId: 'item-3', openCount: 1, specialOptions: [] },
        { itemId: 'item-4', openCount: 1, specialOptions: ['纱绑带'] },
      ] as unknown as ProcessingOrderItem[],
    })
    // 第 1 套：布 ×2 → 纱 ×1 → 余料 ×1；第 2 套：布 ×1 → 纱 ×1 → 绑带 ×1
    expect(sheets).toHaveLength(7)
    expect(sheets.map((sheet) => sheet.setNo)).toEqual([1, 1, 1, 1, 2, 2, 2])
    expect(sheets.map((sheet) => sheet.qrValue)).toEqual([
      'scan-1-bu',
      'scan-1-bu',
      'scan-1-sha',
      'scan-1-bu',
      'scan-2-bu',
      'scan-2-sha',
      'scan-2-sha',
    ])
    expect(sheets.map((sheet) => sheet.optionLabel)).toEqual([
      null,
      null,
      null,
      '余料带回',
      null,
      null,
      '绑带',
    ])
  })

  it('🔴 不变量（类级）：**任意部位入参顺序** ⇒ 出纸的套序单调不降、每套是连续段（issue #8074）', () => {
    // 交叉入参只是**一种**顺序；读面顺序会随 `position_name` / 数据漂移 ⇒ 用全排列钉住「与入参顺序无关」。
    const base = [
      { ...POSITION, order_item_id: 'item-1', set_no: `${PROCESSING_ORDER_NO}-001`, scan_url: 'scan-1-bu' },
      { ...POSITION, order_item_id: 'item-2', set_no: `${PROCESSING_ORDER_NO}-002`, scan_url: 'scan-2-bu' },
      { ...POSITION, order_item_id: 'item-3', set_no: `${PROCESSING_ORDER_NO}-001`, scan_url: 'scan-1-sha' },
      { ...POSITION, order_item_id: 'item-4', set_no: `${PROCESSING_ORDER_NO}-002`, scan_url: 'scan-2-sha' },
    ] as ProductionPosition[]
    const itemList = [
      { itemId: 'item-1', openCount: 2, specialOptions: ['余料带回-布'] },
      { itemId: 'item-2', openCount: 1, specialOptions: [] },
      { itemId: 'item-3', openCount: 1, specialOptions: [] },
      { itemId: 'item-4', openCount: 1, specialOptions: ['纱绑带'] },
    ] as unknown as ProcessingOrderItem[]
    const permutations = (list: ProductionPosition[]): ProductionPosition[][] =>
      list.length <= 1
        ? [list]
        : list.flatMap((head, index) =>
            permutations([...list.slice(0, index), ...list.slice(index + 1)]).map((rest) => [head, ...rest]),
          )
    let checked = 0
    for (const positions of permutations(base)) {
      const setNos = washLabelSheets({ positions, items: itemList }).map((sheet) => sheet.setNo)
      expect(setNos).toHaveLength(7)
      // ① 套序单调不降：第 N 套的纸不得出现在第 N+1 套之后
      expect(setNos).toEqual([...setNos].sort((a, b) => a - b))
      // ② 每个套号占的下标集合必须是**连续段**（= 每套的纸不拆开）
      for (const setNo of new Set(setNos)) {
        const indices = setNos.map((value, index) => (value === setNo ? index : -1)).filter((index) => index >= 0)
        expect(indices[indices.length - 1] - indices[0] + 1).toBe(indices.length)
      }
      checked += 1
    }
    expect(checked).toBe(24)
  })

  it('直连通道同样含专属唛（与系统打印同源）：条数 / 副标题 / 纸型一致；行清单 = 专属唛 5 行', () => {
    const labels = toWashLabelInputs({
      processingOrderNo: PROCESSING_ORDER_NO,
      customerName: CUSTOMER,
      positions: [POSITION],
      items: [optionItem(['余料带回-布'])],
    })
    // 双开 2 + 余料 1
    expect(labels).toHaveLength(3)
    expect(labels.map((label) => label.optionLabel ?? null)).toEqual([null, null, '余料带回'])
    // 🔴 issue #8107：专属唛的行清单 = 同一份 `washLabelRows`（**`variant: 'option'`**，不另写推导）——
    //    与常规唛共用取值链、只是行集合收窄到 5 行
    expect(labels[2].rows?.map((row) => row.text)).toEqual(
      washLabelRows({
        position: POSITION,
        item: optionItem(['余料带回-布']),
        setNo: 1,
        setCount: 1,
        customerName: CUSTOMER,
        processingOrderNo: PROCESSING_ORDER_NO,
        variant: 'option',
      }).map((row) => row.text),
    )
    // 纸型也跟着这张纸走（两条通道同读 `sheet.media`）
    expect(labels.map((label) => label.media)).toEqual(['label-50x140', 'label-50x140', 'label-50x100'])
  })
})

describe('专属唛瘦身 —— 只印 5 行 + 二维码，纸型 50×100（issue #8107）', () => {
  const OPTION_ITEM = { ...ITEM, specialOptions: ['余料带回-布', '布绑带'] } as unknown as ProcessingOrderItem

  it('🔴 专属唛的行集合 = 恰好 5 行，顺序 = 货号 / 门幅 / 宽高 / 工艺 / 特殊选项', () => {
    const rows = washLabelRows({
      position: POSITION,
      item: OPTION_ITEM,
      setNo: 1,
      setCount: 2,
      customerName: CUSTOMER,
      processingOrderNo: PROCESSING_ORDER_NO,
      variant: 'option',
    })
    expect(rows.map((row) => row.key)).toEqual([...WASH_LABEL_OPTION_ROW_KEYS])
    expect(rows.map((row) => row.key)).toEqual(['color', 'doorWidth', 'size', 'craft', 'specialOptions'])
    // 逐行文本 = 与常规唛**同一套取值链**（不是另写的推导）
    expect(rows.map((row) => row.text)).toEqual([
      '货号: 米白',
      '门幅: 2.8米',
      '宽高: 3×2.75米',
      '韩褶 · 超高 · 倒幅 · 双开 · 定型',
      // 🔴 issue #8108 口径迁移（不是放宽）：纸面「特殊选项」行读**展示名**，
      // `布绑带` / `纱绑带` 自 #8108 起收回语义名 `绑带` ⇒ 同一份夹具的纸面文本从
      // `余料带回、布绑带` 变成 `余料带回、绑带`。这里仍是**逐字精确**断言：退回旧词表 ⇒ 必红。
      '特殊选项: 余料带回、绑带',
    ])
  })

  it('🔴 负控：退场行在专属唛里**一条都取不到**（10 个键逐个反查）', () => {
    const rows = washLabelRows({
      position: POSITION,
      item: OPTION_ITEM,
      setNo: 1,
      setCount: 2,
      customerName: CUSTOMER,
      processingOrderNo: PROCESSING_ORDER_NO,
      variant: 'option',
    })
    const keys = rows.map((row) => row.key)
    for (const gone of [
      'docNo',
      'customer',
      'setNo',
      'positionKind',
      'installCommunity',
      'installRoom',
      'meters',
      'pleats',
      'remark',
      'batchNo',
    ] as const) {
      expect(keys, `专属唛不得印「${gone}」`).not.toContain(gone)
    }
    // 纸面文本里也不得出现它们的值（改回全字段 ⇒ 任一条必红）
    const paper = rows.map((row) => row.text).join('｜')
    expect(paper).not.toContain(CUSTOMER)
    expect(paper).not.toContain('20260921-8237')
    expect(paper).not.toContain('第 1 套')
    expect(paper).not.toContain('春江花园')
    expect(paper).not.toContain('主卧')
    expect(paper).not.toContain('用料')
    expect(paper).not.toContain('韩褶公式 52折')
    expect(paper).not.toContain('加铅块')
    expect(paper).not.toContain('PC-20261026-0001')
  })

  it('🔴 负控：常规唛仍是 15 行、一字未改（专属唛瘦身不许波及常规唛）', () => {
    const rows = fullRows()
    expect(rows).toHaveLength(15)
    // 🔴 issue #8145 收口：常规唛的**行集合与纸型**没变，但「特殊选项」行**确实**变了 ——
    // 它随 #8007 全系统展示归一改印展示名（`余料带回-布` ⇒ `余料带回`、`布绑带` ⇒ `绑带`）。
    // 有人把纸面改回 join key（`余料带回-布、布绑带`）⇒ 下面这条逐字断言必红。
    const familyRegular = textOf(
      washLabelRows({
        position: POSITION,
        item: { ...ITEM, specialOptions: ['余料带回-布', '布绑带'] } as unknown as ProcessingOrderItem,
        variant: 'regular',
      }),
      'specialOptions',
    )
    expect(familyRegular).toBe('特殊选项: 余料带回、绑带')

    expect(rows.map((row) => row.key)).toEqual([...WASH_LABEL_ROW_KEYS])
    // 缺省 variant = 常规
    expect(rows.map((row) => row.key)).toEqual(
      washLabelRows({
        position: POSITION,
        item: ITEM,
        setNo: 1,
        setCount: 2,
        customerName: CUSTOMER,
        processingOrderNo: PROCESSING_ORDER_NO,
        variant: 'regular',
      }).map((row) => row.key),
    )
  })

  it('🔴「特殊选项」行印**展示名**（issue #8007 的展示归一落点）：`余料带回-布` ⇒ `余料带回`', () => {
    const regular = textOf(fullRows(), 'specialOptions')
    // 常规唛：落库键不上纸（改回 `加logo条、防翘扣` 之外的原样键 ⇒ 本例只判去族化）
    expect(regular).toBe('特殊选项: 加logo条、防翘扣')
    const family = textOf(
      washLabelRows({ position: POSITION, item: { ...ITEM, specialOptions: ['余料带回-布', '加logo条'] } as unknown as ProcessingOrderItem }),
      'specialOptions',
    )
    expect(family).toBe('特殊选项: 余料带回、加logo条')
    // 反向：落库键后缀不得上纸
    expect(family).not.toContain('余料带回-布')
    // 语义名（AI / 其它写入口）同样原样印（它本来就是展示名）
    const semantic = textOf(
      washLabelRows({ position: POSITION, item: { ...ITEM, specialOptions: ['余料带回'] } as unknown as ProcessingOrderItem }),
      'specialOptions',
    )
    expect(semantic).toBe('特殊选项: 余料带回')
    // 专属唛同一份取值链 ⇒ 同样印展示名
    const option = textOf(
      washLabelRows({
        position: POSITION,
        item: { ...ITEM, specialOptions: ['余料带回-纱'] } as unknown as ProcessingOrderItem,
        variant: 'option',
      }),
      'specialOptions',
    )
    expect(option).toBe('特殊选项: 余料带回')
  })

  it('🔴 触发：落库键与**语义名**都认（AI / 其它写入口可能写语义名）；`余料做绑带` 仍不触发', () => {
    expect(washLabelOptionGroupsOf({ specialOptions: ['余料带回'] } as unknown as ProcessingOrderItem)).toEqual([
      { label: '余料带回', options: ['余料带回'] },
    ])
    expect(washLabelOptionGroupsOf({ specialOptions: ['绑带'] } as unknown as ProcessingOrderItem)).toEqual([
      { label: '绑带', options: ['绑带'] },
    ])
    // 落库键仍照旧（这一条不是替代，而是**额外**）
    expect(washLabelOptionGroupsOf({ specialOptions: ['余料带回-布'] } as unknown as ProcessingOrderItem)).toEqual([
      { label: '余料带回', options: ['余料带回-布'] },
    ])
    expect(washLabelOptionGroupsOf({ specialOptions: ['布绑带'] } as unknown as ProcessingOrderItem)).toEqual([
      { label: '绑带', options: ['布绑带'] },
    ])
    // 不产生「要交还客户的那袋东西」的选项不触发（改宽表 ⇒ 必红）
    expect(washLabelOptionGroupsOf({ specialOptions: ['余料做绑带', '余料做帘头'] } as unknown as ProcessingOrderItem)).toEqual(
      [],
    )
  })

  it('🔴 纸型：专属唛 = label-50x100、常规唛 = label-50x140（sheet 上给，两条通道同读）', () => {
    const sheets = washLabelSheets({ positions: [POSITION], items: [OPTION_ITEM] })
    // 双开 ⇒ 常规 2 张 + 专属 2 张（余料 / 绑带）
    expect(sheets).toHaveLength(4)
    expect(sheets.map((sheet) => sheet.media)).toEqual([
      'label-50x140',
      'label-50x140',
      'label-50x100',
      'label-50x100',
    ])
    expect(sheets.map((sheet) => sheet.variant)).toEqual(['regular', 'regular', 'option', 'option'])
    // 常量本身 = 矩阵里那两张纸（写死别的 id ⇒ TS 类型 + 本判据双红）
    expect(WASH_LABEL_REGULAR_MEDIA).toBe('label-50x140')
    expect(WASH_LABEL_OPTION_MEDIA).toBe('label-50x100')
    // 直连通道按 sheet 给到每张输入
    const labels = toWashLabelInputs({ positions: [POSITION], items: [OPTION_ITEM] })
    expect(labels.map((label) => label.media)).toEqual([
      'label-50x140',
      'label-50x140',
      'label-50x100',
      'label-50x100',
    ])
  })

  it('🔴 张数 / 张序 / 每套连续（#8074 既有判据）**一字不改**（瘦身只动行集合与纸型）', () => {
    const sheets = washLabelSheets({ positions: [POSITION], items: [OPTION_ITEM] })
    expect(sheets.map((sheet) => sheet.optionLabel)).toEqual([null, null, '余料带回', '绑带'])
    expect(sheets.map((sheet) => sheet.subtitle)).toEqual([
      '成品定制',
      '成品定制',
      '余料带回',
      '绑带',
    ])
    // 抬头标记保留（它是「这张纸属于哪个特殊选项」的标记）：常规唛 = `成品定制`、专属唛 = 语义名本身
    expect(sheets[0].subtitle).toBe('成品定制')
    expect(sheets[2].subtitle).toBe('余料带回')
    expect(sheets.slice(2).every((sheet) => sheet.subtitle !== '成品定制' && sheet.subtitle !== '')).toBe(true)
    // 码与快照行沿用该部位（不另造内容）
    expect(sheets[2].qrValue).toBe(POSITION.scan_url)
    expect(sheets[2].position).toBe(POSITION)
    expect(sheets[2].item?.itemId).toBe('item-1')
  })
})
