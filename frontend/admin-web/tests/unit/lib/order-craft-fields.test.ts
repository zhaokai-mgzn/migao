// case_ids: OR-035, OR-038
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为（写侧录入）。
// 改用 **OR-035**（本 PR 新增，判据即本文件 + OrderCraftFields.test.tsx + craft-calc-defaults.test.ts）。
// OR-038（issue #4521 新增）：**移除部位 + 帘体四类购买情况**（布帘 / 纱帘 / 布帘+纱帘 / 布料）
// 的写侧判据 —— 主帘不写 `curtainType`、纱帘行显式写 + 携带同一份工艺规格。
/**
 * 下单页工艺规格**写侧**（issue #4375 包 4b · 设计文档 §4.2/§4.5/§4.8）。
 *
 * 两条硬约束的判据：
 * 1. **缺值不写**：用户没填 ⇒ 该键**不出现**（不写空串 / 0 / false —— 下游会当成真值）；
 * 2. **键名 camelCase**（§4.5）：订单/快照层与 Java 侧一致。
 */
import { describe, it, expect } from 'vitest'
import * as orderCraftFields from '@/lib/order-craft-fields'
import {
  CRAFT_OPTIONS,
  CURTAIN_BODY_CLOTH,
  CURTAIN_BODY_OPTIONS,
  CURTAIN_BODY_SHEER,
  CURTAIN_TYPE_OPTIONS,
  CURTAIN_TYPE_SHEER,
  CUTTING_MODE_OPTIONS,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  SPECIAL_OPTIONS,
  STYLE_OPTIONS,
  buildCraftSpec,
  buildEdgeLineCraftSpec,
  buildMainLineGroupKeys,
  buildWindowGroupKey,
  curtainTypeOfBody,
  defaultIsShapedForBody,
  resolveWindowCraftLineIds,
} from '@/lib/order-craft-fields'

describe('枚举清单（与库侧逐字一致）', () => {
  it('部位 = 布帘/纱帘/帘头', () => {
    expect(CURTAIN_TYPE_OPTIONS).toEqual(['布帘', '纱帘', '帘头'])
  })

  it('工艺 = 韩褶/打孔/四爪钩/穿杆/平幔（错值会让加工单取到错误工序路线）', () => {
    expect(CRAFT_OPTIONS).toEqual(['韩褶', '打孔', '四爪钩', '穿杆', '平幔'])
  })

  it('加工类型 = 定高买宽/定宽买高', () => {
    expect(CUTTING_MODE_OPTIONS).toEqual(['定高买宽', '定宽买高'])
  })

  // issue #4387 判据 1：`open_count` 是**开数（正整数）**，不是固定枚举 ——
  // 用户口径明确含**三开**，而 V63 列注释与下拉此前只有 1/2/4（三开选不出来 ⇒ 红）。
  it('打开方式 = 单开(1)/双开(2)/三开(3)/四开(4)（#4387 判据 1：候选必须含 3）', () => {
    expect(OPEN_COUNT_OPTIONS.map((o) => [o.value, o.label])).toEqual([
      [1, '单开'],
      [2, '双开'],
      [3, '三开'],
      [4, '四开'],
    ])
  })

  it('款式 = 单色/拼色', () => {
    expect(STYLE_OPTIONS).toEqual(['单色', '拼色'])
  })

  it('特殊选项 19 项，逐字等于真值源 §1 清单（选项名 = ERP 名，issue #4389）', () => {
    expect(SPECIAL_OPTIONS).toEqual([
      '余料带回-布', '余料带回-纱', '布绑带', '纱绑带', '加logo条', '加立边',
      '加花边', '拼1次', '拼2次', '拼3次', '加铅块', '接高', '双眼皮接高',
      '扣环', '抱枕', '防翘扣', '一分为二', '余料做绑带', '余料做帘头',
    ])
    expect(new Set(SPECIAL_OPTIONS).size).toBe(19)
  })

  it('特殊选项名是 join key：不得残留旧写法（与库侧差一个字 ⇒ 静默失效）', () => {
    // issue #4389：`一分二` / `余料带回(布)` / `余料带回(纱)` 是 ERP 名对齐**之前**的写法，
    // 服务端按 option_name 逐字匹配 ⇒ 写侧残留旧名 = 条件工序不加、系数静默退回 1.0。
    for (const stale of ['一分二', '余料带回(布)', '余料带回(纱)']) {
      expect(SPECIAL_OPTIONS as readonly string[]).not.toContain(stale)
    }
  })
})

