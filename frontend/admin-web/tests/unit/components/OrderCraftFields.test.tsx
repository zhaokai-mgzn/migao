// case_ids: OR-035
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为（录入控件）。
// 改用 **OR-035**（本 PR 新增，判据即本文件 + order-craft-fields.test.ts + craft-calc-defaults.test.ts）。
/**
 * 下单页工艺规格**录入控件**（issue #4375 包 4b · 设计文档 §4.6 入口 2）。
 *
 * 判据聚焦「录入 → 回调」的确定性行为（缺值不写、显式「否」是真值、拼色才出配布边）。
 *
 * ── issue #4489：下拉 → chips（一击即中）+ 部位联动定型默认 ──────────────────────
 * 定位方式随之从 `getByLabelText('部位')`（`<select>`）改为
 * `getByRole('radiogroup', { name: '部位' })` + `getByRole('radio', { name: '纱帘' })`。
 * **断言强度不降**：原先逐字比对 `options.map(o => o.value)` 的判据，改为逐字比对
 * **每个 chip 的可见文案**（`getAllByRole('radio').map(r => r.textContent)`）；
 * 原先 `fireEvent.change(select, {value})` 的判据，改为**一次点击** chip 后断言 patch
 * （点击即选中 —— 这正是本单要的「一击即中」，比「展开→选」两步更强）。
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
  edgeMeters = null,
  edgeUnitPrice = null,
  onChangeSpy,
}: {
  initial?: CraftSpecInput
  mainMeters?: number
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

/** 展开「特殊选项」区（issue #4420：默认收起） */
const expandSpecial = () =>
  fireEvent.click(screen.getByRole('button', { name: /特殊选项/ }))

