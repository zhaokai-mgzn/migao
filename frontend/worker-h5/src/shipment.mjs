// case_ids: PG-018, BM-006, DF-017, OR-045
//
// 工人端 H5 发货页纯逻辑（issue #5648）：请求体白名单 + 「识别不确定 ⇒ 不预填」+ 实发汇总。
//
// 三条纪律（每条都有对应断言，见 tests/worker-h5-shipment.test.mjs）：
//   ① 🔴 **白名单式构造请求体**：`worker_id` / `worker_name` 一个字节都不进 body
//      （身份只由 `X-Worker-Session-Id` 解，服务端说）—— 与报工侧同一条纪律，
//      理由更硬：发货留痕（谁发的货）是**责任凭证**；
//   ② 🔴 **识别只是候选**：`recognition.fields` 里 `value` 为 null 的格子 ⇒ **留空**，
//      **绝不**预填 0 / 空串 / 猜测值（服务端也会拒非正数，但前端不该先把脏值递上去）；
//   ③ 🔴 **实发数量由人给**：没有识别结果、或工人没核过 ⇒ `buildShipBody` **不构造** items
//      （缺 items 服务端会 400 —— 那正是我们要的：宁可提交失败，不要静默记错数量）。
//
// 零依赖（同 `api.mjs` / `render.mjs`）：同一份 `.mjs` 直接给浏览器 `<script type="module">` 用，
// 也给 `node --test` 用。

/** 工人发货面前缀（与后端 `WorkerShipmentController` 的 `@RequestMapping` **逐字同名**）。 */
export const SHIPMENT_PREFIX = '/api/worker/shipment'

/** 识别候选的字段面（与后端 `app/vision/targets.py` 的 `shipment` target **逐字同名**）。 */
export const SHIPMENT_FIELD_KEYS = ['order_no', 'product_name', 'quantity', 'width', 'height']

/**
 * 识别候选 → 可编辑的表格行（**不确定的格子留空**）。
 *
 * @param {Array<{key:string,label:string,value:?string,source:?string,reason:?string}>} fields
 *        `POST /api/worker/shipment/recognize` 回来的**整张**字段表（含留空格）
 * @returns {{orderNo:string, productName:string, quantity:string, unit:string, width:string, height:string,
 *            uncertain:Array<{key:string,label:string,reason:string}>}}
 *          `uncertain` = 需要工人**手输**的格子（页面据此提示，而不是替工人猜）
 */
export function prefillFromRecognition(fields) {
  const valueOf = (key) => {
    const cell = (fields ?? []).find((f) => f?.key === key)
    // 🔴 `value` 为 null / 空串 ⇒ 空串（**不是** 0、不是 "0"、不是任何默认值）
    return cell && typeof cell.value === 'string' && cell.value.trim() !== '' ? cell.value.trim() : ''
  }
  const uncertain = (fields ?? [])
    .filter((f) => f && (!f.value || String(f.value).trim() === ''))
    .map((f) => ({ key: f.key, label: f.label ?? f.key, reason: f.reason ?? '识别不确定，请手工填写' }))
  return {
    orderNo: valueOf('order_no'),
    productName: valueOf('product_name'),
    quantity: valueOf('quantity'),
    // 单位**不从识别结果推**（识别面只认数量，单位由工人选）：默认空，页面给「米/套/件」三选一
    unit: '',
    width: valueOf('width'),
    height: valueOf('height'),
    uncertain,
  }
}

/**
 * 构造发货请求体（**白名单**）。
 *
 * @param {object} p
 * @param {string} p.trackingNo 货运单号（必填；服务端也校验）
 * @param {string} [p.logisticsCompany]
 * @param {string[]} [p.photoRefs] 照片引用（上传后的 URL）
 * @param {object} [p.recognition] 识别留痕（**原样**搬运，服务端只存不算）
 * @param {Array<{order_item_id?:string, product_name?:string, shipped_quantity:number|string, unit:string}>} p.items
 * @returns {object} 恰好五个键（`trackingNo` / `logisticsCompany` / `photoRefs` / `recognition` / `items`）
 */
