// case_ids: OR-009, UI-038
/**
 * 下单页工艺规格**录入控件**（issue #4375 包 4b · 设计文档 §4.6 入口 2）。
 *
 * 判据聚焦「录入 → 回调」的确定性行为（缺值不写、显式「否」是真值、拼色才出配布边）。
 */
import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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

const selectByName = (name: string) => screen.getByLabelText(name) as HTMLSelectElement
const inputByName = (name: string) => screen.getByLabelText(name) as HTMLInputElement

describe('OrderCraftFields', () => {
  it('渲染 §4.2 的八个工艺控件（部位/工艺/加工类型/打开方式/是否定型/款式/褶距/是否对花）', () => {
    render(<Harness />)
    for (const name of [
      '部位',
      '工艺',
      '加工类型',
      '打开方式',
      '是否定型',
      '款式',
      '褶距',
      '是否对花',
    ]) {
      expect(screen.getByLabelText(name)).toBeInTheDocument()
    }
  })

  it('渲染 19 项特殊选项（部位级多选）', () => {
    render(<Harness />)
    for (const option of SPECIAL_OPTIONS) {
      expect(screen.getByRole('button', { name: option })).toBeInTheDocument()
    }
  })

  it('部位下拉的候选逐字 = 布帘/纱帘/帘头（错值会让加工单取错工序路线）', () => {
    render(<Harness />)
    const values = Array.from(selectByName('部位').options).map((o) => o.value)
    expect(values).toEqual(['', '布帘', '纱帘', '帘头'])
  })

  it('工艺下拉的候选逐字 = 韩褶/打孔/四爪钩/穿杆/平幔', () => {
    render(<Harness />)
    const values = Array.from(selectByName('工艺').options).map((o) => o.value)
    expect(values).toEqual(['', '韩褶', '打孔', '四爪钩', '穿杆', '平幔'])
  })

  it('选部位/工艺 ⇒ onChange 收到 camelCase patch', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(selectByName('部位'), { target: { value: '纱帘' } })
    fireEvent.change(selectByName('工艺'), { target: { value: '打孔' } })
    expect(spy).toHaveBeenCalledWith({ curtainType: '纱帘' })
    expect(spy).toHaveBeenCalledWith({ craft: '打孔' })
  })

  it('打开方式选中「双开」⇒ openCount 是数字 2（不是字符串）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(selectByName('打开方式'), { target: { value: '2' } })
    expect(spy).toHaveBeenCalledWith({ openCount: 2 })
  })

  // issue #4387 判据 1（三开可录入）：用户口径含三开，而此前候选只有 1/2/4
  // ⇒ 商家**选不出**三开（只能靠 API/Agent 直写）。候选必须含 '3' 且标签是「三开」。
  it('#4387 打开方式候选含三开（3）⇒ 选中后 openCount 是数字 3', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    const options = Array.from(selectByName('打开方式').options)
    expect(options.map((o) => o.value)).toEqual(['', '1', '2', '3', '4'])
    expect(options.find((o) => o.value === '3')?.textContent).toBe('三开')
    fireEvent.change(selectByName('打开方式'), { target: { value: '3' } })
    expect(spy).toHaveBeenCalledWith({ openCount: 3 })
  })

  it('是否定型选「否」⇒ isShaped=false（显式否是真值，不得当成未填）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(selectByName('是否定型'), { target: { value: 'false' } })
    expect(spy).toHaveBeenCalledWith({ isShaped: false })
  })

  it('是否定型回到「未指定」⇒ isShaped=undefined（键不落库）', () => {
    const spy = vi.fn()
    render(<Harness initial={{ isShaped: true }} onChangeSpy={spy} />)
    fireEvent.change(selectByName('是否定型'), { target: { value: '' } })
    expect(spy).toHaveBeenCalledWith({ isShaped: undefined })
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
    fireEvent.change(selectByName('是否对花'), { target: { value: 'true' } })
    expect(screen.getByLabelText('花距')).toBeInTheDocument()
  })

  it('特殊选项多选：逐个累积，再点一次取消', () => {
    render(<Harness />)
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
    fireEvent.change(selectByName('款式'), { target: { value: '拼色' } })
    expect(inputByName('配布边米数')).toHaveValue(3)
    expect(inputByName('配布边单价')).toHaveValue(null)
  })

  it('配布边米数可编辑 ⇒ onEdgeMetersChange 收到新米数', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.change(selectByName('款式'), { target: { value: '拼色' } })
    fireEvent.change(inputByName('配布边米数'), { target: { value: '2.5' } })
    expect(inputByName('配布边米数')).toHaveValue(2.5)
  })

  it('配布边米数提示「默认 = 主布米数，可编辑」', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.change(selectByName('款式'), { target: { value: '拼色' } })
    expect(screen.getByText(/默认 = 主布米数/)).toBeInTheDocument()
  })

  it('配布边米数未改过 ⇒ 来源「跟随主布」；改过 ⇒ 来源「人工指定」', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.change(selectByName('款式'), { target: { value: '拼色' } })
    expect(screen.getByText('配布边米数来源：跟随主布')).toBeInTheDocument()
    fireEvent.change(inputByName('配布边米数'), { target: { value: '2' } })
    expect(screen.getByText('配布边米数来源：人工指定')).toBeInTheDocument()
  })

  it('配布边米数清空 ⇒ 回到「跟随主布」（不是 0，也不落 0 米）', () => {
    render(<Harness mainMeters={3} />)
    fireEvent.change(selectByName('款式'), { target: { value: '拼色' } })
    fireEvent.change(inputByName('配布边米数'), { target: { value: '2' } })
    fireEvent.change(inputByName('配布边米数'), { target: { value: '' } })
    expect(screen.getByText('配布边米数来源：跟随主布')).toBeInTheDocument()
    expect(inputByName('配布边米数')).toHaveValue(3)
  })
})
