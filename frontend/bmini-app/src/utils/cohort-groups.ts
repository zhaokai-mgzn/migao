/**
 * 会话卡「来源组」文案（**B 端移动副本**）—— issue #6461。
 *
 * 与 B 端桌面 `frontend/admin-web/src/lib/cohort-groups.ts` **同一份文案**。
 * bmini 是独立 npm 工程（不许 import admin-web 的 TS），故这里是副本；
 * **单一真值**在 admin-web 那一份，两边由
 * `frontend/admin-web/tests/unit/lib/cohort-groups.test.ts` 逐项比对锁死
 * （只改一侧 ⇒ 那条判据红）。同款范式见 `src/utils/selling-method.ts`
 * （售卖方式展示名，判据 = `tests/selling-method-same-source.test.ts`）。
 *
 * 纪律：① 服务端 `cohortLabel`（内部口径词）**不上屏**；② 键覆盖服务端枚举全集；
 * ③ 认不出的键 ⇒ 兜底话术，**不回显原值**。
 */

/** 服务端来源组枚举 → 上屏文案（键 = `SavingMetricViews#cohortOf` 的可能取值）。 */
export const COHORT_GROUP_TITLES: Record<string, string> = {
  purchase: '采购入库的布',
  opening: '开业时导入的老库存',
  unknown: '还没记清来源的布',
}

/** 兜底：认不出的/缺失的来源组 ⇒ 商家话术（不回显原始值）。 */
export const COHORT_GROUP_FALLBACK = '其它来源的布'

/**
 * 来源组机器键 → 上屏文案（缺失 / 认不出 ⇒ 兜底，不回显原值）。
 *
 * 语义与 admin-web 的 `cohortGroupTitle()` **逐值相同**（判据 ⑤ 锁死文案；本函数不用
 * 「查表 + `||` 兜底」那种形态 —— 那一族已被 `design-baseline-expression-fallback` 判成
 * 「查表兜底 = 原始值」的坏形态）。
 */
export function cohortGroupTitle(cohort: string | null | undefined): string {
  const key = typeof cohort === 'string' ? cohort.trim() : ''
  const hit = key === '' ? undefined : COHORT_GROUP_TITLES[key]
  return typeof hit === 'string' && hit.trim() !== '' ? hit : COHORT_GROUP_FALLBACK
}