describe('buildCraftSpec：缺值不写', () => {
  it('未填任何工艺 ⇒ 空对象（不写空串 / 0 / false 占位）', () => {
    expect(buildCraftSpec({})).toEqual({})
  })

  it('全填 ⇒ 逐键 camelCase 落库', () => {
    expect(
      buildCraftSpec({
        craft: '打孔',
        cuttingMode: '定高买宽',
        openCount: 2,
        isShaped: false,
        formula: 'fullness',
        craftTier: 'standard',
        hasPattern: true,
        patternRepeat: 0.6,
        style: '拼色',
        specialOptions: ['加铅块', '拼2次'],
      })
    ).toEqual({
      craft: '打孔',
      cuttingMode: '定高买宽',
      openCount: 2,
      isShaped: false,
      formula: 'fullness',
      craftTier: 'standard',
      hasPattern: true,
      patternRepeat: 0.6,
      style: '拼色',
      specialOptions: ['加铅块', '拼2次'],
    })
  })

  // issue #4521：部位已从录入面移除 —— 主帘**缺省即布帘**（下游 ProcessingOrderService
  // 的 DEFAULT_CURTAIN_TYPE 同值）。写侧一旦再写 `curtainType`，就等于给商家留了一条
  // 「把主帘标成纱帘」的口子（工序路线会取错）。
  it('#4521 buildCraftSpec **不写** curtainType（部位已移除；纱帘行由 buildSheerLineCraftSpec 显式写）', () => {
    const built = buildCraftSpec({
      craft: '韩褶',
      cuttingMode: '定高买宽',
      isShaped: true,
    })
    expect(built).not.toHaveProperty('curtainType')
    expect(Object.keys(built)).not.toContain('curtainType')
  })

  it('显式「否」是真值 ⇒ 必须写（isShaped=false / hasPattern=false 不得当成未填丢弃）', () => {
    expect(buildCraftSpec({ isShaped: false, hasPattern: false })).toEqual({
      isShaped: false,
      hasPattern: false,
    })
  })

  it('空串 / 纯空白字符串 ⇒ 不写该键', () => {
    expect(buildCraftSpec({ craft: '   ', style: '' })).toEqual({})
  })

  it('数值占位 0 / NaN / 非数值 ⇒ 不写该键（0 会被下游当成真值）', () => {
    expect(
      buildCraftSpec({
        openCount: 0,
        patternRepeat: 0,
      })
    ).toEqual({})
    expect(
      buildCraftSpec({
        openCount: Number.NaN,
      })
    ).toEqual({})
  })

  it('特殊选项：空数组 ⇒ 不写；空串项被丢弃', () => {
    expect(buildCraftSpec({ specialOptions: [] })).toEqual({})
    expect(buildCraftSpec({ specialOptions: ['  ', '加铅块', ''] })).toEqual({
      specialOptions: ['加铅块'],
    })
  })

  it('是否对花 = 否 ⇒ 花距无意义，不写 patternRepeat（不留自相矛盾的真值）', () => {
    expect(buildCraftSpec({ hasPattern: false, patternRepeat: 0.6 })).toEqual({
      hasPattern: false,
    })
  })

  it('是否对花 = 是但花距未填 ⇒ 只写 hasPattern（不补默认花距）', () => {
    expect(buildCraftSpec({ hasPattern: true })).toEqual({ hasPattern: true })
  })

  it('未知键不进 payload（只落白名单工艺键）', () => {
    const built = buildCraftSpec({ craft: '韩褶' } as never)
    expect(Object.keys(built)).toEqual(['craft'])
  })
})

