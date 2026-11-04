/**
 * 「配置就绪度」端点（`GET /api/admin/config-readiness`）的响应形状（issue #6579）。
 *
 * ## 为什么单开一个类型模块
 *
 * `frontend/admin-web/src/types/index.ts` 有**只许向下**的行数棘轮
 * （`tests/unit_ci_workflows/loc_freeze_ledger.json`）⇒ 新接口面放新文件，
 * **不回导出行**。与 `types/reports.ts` / `types/rework.ts` 同一做法。
 *
 * ## 这里**只有事实的形状**，没有任何三态
 *
 * 服务端只给计数与取值（`total` / `unpriced` / `orphans` / `source` …），
 * `done` / `todo` / `unknown` 的判定在 `@/lib/config-readiness` 的 `judge*` 系列
 * —— 那是唯一真值源（类级守卫 `tests/unit_ci_workflows/test_config_readiness_single_source.py`）。
 * 所以这个类型里**不许出现** `state` 字段：出现了就说明有人把判定搬到了第二处。
 */

/** 一步的载荷：**事实** + 该步的可点去处。 */
export interface ConfigReadinessStep {
  /**
   * 这一步的事实（计数 / 取值）。
   *
   * 🔴 **缺键 = 本次没取到** ⇒ 前端读成 `unknown`（读不到 ≠ 没配）。
   * 服务端取数失败时给的就是**空对象**（不是 0 —— 0 是「真的没有」）。
   */
  facts?: Record<string, unknown>
  /** 该步的可点去处（深链；出处由服务端给，前端只格式化 —— `migao-dev-flow` §22 基线 ①） */
  href?: string
}

/** 端点响应：`data.steps = {<stepKey>: {facts, href}}`。 */
export interface ConfigReadinessResponse {
  /**
   * 逐步骤事实。
   *
   * 🔴 **某一步整个缺席 = 它不适用于调用方**（跨码步骤按调用方权限省略：不持那个码的人
   * 连「这一步」都不该看见 —— 不返回 0、不返回 forbidden 占位）。**不是**「读不到」。
   */
  steps?: Record<string, ConfigReadinessStep>
}
