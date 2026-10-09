/**
 * 「加工项与加工费」域**两个面板共用**的取值与常量（issue #6585 拆分）。
 *
 * 为什么有本文件：#6585 把 v1 的 `ProcessingBoard`（域内自带 `加工项 | 加工费组合` 两个 tab）
 * 拆成 `ProcessingItemsPanel` / `FeeCombinationsPanel` 两个**可独立挂载**的面板（设计死线：
 * 「域内不许再套一层导航」）。两个面板都要的那几件东西**只留一份** —— 复制两份 = 造第二份会漂的口径。
 *
 * ## 这里有什么（以及**没有什么**）
 *
 * - {@link ItemForm} —— 加工项表单数据。**不是**加工项面板私有：加工费面板的「新建组合」弹窗
 *   与它共用同一份加工项目录类型（`ProcessingItem`），且表单常量由两处共同引用。
 * - {@link DISCOUNT_OPTIONS} / {@link QTY_OPTIONS} / {@link EMPTY_FORM} —— 加工项表单的选项与初值。
 * - {@link money} / {@link inputCls} —— 加工费面板（改单价输入框 / 单价展示）与加工项面板共用。
 *
 * 🔴 **本模块不持有任何取数逻辑、不判任何口径**（同 `config-readiness.ts` 的纪律）：拉数据在
 * 各自面板里（自包含），这里只有「两处都要的字面量与纯函数」。
 */

/**
 * 弹窗内表单数据（加工项）。
 *
 * issue #4882（用户裁定）：加工项的**单价**与**计价方式**整体退场 —— 加工项本身不再持有价，
 * 价只由「加工费组合」（元/米）决定 ⇒ 表单只留名称 / 加工分类 / 优惠。
 */
export interface ItemForm {
  name: string
  discount: string
  discountQty: string
  discountRate: string
  categoryId: string
}

/** 优惠类型选项 */
export const DISCOUNT_OPTIONS = [
  { value: '', label: '无优惠' },
  { value: 'amount_off', label: '按金额满减' },
]

/** 满X件选项（2-99） */
export const QTY_OPTIONS = Array.from({ length: 98 }, (_, i) => ({
  value: String(i + 2),
  label: `满${i + 2}件`,
}))

export const EMPTY_FORM: ItemForm = {
  name: '',
  discount: '',
  discountQty: '2',
  discountRate: '',
  categoryId: '',
}

export const money = (v?: number | null) => `¥${Number(v ?? 0).toFixed(2)}`

export const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'