// ══════════════════════════════════════════════════════════════════════════
// issue #4874（用户 2026-09-21 需求批次）
//
// ① **褶距字段整体移除**：「移除订单的工艺规格中的褶距字段」—— 写侧键 / 输入框 / 展示行全删
//    （存量单的**读侧**仍容错，`craft-display.ts` 照旧能渲染老单里的该键）。
// ② **补上「用料公式」字段**：「同时加上用料公式字段」—— 它与 `craftTier` 是**同一族**
//    （算料输入），两者**都落库**到 `processingInfo`（camelCase，缺值不写）。
//
// 红证（注入式）：把 `buildCraftSpec` 里 `spec.formula = formula` 那两行删掉 ⇒ 判据 ② 必红；
// 把 `pleatSpacing` 的写键加回来 ⇒ 判据 ① 的反向断言（模块导出清单）必红。
// ══════════════════════════════════════════════════════════════════════════
describe('#4874 用料公式 / 算料档位落库 + 褶距整体退场', () => {
  it('① 褶距写侧键整体退场：模块**不再导出** pleatSpacing 相关符号（红证：改前四个都在）', () => {
    // 反向断言取**模块导出清单**（不是文档措辞）：符号真被删干净才为绿
    for (const gone of [
      'DEFAULT_PLEAT_SPACING',
      'CURTAIN_BODY_BOTH',
      'bodyHasSheerLine',
      'buildSheerLineCraftSpec',
    ]) {
      expect(Object.keys(orderCraftFields)).not.toContain(gone)
    }
    // `CraftSpecInput` 不再有 pleatSpacing 键（传进去也不落库）
    expect(buildCraftSpec({ pleatSpacing: 0.125 } as never)).toEqual({})
  })

  it('② 填了用料公式 ⇒ 落库 processingInfo.formula（camelCase；与 craftTier 同族）', () => {
    expect(buildCraftSpec({ formula: 'fullness' })).toEqual({ formula: 'fullness' })
    expect(buildCraftSpec({ formula: 'pleat', craftTier: 'economy' })).toEqual({
      formula: 'pleat',
      craftTier: 'economy',
    })
  })

  it('② 没填 ⇒ 该键**整个缺席**（缺值不写：不写空串、不写 undefined 键）', () => {
    expect(buildCraftSpec({})).not.toHaveProperty('formula')
    expect(buildCraftSpec({ formula: '   ' })).toEqual({})
    expect(buildCraftSpec({ craftTier: '' })).toEqual({})
  })
})

