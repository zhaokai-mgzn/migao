'use client'

import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FocusEvent,
  type InputHTMLAttributes,
} from 'react'
import { cn } from '@/lib/utils'
import {
  decimalMessage,
  finalizeDraft,
  interpretDecimal,
  type DecimalRules,
} from '@/lib/decimal-input'

/**
 * DecimalInput —— **涉钱 / 带小数数量**面唯一的数字输入原语（issue #8004）。
 *
 * 为什么不用 `<input type="number">`：Chromium 对 `"0."` / `"12."` / `"."` / `"-"` 这类
 * 中间态按「非法浮点数」处理（实测 `el.value` 对 `"0."` 返回 `"0"`、对 `"."` 返回 `""`），
 * 千分位输入直接不认 ⇒ 受控回写即吞掉小数点或整段值。**涉钱面吞一次 = 商家按错的价下单。**
 *
 * 形态：`type="text"` + `inputMode="decimal"` + 内部字符串草稿（用户敲的中间态原样留在框里）。
 * 解析 / 校验 / 话术**全部**走 `frontend/admin-web/src/lib/decimal-input.ts`（一处实现，本组件不另写口径）。
 *
 * ## 对外契约（调用方只须知这三条）
 *
 * ① `onChange` **只收到合法值**（规范串：去千分位、去尾随小数点、去尾随 0）或 `''`（被清空）；
 *    非法输入**永远不回调** ⇒ 调用方的状态里不会出现 `NaN` / 被静默改成 0 的垃圾值。
 * ② 非法输入 ⇒ **出声**：框下方出现具名话术（`role="alert"`，`data-testid="<原 testid>-error"`），
 *    同时 `onValidityChange(false)` —— 调用方据此 `disabled` 掉提交按钮
 *    （涉钱面**不允许带着错误提交**；这是「不许静默变 0 / 变 NaN 后提交」的另一半）。
 * ③ 失焦**只收尾、不改值**：`12.` ⇒ `12`、`1,` ⇒ `1`、`1,234.56` ⇒ `1234.56`；
 *    **不做四舍五入、不按 min/max 夹紧**（`12.345` 不许被悄悄改成 `12.35` —— 那是静默改价）。
 *
 * ## 草稿同步**不在 `useEffect` 里**（issue #7685 / #8043 / #8409）
 *
 * 外部值变化（弹窗预填「默认退款金额 = 实收」）时，草稿是**渲染期**按 React 官方
 * 「adjust state during render」范式一起改掉的（`lastValue` 比对），不是 useEffect 回写：
 * 两阶段回写会让「框里已经能编辑」与「草稿就绪」分处两次提交，用户正好落进那个窗口时
 * 输入会被**盖回基线**（`inline-edit-persistence-guard.test.ts` 判据 C 全仓禁止，**无豁免**）。
 */

/** 与 `Input` / `NumberInput` 同源的 neutral token（UI 回退检测逐字比对，不得引入新色板） */
const BASE_CLASSNAME =
  'w-full h-9 px-3 rounded-lg border border-neutral-300 bg-white text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 disabled:bg-neutral-100 disabled:text-neutral-500 disabled:cursor-not-allowed'

export interface DecimalInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type' | 'min' | 'max'> {
  /** 受控值（字符串口径，与既有表单状态逐字对齐；空串 = 未填） */
  value: string
  /** 只在**合法值**或清空时回调（见契约 ①） */
  onChange: (value: string) => void
  /** 口径名，只用于错误话术（如「退款金额」⇒「退款金额不能小于 0.01」），不上屏 */
  field: string
  /** 可见 label（仅 `RequestApprovalModal` 这类此前用 `<Input label=…>` 的站点需要） */
  label?: string
  /** 小数位上限（金额默认 2；带小数的数量由站点显式给） */
  decimals?: number
  /** 下限（含），金额默认 0 ⇒ 负数一律拒绝 */
  min?: number
  /** 上限（含）：只在业务上确有此口径时才传（**不自造**涉钱上限） */
  max?: number
  /** 允许留空（默认 true）。false ⇒ 空值也算错误（出声 + 提交禁用） */
  allowEmpty?: boolean
  /** 当前离线合法性（供调用方禁用提交：涉钱面带着错误提交 = 静默改价）。
   *  第二参 = 本框的稳定键，多字段表单据此合并（`useDecimalValidity`）。 */
  onValidityChange?: (valid: boolean, key: string) => void
}

