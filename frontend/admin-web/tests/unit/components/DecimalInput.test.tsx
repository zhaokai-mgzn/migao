// @vitest-environment jsdom
// case_ids: MC-159
/**
 * `DecimalInput` —— 涉钱 / 带小数数量面唯一输入原语的**行为判据**（issue #8004）。
 *
 * 三条契约各有一组断言：
 * ① `onChange` **只收合法值**（非法/中间态一律不回调）⇒ 调用方状态里不会出现垃圾值；
 * ② 非法 ⇒ **出声**（`role="alert"` 具名话术）+ `onValidityChange(false)`（调用方据此禁用提交）；
 * ③ 失焦**只收尾、不改值**（`12.` ⇒ `12`、千分位去掉、不做四舍五入 / 不按 min·max 夹紧）。
 *
 * 末尾一条**接线判据**：真页面（`RefundOrderModal`）在非法金额下，确定按钮必须是 disabled
 * —— 「解析失败出声」若只写在组件里、没接进消费点，商家照样能带着错值提交。
 */
import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import DecimalInput from '@/components/ui/DecimalInput'
import RefundOrderModal from '@/components/orders/RefundOrderModal'
import type { Order } from '@/types'

type Spy = ReturnType<typeof vi.fn>

function Harness({
  initial = '',
  onChangeSpy,
  onValiditySpy,
  ...props
}: {
  initial?: string
  onChangeSpy: Spy
  onValiditySpy?: Spy
} & Record<string, unknown>) {
  const [value, setValue] = useState(initial)
  return (
    <DecimalInput
      data-testid="amount"
      field="退款金额"
      value={value}
      onChange={(next) => {
        onChangeSpy(next)
        setValue(next)
      }}
      onValidityChange={(ok) => onValiditySpy?.(ok)}
      {...props}
    />
  )
}

const amount = () => screen.getByTestId('amount') as HTMLInputElement
const type = (value: string) => fireEvent.change(amount(), { target: { value } })

describe('契约 ①：只回调合法值（非法 / 中间态一概不回调）', () => {
  it('控件是 `type="text"` + `inputMode="decimal"`（`type="number"` 会在浏览器层吞掉中间态）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    expect(amount().getAttribute('type')).toBe('text')
    expect(amount().getAttribute('inputmode')).toBe('decimal')
  })

  it('逐键 `1` → `12` → `12.` → `12.5`：中间态 `12.` 留在框里、不回调；`12.5` 回调 `12.5`', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    type('1')
    expect(amount().value).toBe('1')
    type('12')
    expect(amount().value).toBe('12')
    type('12.')
    expect(amount().value).toBe('12.') // 不许被吞成 '12'
    expect(spy).toHaveBeenCalledTimes(2)
    type('12.5')
    expect(spy).toHaveBeenLastCalledWith('12.5')
  })

  it('千分位 `1,234.56`：框里原样保留、回调**规范串** `1234.56`（不把逗号发给接口）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    type('1,234.56')
    expect(amount().value).toBe('1,234.56')
    expect(spy).toHaveBeenLastCalledWith('1234.56')
  })

  it('`12.345`（3 位小数）**一次都不回调**（既不变 0 也不变 12.34 —— 那就是静默改价）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    type('12.345')
    expect(spy).not.toHaveBeenCalled()
    // 对照：同一格里合法的 12.34 **会**回调（证明「不回调」不是「根本没接线」）
    type('12.34')
    expect(spy).toHaveBeenLastCalledWith('12.34')
  })

  it('清空 ⇒ 回调 `\'\'`（空 = 未填，不是 0）', () => {
    const spy = vi.fn()
    render(<Harness initial="12.5" onChangeSpy={spy} />)
    type('')
    expect(spy).toHaveBeenLastCalledWith('')
  })
})

