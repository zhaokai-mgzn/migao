/**
 * 工序显示名的**唯一**口径（issue #4621，web 面工序命名统一 · 阶段 1）。
 *
 * ## 病根
 *
 * web 面存在**两套工序名**：`production_operations.name` 是旧命名（把部位编进名字：
 * `布三边` / `精裁-布`），而主线 / 规则 / 矩阵用的是**逻辑名**（`三边` / `精裁`）
 * ⇒ 商家在界面上一会儿看到 `布三边`、一会儿看到 `三边`。
 *
 * ## 口径（冻结）
 *
 * 显示名 = **逻辑工序名**；该实例**有部位**时拼成 `逻辑名 · 部位`（如 `三边 · 布帘`）；
 * 部位无关工序（如 `外帘装袋`）⇒ 只显示逻辑名。
 *
 * 数据来源：后端读面在返回工序名的位置**同时**给出 `logical_name` + `position`
 * （**读时派生、不写库**）；既有 `operation` / `operation_name` 是**工人端快照名**（变体名），
 * **web 界面不得渲染该键**（它们是历史快照名，其它消费者仍要读）。
 *
 * ⚠️ **拼装只此一份**：各面（加工单进度表 / 任务卡打印 / 计件报表…）一律调本函数 ——
 * 各页各拼一份必然漂移，而漂移的那一份不会变红。
 * 守卫：`tests/unit_ci_workflows/test_operation_display_name_guard.py`（禁止各面直接渲染变体名）。
 */

/** 后端读面里与工序名有关的三个键（`operation` 是工人端快照名，只作老数据兜底）。 */
export interface OperationNameFields {
  /**
   * 工人端**快照名**（变体名，如 `精裁-布`）。
   * ⚠️ **不得直接渲染**（issue #4621）—— 只作「老数据没有 `logical_name`」时的兜底。
   */
  operation?: string | null
  /**
   * **同一个语义的另一个键名**（同义不同名，issue #5003②）：报工流水读面（`WorkLogRow`）
   * 把快照 / 变体名放在这个键下 —— 兜底分支两个键名都认（改前只认 `operation` ⇒ 读面行
   * 传进来时兜底取不到值，显示空串）。两键同时在 ⇒ `operation` 优先。
   * ⚠️ **同名不同义**：`per_operation[].operation`（计件汇总）是**逻辑名**，不得喂兜底分支。
   */
  operation_name?: string | null
  /** 逻辑工序名（后端读时派生，如 `精裁`）；老数据 / 商家自建工序可能缺 ⇒ 退回 `operation` 原文 */
  logical_name?: string | null
  /** 部位（如 `布帘`）；部位无关工序 / 老数据为空 ⇒ 只显示逻辑名 */
  position?: string | null
}

/**
 * 工序显示名 = `逻辑名` 或 `逻辑名 · 部位`。
 *
 * 边界（三条，与后端读面契约一致）：
 * ① `logical_name` 缺失（老数据 / 商家自建工序）⇒ 退回 `operation` 原文（**不显示空白**）；
 * ② `position` 为空 / 全空白（部位无关工序）⇒ 只显示逻辑名；
 * ③ 两者都缺 ⇒ 空串（调用方按空态渲染，**不编占位名**）。
 *
 * 🔴 **同义不同名（issue #5003②）**：兜底分支同时认 `operation` 与 `operation_name`
 * （后者是报工流水读面的键名）—— 改前只认 `operation` ⇒ 传进来的是读面行时兜底取不到值。
 */
export function operationDisplayName(op?: OperationNameFields | null): string {
  const logical = (op?.logical_name ?? '').trim() || (op?.operation ?? '').trim() || (op?.operation_name ?? '').trim()
  const position = (op?.position ?? '').trim()
  return logical && position ? `${logical} · ${position}` : logical
}
