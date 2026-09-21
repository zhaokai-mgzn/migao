// case_ids: OR-035, OR-038
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为（录入控件）。
// 改用 **OR-035**（工艺规格写侧录入，判据即本文件 + order-craft-fields.test.ts + craft-calc-defaults.test.ts）。
// OR-038（issue #4521 新增②、issue #4874 改判）：**移除部位字段** + 帘体两档（`布帘+纱帘` 已删除）。
/**
 * 下单页工艺规格**录入控件**（issue #4375 包 4b · 设计文档 §4.6 入口 2）。
 *
 * 判据聚焦「录入 → 回调」的确定性行为（缺值不写、显式「否」是真值、拼色才出配布边）。
 *
 * ── issue #4489：下拉 → chips（一击即中）──────────────────────────────────────
 * **断言强度不降**：原先逐字比对 `options.map(o => o.value)` 的判据，改为逐字比对
 * **每个 chip 的可见文案**（`getAllByRole('radio').map(r => r.textContent)`）；
 * 原先 `fireEvent.change(select, {value})` 的判据，改为**一次点击** chip 后断言 patch
 * （点击即选中 —— 这正是「一击即中」，比「展开→选」两步更强）。
 *
 * ── issue #4566：**「工艺」与「是否定型」搬出本组件**（用户 2026-09-19 裁定）──────────
 * ① 两个 radiogroup 消失（红证：修复前 `name='工艺'` / `name='是否定型'` 存在），
 *    本文件原有 6 条判据随之改判/搬迁（**不是删断言**：真值源与判据在 `orders-new.test.tsx`
 *    的 #4566 组里以**加工项**为承载重新断言 —— 派生、单值护栏、默认勾选、无该项不报错）；
 * ② 三态只剩「是否对花」（三段语义一字不动）。
 *
 * ── issue #4874（用户 2026-09-21 需求批次）─────────────────────────────────────
 * ① **褶距控件整体删除**（「移除订单的工艺规格中的褶距字段」）⇒ 本文件原「褶距输入 ⇒ pleatSpacing
 *    数字 / 清空 ⇒ undefined」与「默认档里褶距 0.125 可见可改」两条判据**改判为反向断言**
 *    （控件不存在），**不是删断言**：写侧的键退场判据在 `lib/order-craft-fields.test.ts` 的 #4874 组。
 * ② **新增「用料公式」chips**（`pleat` / `fullness`）+ **褶数展示 / 档位 chips**：
 *    值域 = `lib/craft-calc-request.ts` 的 `CRAFT_CALC_FORMULAS`；档位的**值域与文案都取自
 *    算料配置**（`tiers` 的键 / `tiers[key].label`）—— 本文件用**与键名不同字**的 label 做红证。
 * ③ **纱帘子块整体删除**（`布帘+纱帘` 档已移除）⇒ 原「含纱帘才出纱帘米数/单价」一族判据改判为
 *    反向断言（该子块与 `sheer*` props 都不存在）。
 */
import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import OrderCraftFields from '@/components/orders/OrderCraftFields'
import type { CraftSpecInput } from '@/lib/order-craft-fields'
import type { CraftCalcConfig } from '@/types'

/**
 * 算料配置桩（issue #4874）——档位 chips 的**值域**（`tiers` 的键）与**文案**（`tiers[key].label`）
 * 都只能来自这里。label 刻意与键名不同字（`标准档（2.0倍）` ≠ `standard`）：
 * 组件若自己写死一套中文档位名，断言必红。
 */
const CALC_CONFIG: CraftCalcConfig = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.3,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: {
    standard: { fullness: 2.0, label: '标准档（2.0倍）' },
    economy: { fullness: 1.8, label: '经济档（1.8倍）' },
  },
  default_formula: 'pleat',
  side_margin: 0.15,
  hem_margin: 0.3,
  meters_rounding_step: 0.1,
}