describe('OrderCraftFields', () => {
  it('渲染 §4.2 的八个工艺控件（部位/工艺/加工类型/打开方式/是否定型/款式/褶距/是否对花）', () => {
    render(<Harness />)
    // 七个枚举字段 = chips 组（一击即中）；褶距仍是数值输入
    for (const name of [
      '部位',
      '工艺',
      '加工类型',
      '打开方式',
      '是否定型',
      '款式',
      '是否对花',
    ]) {
      expect(chipGroup(name)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('褶距')).toBeInTheDocument()
  })

  // issue #4489 判据「8 个字段全部可见且**一击可选**」：
  // 红证 = 修复前是 `<select>`（无 radiogroup/radio 角色）⇒ 本判据必红；
  // 且「一击」是实质断言：**一次点击**即 `aria-checked=true`，不需要先「展开」。
  it('#4489 枚举字段一击即中：点一下 chip 就选中（无需先展开下拉）', () => {
    render(<Harness />)
    expect(chip('部位', '纱帘')).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(chip('部位', '纱帘'))
    expect(chip('部位', '纱帘')).toHaveAttribute('aria-checked', 'true')
    expect(chip('部位', '未指定')).toHaveAttribute('aria-checked', 'false')
  })

  // issue #4420 展示重构：19 项特殊选项**默认收起**（首屏密度主因），但**可选项集合一个不少**。
  // 这两条是一对：只断言「展开后有 19 项」会漏掉「默认收起」的回归；
  // 只断言「默认收起」会漏掉「收起时把选项删了」的回归。
  it('#4420 特殊选项默认收起（未展开时 19 项按钮不在 DOM 里）', () => {
    render(<Harness />)
    expect(screen.queryByRole('button', { name: SPECIAL_OPTIONS[0] })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /特殊选项/ })).toHaveAttribute(
      'aria-expanded',
      'false'
    )
    expect(screen.getByText('未选')).toBeInTheDocument()
  })

  it('展开后渲染 19 项特殊选项（部位级多选）—— 可选项集合不因收起而减少', () => {
    render(<Harness />)
    expandSpecial()
    for (const option of SPECIAL_OPTIONS) {
      expect(screen.getByRole('button', { name: option })).toBeInTheDocument()
    }
  })

  it('#4420 收起时仍显示「已选 N 项」摘要（收起不等于隐藏已选事实）', () => {
    render(<Harness initial={{ specialOptions: ['加铅块', '拼2次'] }} />)
    expect(screen.getByText('已选 2 项')).toBeInTheDocument()
  })

  it('部位 chips 的候选逐字 = 布帘/纱帘/帘头（错值会让加工单取错工序路线）', () => {
    render(<Harness />)
    // 逐字相等（含「未指定」档）—— 少一项 / 多一项 / 改一个字都会红
    expect(chipLabels('部位')).toEqual(['未指定', '布帘', '纱帘', '帘头'])
  })

  it('工艺 chips 的候选逐字 = 韩褶/打孔/四爪钩/穿杆/平幔', () => {
    render(<Harness />)
    expect(chipLabels('工艺')).toEqual(['未指定', '韩褶', '打孔', '四爪钩', '穿杆', '平幔'])
  })

  it('加工类型 / 款式 chips 的候选逐字 = 定高买宽·定宽买高 / 单色·拼色', () => {
    render(<Harness />)
    expect(chipLabels('加工类型')).toEqual(['未指定', '定高买宽', '定宽买高'])
    expect(chipLabels('款式')).toEqual(['未指定', '单色', '拼色'])
  })

  it('选部位/工艺 ⇒ onChange 收到 camelCase patch（部位联动定型见 #4489 判据）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '纱帘'))
    fireEvent.click(chip('工艺', '打孔'))
    // 部位=纱帘 同时带出联动默认 isShaped=false（真值源见组件内注释）—— 一次 patch，不分两次写
    expect(spy).toHaveBeenCalledWith({ curtainType: '纱帘', isShaped: false })
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

  it('特殊选项多选：逐个累积，再点一次取消', () => {
    render(<Harness />)
    expandSpecial()
    fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
    fireEvent.click(screen.getByRole('button', { name: '拼2次' }))
    expect(screen.getByRole('button', { name: '加铅块' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: '拼2次' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
    expect(screen.getByRole('button', { name: '加铅块' })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
  })

  it('特殊选项用 toggle 按钮而非 checkbox —— 不得与「加工选项」的 checkbox 选择器争用', () => {
    render(<Harness />)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
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

  // ── issue #4489 判据 2：部位 → 是否定型 的联动默认 ────────────────────────────
  // 真值源：`curtain_checklist.py` 的 `is_shaped.default_rule = curtain_type`
  // （note 原文「布帘默认是/纱帘默认否/帘头是」）+ `curtain-fabric-quote-rules.md` §10。
  // 红证：修复前无联动（改部位只 patch curtainType）⇒ 本组判据必红。
  it('#4489 选「纱帘」⇒ 是否定型自动置「否」（同一 patch，UI 同步选中）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '纱帘'))
    expect(spy).toHaveBeenCalledWith({ curtainType: '纱帘', isShaped: false })
    expect(chip('是否定型', '否')).toHaveAttribute('aria-checked', 'true')
  })

  it('#4489 选「布帘」⇒ 是否定型自动置「是」', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '布帘'))
    expect(spy).toHaveBeenCalledWith({ curtainType: '布帘', isShaped: true })
    expect(chip('是否定型', '是')).toHaveAttribute('aria-checked', 'true')
  })

  it('#4489 选「帘头」⇒ 是否定型自动置「是」（同一条 default_rule 的第三档）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '帘头'))
    expect(spy).toHaveBeenCalledWith({ curtainType: '帘头', isShaped: true })
  })

  it('#4489 改部位不影响「是否对花」（联动只覆盖 isShaped 一个键）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '纱帘'))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy.mock.calls[0][0]).not.toHaveProperty('hasPattern')
  })

  // ── issue #4489 判据 3：手改留痕（同 #4434 纪律）──────────────────────────────
  // 手改过的值只能由用户显式改回 —— 再改部位**不得覆盖**。
  it('#4489 手改成「是」后再改部位=纱帘 ⇒ 不被覆盖（仍是「是」）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('是否定型', '是'))
    spy.mockClear()
    fireEvent.click(chip('部位', '纱帘'))
    expect(spy).toHaveBeenCalledWith({ curtainType: '纱帘' })
    expect(chip('是否定型', '是')).toHaveAttribute('aria-checked', 'true')
    expect(chip('是否定型', '否')).toHaveAttribute('aria-checked', 'false')
  })

  // 最容易被写错的一档：手改**回「未指定」**也算手改 —— 若把「未指定」当成「没改过」，
  // 下游就会把「商家明确说不问」重新变成「纱帘默认否」。
  it('#4489 手改回「未指定」后再改部位=布帘 ⇒ 不被覆盖（仍是「未指定」）', () => {
    const spy = vi.fn()
    render(<Harness initial={{ isShaped: true }} onChangeSpy={spy} />)
    fireEvent.click(chip('是否定型', '未指定'))
    spy.mockClear()
    fireEvent.click(chip('部位', '布帘'))
    expect(spy).toHaveBeenCalledWith({ curtainType: '布帘' })
    expect(chip('是否定型', '未指定')).toHaveAttribute('aria-checked', 'true')
  })

  it('#4489 带既有 isShaped 值进入（编辑存量行）⇒ 改部位不覆盖既有真值', () => {
    const spy = vi.fn()
    render(<Harness initial={{ isShaped: false }} onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '布帘'))
    expect(spy).toHaveBeenCalledWith({ curtainType: '布帘' })
    expect(chip('是否定型', '否')).toHaveAttribute('aria-checked', 'true')
  })

  it('#4489 未手改时连续改部位 ⇒ 联动跟着走（纱帘→否，布帘→是）', () => {
    render(<Harness />)
    fireEvent.click(chip('部位', '纱帘'))
    expect(chip('是否定型', '否')).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(chip('部位', '布帘'))
    expect(chip('是否定型', '是')).toHaveAttribute('aria-checked', 'true')
  })

  it('#4489 部位回到「未指定」⇒ 不动已联动的 isShaped（不删商家已见到的真值）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.click(chip('部位', '纱帘'))
    spy.mockClear()
    fireEvent.click(chip('部位', '未指定'))
    expect(spy).toHaveBeenCalledWith({ curtainType: undefined })
  })
})
