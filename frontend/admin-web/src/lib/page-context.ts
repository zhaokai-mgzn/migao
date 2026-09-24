/**
 * 页面上下文（issue #5371 · B 端能力地图族 4）—— **前端只递交，不做判定**。
 *
 * ## 为什么前端只做两件事
 *
 * 浮动面板（`components/ai-assistant/FloatingAssistant.tsx`）与米宝同屏 ⇒ 前端**能**直接读到
 * `window.location.pathname` 与当前实体 id。但「读得到」不等于「可以注入」：
 * **route → 真值源** 的登记表、**未登记即不注入**的默认拒绝、以及**按角色裁剪**，唯一真值都在服务端
 * （`backend/ai-agent-service/app/context/page_registry.py`）。本模块只负责把**最小面**递上去：
 *
 * 1. **只取路径**（`normalizeRoute`）：查询串 / 片段一律丢弃 —— 防 PII 进日志。
 *    URL 编码（`%`）、空格、非 ASCII 一律**拒绝**（宁可少传，不把脏数据递上去）。
 * 2. **只取 id，不取实体快照**（`entityIdFromRoute`）：且只认**含数字**的段 ——
 *    `new` / `edit` / `routings` / `production` 这类**路由词**不是对象 id，
 *    把它们当 id 递上去就是「猜错页面」的同族错误（设计里最贵的失效模式）。
 *
 * ## 与 `use-route-id.ts` 的分工（**不是第二套解析器**）
 *
 * `use-route-id.ts` 答的是「我要拿哪个段去发 API 请求」（会把 `new`/`edit` 这类后缀**跳过去**）；
 * 本模块答的是「这一页有没有一个**像 id 的对象**」。两者口径**故意不同**：
 * `/orders/new` 在前者解析出 `orders`（供 API 用），在后者**必须是 undefined**。
 * ⇒ 形态判据（`ENTITY_ID_FORM`）与后端 `ENTITY_ID_RE` **逐字同源**，两侧对同一组语料
 * 的判决必须一致（前端 `tests/unit/lib/page-context.test.ts` + 后端 `tests/test_page_context.py`
 * 的同语料守卫；后端那条还会从本文件里逐条认这些 token）。
 *
 * ## 运输形态
 *
 * 走 `ChatSendRequest.page_context` 一个**可选结构化字段**（`{"route": …, "entityId": …}`）——
 * **不复用** `message` 前缀协议（`__FORM__|` 那种）：页面上下文是**元数据**，不是用户说的话，
 * 挂在消息上会污染会话历史与日志。**角色不进这个字段**（服务端从会话取，客户端说了不算）。
 */

/** 路径长度上限（与后端 `_ROUTE_MAX_LEN` 同值） */
const ROUTE_MAX_LEN = 200

/** 路径字符集：只认路径。`%` / 空格 / 非 ASCII 全部拒绝（URL 编码夹带 PII 的形态进不来） */
const ROUTE_FORM = /^\/[A-Za-z0-9/_.-]*$/

/** 实体 id 形态：**必须含数字**（与后端 `ENTITY_ID_RE` 逐字同源） */
const ENTITY_ID_FORM = /^(?=.*[0-9])[A-Za-z0-9_-]{2,64}$/

export interface PageContextPayload {
  route: string
  /** 没有「像 id 的段」时**整个键缺席**（不是空串占位） */
  entityId?: string
}

/** 规范化路径：**只保留路径**（丢查询串/片段）；非法形态返回 `''`（调用方按「不递交」处理） */
export function normalizeRoute(pathname: string): string {
  if (typeof pathname !== 'string') return ''
  let s = pathname.trim()
  if (!s || s.length > ROUTE_MAX_LEN) return ''
  for (const sep of ['?', '#']) {
    const idx = s.indexOf(sep)
    if (idx >= 0) s = s.slice(0, idx)
  }
  if (!s.startsWith('/') || !ROUTE_FORM.test(s)) return ''
  if (s.includes('..') || s.includes('//')) return ''
  if (s.length > 1) s = s.replace(/\/+$/, '') || '/'
  return s
}

/** 取**最后一个「像 id」的段**；没有 ⇒ `undefined`（绝不把路由词当 id） */
export function entityIdFromRoute(route: string): string | undefined {
  const segments = route.split('/').filter(Boolean)
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    if (ENTITY_ID_FORM.test(segments[i])) return segments[i]
  }
  return undefined
}

/** 路径 → 递交载荷；非法路径 ⇒ `null`（**不递交**，由服务端走默认拒绝） */
export function pageContextPayload(pathname: string): PageContextPayload | null {
  const route = normalizeRoute(pathname)
  if (!route) return null
  const entityId = entityIdFromRoute(route)
  return entityId ? { route, entityId } : { route }
}