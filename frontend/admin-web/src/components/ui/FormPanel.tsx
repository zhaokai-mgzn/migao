'use client'

/**
 * 配置面表单的**唯一版式原语**（issue #7176，2026-10-18 用户裁定）。
 *
 * ## 为什么有这份文件（本仓最容易反复踩的一条）
 *
 * 用户逐字：「这里的风格为什么不和第二张图的风格对齐呢，第二张图可以作为一个标准来参考，
 * **后续都要形成固定的设计风格和组件**，我们一个产品不要出现多种设计和风格样式」。
 *
 * 病灶是**同一个页面里三种字段语言**（真机截图归因）：
 * ① 「阈值试算」—— 浅底面板 + 标题 + 一句说明 + `grid` 栅格 + **标签在上** + 控件填满列 + **单位做框内后缀**；
 * ② 「预演（只读）」—— 标签**顺排在控件左边**、控件定宽、外层白底 `p-5` + `text-base` 标题；
 * ③ 算料口径的标量 —— 标签左 / 控件右的「属性行」。
 * ⇒ 判据、截图与主张逐条见 issue #7176。本文件把 ① 逐字固化成组件，另两种形态**由守卫禁止**。
 *
 * ## 一条纪律：字段形态只许改这里
 *
 * 新增 / 修改配置面表单时**不要**自己拼 `label + input` 的版式 —— 用 `FormPanel` / `FormGrid` / `Field`。
 * 守卫 `tests/unit/design-system-form-fields.test.ts` 扫 `src/`：出现「标签顺排在控件左」这类写法 ⇒ 红。
 *
 * ## 边界（如实登记，§19.1）
 *
 * - 本文件只负责**版式**：不取值、不校验、不判口径、不产出文案；
 * - `Field` 只给**结构**（标签 / 控件 / 框内单位 / 提示），控件本身仍由调用方给（原生 `input` / `NumberInput` / `select`）；
 * - 「满列」不等于「整列拉满」：控件宽度由**栅格列宽**决定（最多几列），列数由 `FormGrid` 的 `cols` 定。
 */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * 控件「铬」—— 与 `frontend/admin-web/src/components/ui/Input.tsx` 同款
 * （`h-9` / `rounded-lg` / `border-neutral-300` / 主色聚焦环）。
 *
 * 🔴 宽度一律 `w-full`：控件不再自己定宽（定宽 + 标签在上会在大屏留一排空白，那正是本单要收口的东西）；
 * 宽度由 `FormGrid` 的列宽决定。
 */
export const FIELD_CONTROL =
  'w-full h-9 rounded-lg border border-neutral-300 bg-white px-3 text-sm placeholder:text-neutral-400 ' +
  'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'

/**
 * 带单位（框内后缀）时的控件铬 —— 右侧留出单位的位，否则数字会压到「米」上。
 *
 * 单位**不从标签里抠掉**再拼：调用方用 `splitUnit()`（`CalcCaliberPanel` 的展示拆分）拿到单位，
 * 文案真值仍是 `CALC_PARAM_COPY[*].label`。
 */
export function fieldControl(unit?: string | null): string {
  return unit ? `${FIELD_CONTROL} pr-9` : FIELD_CONTROL
}

/**
 * 一个配置区块 = **浅底面板 + 标题 + 一句说明**（形态逐字取自「阈值试算」）。
 *
 * `hint` 收 `ReactNode`：口径说明里有 `**加粗**` 的，由调用方用 `InlineMarkdown` 渲染成节点。
 */
export default function FormPanel({
  title,
  hint,
  testid,
  className,
  children,
}: {
  /** 区块标题；**不传 = 无标题面板**（渐进披露里那种「只有字段、标题在开关上」的块） */
  title?: ReactNode
  /** 一句商家可读的说明（`text-xs`）；**不传就不占位** */
  hint?: ReactNode
  testid?: string
  className?: string
  children?: ReactNode
}) {
  return (
    <section
      data-testid={testid}
      className={cn('rounded-lg border border-neutral-200 bg-neutral-50/50 p-4', className)}
    >
      {title === undefined ? null : <h4 className="text-sm font-semibold text-neutral-900">{title}</h4>}
      {hint === undefined || hint === null ? null : (
        <p className="mt-1 text-xs leading-5 text-neutral-500">{hint}</p>
      )}
      {children}
    </section>
  )
}

/** 列数 → 轨道类（**字面量**：Tailwind 只认源码里出现过的类名） */
const COLS: Record<number, string> = {
  2: 'sm:grid-cols-2',
  3: 'sm:grid-cols-3',
  4: 'sm:grid-cols-4',
}

/**
 * 字段栅格（`grid` + 统一间距）。窄屏两列、`sm` 起按 `cols` 铺开 —— 与「阈值试算」一致。
 */
export function FormGrid({
  cols = 3,
  testid,
  className,
  children,
}: {
  cols?: 2 | 3 | 4
  testid?: string
  className?: string
  children: ReactNode
}) {
  return (
    <div
      data-testid={testid}
      className={cn('mt-3 grid grid-cols-2 gap-3', COLS[cols] ?? COLS[3], className)}
    >
      {children}
    </div>
  )
}

/**
 * 一个字段 = **标签在上 + 控件 + （可选）框内单位 + （可选）一句口径提示**。
 *
 * `htmlFor` 能对上真实控件 id 时就传（`NumberInput` / 原生控件都收 `id`），对不上就靠控件自己的
 * `aria-label` —— **不要**为了凑 `htmlFor` 去编一个 id。
 */
export function Field({
  label,
  unit,
  hint,
  htmlFor,
  testid,
  className,
  children,
}: {
  label: ReactNode
  /** 单位（框内后缀）；传了它，控件请用 `fieldControl(unit)` 留出位置 */
  unit?: string | null
  /** 一句口径提示（`text-xs`，控件下方）；产品文案不要塞进 `label` */
  hint?: ReactNode
  htmlFor?: string
  testid?: string
  className?: string
  children: ReactNode
}) {
  return (
    <div data-testid={testid} className={cn('min-w-0', className)}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs text-neutral-500">
        {label}
      </label>
      <div className="relative">
        {children}
        {unit ? (
          <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-500">
            {unit}
          </span>
        ) : null}
      </div>
      {hint === undefined || hint === null ? null : (
        <p className="mt-1 text-xs leading-5 text-neutral-500">{hint}</p>
      )}
    </div>
  )
}