describe('契约 ②：非法 ⇒ 出声（具名话术 + 离线合法性）', () => {
  it('`12.345` ⇒ `role="alert"` 话术出现（含「2 位小数」「不会替你四舍五入」）且 `onValidityChange(false)`', () => {
    const validity = vi.fn()
    render(<Harness onChangeSpy={vi.fn()} onValiditySpy={validity} />)
    type('12.345')
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('退款金额')
    expect(alert.textContent).toContain('2 位小数')
    expect(alert.textContent).toContain('不会替你四舍五入')
    expect(validity).toHaveBeenLastCalledWith(false)
    // 改回合法值 ⇒ 话术消失、合法性回到 true
    type('12.34')
    expect(screen.queryByRole('alert')).toBeNull()
    expect(validity).toHaveBeenLastCalledWith(true)
  })

  it('负数 ⇒ 出声「不能小于 0」（`min = 0` 的格）', () => {
    render(<Harness onChangeSpy={vi.fn()} min={0} />)
    type('-5')
    expect(screen.getByRole('alert').textContent).toContain('不能小于 0')
  })

  it('零在 `min = 0.01` 的格（退款金额）⇒ 出声「不能小于 0.01」', () => {
    render(<Harness onChangeSpy={vi.fn()} min={0.01} />)
    type('0')
    expect(screen.getByRole('alert').textContent).toContain('不能小于 0.01')
  })

  it('超上限 ⇒ 出声「不能超过 100」', () => {
    render(<Harness onChangeSpy={vi.fn()} max={100} />)
    type('101')
    expect(screen.getByRole('alert').textContent).toContain('不能超过 100')
  })

  it('`allowEmpty={false}` + 清空失焦 ⇒ 出声「请填写退款金额」', () => {
    render(<Harness onChangeSpy={vi.fn()} allowEmpty={false} />)
    type('')
    fireEvent.blur(amount())
    expect(screen.getByRole('alert').textContent).toBe('请填写退款金额')
  })

  it('乱码 `abc` ⇒ 出声「只能填数字」（不静默忽略这一次按键）', () => {
    render(<Harness onChangeSpy={vi.fn()} />)
    type('abc')
    expect(amount().value).toBe('abc')
    expect(screen.getByRole('alert').textContent).toContain('只能填数字')
  })
})

describe('契约 ③：失焦只收尾、不改值（不四舍五入、不按 min·max 夹紧）', () => {
  it('`12.` 失焦 ⇒ 上屏 `12` 并回调 `12`（尾随小数点被收尾，值不变）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    type('12.')
    fireEvent.blur(amount())
    expect(amount().value).toBe('12')
    expect(spy).toHaveBeenLastCalledWith('12')
  })

  it('`1,234.56` 失焦 ⇒ 上屏 `1234.56`', () => {
    render(<Harness onChangeSpy={vi.fn()} />)
    type('1,234.56')
    fireEvent.blur(amount())
    expect(amount().value).toBe('1234.56')
  })

  it('`12.345` 失焦 ⇒ **不改小**（不裁成 12.34、不四舍五入成 12.35），话术留着', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    type('12.345')
    fireEvent.blur(amount())
    expect(amount().value).toBe('12.345')
    expect(spy).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toContain('2 位小数')
  })

  it('外部改值（预填「默认退款金额 = 实收」）⇒ 未聚焦时同步草稿', () => {
    const spy = vi.fn()
    const { rerender } = render(<Harness onChangeSpy={spy} />)
    rerender(
      <DecimalInput data-testid="amount" field="退款金额" value="1999" onChange={spy} />
    )
    expect(amount().value).toBe('1999')
  })
})

describe('接线判据：真页面（退款弹窗）在非法金额下**不许**提交', () => {
  const order = {
    id: 'order-1',
    orderNo: 'MG202600001',
    customerName: '张三',
    customerPhone: '13800000000',
    totalAmount: 1999,
    actualAmount: 1999,
    discountAmount: 0,
    status: 'completed',
    hasProcessing: false,
  } as Order

  it('敲 `12.345` ⇒ 框下出声 + 「确定」按钮 disabled；改成 `12.5` ⇒ 可提交且回调精确值', () => {
    const onConfirm = vi.fn()
    render(<RefundOrderModal open onClose={vi.fn()} onConfirm={onConfirm} order={order} />)
    const input = screen.getByTestId('refund-amount') as HTMLInputElement
    fireEvent.change(input, { target: { value: '12.345' } })
    expect(screen.getByRole('alert').textContent).toContain('退款金额')
    const confirm = screen.getByRole('button', { name: '确定' })
    expect(confirm).toBeDisabled()

    fireEvent.change(input, { target: { value: '12.5' } })
    expect(confirm).not.toBeDisabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith({ refundAmount: 12.5, refundReason: expect.any(String) })
  })
})