/** 受控包装：模拟页面用 useState 持有 value，便于断言累积后的值 */
function Harness({
  initial = {},
  mainMeters = 3,
  calcConfig = CALC_CONFIG,
  pleatCount = null,
  edgeMeters = null,
  edgeUnitPrice = null,
  onChangeSpy,
}: {
  initial?: CraftSpecInput
  mainMeters?: number
  calcConfig?: CraftCalcConfig | null
  pleatCount?: number | null
  edgeMeters?: number | null
  edgeUnitPrice?: number | null
  onChangeSpy?: (patch: Partial<CraftSpecInput>) => void
}) {
  const [value, setValue] = useState<CraftSpecInput>(initial)
  const [edge, setEdge] = useState<number | null>(edgeMeters)
  const [price, setPrice] = useState<number | null>(edgeUnitPrice)
  return (
    <OrderCraftFields
      value={value}
      onChange={(patch) => {
        onChangeSpy?.(patch)
        setValue((prev) => ({ ...prev, ...patch }))
      }}
      mainMeters={mainMeters}
      calcConfig={calcConfig}
      pleatCount={pleatCount}
      edgeMeters={edge}
      onEdgeMetersChange={setEdge}
      edgeUnitPrice={price}
      onEdgeUnitPriceChange={setPrice}
    />
  )
}

const inputByName = (name: string) => screen.getByLabelText(name) as HTMLInputElement

/** 枚举字段的 chips 组（issue #4489：一击即中的单选按钮组） */
const chipGroup = (name: string) => screen.getByRole('radiogroup', { name })
/** 组内单个 chip —— 文案即候选值（`未指定` = 键不落库的那一档） */
const chip = (group: string, name: string) => within(chipGroup(group)).getByRole('radio', { name })
/** 组内全部 chip 的**可见文案**（逐字断言用；比旧版比对 `<option>.value` 更贴近商家所见） */
const chipLabels = (group: string) =>
  within(chipGroup(group))
    .getAllByRole('radio')
    .map((el) => el.textContent)