const DecimalInput = forwardRef<HTMLInputElement, DecimalInputProps>(function DecimalInput(
  {
    value,
    onChange,
    field,
    label,
    decimals = 2,
    min = 0,
    max,
    allowEmpty = true,
    onValidityChange,
    className,
    id,
    onBlur,
    onFocus,
    ...props
  },
  ref
) {
  const rules: DecimalRules = { decimals, min, max }
  const [draft, setDraft] = useState<string>(value)
  const [error, setError] = useState<string | null>(null)
  /**
   * 草稿同步的**唯一**机制（判据 C：不许 effect 回写）：
   * `lastValue` = 上一次见到的外部值，在**渲染期**比对 ⇒ 与读面同一次提交落地。
   * `focused` 用 state（不用 ref）：渲染期读 ref 会被 `react-hooks/refs` 判红。
   */
  const [lastValue, setLastValue] = useState(value)
  const [focused, setFocused] = useState(false)
  const dataTestId = (props as { 'data-testid'?: string })['data-testid']
  /** 多字段表单里标识本框的稳定键：`data-testid` ⇒ `id` ⇒ 口径名 */
  const validityKey = String(dataTestId ?? id ?? field)
  /** 最新的 `onValidityChange`（在 effect 里同步，不在渲染期写 ref） */
  const cbRef = useRef(onValidityChange)
  useEffect(() => {
    cbRef.current = onValidityChange
  }, [onValidityChange])

  /**
   * 外部改值（预填「默认退款金额 = 实收」/ 重置）⇒ **未聚焦时**同步草稿；正在输入则让用户赢。
   * 渲染期做（不是 effect）：见文件头「草稿同步不在 useEffect 里」。
   */
  if (!Object.is(lastValue, value)) {
    setLastValue(value)
    if (!focused) setDraft(value)
  }

  /**
   * 离线合法性：`invalid` ⇒ 不合法；`empty && !allowEmpty` ⇒ 不合法；
   * `draft`（`12.` / `1,`）**不**算不合法 —— 它是打字中间态，失焦会自己收尾；
   * 若把它判成不合法，用户敲完 `12.` 点提交会撞上「按钮是灰的但没有任何提示」。
   */
  const offlineInvalid = (text: string): boolean => {
    const r = interpretDecimal(text, { decimals, min, max })
    return r.state === 'invalid' || (r.state === 'empty' && !allowEmpty)
  }

  useEffect(() => {
    cbRef.current?.(!offlineInvalid(draft), validityKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, validityKey, decimals, min, max, allowEmpty])

  /** 卸载（删掉一行明细 / 关掉弹窗）⇒ 把本键报回「合法」，否则表单会永久卡在 disabled */
  useEffect(() => {
    const key = validityKey
    return () => cbRef.current?.(true, key)
  }, [validityKey])

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    const r = interpretDecimal(raw, rules)
    if (r.state === 'invalid') {
      /**
       * 非法：草稿**原样留着**（用户要能看见并改自己敲的东西）+ 出声 + 不回调。
       * 注意这与 `NumberInput` 的「非法字符直接忽略这一次输入」不同：那个组件用于
       * 「允许负数 / 需要截断小数位」的算料参数；在钱上静默忽略一次按键等于
       * 「我敲的没进去、但没人告诉我」。
       */
      setDraft(raw)
      setError(decimalMessage(r.reason, field, rules))
      return
    }
    setDraft(raw)
    setError(null)
    if (r.state === 'ok') {
      setLastValue(r.canonical)
      onChange(r.canonical)
    } else if (r.state === 'empty') {
      setLastValue('')
      onChange('')
    }
    // r.state === 'draft'（`12.` / `1,` / `-`）：不回调，等用户敲完或失焦收尾
  }

  const handleBlur = (e: FocusEvent<HTMLInputElement>) => {
    setFocused(false)
    const { text, result: r } = finalizeDraft(draft, rules)
    if (r.state === 'ok') {
      setDraft(text)
      setError(null)
      if (text !== value) {
        setLastValue(text)
        onChange(text)
      }
    } else if (r.state === 'empty') {
      setError(allowEmpty ? null : decimalMessage('empty', field, rules))
    } else {
      // 收尾后仍解析不出 / 越界：出声，**不改**用户敲的文本（也不把上一个有效值当成本次输入提交）
      setError(decimalMessage(r.state === 'invalid' ? r.reason : 'not-a-number', field, rules))
    }
    onBlur?.(e)
  }

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={id} className="block text-sm font-medium text-neutral-700 mb-1.5">
          {label}
          {props.required && <span className="text-red-500 ml-1">*</span>}
        </label>
      )}
      <input
        {...props}
        id={id}
        ref={ref}
        type="text"
        inputMode="decimal"
        value={draft}
        aria-invalid={error ? true : undefined}
        onChange={handleChange}
        onFocus={(e) => {
          setFocused(true)
          onFocus?.(e)
        }}
        onBlur={handleBlur}
        className={cn(
          BASE_CLASSNAME,
          error && 'border-red-500 focus:border-red-500 focus:ring-red-500/15',
          className
        )}
      />
      {error && (
        <p
          role="alert"
          data-testid={dataTestId ? `${dataTestId}-error` : undefined}
          className="mt-1 text-xs text-red-600"
        >
          {error}
        </p>
      )}
    </div>
  )
})

export default DecimalInput

/**
 * 多字段表单的**合并合法性**：`track` 直接接 `DecimalInput` 的 `onValidityChange`，
 * `hasInvalid` 接提交按钮的 `disabled`。
 *
 * 为什么需要它：`DecimalInput` **永远不回调非法值** ⇒ 调用方的状态里只会停在「上一个有效值」。
 * 若不管提交，商家敲了 `12.345`（被拒绝）却按下了保存，就会把「上一次的 12.34」当成这次的输入
 * 提交出去 —— 那就是**静默改价**。把提交按钮绑在 `hasInvalid` 上，是这条契约的另一半。
 */
export function useDecimalValidity(): {
  track: (valid: boolean, key: string) => void
  hasInvalid: boolean
} {
  const [bad, setBad] = useState<Record<string, boolean>>({})
  const track = useCallback((valid: boolean, key: string) => {
    setBad((prev) => (prev[key] === !valid ? prev : { ...prev, [key]: !valid }))
  }, [])
  return { track, hasInvalid: Object.values(bad).some(Boolean) }
}
