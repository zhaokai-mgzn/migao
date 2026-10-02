// 商家冒烟 spec 的判据最小单元（issue #4226）——纯函数、零依赖、可独立执行。
//
// 为什么单独一个模块：`spec.mjs` 的两条判据（① 加工单号、③ 404 探测豁免）原本**内联在旅程里**，
// 而它们的可信度无法单独验证（真跑整条旅程需要线上/真实商家数据 + 本地起栈）。抽成纯函数后
// 就有了「可执行判据级红证」：`criteria.test.mjs`（node:test，无新依赖）。
//
// 缺陷本体（issue #4226，实测级归因）：
//   ① 判「加工单块出现」用 `text=/PO-[0-9-]+|PG-[0-9-]+/`，而真实加工单号前缀是 **JG-**
//      （实测 JG-20260918-9049）⇒ 该正则**永不命中** ⇒ 证据里恒为「加工单可见=false」= **空判据**。
//   ③ 404 豁免条件写成「错误**消息文本**含 404」⇒ 旅程**自身**抛出的、文案里恰好带 404 的错误
//      也被一并豁免 ⇒ **假绿**。

/**
 * 加工单号形态：2 位大写字母 + 8 位日期 + 序号（实测真值 `JG-20260918-9049`）。
 *
 * 不写死 `JG-` 白名单（那是把「猜前缀」换个前缀再猜一次）；也不再用 `PO-`/`PG-`
 * （真实号从不长这样 ⇒ 判据恒假）。
 *
 * ⚠️ 左右边界不是装饰：`[A-Z]{2}-` 若不加边界，**3 字母前缀**的号为会被「错开一位」命中
 * （`ORD-20260918-1234` → 匹配到 `RD-20260918-1234`）⇒ 判据又会变成「命中别的单号」的假绿。
 * 故左边界要求前一位不是大写字母/数字（或串首），右边界要求序号后不接数字。
 */
export const ORDER_NO_SHAPE = /(?:^|[^A-Z0-9])([A-Z]{2}-\d{8}-\d+)(?![0-9])/

/**
 * 从文本里取加工单号（取不到返回 null）。
 * @param {unknown} text 页面文本/单号字符串
 * @returns {string|null}
 */
export function matchProcessingOrderNo(text) {
  const m = ORDER_NO_SHAPE.exec(String(text ?? ''))
  return m ? m[1] : null
}

/** 加工单未生成时组件探测的 URL：GET /api/admin/processing-orders/{orderId}（后端 404，预期） */
export const PROBE_404_URL = /\/processing-orders\/[^/?#]+$/

/**
 * 一条 res.errors 条目是否为「该 404 探测在浏览器 console 上打出的那条文案」。
 *
 * 收窄点（相对改动前）：必须是 `[console.error]` 通道 + `Failed to load resource` 形态
 * （`[pageerror]` 与旅程自抛的错误文案**都不算**），且文案里带 404。
 * @param {unknown} msg
 * @returns {boolean}
 */
export function isConsoleProbe404(msg) {
  const s = String(msg ?? '')
  return s.startsWith('[console.error]') && s.includes('Failed to load resource') && s.includes('404')
}

/**
 * 是否应豁免「加工单未生成前的 404 探测」导致的旅程失败。
 *
 * 结构化判据（**不再扫错误文本**）：豁免的前提是
 *   ① 真有一条 `response.status() === 404` 且 URL 是加工单探测端点；
 *   ② 失败原因**全部**是「该探测产生的 console 文案」（条数不得超过探测次数）——
 *      任何一条非该形态的错误（含旅程自身抛出、文案里恰好带 404 的）都 ⇒ 不豁免。
 * @param {string[]} errors 旅程记录的失败原因（console/pageerror/自抛混合）
 * @param {{url?: string, status?: number}[]} responses 本旅程收集到的响应（至少含 url/status）
 * @returns {boolean}
 */
export function isProbe404Exempt(errors, responses) {
  const list = Array.isArray(errors) ? errors : []
  const probe = (Array.isArray(responses) ? responses : []).filter(
    (r) => r && r.status === 404 && PROBE_404_URL.test(String(r.url ?? ''))
  )
  if (probe.length === 0) return false
  const exemptable = list.filter(isConsoleProbe404)
  if (exemptable.length === 0 || exemptable.length > probe.length) return false
  return list.every(isConsoleProbe404)
}