export function buildShipBody({ trackingNo, logisticsCompany, photoRefs, recognition, items } = {}) {
  const body = {
    trackingNo: trackingNo ?? '',
    items: (items ?? []).map((it) => ({
      order_item_id: it.order_item_id ?? null,
      product_name: it.product_name ?? null,
      shipped_quantity: it.shipped_quantity,
      unit: it.unit,
      set_count: it.set_count ?? null,
      roll_count: it.roll_count ?? null,
    })),
  }
  if (logisticsCompany) body.logisticsCompany = logisticsCompany
  if (Array.isArray(photoRefs) && photoRefs.length > 0) body.photoRefs = [...photoRefs]
  if (recognition) body.recognition = recognition
  // 刻意**不含** worker_id / worker_name / order_id / status：身份与状态都由服务端定
  return body
}

/**
 * 实发汇总 → 一句话（页面/回执用）。
 *
 * 🔴 `set_count` / `roll_count` 为 0 与「这一维不适用」是**两个意思**：服务端对不适用的行给
 * `null`（不是 0）⇒ 这里也就照实说「0 套」而不是把它藏掉 —— 0 是**真的有**零套这种事吗？
 * 不会：求和是空集才会是 0，页面据此显示「—」。
 */
export function formatShippedTotals(totals) {
  if (!totals) return '—'
  const byUnit = totals.by_unit ?? {}
  const parts = Object.entries(byUnit).map(([unit, qty]) => `${qty}${unit}`)
  const sets = Number(totals.set_count ?? 0)
  const rolls = Number(totals.roll_count ?? 0)
  if (sets > 0) parts.push(`${sets}套`)
  if (rolls > 0) parts.push(`${rolls}卷`)
  return parts.length > 0 ? parts.join(' / ') : '—'
}

/** 极简 HTML 转义（与 `render.mjs` 同一取舍：文本一律转义，避免把识别原文当标记渲染）。 */
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

/**
 * 渲染发货读面（`GET /api/worker/shipment/orders/{orderId}` 的返回体）。
 *
 * 屏幕上的顺序 = 工人关心的顺序：**实发多少**（第一行）→ 单号/照片留痕 → 撤销留痕。
 */
export function renderShipmentSummary(view) {
  if (!view || typeof view !== 'object') return ''
  // 没有任何发货单 ⇒ **不渲染空壳**（页面上出现一块「实发：—」的空面板只会让工人以为出错了）
  if (!Array.isArray(view.shipments) || view.shipments.length === 0) return ''
  const rows = view.shipments.map((s) => {
    const items = (s.items ?? []).map((it) =>
      `<li>${esc(it.product_name ?? '—')}：<b>${esc(it.shipped_quantity)}${esc(it.unit)}</b>`
      + `${it.roll_count ? `（${esc(it.roll_count)} 卷）` : ''}`
      + `${it.set_count ? `（${esc(it.set_count)} 套）` : ''}</li>`).join('')
    const photos = (s.photo_refs ?? []).length
    const unpack = s.unpacked_at
      ? `<p class="wh5-unpack">已撤销打包：${esc(s.unpack_reason)}（${esc(s.unpacked_by)}）</p>`
      : ''
    return `<section class="wh5-shipment">
      <h3>发货单 ${esc(s.shipment_no)}</h3>
      <ul>${items}</ul>
      <p>单号：${esc(s.tracking_no ?? '—')}　承运商：${esc(s.logistics_company ?? '—')}</p>
      <p>经手：${esc(s.shipped_by ?? s.packed_by ?? '—')}　照片：${photos} 张</p>
      ${unpack}
    </section>`
  }).join('')
  return `<div class="wh5-shipments">
    <p class="wh5-totals">实发：<b>${esc(formatShippedTotals(view.shipped_totals))}</b></p>
    ${rows}
  </div>`
}
