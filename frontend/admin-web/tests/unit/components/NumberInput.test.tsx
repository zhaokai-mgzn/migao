// case_ids: UI-055
/**
 * NumberInput 组件测试 —— 「数字输入框 0 打不进去 / 小数点吞键 / 中间态丢失」治理（issue #5198）
 *
 * 红证（每条都能红）：
 * - 用户原始 bug：输入 "0" 后**输入框当场清空**（旧形态 `value={n || ''}` + `onChange(Number(raw) || 0)`
 *   ⇒ `0 || ''` = `''`）⇒ 永远打不出 "0.5" / "0.6"。本文件的第 1、2 条就是它的红证：
 *   把 NumberInput 换成旧形态，这两条必红（`expect(input.value).toBe('0')` 实测收到 `''`）。
 * - 真实浏览器（Chrome + React 19）实测口径见 PR 说明：`type="number"` 下 `el.value` 对 "0." 返回 "0"，
 *   受控回写即吞掉小数点 ⇒ 本组件用 `type="text"` + `inputMode="decimal"` 承载草稿。
 */
import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import NumberInput from '@/components/ui/NumberInput'

/** 受控夹具：把 onChange 的值原样喂回 value（真实页面的最小复现） */
function Harness({
  initial = null,
  onChangeSpy,
  ...props
}: { initial?: number | null; onChangeSpy?: (v: number | null) => void } & Record<string, unknown>) {
  const [value, setValue] = useState<number | null>(initial)
  return (
    <NumberInput
      data-testid="ni"
      value={value}
      onChange={(v) => {
        onChangeSpy?.(v)
        setValue(v)
      }}
      {...props}
    />
  )
}

const input = () => screen.getByTestId('ni') as HTMLInputElement

describe('NumberInput 基础形态（issue #5198）', () => {
  it('控件用 type="text" + inputMode="decimal"（不用 type="number"：浏览器对 "0." 的 el.value 会失真）', () => {
    render(<Harness />)
    expect(input().getAttribute('type')).toBe('text')
    expect(input().getAttribute('inputmode')).toBe('decimal')
  })

  it('默认 className 与仓库既有输入框逐字一致（UI 回退检测比对 neutral token）', () => {
    render(<Harness />)
    expect(input().className).toBe(
      'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'
    )
  })

  it('className 可覆盖默认样式', () => {
    render(<Harness className="h-8 w-20 text-red-600" />)
    expect(input().className).toBe('h-8 w-20 text-red-600')
  })

  it('其余 HTML 属性原样透传（placeholder / disabled / aria-label / required）', () => {
    render(<Harness placeholder="0.00" disabled required aria-label="价格" />)
    expect(input().getAttribute('placeholder')).toBe('0.00')
    expect(input().disabled).toBe(true)
    expect(input().required).toBe(true)
    expect(input().getAttribute('aria-label')).toBe('价格')
  })

  it('forwardRef 拿到真实 input 元素', () => {
    const ref = { current: null as HTMLInputElement | null }
    const Comp = () => (
      <NumberInput ref={ref} value={null} onChange={() => {}} data-testid="ni" />
    )
    render(<Comp />)
    expect(ref.current).toBe(input())
  })
})

