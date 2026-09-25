/**
 * 工序显示名的唯一口径（issue #4963）—— 与
 * `frontend/shared/operation-display.mjs`（worker-h5 直接 import 的那一份）**逐字同语义**。
 *
 * ## 为什么这里是一份**复制**而不是 import
 *
 * `frontend/bmini-app/tsconfig.json` 的 `include` 只含 `./src` + `./types`、`rootDir: "."`
 * ⇒ import 包外文件会让 `tsc` 报 TS6059（"not under rootDir"）；`@/*` 别名也只指向自身 `src`。
 * 跨包 import 只能靠 tsconfig 改写（更大的改动面），故按「最少代码阶梯」复制这一份
 * **9 行**的实现，并**不靠纪律**保证不漂移：
 * `tests/unit_ci_workflows/test_operation_display_name_guard.py` 的 C7 把三份实现
 * （本文件 / `frontend/shared/operation-display.mjs` / `frontend/admin-web/src/lib/operation-display.ts`）
 * 喂同一张输入表**逐值比对**，改任一份而不同步另两份 ⇒ 必红。
 *
 * ## 口径（与 web 面 helper 逐字一致）
 *
 * 显示名 = `logical_name`（缺 ⇒ 退回 `operation` 快照名原文）或 `logical_name · position`；
 * 两者都缺 ⇒ 空串（调用方按空态渲染，**不编占位名** —— 改前这里回退成「工序」）。
 *
 * 🔴 **同义不同名（issue #5003②）**：快照 / 变体名在**报工流水读面**上叫 `operation_name`
 * （`WorkLogRow`）⇒ 兜底分支**两个键名都认**（改前只认 `operation`：传进来的对象只有
 * `operation_name` 时兜底取不到值 ⇒ 显示空串）。两键同时在 ⇒ `operation` 优先。
 * ⚠️ **同名不同义**：`per_operation[].operation`（计件汇总）**是逻辑名**、不是快照名 ——
 * 不得喂进兜底分支（#4963：拿快照名比逻辑名 ⇒ 累计计件静默消失）。
 */
export function operationDisplayName(op?: {
  operation?: string | null
  operation_name?: string | null
  logical_name?: string | null
  position?: string | null
} | null): string {
  const logical = (op?.logical_name ?? '').trim() || (op?.operation ?? '').trim() || (op?.operation_name ?? '').trim()
  const position = (op?.position ?? '').trim()
  return logical && position ? `${logical} · ${position}` : logical
}
