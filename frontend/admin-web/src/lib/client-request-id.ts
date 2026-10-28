/**
 * 发货幂等键的**唯一生成点**（issue #6935 / #6983，2026-10-28 抽取为共享实现）。
 *
 * 口径（与服务端 `ClientRequestIdService` 的「同键回放、失败释放占位」配套）：
 * ① **提交期间一次生成**；② 失败后**重试复用同值**（否则一次超时重试就变成两次发货）；
 * ③ **成功后作废**（下一次发货是一件新事，该拿新键）。
 * ⇒ 调用方把键存在 `useRef` 里（不触发重渲染），且**只在成功路径清空**。
 *
 * 用 `crypto.randomUUID()`，缺失时退到时间戳 + 随机串（老浏览器 / 非安全上下文下
 * `randomUUID` 不可用；键只要**唯一**即可，服务端按 `(tenant_id, client_request_id)` 去重）。
 *
 * 🔴 为什么抽到 lib：`frontend/admin-web/src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx`（整页发货）
 * 与 `frontend/admin-web/src/components/orders/InlineShipForm.tsx`（列表行内发货，issue #8013）是
 * **同一个写面**的两个入口 —— 键的生成规则抄两份迟早漂（例如一处忘了成功作废 ⇒ 下一单复用旧键，
 * 服务端直接回放上一单的结果 = 运单号静默丢失）。
 */
export function newClientRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) return uuid
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
