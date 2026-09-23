'use client'

import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FocusEvent,
  type InputHTMLAttributes,
} from 'react'

/** 与仓库既有输入框逐字一致的默认样式（UI 回退检测比对 neutral token，不得引入新色板） */
const DEFAULT_CLASSNAME =
  'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'

/** 允许停留在输入框里的中间态（含 "" / "-" / "." / "0."）—— 一律原样保留，**不做 `|| 0` 归一化** */
const DRAFT_RE = /^-?\d*\.?\d*$/
/** 可解析成有限数的**完整**形态；"0." / "." / "-" 不算完整 ⇒ 回调 null（不谎报成 0） */
const COMPLETE_RE = /^-?(?:\d+(?:\.\d+)?|\.\d+)$/

function parseComplete(draft: string): number | null {
  if (!COMPLETE_RE.test(draft)) return null
  const n = Number(draft)
  return Number.isFinite(n) ? n : null
}

function formatDraft(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

export interface NumberInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> {
  value: number | null
  onChange: (value: number | null) => void
  min?: number
  max?: number
  decimals?: number
  /** 失焦后是否把空草稿归一为 value=null（默认 true）；false ⇒ 回到上一个有效值 */
  allowEmpty?: boolean
}

/**
 * NumberInput —— 能正确处理小数录入的数字输入框（issue #5198）
 *
 * 为什么不用 `type="number"`：浏览器对 `"0."` / `"."` / `"-"` 这类中间态按「非法浮点数」处理
 * （真实 Chromium 实测：`el.value` 对 "0." 返回 "0"，对 "." 返回 ""），受控组件一旦按
 * `e.target.value` 回写就会**吞掉小数点**；`Number(raw) || 0` / `value={n || ''}` 同族形态
 * 还会把合法的 `0` 当成空值 ⇒ 用户**永远打不出 "0.5"**。
 *
 * 本组件的做法：`type="text"` + `inputMode="decimal"` + **内部字符串草稿**——
 * 用户敲的中间态原样留在框里，只有能解析成有限数时才回调（`0` 原样回调），
 * 失焦时才做归一化（去尾随小数点 / 截断到 `decimals` 位 / 按 `min`·`max` 夹紧 / 空 ⇒ null）。
 */
const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(function NumberInput(
  { value, onChange, min, max, decimals = 2, allowEmpty = true, className, onBlur, ...props },
  ref
) {
  const [draft, setDraft] = useState<string>(() => formatDraft(value))
  const draftRef = useRef(draft)
  const editingRef = useRef(false)
  const lastEmittedRef = useRef<number | null | undefined>(undefined)
  /** 最近一个**有效**值（allowEmpty={false} 时失焦回退用；清空草稿不会把它抹掉） */
  const lastValidRef = useRef<number | null>(typeof value === 'number' ? value : null)
  draftRef.current = draft

  // 外部 value 变化 ⇒ 同步草稿；但**正在输入的中间态优先**，不覆盖（否则又是吞键）：
  // ① 草稿现有解析值恰等于外部值（"0" 对 0）⇒ 保留；② 外部值就是我们刚回调出去的值（含 null，
  //    如草稿 "0." 回调 null 后外部仍是 null）⇒ 保留。
  useEffect(() => {
    if (typeof value === 'number') lastValidRef.current = value
    if (parseComplete(draftRef.current) === value) return
    if (editingRef.current && value === lastEmittedRef.current) return
    setDraft(formatDraft(value))
  }, [value])

  const commit = (next: number | null) => {
    lastEmittedRef.current = next
    if (next !== null) lastValidRef.current = next
    onChange(next)
  }

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    if (!DRAFT_RE.test(raw)) return // 非法字符（如 "abc"）：忽略这一次输入，不静默变成 0
    editingRef.current = true
    setDraft(raw)
    commit(parseComplete(raw))
  }

  const handleBlur = (e: FocusEvent<HTMLInputElement>) => {
    editingRef.current = false
    // 去尾随小数点（"2." ⇒ "2"）——"." / "-" / "" 仍解析不出来
    let next = parseComplete(draftRef.current.trim().replace(/\.$/, ''))
    if (next === null) {
      next = allowEmpty ? null : (lastValidRef.current ?? min ?? 0)
    } else {
      const d = Math.min(Math.max(Math.trunc(decimals), 0), 20)
      next = Number(next.toFixed(d))
      if (min !== undefined && next < min) next = min
      if (max !== undefined && next > max) next = max
    }
    setDraft(formatDraft(next))
    if (next !== lastEmittedRef.current) commit(next)
    onBlur?.(e)
  }

  return (
    <input
      {...props}
      ref={ref}
      type="text"
      inputMode="decimal"
      value={draft}
      onChange={handleChange}
      onBlur={handleBlur}
      className={className ?? DEFAULT_CLASSNAME}
    />
  )
})

export default NumberInput
