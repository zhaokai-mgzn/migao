'use client'

import {
  forwardRef,
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

/**
 * 草稿的**数值读法**：`''` 读作 `0`（与调用方 `next ?? 0` / `value ?? 0` 同口径），
 * 不完整草稿（"." / "-"）读不出 ⇒ `null`。用途见下面「渲染期同步草稿」的守卫 ②。
 */
function draftNumber(draft: string): number | null {
  if (draft === '') return 0
  const n = Number(draft)
  return Number.isFinite(n) ? n : null
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
 * 用户敲的中间态原样留在框里，只有能解析成有限数时才回调（`0` 原样回调）。
 *
 * **失焦归一化的契约（issue #5210 起：只有「本次聚焦敲过键」才归一化）**：本次聚焦期间
 * **敲过键** ⇒ 失焦时归一化（去尾随小数点 / 截断到 `decimals` 位 / 按 `min`·`max` 夹紧 /
 * 空 ⇒ `allowEmpty ? null : 上一个有效值`），结果回写 DOM 并回调；**没敲过键**（只是点进来又点出去）
 * ⇒ **既不归一化、也不回调**（值与草稿都原样）。理由见 `handleBlur` 上方注释：
 * 归一化会把 `decimals` 之外的精度静默改小（`6.112` ⇒ `6.11`），且会唤醒调用方带副作用的 `onChange`。
 *
 * ## 同一真值的另一份实现：**显式互相登记**（issue #5210）
 *
 * `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` 的**行内单价格**
 * （`data-testid="route-rule-price-input-…"`）是仓里**有意保留**的另一份「`type="text"` +
 * `inputMode="decimal"` + 字符串草稿」实现 —— 它**故意不用**本组件：那格的本地预检要**拒绝**
 * 三位小数并给出理由，而本组件的失焦归一化会按 `decimals` 把 `6.005` **静默改成** `6.01`
 * （正好把该拒的输入变成合法值，实测改成 NumberInput 后该判据直接红）。
 * ⇒ 两处注释**互相登记**（该页那段注释也指向本文件）：本仓对「同一真值两份口径」的处置是
 * **要么收敛，要么显式登记**，不许静默并存。#5210 收敛了 `orders/new/page.tsx` 的私有
 * `NumberField`（8 个调用点 ⇒ 本组件），这一处是**登记在案的例外**。
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

  /**
   * 上一次见到的**外部值** ⇒ 在**渲染期**同步草稿（React 官方「props 变化时调整 state」范式），
   * 而不是放进 `useEffect`。为什么必须渲染期做（issue #5210 实测）：
   * 试算写回 `quantity` 是**异步**的（防抖 + await，落在 act() 之外）⇒ effect 里的 `setDraft`
   * 会**晚一帧**才上屏（`orders-new-plan` 判据 10「写回后立刻读输入框」实测读到旧草稿 `1`）。
   * 旧 `NumberField` 是**渲染期派生**显示值（`draftAlive ? draft : String(value)`）⇒ 本来就当帧上屏，
   * 收敛到本组件后必须保持「外部改值**当帧**上屏」，否则是行为回退（真实浏览器里也会闪一帧旧值）。
   */
  const [lastValue, setLastValue] = useState<number | null>(value)
  // ⚠️ 比较用 `Object.is` 而**不是** `!==`：老调用方拿 `NaN` 当「未定价 / 无值」占位
  // （如 `production/routings` 的档位格把 `null` 存成 `Number.NaN`）——`NaN !== NaN` **恒为真**
  // ⇒ 渲染期 setState 会**每次都触发**（死循环风险，React「Too many re-renders」）。
  // `Object.is(NaN, NaN) === true`（同时把 `-0 / 0` 视为不同值，对本组件的草稿渲染无影响：
  // `formatDraft(-0)` 与 `formatDraft(0)` 都是 `"0"`）。红证：tests/unit/components/NumberInput.test.tsx
  // 「④ 外部 value 是 NaN ⇒ 不得死循环」。
  if (!Object.is(value, lastValue)) {
    setLastValue(value)
    if (typeof value === 'number') lastValidRef.current = value
    /**
     * 两条守卫**都承重**，红证各自独立（删任一条 ⇒ 对应测试必红，实测）：
     * ① 回显**逐值相等** ⇒ 不顶草稿（红证：tests/unit/components/NumberInput.test.tsx
     *    「⑤c 外部回传「空」不得吞掉正在输入的中间态」）；
     * ② 回显被调用方**映射**过（`onChange={(v) => onChangeQty(v ?? 0)}` / `positiveOrNull(v)`
     *    ⇒ 回显值 ≠ 我们发出的值，但仍是这次输入的回显：草稿的数值读法与之相同）⇒ 同样不顶草稿。
     *    缺这条 ⇒ 「框里已有 13.3，粘贴/全选改写 `0.`」会被父值洗成 `0`（小数点被吞），
     *    「敲 `0`」在 `positiveOrNull` 那类站点会被洗成 `''`（框当场清空）。
     *    红证：tests/unit/components/NumberInput.test.tsx「行为保真守卫 ②/②b」+
     *    tests/unit/pages/orders-new-number-parity.test.tsx 的逐键用例 +
     *    既有 orders-new-plan 判据 6b（窗宽 `positiveOrNull` 把 0 归 null）。形态同旧
     *    `NumberField.draftAlive`（`Number(draft === '' ? 0 : draft) === (value ?? 0)`，`''` 与 `0` 同义）。
     *
     * 历史上还有一条 `if (parseComplete(draft) === value) return`，它**删掉也不会有任何测试变红**
     * （issue #5218 发现 #7）⇒ 按「假红证比没有红证更坏」+ 最少代码阶梯删掉了它。
     */
    const echo =
      editingRef.current &&
      (value === lastEmittedRef.current || (value ?? 0) === draftNumber(draft))
    if (!echo) setDraft(formatDraft(value))
  }

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
    /**
     * 本次聚焦期间用户**敲过键**吗（`editingRef` 只在 `handleChange` 里置位）—— 没敲过 ⇒ 失焦是
     * **只读**的：既不归一化、也不回调。两个理由都来自真实调用方（issue #5210）：
     * ① 归一化会把「只是点进来又点出去」的框按 `decimals` **改小**（`6.112` ⇒ `6.11`）——
     *    调用方若没有本地精度校验（`orders/new` 的 8 格都没有），这就是静默改值；
     * ② 回调带**副作用**（`orders/new` 的 `onChangeQty` 会把米数标成「人工指定」⇒ 改宽/高不再跟随
     *    重算；`onChangeWidth` 会顺手跑打开方式启发式）⇒「点进来又点出去」不该改变任何东西。
     *    （旧 `NumberField` 的 `onBlur` 只有一句 `setDraft(null)`：同样不改值、不回调。）
     */
    const typed = editingRef.current
    editingRef.current = false
    if (!typed) {
      onBlur?.(e)
      return
    }
    // 去尾随小数点（"2." ⇒ "2"）——"." / "-" / "" 仍解析不出来
    let next = parseComplete(draftRef.current.trim().replace(/\.$/, ''))
    if (next === null) {
      next = allowEmpty ? null : (lastValidRef.current ?? min ?? 0)
      /**
       * 解析不出数（`null`）时，**上屏回落调用方当前持有的值**，而不是一律显示空串：
       * `null` 是**我们发出去的值**，调用方常把它映射成别的（`orders/new` 的 `next ?? 0` ⇒ `0`）
       * ⇒ 若显示空串，就会与旧 `NumberField` 的失焦回落（`setDraft(null)` ⇒ 渲染 `String(value)`）
       * **分叉**：清空 + 失焦后旧实现显示 `0`、本组件显示 `""`（同一件事两种上屏形态）。
       * `allowEmpty={false}` 时 `next` 是数字 ⇒ 走下面分支，不受影响。
       */
      setDraft(next === null ? formatDraft(value) : formatDraft(next))
    } else {
      const d = Math.min(Math.max(Math.trunc(decimals), 0), 20)
      next = Number(next.toFixed(d))
      if (min !== undefined && next < min) next = min
      if (max !== undefined && next > max) next = max
      setDraft(formatDraft(next))
    }
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
