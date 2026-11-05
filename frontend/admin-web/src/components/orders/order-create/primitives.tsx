/**
 * 下单页的**内联小组件**（标题 / 标签 / 读数行 / 算式行）—— issue #8725 第一档切片产物。
 *
 * 单一职责：只负责「一行字怎么排」，不含任何业务判断。
 * 页面与四个表单组件共用它们（切片前它们散在页面末尾 6,822 行起）。
 */
import { formatAmount } from '@/lib/order-create/display'

// ====== 内联小组件 ======
export function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-6 h-6 rounded bg-primary-50 text-primary-600 inline-flex items-center justify-center">
        {icon}
      </span>
      <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
    </div>
  )
}

export function Label({
  children,
  required,
  small,
}: {
  children: React.ReactNode
  required?: boolean
  /**
   * **小号**（2026-09-30 第五批）：用户逐字「这里的**字体**可以和售卖形态的字体大小保持一致，
   * 当前太占空间了」—— 颜色那一块的标签与 chips 与组级输入行（售卖形态 / 帘体 / 净尺寸）对齐。
   */
  small?: boolean
}) {
  return (
    <label
      className={
        'block font-medium text-neutral-700 ' + (small ? 'text-xs mb-1' : 'text-sm mb-1.5')
      }
    >
      {children}
      {required && <span className="text-red-500 ml-1">*</span>}
    </label>
  )
}

export function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-neutral-500">{label}</span>
      <span className={highlight ? 'text-orange-600 font-medium' : 'text-neutral-800'}>{value}</span>
    </div>
  )
}

/**
 * 一行**可核对的算式**（issue #4420）：左 = 「数量 单位 × 单价」，右 = 金额。
 *
 * 为什么要把算式显式写出来：用户口径「需要额外把计算公式体现出来，比如
 * 展示窗帘米数 × 组合加工费 = 具体费用」—— 只给金额时，商家对不上报价单与加工单，
 * 也无从判断系统算得对不对（#4118 的「双算」正是靠这种不透明活下来的）。
 */
export function CostRow({
  label,
  expr,
  amount,
  amountLabel,
}: {
  label: string
  expr: string
  amount: number
  /** 覆盖金额那格（未定价 ⇒ 「未定价」，**不得**渲染成 `¥0.00` —— 仓库硬纪律） */
  amountLabel?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-neutral-500 truncate">
        <span className="text-neutral-400">{label}</span>
        <span className="ml-1.5 tabular-nums">{expr}</span>
      </span>
      <span
        className={
          amountLabel
            ? 'text-amber-600 shrink-0'
            : 'text-neutral-700 tabular-nums shrink-0'
        }
      >
        {amountLabel ?? formatAmount(amount)}
      </span>
    </div>
  )
}
