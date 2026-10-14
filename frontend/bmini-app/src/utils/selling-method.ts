/**
 * 售卖方式（`sellingMethod`）的**展示名** —— 单一口径，供商家端小程序各面复用。
 *
 * ## 为什么单独一个文件（而不是在页面里写一张表）
 *
 * 小程序的加工单面（`pages/production/order-detail`）要印「售卖方式」，而**真值**是
 * `order_items.processing_info.sellingMethod` 的**内部键**（`bulk_cut` / `full_roll`）。
 * 直接把内部键摆上商家可见面 = 把系统内部标识漏给商家（`migao-dev-flow` §31 P3）。
 *
 * 单一真值在 **admin-web**：`frontend/admin-web/src/types/index.ts` 的 `SellingMethodLabels`
 * （`types` 的 `SellingMethod` 联合类型一并定义在那里）。三端是独立 npm 工程、无共享包
 * ⇒ 本文件是**同源副本**，**漂移守卫** =
 * `frontend/bmini-app/tests/selling-method-same-source.test.ts`（逐值比对 admin-web 的那份，
 * 守卫**现取**双方键值 ⇒ 任一侧改了另一侧没跟 ⇒ 当场红）。
 * 「未知取值」的处理与 `ProcessingOrderBlock.tsx::sellingMethodLabel` 同口径：
 * **如实回显原值**（至少可核对），不编、不吞、不裸奔英文键的例外只留给真未知。
 */
export const SELLING_METHOD_LABELS: Record<string, string> = {
  bulk_cut: '散剪',
  full_roll: '整卷',
}

/** 售卖方式展示名：登记键 → 人话；未登记 ⇒ **如实回显原值**（不编默认值、不吞值为空） */
export function sellingMethodLabel(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const key = value.trim()
  if (key === '') return null
  return SELLING_METHOD_LABELS[key] ?? key
}
