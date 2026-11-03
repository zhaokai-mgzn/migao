/**
 * 会话卡「来源组」文案 —— 服务端**分组枚举** → 商家看得懂的话（issue #6461）。
 *
 * ## 为什么有这张表
 *
 * 批次账读面在 `cohorts[]` 上同时给两样东西：`cohort`（机器键：`purchase` / `opening` /
 * `unknown`）与 `cohortLabel`（服务端给人看的标签）。前者是内部标识（`migao-dev-flow` §31
 * **P3 不摆内部标识**），后者是**内部口径词**（`切换后（采购入库）` / `存量导入（切换前历史包袱）`
 * / `来源未知`）—— 用户在新版省料看板上逐字问过「让新用户如何理解」（issue #6459），
 * 三个词商家一个也读不懂。⇒ 会话卡**按机器键映射**，服务端下发的标签一律不上屏。
 *
 * ## 纪律（三条，都有会红的判据）
 *
 * 1. **一处**：B 端两端（桌面 `components/chat/BatchStockCard.tsx` + 移动
 *    `frontend/bmini-app/src/components/cards/BatchStockCard.tsx`）用**同一份文案**
 *    —— bmini 是独立 npm 工程（不许 import 本文件），那边是**副本**
 *    `frontend/bmini-app/src/utils/cohort-groups.ts`，由
 *    `tests/unit/lib/cohort-groups.test.ts` 逐项比对锁死（改一侧不改另一侧 ⇒ 红）。
 * 2. **覆盖**：键必须等于服务端枚举全集（同一判据现取 `SavingMetricViews.java` 的
 *    `COHORT_*` 常量）—— 服务端新增来源组而这里没跟上 ⇒ 红。
 * 3. **兜底**：认不出的键 ⇒ {@link COHORT_GROUP_FALLBACK}（商家话术），**绝不回显原始值**
 *    —— 新增枚举不会白屏、也不会把 `switched` 这种东西摆到商家面前。
 */

/** 服务端来源组枚举 → 上屏文案（键 = `SavingMetricViews#cohortOf` 的可能取值）。 */
export const COHORT_GROUP_TITLES: Record<string, string> = {
  // 系统里正常走「入库单过账」进来的批次。
  purchase: '采购入库的布',
  // 启用系统之前就有的库存（期初建账导入）——它不是「这个月的采购」。
  opening: '开业时导入的老库存',
  // 批次没记来源（读面把它单列，不并进上面两组）。
  unknown: '还没记清来源的布',
}

/**
 * 兜底：认不出的/缺失的来源组 ⇒ 一句商家话术。
 *
 * 🔴 **不许**改成回显 `cohort` 原值：那是内部标识（`migao-dev-flow` §31 P3），
 * 而且服务端一加枚举就会把它直接摆上屏。红证 = 把本常量从 {@link cohortGroupTitle}
 * 里摘掉 ⇒ `cohort-groups.test.ts` 的兜底判据立刻红。
 */
export const COHORT_GROUP_FALLBACK = '其它来源的布'

/** 来源组机器键 → 上屏文案（缺失 / 认不出 ⇒ 兜底，不回显原值）。 */
export function cohortGroupTitle(cohort: string | null | undefined): string {
  const key = (cohort ?? '').trim()
  return COHORT_GROUP_TITLES[key] || COHORT_GROUP_FALLBACK
}