describe('NumberInput 中间态不吞键（issue #5198，用户原始 bug 的红证）', () => {
  it('① 输入 "0" ⇒ DOM 值仍为 "0"、回调 0（旧形态 `0 || \'\'` 会当场清空）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '0' } })
    expect(input().value).toBe('0')
    expect(spy).toHaveBeenLastCalledWith(0)
  })

  it('② 续输 "0." ⇒ DOM 值为 "0."（中间态原样保留）；再输 "0.5" ⇒ 回调 0.5', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '0' } })
    fireEvent.change(input(), { target: { value: '0.' } })
    expect(input().value).toBe('0.')
    // "0." 是不完整草稿 ⇒ 回调 null（不谎报成 0）
    expect(spy).toHaveBeenLastCalledWith(null)
    fireEvent.change(input(), { target: { value: '0.5' } })
    expect(input().value).toBe('0.5')
    expect(spy).toHaveBeenLastCalledWith(0.5)
  })

  it('③ 清空 ⇒ 回调 null、DOM 为 ""', () => {
    const spy = vi.fn()
    render(<Harness initial={1} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '' } })
    expect(input().value).toBe('')
    expect(spy).toHaveBeenLastCalledWith(null)
  })

  it('④ 外部 value 从 1 改成 2 ⇒ DOM 同步 "2"；外部 value 未变时输入 "2." 不被覆盖', () => {
    const { rerender } = render(<NumberInput data-testid="ni" value={1} onChange={() => {}} />)
    expect(input().value).toBe('1')
    rerender(<NumberInput data-testid="ni" value={2} onChange={() => {}} />)
    expect(input().value).toBe('2')

    // 用户正在输入的中间态：外部 value 一点没变 ⇒ 不得把 "2." 洗回 "2"（否则小数点又被吞）
    fireEvent.change(input(), { target: { value: '2.' } })
    expect(input().value).toBe('2.')
    rerender(<NumberInput data-testid="ni" value={2} onChange={() => {}} />)
    expect(input().value).toBe('2.')
  })

  it('⑥ 负号中间态 "-" 不被吞（DOM 保持 "-"，回调 null）', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '-' } })
    expect(input().value).toBe('-')
    expect(spy).toHaveBeenLastCalledWith(null)
    fireEvent.change(input(), { target: { value: '-0.5' } })
    expect(input().value).toBe('-0.5')
    expect(spy).toHaveBeenLastCalledWith(-0.5)
  })

  it('非法字符被忽略：草稿与 DOM 都不变（不把 "abc" 静默变成 0）', () => {
    const spy = vi.fn()
    render(<Harness initial={7} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: 'abc' } })
    expect(input().value).toBe('7')
    expect(spy).not.toHaveBeenCalled()
  })
})

describe('NumberInput 失焦归一化与边界（issue #5198）', () => {
  it('⑤a min={0} 下输入 "0" 不被拒（0 是合法值，不被当空）', () => {
    const spy = vi.fn()
    render(<Harness min={0} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '0' } })
    expect(input().value).toBe('0')
    expect(spy).toHaveBeenLastCalledWith(0)
    fireEvent.blur(input())
    expect(input().value).toBe('0')
    expect(spy).toHaveBeenLastCalledWith(0)
  })

  it('⑤b decimals={2} 下 blur 把 "0.567" 截成 0.57（并回写 DOM）', () => {
    const spy = vi.fn()
    render(<Harness decimals={2} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '0.567' } })
    expect(input().value).toBe('0.567')
    fireEvent.blur(input())
    expect(input().value).toBe('0.57')
    expect(spy).toHaveBeenLastCalledWith(0.57)
  })

  it('blur 去掉尾随小数点："2." ⇒ 2', () => {
    const spy = vi.fn()
    render(<Harness onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '2.' } })
    fireEvent.blur(input())
    expect(input().value).toBe('2')
    expect(spy).toHaveBeenLastCalledWith(2)
  })

  it('blur 按 min 夹紧："1.2" + min={5} ⇒ 5', () => {
    const spy = vi.fn()
    render(<Harness min={5} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '1.2' } })
    fireEvent.blur(input())
    expect(input().value).toBe('5')
    expect(spy).toHaveBeenLastCalledWith(5)
  })

  it('blur 按 max 夹紧："99" + max={10} ⇒ 10', () => {
    const spy = vi.fn()
    render(<Harness max={10} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '99' } })
    fireEvent.blur(input())
    expect(input().value).toBe('10')
    expect(spy).toHaveBeenLastCalledWith(10)
  })

  it('空草稿 blur（allowEmpty 默认 true）⇒ 归一为 null，DOM 保持 ""', () => {
    const spy = vi.fn()
    render(<Harness initial={3} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '' } })
    fireEvent.blur(input())
    expect(input().value).toBe('')
    expect(spy).toHaveBeenLastCalledWith(null)
  })

  it('allowEmpty={false}：空草稿 blur ⇒ 回到上一个有效值，不落 null', () => {
    const spy = vi.fn()
    render(<Harness initial={3} allowEmpty={false} onChangeSpy={spy} />)
    fireEvent.change(input(), { target: { value: '' } })
    fireEvent.blur(input())
    expect(input().value).toBe('3')
    expect(spy).toHaveBeenLastCalledWith(3)
  })

  it('外部 value 置 null ⇒ 草稿清空（外部变化要能同步进来）', () => {
    const { rerender } = render(<NumberInput data-testid="ni" value={4} onChange={() => {}} />)
    expect(input().value).toBe('4')
    rerender(<NumberInput data-testid="ni" value={null} onChange={() => {}} />)
    expect(input().value).toBe('')
  })
})
