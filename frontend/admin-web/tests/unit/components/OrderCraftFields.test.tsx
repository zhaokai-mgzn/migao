// case_ids: OR-035, OR-038
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为（录入控件）。
// 改用 **OR-035**（本 PR 新增，判据即本文件 + order-craft-fields.test.ts + craft-calc-defaults.test.ts）。
// OR-038（issue #4521 新增）：**移除部位字段** + **纱帘子块**（与配布边逐字同构）。
/**
 * 下单页工艺规格**录入控件**（issue #4375 包 4b · 设计文档 §4.6 入口 2）。
 *
 * 判据聚焦「录入 → 回调」的确定性行为（缺值不写、显式「否」是真值、拼色才出配布边、
 * 带纱帘才出纱帘米数/单价）。
 *
 * ── issue #4489：下拉 → chips（一击即中）──────────────────────────────────────
 * **断言强度不降**：原先逐字比对 `options.map(o => o.value)` 的判据，改为逐字比对
 * **每个 chip 的可见文案**（`getAllByRole('radio').map(r => r.textContent)`）；
 * 原先 `fireEvent.change(select, {value})` 的判据，改为**一次点击** chip 后断言 patch
 * （点击即选中 —— 这正是「一击即中」，比「展开→选」两步更强）。
 *
 * ── issue #4521：**移除「部位」** + 纱帘子块 ──────────────────────────────────
 * ① 「部位」chips 整体消失（红证：修复前 `getByRole('radiogroup', {name:'部位'})` 存在）；
 * ② 「是否定型」的行业默认改由**帘体**结构决定（页面侧写回）⇒ 本组不再有部位联动判据，
 *    改为判「改定型只 patch isShaped 一个键」；
 * ③ 新增**纱帘子块**判据：`sheer=false` 不出现；`sheer=true` 出「纱帘米数 / 纱帘单价」，
 *    米数默认 = 主布米数、可改、带来源留痕 —— 与「配布边」逐字同构。
 */
import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import OrderCraftFields from '@/components/orders/OrderCraftFields'
import { SPECIAL_OPTIONS, type CraftSpecInput } from '@/lib/order-craft-fields'

