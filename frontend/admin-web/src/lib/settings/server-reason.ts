// case_ids: UI-057, UI-058
/**
 * 服务端拒绝理由 → **商家可读的行**（issue #6663）。
 *
 * ## 为什么要有它
 *
 * 「设置」域的几个面板（工人端页面 / 小件用料尺寸）把服务端 422 的逐条理由**原样**贴给商家，
 * 理由是「不自己编文案、不静默丢弃被拒的键」（那个初衷是对的）。但服务端的原文是**给开发者**的：
 *
 * - `pages：必须是数组（如 ["report","order"]）` —— 字段名 + JSON 示例；
 * - `小件配置缺少 item_key（= 该小件对应的工序名）` —— 字段名 + 表意括号。
 *
 * 它同时踩了本仓两条纪律：**「不摆内部标识」**（§31 P3：字段名不该出现在商家可见面）与
 * 有 **§22 P4「改完会怎样」** 的要求（文案要落到商家能做的动作）。商家看到 `["report","order"]`
 * 既不知道「pages 是哪个东西」，也没法照着改 —— 那是一条**不可行动**的提示。
 *
 * ## 口径（做什么 / 不做什么）
 *
 * - **保留服务端语义**：只去掉**内部标识**（`字段名:` 前缀 / JSON 示例片段），逐条理由本身一字不动；
 * - **不编造理由**：拿不到 `details` 时退回调用方给的兜底句（`fallback`），**不猜病因**；
 * - **不冒充展示名**：**不**在前端把 `item_key` 映射成「小件名」——展示名与标识的分离要在服务端
 *   （§31 P3 的硬约束：前端映射是第二份会漂的口径）。这里只是**不把标识读出来**。
 *
 * 判据：`tests/unit/user-copy-jargon-guard.test.ts` 的 R11（直接渲染内部键 / 环境变量名）。
 */

/** 服务端错误信封（`{ success:false, error:{ message, details:[{field,message}] } }` 的那一层） */
interface ServerErrorBody {
  message?: string
  details?: unknown
}

/**
 * 内部标识清理：把残留的字段名与 JSON 示例擦掉。
 *
 * - `小件配置缺少 item_key（= …）` ⇒ `小件配置缺少该项（= …）`；
 * - `如 ["report","order"]` 这类**代码示例**整段去掉（商家照着它填不了任何东西）。
 */
export function stripInternalTokens(text: string): string {
  return text
    // JSON / 数组示例：`（如 ["report","order"]）`、`(如 ['a','b'])` —— 整段连括号一起去掉
    .replace(/[（(]\s*如\s*[[{][^）)]*[）)]/g, '')
    // 中文括号里剩下的**裸字段名 / 代码标识符**：`（item_key）` / `（= itemKey）`
    .replace(/[（(]\s*=?\s*[a-z][A-Za-z0-9_]*\s*[）)]/g, '')
    // 句子里残留的 snake_case / camelCase 字段名
    // ⚠️ 三个边界都要放过：**前面**不能是标识符字符（lookbehind，避免切掉 `params.x` 的尾巴），
    //    **后面**可以是空白 + `=`（`item_key = …`）、全角/半角括号、冒号、逗号或句末。
    .replace(/(?<![\w$])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?=\s*[\s、，,。：:=（(）)]|$)/g, '该项')
    // camelCase：`[A-Z][a-z0-9]*`（**不是** `+`）—— 服务端真有 `lengthM` 这种「尾字母单大写」的字段名，
    // 写成 `+` 会漏掉它（实测：`lengthM 必须大于 0` 原样上屏）。
    .replace(/(?<![\w$])[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+(?=\s*[\s、，,。：:=（(）)]|$)/g, '该项')
    // 擦掉标识符后留下的**分隔空格**：`缺少 item_key（…）` ⇒ `缺少该项（…）`（商家看的是文案，
    // 不该多一个空格）。⚠️ 只在后面紧跟中文/标点或**句末**时收掉 —— `该项 必须大于 0` 那个空格是真分隔符。
    .replace(/ 该项(?=[^\sA-Za-z0-9]|$)/g, '该项')
    .replace(/[（(]\s*[）)]/g, '') // 掏空后剩下的空括号
    .trim()
}

/**
 * 服务端 422 的逐条理由 ⇒ 商家可读行。
 *
 * 出参顺序与 `details` 一致（**不重排、不合并**）——「哪一项、怎么改」的对应关系靠它。
 * `details` 缺失 / 非数组 / 全空 ⇒ 退回 `fallback`（不编理由）。
 */
export function merchantReasonsOf(error: unknown, fallback: string): string[] {
  const err = (error as { response?: { data?: { error?: ServerErrorBody } } })?.response?.data?.error
  const details = err?.details
  if (Array.isArray(details) && details.length > 0) {
    const lines = details
      .map((d) => {
        const item = d as { field?: string; message?: string }
        // 🔴 **有意丢掉 `item.field`**：字段名是内部标识（§31 P3），商家看不到也不需要看；
        //    他需要的是「服务端说这一项不对」+ 怎么改（在 `message` 里）。
        if (!item?.message) return ''
        return stripInternalTokens(item.message)
      })
      .filter((line): line is string => Boolean(line))
    if (lines.length > 0) return lines
  }
  const summary = err?.message ? stripInternalTokens(err.message) : ''
  return summary ? [summary] : [fallback]
}
