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

// ════════════════════════════════════════════════════════════════════════════════
// 发货页（issue #7761）：全完工订单列表 + 50×70 发货联（整套出库单，issue #7786）
//
// 用户 2026-10-25 逐字：「发货工人要能看到全部完结的订单列表，即订单内的多套窗帘全完工的数据。
// 支持工人对完工的订单进行发货标签打印，包含客户的收货信息，走哪个物流/快递方式和公司」。
//
// 四条纪律（每条都有对应断言，见 tests/worker-h5-shipment-ready.test.mjs）：
//   ① 🔴 **筛选不在前端**：列表内容 = 服务端给的行，客户端不过滤、不排序、不补算「几套完工」
//      （那是第二份完工口径 —— 与后端 == 并列的那份迟早分叉）；
//   ② 🔴 **标签行清单是唯一真值**（`buildShipLabelRows`）：屏幕预览与打印读**同一份**行，
//      两处各拼一份字段就是「预览和纸上不一样」的经典形态（洗水唛 #6656 已踩过）；
//   ③ 🔴 **缺值不编造**：`null` / 空串 ⇒ `—`（不印 0、不印 `undefined`、不猜「快递」）；
//   ④ 🔴 **纸型只有一个来源**：`SHIP_LABEL_PAGE_SIZE` 必须逐字等于打印介质矩阵
//      `frontend/admin-web/src/lib/print-media.json` 的 `label-50x70.pageSize` ——
//      守卫测试直接比对那份 JSON（这里写死第二份就等于埋一颗会漂的雷）。
// ════════════════════════════════════════════════════════════════════════════════

/** 发货标签的介质 id（= 介质矩阵 `media[].id`；DP235S 的 50mm × 70mm 卷）。 */
export const SHIP_LABEL_MEDIA_ID = 'label-50x70'

/** 发货标签的 `@page` 尺寸（**必须**与介质矩阵逐字相等；守卫测试比对 print-media.json）。 */
export const SHIP_LABEL_PAGE_SIZE = '50mm 70mm'

/**
 * **纸长按内容撑开**（issue #7776；用户 2026-10-25 逐字「字体太小了，可以把长度延长些，因为长度可以无限长，
 * 宁愿长点也要把字体和信息都呈现出来……打印预览的时候我就发现上下两头留白太多了」）。
 *
 * 发货标签与洗水唛是**同一卷纸**（50mm 宽连续纸卷）：宽度固定 50mm、长度按纸面内容算。
 * 取整 / 夹取口径与洗水唛 `washLabelLengthMm()` 一致：上取整到 1mm、夹在
 * `[SHIP_LABEL_MIN_LENGTH_MM, SHIP_LABEL_MAX_LENGTH_MM]`（下限 = 介质矩阵登记的**最短**纸长，也是驱动里
 * 该登记的那档；上限 = 再长说明内容该拆了）。宽 / 上下限由守卫比对介质矩阵，不写第二份真值。
 */
export const SHIP_LABEL_WIDTH_MM = 50
export const SHIP_LABEL_MIN_LENGTH_MM = 70
export const SHIP_LABEL_MAX_LENGTH_MM = 150

/** 1 CSS px = 1/96 英寸（浏览器度量口径；`scrollHeight` 是 px） */
const CSS_PX_TO_MM = 25.4 / 96

/** 夹取纸长：无效值 ⇒ 下限；不向下取整（宁可长 1mm，也不裁内容） */
function clampLabelLength(mm) {
  const value = Number.isFinite(mm) && mm > 0 ? Math.ceil(mm) : SHIP_LABEL_MIN_LENGTH_MM
  return Math.min(Math.max(value, SHIP_LABEL_MIN_LENGTH_MM), SHIP_LABEL_MAX_LENGTH_MM)
}

/** 量到的**内容像素高** ⇒ 纸长（mm）：上取整到 1mm、夹在上下限内 */
export function shipLabelLengthMm(contentPx) {
  const px = Number.isFinite(contentPx) && contentPx > 0 ? contentPx : 0
  return clampLabelLength(px * CSS_PX_TO_MM)
}

/**
 * 动态纸型的 `@page` 规则（纸长变了才拼一条；宽度始终 = {@link SHIP_LABEL_WIDTH_MM}）。
 *
 * 🔴 静态兜底仍在 `ship-label.css`（`size: 50mm 70mm` —— JS 没跑 / 量不到时按最短纸长出纸）；
 * 本函数产出的规则由调用方**后**插进文档 ⇒ 后声明者赢（`@page` 是文档级规则）。
 */