/** 受控包装：模拟页面用 useState 持有 value，便于断言累积后的值 */
function Harness({
  initial = {},
  mainMeters = 3,
  sheer = false,
  sheerMeters = null,
  sheerUnitPrice = null,
  edgeMeters = null,
  edgeUnitPrice = null,
  onChangeSpy,
}: {
  initial?: CraftSpecInput
  mainMeters?: number
  sheer?: boolean
  sheerMeters?: number | null
  sheerUnitPrice?: number | null
  edgeMeters?: number | null
  edgeUnitPrice?: number | null
  onChangeSpy?: (patch: Partial<CraftSpecInput>) => void
}) {
  const [value, setValue] = useState<CraftSpecInput>(initial)
  const [edge, setEdge] = useState<number | null>(edgeMeters)
  const [price, setPrice] = useState<number | null>(edgeUnitPrice)
  const [sMeters, setSMeters] = useState<number | null>(sheerMeters)
  const [sPrice, setSPrice] = useState<number | null>(sheerUnitPrice)
  return (
    <OrderCraftFields
      value={value}
      onChange={(patch) => {
        onChangeSpy?.(patch)
        setValue((prev) => ({ ...prev, ...patch }))
      }}
      mainMeters={mainMeters}
      sheer={sheer}
      sheerMeters={sMeters}
      onSheerMetersChange={setSMeters}
      sheerUnitPrice={sPrice}
      onSheerUnitPriceChange={setSPrice}
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
  it('渲染 §4.2 的七个工艺控件（工艺/加工类型/打开方式/是否定型/款式/褶距/是否对花）', () => {
    render(<Harness />)
    // 六个枚举字段 = chips 组（一击即中）；褶距仍是数值输入
    for (const name of ['工艺', '加工类型', '打开方式', '是否定型', '款式', '是否对花']) {
      expect(chipGroup(name)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('褶距')).toBeInTheDocument()
  })

  // issue #4521 红证：修复前这里有 `radiogroup name="部位"`（布帘/纱帘/帘头 chips）。
  // 部位已由**帘体**（商品组级）承载 ⇒ 本组件再出现部位 = 商家能选出与帘体矛盾的部位。
  it('#4521 **不再有**「部位」字段（红证：修复前 radiogroup name=部位 存在）', () => {
    render(<Harness />)
    expect(screen.queryByRole('radiogroup', { name: '部位' })).toBeNull()
    expect(screen.queryByRole('radio', { name: '帘头' })).toBeNull()
  })

  // issue #4489 判据「枚举字段全部可见且**一击可选**」：
  // 红证 = 修复前是 `<select>`（无 radiogroup/radio 角色）⇒ 本判据必红；
  // 且「一击」是实质断言：**一次点击**即 `aria-checked=true`，不需要先「展开」。
  it('#4489 枚举字段一击即中：点一下 chip 就选中（无需先展开下拉）', () => {
    render(<Harness />)
    expect(chip('工艺', '打孔')).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(chip('工艺', '打孔'))
    expect(chip('工艺', '打孔')).toHaveAttribute('aria-checked', 'true')
    expect(chip('工艺', '未指定')).toHaveAttribute('aria-checked', 'false')
  })

  // 19 项特殊选项的判据已迁到 `OrderSpecialOptions.test.tsx`（issue #4511 组件抽离）。
  it('工艺 chips 的候选逐字 = 韩褶/打孔/四爪钩/穿杆/平幔', () => {
    render(<Harness />)
    expect(chipLabels('工艺')).toEqual(['未指定', '韩褶', '打孔', '四爪钩', '穿杆', '平幔'])
  })

  it('加工类型 / 款式 chips 的候选逐字 = 定高买宽·定宽买高 / 单色·拼色', () => {
    render(<Harness />)
    expect(chipLabels('加工类型')).toEqual(['未指定', '定高买宽', '定宽买高'])
    expect(chipLabels('款式')).toEqual(['未指定', '单色', '拼色'])
  })

  it('选工艺 ⇒ onChange 收到 camelCase patch', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('工艺', '打孔'))
    expect(spy).toHaveBeenCalledWith({ craft: '打孔' })
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

  it('是否定型选「否」⇒ isShaped=false（显式否是真值，不得当成未填）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('是否定型', '否'))
    expect(spy).toHaveBeenCalledWith({ isShaped: false })
  })

  it('是否定型回到「未指定」⇒ isShaped=undefined（键不落库）', () => {
    const spy = vi.fn()
    render(<Harness initial={{ isShaped: true }} onChangeSpy={spy} />)
    fireEvent.click(chip('是否定型', '未指定'))
    expect(spy).toHaveBeenCalledWith({ isShaped: undefined })
  })

  // issue #4489 硬约束：「未指定」与「否」是两个真值 ⇒ 三态必须是**三段**分段按钮。
  // 红证：若把三态做成两段（是/否）或布尔开关，本判据必红（「未指定」档消失）。
  it('#4489 三态字段是三段分段按钮，「未指定」档保留（没问过 ≠ 否）', () => {
    render(<Harness />)
    expect(chipLabels('是否定型')).toEqual(['未指定', '是', '否'])
    expect(chipLabels('是否对花')).toEqual(['未指定', '是', '否'])
    // 未指定 ⇒ 两档都不是选中态（不是被当成「否」）
    expect(chip('是否定型', '未指定')).toHaveAttribute('aria-checked', 'true')
    expect(chip('是否定型', '否')).toHaveAttribute('aria-checked', 'false')
    // 显式「否」⇒ 只有「否」是选中态（未指定与否在 UI 上可区分）
    fireEvent.click(chip('是否定型', '否'))
    expect(chip('是否定型', '否')).toHaveAttribute('aria-checked', 'true')
    expect(chip('是否定型', '未指定')).toHaveAttribute('aria-checked', 'false')
  })

  it('褶距输入 ⇒ pleatSpacing 数字；清空 ⇒ undefined', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(inputByName('褶距'), { target: { value: '0.1' } })
    expect(spy).toHaveBeenCalledWith({ pleatSpacing: 0.1 })
    fireEvent.change(inputByName('褶距'), { target: { value: '' } })
    expect(spy).toHaveBeenCalledWith({ pleatSpacing: undefined })
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

  // ── issue #4521：部位联动**已移除**，定型默认改由帘体结构决定 ────────────────────
  //
  // 原 #4489 的「选部位 ⇒ 是否定型联动」判据整体作废（部位字段已不存在）。同一份真值源
  // （布帘默认是 / 纱帘否）现在由**帘体**驱动，落点在页面侧（`defaultIsShapedForBody`）
  // 与 `order-craft-fields.test.ts` 的纯函数判据 ⇒ 本组件只剩一条：改定型只 patch 一个键。
  it('#4521 改「是否定型」只 patch isShaped 一个键（不再带出部位联动）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('是否定型', '否'))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy.mock.calls[0][0]).toEqual({ isShaped: false })
  })

  // ── issue #4521：纱帘子块（用户口径「带纱帘就像配布边一样，让用户输入米数和单价」）────
  it('#4521 帘体不含纱帘 ⇒ 不出现纱帘录入', () => {
    render(<Harness sheer={false} />)
    expect(screen.queryByLabelText('纱帘米数')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('纱帘单价')).not.toBeInTheDocument()
  })

  it('#4521 帘体含纱帘 ⇒ 出现纱帘米数（默认显示主布米数）与纱帘单价', () => {
    render(<Harness sheer mainMeters={3} />)
    expect(inputByName('纱帘米数')).toHaveValue(3)
    expect(inputByName('纱帘单价')).toHaveValue(null)
    expect(screen.getByText(/默认 = 主布米数/)).toBeInTheDocument()
  })

  it('#4521 纱帘米数可编辑 ⇒ 回调收到新米数', () => {
    render(<Harness sheer mainMeters={3} />)
    fireEvent.change(inputByName('纱帘米数'), { target: { value: '4.5' } })
    expect(inputByName('纱帘米数')).toHaveValue(4.5)
  })

  it('#4521 纱帘米数来源：未改过「跟随主布」/ 改过「人工指定」/ 清空回到跟随', () => {
    render(<Harness sheer mainMeters={3} />)
    expect(screen.getByText('纱帘米数来源：跟随主布')).toBeInTheDocument()
    fireEvent.change(inputByName('纱帘米数'), { target: { value: '4.5' } })
    expect(screen.getByText('纱帘米数来源：人工指定')).toBeInTheDocument()
    fireEvent.change(inputByName('纱帘米数'), { target: { value: '' } })
    expect(screen.getByText('纱帘米数来源：跟随主布')).toBeInTheDocument()
    expect(inputByName('纱帘米数')).toHaveValue(3)
  })

  it('#4521 纱帘与配布边**互不串**：只带纱帘时配布边不出现，反之亦然', () => {
    const { unmount } = render(<Harness sheer mainMeters={3} />)
    expect(screen.queryByLabelText('配布边米数')).not.toBeInTheDocument()
    unmount()
    render(<Harness mainMeters={3} />)
    fireEvent.click(chip('款式', '拼色'))
    expect(screen.queryByLabelText('纱帘米数')).not.toBeInTheDocument()
    expect(inputByName('配布边米数')).toHaveValue(3)
  })
})
