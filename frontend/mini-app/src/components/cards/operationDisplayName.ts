// case_ids: UI-045
/**
 * 工序显示名的唯一口径（issue #4963）—— 与
 * `frontend/shared/operation-display.mjs`（worker-h5 直接 import 的那一份）**逐字同语义**。
 *
 * ## 为什么这里是一份**复制**而不是 import
 *
 * `frontend/mini-app` 的 `@/*` 别名只指向自身 `src`，且它是独立 Taro 包（自己的 tsconfig
 * `include`/`rootDir`）⇒ import 包外文件会让 `tsc` 报 TS6059。跨包 import 只能靠改写
 * tsconfig（更大的改动面），故按「最少代码阶梯」复制这一份 **9 行** 的实现，并**不靠纪律**
 * 保证不漂移：`tests/unit_ci_workflows/test_operation_display_name_guard.py` 的 C7 把四份实现
 * （本文件 / `frontend/shared/operation-display.mjs` / `frontend/bmini-app/src/utils/operationDisplayName.ts` /
 * `frontend/admin-web/src/lib/operation-display.ts`）喂同一张输入表**逐值比对**，改一份而不同步 ⇒ 必红。
 *
 * ## 口径
 *
 * 显示名 = `logical_name`（缺 ⇒ 退回 `operation` 快照名原文）或 `logical_name · position`；
 * 两者都缺 ⇒ 空串（调用方按空态渲染，**不编占位名**）。
 * 改前本卡片直接渲染 `data.current_operation`（工人端**快照名**，变体名 `精裁-布`）⇒ 顾客端
 * 看到的是内部变体名而不是「精裁 · 布帘」。
 *
 * 🔴 **同义不同名（issue #5003②）**：快照 / 变体名在**报工流水读面**上叫 `operation_name`
 * ⇒ 兜底分支**两个键名都认**（改前只认 `operation`：传进来的对象只有 `operation_name` 时
 * 兜底取不到值 ⇒ 显示空串）。两键同时在 ⇒ `operation` 优先。
 * ⚠️ 本卡片把 `current_operation` **显式映射**成 `operation` 后传进来（映射点见调用方）。
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