export function shipLabelPageRule(lengthMm) {
  return `@page { size: ${SHIP_LABEL_WIDTH_MM}mm ${clampLabelLength(lengthMm)}mm; margin: 0; }`
}

/** 缺值占位符（与发货单纸面 `—` 同口径；**不是** 0、不是空串）。 */
export const SHIP_LABEL_MISSING = '—'

/** 值 → 纸面文本：去空白后为空 ⇒ `—`（缺值不编造）。 */
function labelText(value) {
  const text = value == null ? '' : String(value).trim()
  return text === '' ? SHIP_LABEL_MISSING : text
}

/** 业务时区（与后端 `businessClock` 同口径）—— 下单日期按它取日期，不按浏览器本地时区。 */
const SHIP_LABEL_TIME_ZONE = 'Asia/Shanghai'

/**
 * 下单日期（issue #7786）：服务端 `created_at`（ISO / 带偏移）⇒ `YYYY-MM-DD`，按**业务时区**取日期。
 *
 * 🔴 不按 UTC / 浏览器本地时区切字符串：`2026-09-01T16:30:00Z` 在上海是 **09-02** 00:30，
 * 按 UTC 切会印成 09-01（差一天的单据在车间会被当成另一天的货）。
 * 缺值 / 坏值 ⇒ `—`（不猜今天、不印 `Invalid Date`）。
 */
export function shipLabelDateText(value) {
  const raw = value == null ? '' : String(value).trim()
  if (raw === '') return SHIP_LABEL_MISSING
  const at = new Date(raw)
  if (Number.isNaN(at.getTime())) return SHIP_LABEL_MISSING
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: SHIP_LABEL_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(at)
  const pick = (type) => parts.find((part) => part.type === type)?.value ?? ''
  const year = pick('year')
  const month = pick('month')
  const day = pick('day')
  return year && month && day ? `${year}-${month}-${day}` : SHIP_LABEL_MISSING
}

/** 物流类型：服务端已给展示名就照用；没给（未采集 / 未知取值）⇒ `—`，**绝不回退「快递」**。 */
function logisticsText(order) {
  const label = order?.logistics_type_label
  return labelText(label)
}

/** 套数：只读服务端给的 `total_sets` / `completed_sets`，不自己数（第二份完工口径）。 */
function setsText(order) {
  const total = Number(order?.total_sets)
  const completed = Number(order?.completed_sets)
  if (!Number.isFinite(total) || total <= 0) return SHIP_LABEL_MISSING
  if (completed === total) return `${total} 套（全完工）`
  return `${completed}/${total} 套`
}

/**
 * 发货联（整套出库单）的**行清单**（唯一真值）：屏幕预览、打印、测试都读它。
 *
 * 行序 = 拣货/贴箱的人从上到下核对的顺序：单号 → 收件人 → 电话 → 地址 → 物流类型 → 物流公司 →
 * 下单日期 → 套数 → 备注（issue #7786：抬头改「发货联」、补「下单日期」，与用户那张现场发货联对齐）。
 * 🔴 **不重复印「客户」**：本系统的客户 = 收货人（`orders.customer_name`），
 * 同一个人印两遍只是白吃 50mm 版心的两行（信息不重复，`migao-dev-flow` §31 P2）。
 *
 * @param {object} order 列表行（`GET /api/worker/shipment/orders` 的 `items[]`）
 * @returns {Array<{key:string,label:string,value:string,multiline?:boolean}>}
 *          `multiline` = 地址 / 备注可折行（其余行一律单行，折行会把版面推高）
 */
