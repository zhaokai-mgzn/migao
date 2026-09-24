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

  it('⑤c 外部回传「空」不得吞掉正在输入的中间态（issue #5218 #7：唯一承重守卫的红证）', () => {
    // 受控夹具：**已有值 12.5**，用户全选改写。敲 "0." 时回调的是 null（不完整草稿），
    // 父组件把 null 原样回传（外部值由 12.5 变成 null）——若照单覆盖草稿，
    // 用户刚敲的小数点就没了。这是 #5198 那族「吞键」在 #5218 里的新入口。
    function Echo() {
      const [v, setV] = useState<number | null>(12.5)
      return <NumberInput data-testid="ni" value={v} onChange={setV} />
    }
    render(<Echo />)
    expect(input().value).toBe('12.5')
    fireEvent.change(input(), { target: { value: '0' } })
    expect(input().value).toBe('0')
    fireEvent.change(input(), { target: { value: '0.' } })
    // 红证（单点变异，实测）：删掉 NumberInput.tsx 里
    // `if (editingRef.current && value === lastEmittedRef.current) return` 这一行 ⇒ 本断言必红（收到 ''）
    expect(input().value).toBe('0.')
    fireEvent.change(input(), { target: { value: '0.6' } })
    expect(input().value).toBe('0.6')
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

/**
 * issue #5210（下单页 8 个数字框从页面私有 `NumberField` 收敛到本组件）逼出来的两条
 * **行为保真**守卫 —— 它们不是新功能，而是旧实现本来就有的语义：
 * ① 「调用方会把我们回调的值**映射**一下」（`next ?? 0` / `positiveOrNull`）时，
 *    正在输入的草稿不得被那个映射后的回显顶掉；
 * ② 「只是点进来又点出去」的框不得被归一化、也不得回调（旧 `NumberField` 的 onBlur 只有
 *    `setDraft(null)`）—— 否则会把调用方带副作用的 onChange 唤醒（米数被标「人工指定」等）。
 * 两条都**可单点变异变红**（红证逐条写在断言上方）。
 */
describe('NumberInput 行为保真守卫（issue #5210 收敛）', () => {
  it('② 调用方把 null 映射成 0（`?? 0`）：一次 change 粘贴 "0." 不吞小数点', () => {
    function Mapped() {
      const [v, setV] = useState<number | null>(13.3)
      return <NumberInput data-testid="ni" value={v} onChange={(next) => setV(next ?? 0)} />
    }
    render(<Mapped />)
    expect(input().value).toBe('13.3')
    // 一次 change 把**不完整草稿** "0." 发出去（粘贴 / 全选改写）⇒ 调用方映射成 0（外部值 13.3 → 0）
    fireEvent.change(input(), { target: { value: '0.' } })
    // 红证（单点变异，实测）：删掉 effect 里
    // `if (editingRef.current && (value ?? 0) === draftNumber(draftRef.current)) return` ⇒ 本断言收到 '0'
    expect(input().value).toBe('0.')
    fireEvent.change(input(), { target: { value: '0.5' } })
    expect(input().value).toBe('0.5')
  })

  it('②b 调用方把 0 归 null（`positiveOrNull`）：敲 "0" 不把框清空', () => {
    function Positive() {
      const [v, setV] = useState<number | null>(6.6)
      return (
        <NumberInput
          data-testid="ni"
          value={v}
          onChange={(next) => setV(next !== null && next > 0 ? next : null)}
        />
      )
    }
    render(<Positive />)
    fireEvent.change(input(), { target: { value: '0' } })
    // 红证（单点变异，实测）：删掉上面那条守卫 ⇒ 本断言收到 ''（框当场清空）。
    // 页面同形态判据：tests/unit/pages/orders-new-plan.test.tsx 判据 6b（窗宽敲 0 ⇒ 框里是 "0"）。
    expect(input().value).toBe('0')
    fireEvent.change(input(), { target: { value: '0.' } })
    expect(input().value).toBe('0.')
  })

  it('③ 只聚焦 + 离开：不归一化、不回调（精度 > decimals 的值原样留着）', () => {
    const spy = vi.fn()
    render(<NumberInput data-testid="ni" value={13.375} decimals={2} onChange={spy} />)
    fireEvent.focus(input())
    fireEvent.blur(input())
    // 红证（单点变异，实测）：删掉 handleBlur 开头的 `const typed = editingRef.current … if (!typed) { … return }`
    // ⇒ 本断言收到 '13.38'、且 spy 被调用（= 「点进来又点出去」静默改值 + 唤醒带副作用的 onChange）
    expect(input().value).toBe('13.375')
    expect(spy).not.toHaveBeenCalled()
  })

  it('③b 敲过键时失焦归一化照旧（守卫不得把正常归一化一起关掉）', () => {
    const spy = vi.fn()
    render(<NumberInput data-testid="ni" value={13.3} decimals={2} onChange={spy} />)
    fireEvent.change(input(), { target: { value: '13.375' } })
    fireEvent.blur(input())
    expect(input().value).toBe('13.38')
    expect(spy).toHaveBeenLastCalledWith(13.38)
  })

  it('④ 外部 value 是 NaN（老调用方拿它当「未定价」占位）⇒ 渲染期同步不得死循环', () => {
    const { rerender } = render(
      <NumberInput data-testid="ni" value={Number.NaN} onChange={() => {}} />
    )
    // 红证（单点变异，实测）：把同步条件从 `Object.is(value, lastValue)` 改回 `value !== lastValue`
    // ⇒ `NaN !== NaN` 恒真 ⇒ 渲染期 setState 每次都触发 ⇒ React「Too many re-renders」⇒ 本用例必红。
    expect(input().value).toBe('')
    rerender(<NumberInput data-testid="ni" value={Number.NaN} onChange={() => {}} />)
    expect(input().value).toBe('')
    // NaN ⇒ 数字仍要能同步（守卫只吞「NaN ⇒ NaN」这一对）
    rerender(<NumberInput data-testid="ni" value={5} onChange={() => {}} />)
    expect(input().value).toBe('5')
  })
})