describe('OrderCraftFields', () => {
  it('渲染保留的工艺控件（加工类型/打开方式/款式/用料公式/是否对花）', () => {
    render(<Harness />)
    // 枚举字段 = chips 组（一击即中）；本组件已无任何数值输入框（褶距已移除，见 #4874 判据）
    for (const name of ['加工类型', '打开方式', '款式', '用料公式', '是否对花']) {
      expect(chipGroup(name)).toBeInTheDocument()
    }
  })

  // ── issue #4874 ①：褶距控件整体退场（用户 2026-09-21「移除订单的工艺规格中的褶距字段」）──
  // 红证（改前）：本组件有一个「褶距」number 输入框（`getByLabelText('褶距')` 命中），
  // 且 `onChange` 会 patch `{ pleatSpacing: … }` ⇒ 本判据两条断言必红。
  it('#4874 **不再有**「褶距」控件（红证：改前有 `褶距` number 输入框）', () => {
    render(<Harness />)
    expect(screen.queryByLabelText('褶距')).toBeNull()
    expect(screen.queryByText('褶距')).toBeNull()
  })

  // ── issue #4874 ②：用料公式 chips（值域与算料引擎同源，文案只有一份）────────────────
  it('#4874 用料公式 chips 逐字 = 韩褶公式（褶数法）/ 褶倍数公式（倍数法）', () => {
    render(<Harness />)
    expect(chipLabels('用料公式')).toEqual(['韩褶公式（褶数法）', '褶倍数公式（倍数法）'])
  })

  it('#4874 选用料公式 ⇒ onChange 收到 `formula`（值域 = pleat / fullness）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('用料公式', '褶倍数公式（倍数法）'))
    expect(spy).toHaveBeenCalledWith({ formula: 'fullness' })
  })

  // ── issue #4874 ③：选韩褶公式 ⇒ 展示**自动算出的褶数**（试算响应 `pleat_count`）──────
  // 没结果展示「—」：**不编数**（编一个褶数 = 第二份算料逻辑）。默认公式 = 算料配置的
  // `default_formula`（本 fixture = pleat）⇒ 块默认就在。
  it('#4874 韩褶公式 ⇒ 展示褶数（有结果显数字；无结果显示「—」，不编数）', () => {
    const { unmount } = render(<Harness pleatCount={52} />)
    expect(within(screen.getByTestId('craft-pleat-count')).getByText('52')).toBeInTheDocument()
    unmount()

    render(<Harness pleatCount={null} />)
    expect(within(screen.getByTestId('craft-pleat-count')).getByText('—')).toBeInTheDocument()
  })

  it('#4874 选褶倍数公式 ⇒ **不**展示褶数块，改为展示档位 chips', () => {
    render(<Harness pleatCount={52} />)
    fireEvent.click(chip('用料公式', '褶倍数公式（倍数法）'))
    expect(screen.queryByTestId('craft-pleat-count')).toBeNull()
    expect(screen.getByTestId('craft-tier-options')).toBeInTheDocument()
  })

  // ── issue #4874 ④⑤：档位 = 算料配置 `tiers` 的键（值）+ `label`（文案）───────────────
  it('#4874 档位 chips 值域与文案**逐字取自算料配置**（红证：写死一套中文档位名 ⇒ 必红）', () => {
    render(<Harness initial={{ formula: 'fullness' }} />)
    const group = chipGroup('档位')
    expect(
      within(group)
        .getAllByRole('radio')
        .map((r) => r.textContent)
    ).toEqual(['标准档（2.0倍）', '经济档（1.8倍）'])
  })

  it('#4874 选档位 ⇒ onChange 收到 `craftTier`（键 = 配置的阶位键，不是文案）', () => {
    const spy = vi.fn()
    render(<Harness initial={{ formula: 'fullness' }} onChangeSpy={spy} />)
    fireEvent.click(chip('档位', '经济档（1.8倍）'))
    expect(spy).toHaveBeenCalledWith({ craftTier: 'economy' })
  })

  // ── issue #4874 ⑥：配置加载失败 ⇒ 按缺省走 + **显式提示**（不静默、不阻断录入）────────
  it('#4874 算料配置未加载 ⇒ 显式提示 + 不渲染档位 chips + 其余控件照常可用', () => {
    render(<Harness calcConfig={null} initial={{ formula: 'fullness' }} />)
    expect(screen.getByTestId('craft-calc-config-missing')).toBeInTheDocument()
    // 档位**值域无从得知** ⇒ 不渲染 chips（编一套 = 第二份档位真值）
    expect(screen.queryByTestId('craft-tier-options')).toBeNull()
    expect(screen.queryByRole('radiogroup', { name: '档位' })).toBeNull()
    // 录入不被阻断：其余 chips 照常可用
    expect(chipGroup('款式')).toBeInTheDocument()
  })

  // issue #4566 红证（用户 2026-09-19 裁定「工艺规格中的**工艺，定型**，对花我觉得**直接通过
  // 加工项来勾选**，其他保留」）：修复前这两个 radiogroup 存在（`name="工艺"` / `name="是否定型"`）
  // ⇒ 本判据必红。搬走后它们由**加工项**承载（页面侧 `craftFromItems` / 加工项「定型」勾选态）
  // ⇒ 本组件再渲染它们 = 与加工项派生出的第二份口径打架。
  it('#4566 **不再有**「工艺」与「是否定型」控件（红证：修复前两个 radiogroup 存在）', () => {
    render(<Harness />)
    expect(screen.queryByRole('radiogroup', { name: '工艺' })).toBeNull()
    expect(screen.queryByRole('radiogroup', { name: '是否定型' })).toBeNull()
    expect(screen.queryByRole('radio', { name: '韩褶' })).toBeNull()
    expect(screen.queryByRole('radio', { name: '四爪钩' })).toBeNull()
  })

  // issue #4521 红证：修复前这里有 `radiogroup name="部位"`（布帘/纱帘/帘头 chips）。
  // 部位已由**帘体**（商品组级）承载 ⇒ 本组件再出现部位 = 商家能选出与帘体矛盾的部位。
  it('#4521 **不再有**「部位」字段（红证：修复前 radiogroup name=部位 存在）', () => {
    render(<Harness />)
    expect(screen.queryByRole('radiogroup', { name: '部位' })).toBeNull()
    expect(screen.queryByRole('radio', { name: '帘头' })).toBeNull()
  })

  // ── issue #4874 ③（纱帘侧）：纱帘子块整体删除（`布帘+纱帘` 档已移除）────────────────
  // 红证（改前）：`sheer=true` 时本组件渲染「纱帘米数 / 纱帘单价」两个输入框 ⇒ 必红。
  // 「纱帘仍是一条独立明细行」的真值由**独立商品组**（帘体 = 纱帘）承载，不在本组件里。
  it('#4874 **不再有**纱帘米数 / 纱帘单价子块（红证：改前 `sheer` 为真时两个输入框存在）', () => {
    render(<Harness />)
    expect(screen.queryByLabelText('纱帘米数')).toBeNull()
    expect(screen.queryByLabelText('纱帘单价')).toBeNull()
    expect(screen.queryByText(/纱帘米数来源/)).toBeNull()
  })

  // issue #4489 判据「枚举字段全部可见且**一击可选**」：
  // 红证 = 修复前是 `<select>`（无 radiogroup/radio 角色）⇒ 本判据必红；
  // 且「一击」是实质断言：**一次点击**即 `aria-checked=true`，不需要先「展开」。
  it('#4489 枚举字段一击即中：点一下 chip 就选中（无需先展开下拉）', () => {
    render(<Harness />)
    expect(chip('加工类型', '定高买宽')).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(chip('加工类型', '定高买宽'))
    expect(chip('加工类型', '定高买宽')).toHaveAttribute('aria-checked', 'true')
    expect(chip('加工类型', '未指定')).toHaveAttribute('aria-checked', 'false')
  })

  it('加工类型 / 款式 chips 的候选逐字 = 定高买宽·定宽买高 / 单色·拼色', () => {
    render(<Harness />)
    expect(chipLabels('加工类型')).toEqual(['未指定', '定高买宽', '定宽买高'])
    expect(chipLabels('款式')).toEqual(['未指定', '单色', '拼色'])
  })

  it('选款式 ⇒ onChange 收到 camelCase patch', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('款式', '拼色'))
    expect(spy).toHaveBeenCalledWith({ style: '拼色' })
  })

  it('打开方式选中「双开」⇒ openCount 是数字 2（不是字符串）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('打开方式', '双开'))
    expect(spy).toHaveBeenCalledWith({ openCount: 2 })
  })

  // issue #4387 判据 1（三开可录入）：用户口径含三开，而此前候选只有 1/2/4
  // ⇒ 商家**选不出**三开（只能靠 API/Agent 直写）。候选必须含三开且映射到数字 3。
  it('#4387 打开方式候选含三开（3）⇒ 选中后 openCount 是数字 3', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    expect(chipLabels('打开方式')).toEqual(['未指定', '单开', '双开', '三开', '四开'])
    // 四档逐档验数字映射（比只验一档更强：错位 / 字符串都会红）
    for (const [label, count] of [
      ['单开', 1],
      ['双开', 2],
      ['三开', 3],
      ['四开', 4],
    ] as const) {
      fireEvent.click(chip('打开方式', label))
      expect(spy).toHaveBeenCalledWith({ openCount: count })
    }
  })

  // issue #4489 硬约束：「未指定」与「否」是两个真值 ⇒ 三态必须是**三段**分段按钮。
  // 红证：若把三态做成两段（是/否）或布尔开关，本判据必红（「未指定」档消失）。
  // ⚠️ #4566 后本组件**只剩「是否对花」**用三态（「是否定型」已搬到加工项）。
  it('#4489 三态字段是三段分段按钮，「未指定」档保留（没问过 ≠ 否）', () => {
    render(<Harness />)
    expect(chipLabels('是否对花')).toEqual(['未指定', '是', '否'])
    // 未指定 ⇒ 两档都不是选中态（不是被当成「否」）
    expect(chip('是否对花', '未指定')).toHaveAttribute('aria-checked', 'true')
    expect(chip('是否对花', '否')).toHaveAttribute('aria-checked', 'false')
    // 显式「否」⇒ 只有「否」是选中态（未指定与否在 UI 上可区分）
    fireEvent.click(chip('是否对花', '否'))
    expect(chip('是否对花', '否')).toHaveAttribute('aria-checked', 'true')
    expect(chip('是否对花', '未指定')).toHaveAttribute('aria-checked', 'false')
  })

  it('花距输入框只在「是否对花 = 是」时出现', () => {
    render(<Harness />)
    expect(screen.queryByLabelText('花距')).not.toBeInTheDocument()
    fireEvent.click(chip('是否对花', '是'))
    expect(screen.getByLabelText('花距')).toBeInTheDocument()
  })

  it('款式非拼色 ⇒ 不出现配布边录入', () => {
    render(<Harness />)
    expect(screen.queryByLabelText('配布边米数')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('配布边单价')).not.toBeInTheDocument()
  })

  it('款式 = 拼色 ⇒ 出现配布边米数（默认显示主布米数）与配布边单价', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.click(chip('款式', '拼色'))
    expect(inputByName('配布边米数')).toHaveValue(3)
    expect(inputByName('配布边单价')).toHaveValue(null)
  })

  it('配布边米数可编辑 ⇒ onEdgeMetersChange 收到新米数', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.click(chip('款式', '拼色'))
    fireEvent.change(inputByName('配布边米数'), { target: { value: '2.5' } })
    expect(inputByName('配布边米数')).toHaveValue(2.5)
  })

  it('配布边米数提示「默认 = 主布米数，可编辑」', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.click(chip('款式', '拼色'))
    expect(screen.getByText(/默认 = 主布米数/)).toBeInTheDocument()
  })

  it('配布边米数未改过 ⇒ 来源「跟随主布」；改过 ⇒ 来源「人工指定」', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.click(chip('款式', '拼色'))
    expect(screen.getByText('配布边米数来源：跟随主布')).toBeInTheDocument()
    fireEvent.change(inputByName('配布边米数'), { target: { value: '2' } })
    expect(screen.getByText('配布边米数来源：人工指定')).toBeInTheDocument()
  })

  it('配布边米数清空 ⇒ 回到「跟随主布」（不是 0，也不落 0 米）', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.click(chip('款式', '拼色'))
    fireEvent.change(inputByName('配布边米数'), { target: { value: '2' } })
    fireEvent.change(inputByName('配布边米数'), { target: { value: '' } })
    expect(screen.getByText('配布边米数来源：跟随主布')).toBeInTheDocument()
    expect(inputByName('配布边米数')).toHaveValue(3)
  })

  // ── issue #4566：「工艺」/「是否定型」已搬出本组件 ──────────────────────────────
  //
  // 原 #4489 的「选部位 ⇒ 是否定型联动」与 #4521 的「改定型只 patch isShaped 一个键」判据
  // 均随裁定作废（控件已不在本组件里）——真值源与判据一字未丢，只是**换了承载控件**：
  // 工艺 = 加工项的 `craftHint`（`orders-new.test.tsx` 的 #4566 组 + `craft-auto-features`），
  // 定型 = 加工项「定型」的勾选态（同处），纯函数半边在 `order-craft-fields.test.ts`。
})