// ── 帘体（issue #4521；issue #4874 收窄为两类）────────────────────────────────
//
// 用户口径：「用户可能购买**带纱帘的窗帘，不带纱帘的窗帘和只买纱帘，还有布料**，这四种情况，
// **布帘需要算用料米数，纱帘不需要算用料米数，买多少就是多少**」。
// 本组判据钉住「帘体 → 部位 / 用料来源 / 是否定型默认」的纯函数半边。
//
// ⚠️ issue #4874（用户 2026-09-21「订单需要**移除布帘+纱帘的选项**」）：`布帘+纱帘` 档与它那一
// 整族派生（`bodyHasSheerLine` / 纱帘米数 / 纱帘单价 / 第二条纱帘明细行 / `buildSheerLineCraftSpec`）
// **已整体删除** ⇒ 原「bodyHasSheerLine 只有该档为真」「纱帘行 = 同一份工艺规格 + 同 craftLineId」
// 「纱帘行不冒充配布边」三条判据**改判为反向断言**（「那族符号都不存在」），**不是删断言**：
// 见上面 `#4874 用料公式 / 算料档位落库 + 褶距整体退场` 组的模块导出清单判据
// （`Object.keys(orderCraftFields)` 不含 `bodyHasSheerLine` / `buildSheerLineCraftSpec`）。
// 「纱帘仍是一条独立明细行」这一真值**没有消失**：它由**独立商品组**（帘体 = 纱帘）承载，
// 该行的 `curtainType=纱帘` 由 `curtainTypeOfBody` 写（见下一条）。
describe('#4521/#4874 帘体：布帘 / 纱帘（`布帘+纱帘` 档已移除）', () => {
  it('帘体清单逐字 = 布帘 / 纱帘；**不再有**「布帘+纱帘」档（第四类「布料」是售卖形态）', () => {
    expect(CURTAIN_BODY_OPTIONS).toEqual(['布帘', '纱帘'])
    expect(CURTAIN_BODY_OPTIONS).not.toContain('布帘+纱帘')
  })

  it('curtainTypeOfBody：**只有「只买纱帘」显式写部位**；布帘不写', () => {
    expect(curtainTypeOfBody(CURTAIN_BODY_SHEER)).toBe(CURTAIN_TYPE_SHEER)
    expect(curtainTypeOfBody(CURTAIN_BODY_CLOTH)).toBeUndefined()
  })

  it('defaultIsShapedForBody：布帘默认「是」、纱帘默认「否」（真值源 §10）', () => {
    expect(defaultIsShapedForBody(CURTAIN_BODY_CLOTH)).toBe(true)
    expect(defaultIsShapedForBody(CURTAIN_BODY_SHEER)).toBe(false)
  })

  it('纱帘行不冒充配布边（componentRole 不写 —— 纱帘既不是主布也不是配布边）', () => {
    // 纱帘行由**独立商品组**（帘体 = 纱帘）承载：`buildCraftSpec` 只写工艺规格，
    // 不写 `componentRole`（那是**配布边**的专有键，见 `buildEdgeLineCraftSpec`）
    const sheer = buildCraftSpec({ craft: '韩褶' })
    expect(sheer).not.toHaveProperty('componentRole')
    expect(buildEdgeLineCraftSpec('item-1', METERS_SOURCE_FOLLOW).componentRole).toBe('配布边')
  })
})

describe('双拼（§4.8）：主布行 / 配布边行的绑组键', () => {
  it('主布行绑组键 = componentRole=主布 + craftLineId（自指）', () => {
    expect(buildMainLineGroupKeys('item-1')).toEqual({
      componentRole: '主布',
      craftLineId: 'item-1',
    })
  })

  it('配布边行 = componentRole=配布边 + craftLineId（指向主布行）+ metersSource', () => {
    expect(buildEdgeLineCraftSpec('item-1', METERS_SOURCE_FOLLOW)).toEqual({
      componentRole: '配布边',
      craftLineId: 'item-1',
      metersSource: '跟随主布',
    })
    expect(buildEdgeLineCraftSpec('item-1', METERS_SOURCE_MANUAL)).toEqual({
      componentRole: '配布边',
      craftLineId: 'item-1',
      metersSource: '人工指定',
    })
  })

  it('配布边行不携带工艺规格键（折数/开数/幅数是一扇窗的属性，不是每块布的）', () => {
    const edge = buildEdgeLineCraftSpec('item-1', METERS_SOURCE_FOLLOW)
    for (const key of ['curtainType', 'craft', 'openCount', 'isShaped', 'specialOptions']) {
      expect(edge).not.toHaveProperty(key)
    }
  })

  it('metersSource 取值逐字 = 跟随主布 / 人工指定', () => {
    expect(METERS_SOURCE_FOLLOW).toBe('跟随主布')
    expect(METERS_SOURCE_MANUAL).toBe('人工指定')
  })
})