export function buildShipLabelRows(order) {
  const rows = [
    { key: 'order_no', label: '订单号', value: labelText(order?.order_no) },
    { key: 'consignee', label: '收货人', value: labelText(order?.customer_name) },
    { key: 'customer_phone', label: '电话', value: labelText(order?.customer_phone) },
    { key: 'customer_address', label: '地址', value: labelText(order?.customer_address), multiline: true },
  ]
  /**
   * 随货标识（issue #7856，用户 2026-10-26「发货联标签都要加上帘种，和安装信息」）。
   *
   * 🔴 **缺值不印该行**（与水洗唛同一口径）：这三个是选填附注，印「帘种 —」/「安装小区 —」
   * 只会在 50mm 版心上白吃行高。地址是必印行，故它上面仍走 `labelText` 的 `—`。
   * 值来自 `GET /api/worker/shipment/orders` 的 `items[]`（服务端按部位序去重、`/` 连接）。
   */
  const optionalText = (value) => (value == null ? '' : String(value).trim())
  for (const [key, label, value, multiline] of [
    ['curtain_types', '帘种', optionalText(order?.curtain_types)],
    ['install_community', '安装小区', optionalText(order?.install_community)],
    ['install_rooms', '安装位置', optionalText(order?.install_rooms), true],
  ]) {
    if (value !== '') rows.push({ key, label, value, ...(multiline ? { multiline: true } : {}) })
  }
  rows.push(
    // 术语（issue #8080）：这一栏是 **物流类型**（快递 / 物流专线），不是「物流方式」——
    // 商家后台的「物流方式」= `shippingMethod`（物流发货 / 无需物流），同一个词两端口径不同
    // 会让工人与商家对不上话。逐字对齐商家发货页 / 行内快捷发货的「物流类型」。
    { key: 'logistics_type', label: '物流类型', value: logisticsText(order) },
    { key: 'logistics_company', label: '物流公司', value: labelText(order?.logistics_company) },
    { key: 'order_date', label: '下单日期', value: shipLabelDateText(order?.created_at) },
    { key: 'sets', label: '套数', value: setsText(order) },
  )
  const remark = order?.remark == null ? '' : String(order.remark).trim()
  if (remark !== '') {
    rows.push({ key: 'remark', label: '备注', value: remark, multiline: true })
  }
  return rows
}

/** 标签纸面 HTML（`ship-label.css` 负责 50mm × 70mm 的版面与字号）。 */
export function renderShipLabel(order) {
  const rows = buildShipLabelRows(order).map((row) => (
    `<div class="wh5-label-row${row.multiline ? ' wh5-label-row-wrap' : ''}" data-label-key="${esc(row.key)}">`
    + `<dt class="wh5-label-key">${esc(row.label)}</dt>`
    + `<dd class="wh5-label-value">${esc(row.value)}</dd></div>`
  )).join('')
  return `<section class="wh5-ship-label" id="wh5-ship-label" aria-label="发货联（整套出库单）">
    <h2 class="wh5-label-title">发货联</h2>
    <dl class="wh5-label-rows">${rows}</dl>
  </section>`
}

/**
 * 待发货列表（`GET /api/worker/shipment/orders` 的返回体）。
 *
 * 三种状态互斥、各有稳定 id（判据按 id 取，不按文案）：列表 / 空态 / 截断提示。
 * 空态文案只说**事实 + 下一步**（「没有全部完工的订单 ⇒ 报完最后一道工序就会出现在这里」），
 * 不催促、不责备（§31 P4）。
 */
export function renderReadyOrders(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : []
  const count = items.length
  const countLine = `<p class="wh5-ready-count" id="wh5-ready-count">待发货 ${count} 单（全部套已完工）</p>`
  const truncated = payload?.scan?.truncated
    ? `<p class="wh5-ready-more" id="wh5-ready-truncated">还有更多单未列出（本次最多 ${esc(payload.scan.limit)} 单），发完再来刷新</p>`
    : ''
  if (count === 0) {
    return `<section class="wh5-ready" id="wh5-ready-orders">
      ${countLine}
      <p class="wh5-ready-empty" id="wh5-ready-empty">暂无全部完工的订单：最后一道工序报完后，这一单会自动出现在这里</p>
      ${truncated}
    </section>`
  }
  const rows = items.map((order, index) => {
    const no = labelText(order?.order_no)
    const sets = setsText(order)
    const logistics = [logisticsText(order), labelText(order?.logistics_company)]
      .filter((part) => part !== SHIP_LABEL_MISSING).join(' · ') || SHIP_LABEL_MISSING
    return `<li class="wh5-ready-row" id="wh5-ready-${index}">
      <p class="wh5-ready-no" id="wh5-ready-no-${index}">${esc(no)}</p>
      <p class="wh5-ready-sub">收货人：${esc(labelText(order?.customer_name))}　电话：${esc(labelText(order?.customer_phone))}</p>
      <p class="wh5-ready-sub wh5-ready-addr">地址：${esc(labelText(order?.customer_address))}</p>
      <p class="wh5-ready-sub">${esc(logistics)}　${esc(sets)}</p>
      <button type="button" class="wh5-entry" id="wh5-label-${index}" data-label-order="${esc(order?.order_id ?? '')}">发货联</button>
    </li>`
  }).join('')
  return `<section class="wh5-ready" id="wh5-ready-orders">
    ${countLine}
    <ul class="wh5-ready-list">${rows}</ul>
    ${truncated}
  </section>`
}

