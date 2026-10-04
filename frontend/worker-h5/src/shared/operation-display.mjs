// case_ids: PG-018, BM-006
//
// 工序显示名的**唯一**口径 —— 工人端（worker-h5 / bmini）共用这一份（issue #4963）。
//
// ## 病根
//
// 工人端此前各拼一份：`worker-h5/src/render.mjs` 自拼 `${logical_name} · ${position ?? 部位}`，
// `bmini-app` 的 `operationLabel()` 自拼 `[logical_name, position].filter(Boolean).join(' · ') || '工序'`
// ⇒ 与 web 面唯一的 `frontend/admin-web/src/lib/operation-display.ts` 在三种输入下渲染不同：
//   ① 缺 `logical_name` 时 bmini 只显示部位（如「布帘」），web 退回快照名原文；
//   ② 键值带空白不 trim（`' 精裁 '` 原样上屏）；
//   ③ 全缺时 bmini 编占位名「工序」，web 给空串（调用方按空态渲染，**不编占位名**）。
//
// ## 口径（与 web 面 helper **逐字同语义**）
//
// 显示名 = `logical_name`（缺 ⇒ 退回 `operation` 快照名原文）或 `logical_name · position`。
// 两者都缺 ⇒ **空串**（调用方按空态渲染）。
//
// ## 为什么是 .mjs 而不是复用 admin-web 的 .ts
//
// `@/*` 别名各自指向自身 `src`（`frontend/bmini-app/tsconfig.json` 的 `paths`），
// 且 bmini 的 `tsconfig.include` 只含 `./src` + `./types` ⇒ 跨包 import 会让 tsc 报 TS6059。
// 故新造这份**极小**的共享模块：worker-h5 直接 `import`；bmini 因 tsconfig rootDir 约束
// **逐字复制**（`frontend/bmini-app/src/utils/operationDisplayName.ts`），由
// `tests/unit_ci_workflows/test_operation_display_name_guard.py` 的 C6/C7 逐值锁死不许漂移。
//
// 守卫：`tests/unit_ci_workflows/test_operation_display_name_guard.py`（C6 worker-h5 引用 /
// C7 三份实现逐值等价 + 注入式红证）。

/**
 * 工序显示名 = `逻辑名` 或 `逻辑名 · 部位`。
 *
 * 边界（三条，与后端读面契约一致）：
 * ① `logical_name` 缺失（老数据 / 商家自建工序）⇒ 退回 `operation` 原文（**不显示空白**）；
 * ② `position` 为空 / 全空白（部位无关工序）⇒ 只显示逻辑名；
 * ③ 两者都缺 ⇒ 空串（调用方按空态渲染，**不编占位名**）。
 *
 * 🔴 **同义不同名（issue #5003②）**：快照 / 变体名在**报工流水读面**上叫 `operation_name`
 * （`WorkLogRow`）—— 它与 `operation` 是**同一语义**的两个键名 ⇒ 兜底分支**两个都认**
 * （改前只认 `operation`：传进来的对象只有 `operation_name` 时兜底取不到值，显示空串）。
 * 两键同时在 ⇒ `operation` 优先（口径显式，不靠对象字面量的书写顺序）。
 * ⚠️ **同名不同义**：`per_operation[].operation`（计件汇总）**是逻辑名**、不是快照名 ——
 * 不得把它喂进本函数的兜底分支（#4963：拿快照名比逻辑名 ⇒ 累计计件静默消失）。
 *
 * @param {{operation?: string|null, operation_name?: string|null, logical_name?: string|null, position?: string|null}|null|undefined} op
 * @returns {string}
 */
export function operationDisplayName(op) {
  const logical = (op?.logical_name ?? '').trim() || (op?.operation ?? '').trim() || (op?.operation_name ?? '').trim()
  const position = (op?.position ?? '').trim()
  return logical && position ? `${logical} · ${position}` : logical
}