// ── 樘窗绑组（issue #4395 判据 1 的纯函数半边）──────────────────────────────
//
// 病根（#4387 的「未做」项）：下单页**只在拼色时**写 `craftLineId` ⇒ 顾客下「布 + 纱」
// （两条明细行、都不带该键）⇒ 消费端 `craftGroupKey` 回落到各自 `itemId` ⇒ **两行各成一樘窗**。
// 本组判据把「同一樘窗的多条部位行 ⇒ 同一个 craftLineId」钉在**纯函数**层面。
describe('樘窗绑组（#4395）：同一樘窗的多条部位行 ⇒ 同一个 craftLineId', () => {
  it('布行 + 纱行同樘窗 ⇒ 两行同一个 craftLineId，且 = **主布行**（部位=布帘）的行标识', () => {
    const map = resolveWindowCraftLineIds([
      { id: 'line-cloth', windowLabel: '客厅主窗', curtainType: '布帘' },
      { id: 'line-sheer', windowLabel: '客厅主窗', curtainType: '纱帘' },
    ])
    expect(map).toEqual({ 'line-cloth': 'line-cloth', 'line-sheer': 'line-cloth' })
  })

  it('纱行写在前面也取**主布行**（部位=布帘）作代表行，不取页面顺序首行', () => {
    const map = resolveWindowCraftLineIds([
      { id: 'line-sheer', windowLabel: '主卧窗', curtainType: '纱帘' },
      { id: 'line-cloth', windowLabel: '主卧窗', curtainType: '布帘' },
    ])
    expect(map).toEqual({ 'line-sheer': 'line-cloth', 'line-cloth': 'line-cloth' })
  })

  it('组内没有布帘（纱 + 帘头）⇒ 取组内**首行**作代表行（不猜、不丢组）', () => {
    const map = resolveWindowCraftLineIds([
      { id: 'line-sheer', windowLabel: '书房窗', curtainType: '纱帘' },
      { id: 'line-valance', windowLabel: '书房窗', curtainType: '帘头' },
    ])
    expect(map).toEqual({ 'line-sheer': 'line-sheer', 'line-valance': 'line-sheer' })
  })

  it('两樘窗各自成组（不同窗号 ⇒ 不同 craftLineId）', () => {
    const map = resolveWindowCraftLineIds([
      { id: 'a-cloth', windowLabel: '客厅主窗', curtainType: '布帘' },
      { id: 'a-sheer', windowLabel: '客厅主窗', curtainType: '纱帘' },
      { id: 'b-cloth', windowLabel: '次卧窗', curtainType: '布帘' },
      { id: 'b-sheer', windowLabel: '次卧窗', curtainType: '纱帘' },
    ])
    expect(map).toEqual({
      'a-cloth': 'a-cloth',
      'a-sheer': 'a-cloth',
      'b-cloth': 'b-cloth',
      'b-sheer': 'b-cloth',
    })
  })

  // ── ⭐ issue #4693：口径改判「一樘窗 = 一套」（作废 #4373「1 个窗帘商品 = 1 套」）──
  //
  // 现行口径（用户 2026-09-20 逐字裁定「**一樘窗 = 一套**」，设计文档
  // `docs/design/position-instance-routing-model.md` §2.1.1）：**一套 = 一樘窗 = 一个
  // `craftLineId` 组** —— 一个窗户的**全部部位**（布帘 + 纱帘 + 帘头）**合计一套**。
  // 旧口径（#4373）把「套」钉在**明细行**上 ⇒ 同一樘窗的 3 条部位行会被算成 **3 套**。
  it('#4693 一樘窗含全部部位（布帘 + 纱帘 + 帘头）= **1 套**（同一 craftLineId 组；旧口径 = 3 套）', () => {
    const lines = [
      { id: 'line-cloth', windowLabel: '客厅主窗', curtainType: '布帘' },
      { id: 'line-sheer', windowLabel: '客厅主窗', curtainType: '纱帘' },
      { id: 'line-valance', windowLabel: '客厅主窗', curtainType: '帘头' },
    ]
    // 前置自断言（**不是**被测行为）：该夹具确实是**三条明细行** ——
    // 旧口径（套 ≡ 明细行）下这个数就是「套数」= 3，红证读数由此可复核。
    expect(lines).toHaveLength(3)

    const map = resolveWindowCraftLineIds(lines)
    // 三行都绑到**同一个** craftLineId（代表行 = 主布行）
    expect(map).toEqual({
      'line-cloth': 'line-cloth',
      'line-sheer': 'line-cloth',
      'line-valance': 'line-cloth',
    })
    // ⭐ 套数 = 樘窗组数（**去重后的 craftLineId 取值个数**），不是明细行数
    expect(new Set(Object.values(map)).size).toBe(1)
  })

  it('#4693 两樘窗（各含布 + 纱 + 帘头）= **2 套**（套数 = 窗数，不随部位数增长）', () => {
    const map = resolveWindowCraftLineIds([
      { id: 'a-cloth', windowLabel: '客厅主窗', curtainType: '布帘' },
      { id: 'a-sheer', windowLabel: '客厅主窗', curtainType: '纱帘' },
      { id: 'a-valance', windowLabel: '客厅主窗', curtainType: '帘头' },
      { id: 'b-cloth', windowLabel: '次卧窗', curtainType: '布帘' },
      { id: 'b-sheer', windowLabel: '次卧窗', curtainType: '纱帘' },
      { id: 'b-valance', windowLabel: '次卧窗', curtainType: '帘头' },
    ])
    expect(Object.keys(map)).toHaveLength(6) // 前置自断言：6 条明细行（旧口径 = 6 套）
    expect(new Set(Object.values(map)).size).toBe(2) // 新口径：2 樘窗 = 2 套
  })

  it('#4693 一樘窗只含布帘（单行）= **1 套**（边界：单部位窗不被多算）', () => {
    // 单行樘窗不写 craftLineId（`resolveWindowCraftLineIds` 的口径 2）⇒ 消费端回落本行 itemId
    // ⇒ 自成一组 = 1 套。本断言钉的是**套数**，不是「写不写该键」。
    expect(resolveWindowCraftLineIds([
      { id: 'line-cloth', windowLabel: '客厅主窗', curtainType: '布帘' },
    ])).toEqual({})
  })

  it('未填樘窗 ⇒ 一个键都不写（**存量语义不变**：缺省回落本行 itemId ⇒ 各自成组）', () => {
    expect(
      resolveWindowCraftLineIds([
        { id: 'line-1', curtainType: '布帘' },
        { id: 'line-2', curtainType: '纱帘' },
      ])
    ).toEqual({})
    expect(
      resolveWindowCraftLineIds([
        { id: 'line-1', windowLabel: '   ', curtainType: '布帘' },
        { id: 'line-2', windowLabel: '', curtainType: '纱帘' },
      ])
    ).toEqual({})
  })

  it('窗号只有一行 ⇒ 不写（单行樘窗的组键本来就 = 本行 itemId，写它没有信息量）', () => {
    expect(
      resolveWindowCraftLineIds([{ id: 'line-1', windowLabel: '客厅主窗', curtainType: '布帘' }])
    ).toEqual({})
  })

  it('窗号两侧空白不影响归组（去空白后比较）', () => {
    const map = resolveWindowCraftLineIds([
      { id: 'line-cloth', windowLabel: ' 客厅主窗 ', curtainType: '布帘' },
      { id: 'line-sheer', windowLabel: '客厅主窗', curtainType: '纱帘' },
    ])
    expect(map).toEqual({ 'line-cloth': 'line-cloth', 'line-sheer': 'line-cloth' })
  })

  it('绑组键只写 craftLineId —— **不写 componentRole**（缺省即主布；纱行不是主布也不冒充配布边）', () => {
    expect(buildWindowGroupKey('line-cloth')).toEqual({ craftLineId: 'line-cloth' })
  })
})
