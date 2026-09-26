// case_ids: PG-018, BM-006, DF-017, OR-045
//
// 工人端 H5 发货页（issue #5648）—— **纯逻辑 + API 客户端**两侧的判据。
//
// 三条硬纪律（与后端同一份口径，前端不是"另一套"）：
//   ① 身份只由 `X-Worker-Session-Id` 解 ⇒ 发货 body 里**没有** worker_id / worker_name；
//   ② 识别是**候选**：`value` 为 null 的格子 ⇒ 留空 + 提示手输（**绝不**预填 0 / 默认值）；
//   ③ 实发数量由人给 ⇒ 缺 items 时**照样提交**（让服务端 400），不在前端编造数量。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  SHIPMENT_FIELD_KEYS,
  SHIPMENT_PREFIX,
  buildShipBody,
  formatShippedTotals,
  prefillFromRecognition,
  renderShipmentSummary,
} from '../src/shipment.mjs'
import { createApi, SESSION_HEADER, CLIENT_REQUEST_ID_HEADER } from '../src/api.mjs'

/** 内存版 localStorage 替身（与既有 worker-h5 测试同一写法）。 */
function memoryStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

function okFetch(data, seen = []) {
  return async (url, init = {}) => {
    seen.push({ url, init })
    return { ok: true, status: 200, json: async () => ({ success: true, data }) }
  }
}

const LOGGED_IN = { 'migao:worker-h5:session': JSON.stringify({ sessionId: 'sess-1', workerName: '张三' }) }

// ── ① 请求体白名单：身份/状态都不由前端定 ─────────────────────────────────────

test('发货 body 是白名单：identity 与 status 一个字节都不进请求体', () => {
  const body = buildShipBody({
    trackingNo: 'SF123',
    logisticsCompany: '顺丰',
    photoRefs: ['https://cdn/a.jpg'],
    recognition: { target_type: 'shipment', fields: [] },
    items: [{ order_item_id: 'i1', product_name: '遮光窗帘', shipped_quantity: 10, unit: '米' }],
    // 调用方硬塞这些键 —— 必须进不去
    worker_id: 'worker-li',
    worker_name: '李四',
    status: 'shipped',
    order_id: 'other-order',
  })
  assert.deepEqual(Object.keys(body).sort(),
    ['items', 'logisticsCompany', 'photoRefs', 'recognition', 'trackingNo'])
  assert.equal(body.worker_id, undefined)
  assert.equal(body.worker_name, undefined)
  assert.equal(body.status, undefined)
})

test('发货 body 的明细逐行只带服务端认得的列（缺值用 null，不填 0）', () => {
  const body = buildShipBody({ trackingNo: 'SF123', items: [{ shipped_quantity: 3, unit: '件' }] })
  assert.equal(body.items.length, 1)
  assert.deepEqual(Object.keys(body.items[0]).sort(),
    ['order_item_id', 'product_name', 'roll_count', 'set_count', 'shipped_quantity', 'unit'])
  assert.equal(body.items[0].set_count, null)
  assert.equal(body.items[0].roll_count, null)
  assert.equal(body.items[0].product_name, null)
})

test('没给照片 / 没给识别留痕 ⇒ 请求体里就没有这两个键（手工录入是正常路径，不是降级）', () => {
  const body = buildShipBody({ trackingNo: 'SF123', items: [], photoRefs: [] })
  assert.equal(body.photoRefs, undefined)
  assert.equal(body.recognition, undefined)
})

// ── ② 识别不确定 ⇒ 不预填 ─────────────────────────────────────────────────────

test('识别不确定的格子留空（不是 0、不是空串占位），并列出需要手输的格子', () => {
  const fields = [
    { key: 'order_no', label: '订单号', value: 'ORD-1', source: '[图片识别]', reason: null },
    { key: 'product_name', label: '商品名称', value: null, source: null, reason: '图片未标注名称' },
    { key: 'quantity', label: '数量', value: null, source: null, reason: '置信度 0.4 低于发货侧阈值 0.9，宁可不填' },
    { key: 'width', label: '宽', value: '2.8', source: '[图片识别]', reason: null },
    { key: 'height', label: '高', value: null, source: null, reason: '方向不明、不猜顺序' },
  ]
  const p = prefillFromRecognition(fields)
  assert.equal(p.orderNo, 'ORD-1')
  assert.equal(p.productName, '')
  assert.equal(p.quantity, '')
  assert.equal(p.width, '2.8')
  assert.equal(p.height, '')
  assert.equal(p.unit, '', '单位不从识别结果推 —— 识别面只认数量，单位由工人在「米/套/件」里选')
  assert.deepEqual(p.uncertain.map((u) => u.key), ['product_name', 'quantity', 'height'])
  assert.ok(p.uncertain.every((u) => u.reason && u.reason.length > 0), '留空必须给得出理由')
})

test('识别整张表都空（degraded）⇒ 全部留空 + 每一格都给手输提示', () => {
  const p = prefillFromRecognition([])
  assert.deepEqual([p.orderNo, p.productName, p.quantity, p.width, p.height], ['', '', '', '', ''])
  assert.equal(p.uncertain.length, 0)
})

test('识别字段面与后端 targets.py 的 shipment target 逐字同名（前端不另立口径）', () => {
  assert.deepEqual(SHIPMENT_FIELD_KEYS, ['order_no', 'product_name', 'quantity', 'width', 'height'])
})

// ── ③ 实发汇总：0 与「不适用」不是一回事 ─────────────────────────────────────

test('实发汇总读得出「几套/几件/几卷」；空集显示「—」而不是「0」', () => {
  assert.equal(formatShippedTotals({
    set_count: 3, roll_count: 2, by_unit: { 米: '10.00', 件: '3.00' },
  }), '10.00米 / 3.00件 / 3套 / 2卷')
  assert.equal(formatShippedTotals({ set_count: 0, roll_count: 0, by_unit: {} }), '—')
  assert.equal(formatShippedTotals(null), '—')
})

// ── ④ 渲染：识别原文一律转义（不把单据文字当标记渲染） ───────────────────────

test('发货读面渲染实发与留痕，且把文本转义', () => {
  const html = renderShipmentSummary({
    status: 'shipped',
    shipped_totals: { set_count: 1, roll_count: 2, by_unit: { 米: '10.00' } },
    shipments: [{
      shipment_no: 'SH1', tracking_no: 'SF123', logistics_company: '顺丰',
      shipped_by: '张三', photo_refs: ['https://cdn/a.jpg'],
      unpacked_at: '2026-09-26T10:00:00+08:00', unpacked_by: '张三', unpack_reason: '<b>装错单</b>',
      items: [{ product_name: '遮光窗帘<script>', shipped_quantity: '10.00', unit: '米', roll_count: 2 }],
    }],
  })
  assert.match(html, /实发：<b>10\.00米 \/ 1套 \/ 2卷<\/b>/)
  assert.match(html, /遮光窗帘&lt;script&gt;/)
  assert.match(html, /&lt;b&gt;装错单&lt;\/b&gt;/, '撤销理由必须转义')
  assert.match(html, /照片：1 张/)
})

test('没有发货记录 ⇒ 渲染空串（不是 undefined / 不是半截 HTML）', () => {
  assert.equal(renderShipmentSummary(null), '')
  assert.equal(renderShipmentSummary({ shipments: [], shipped_totals: null }), '')
})

// ── ⑤ API 客户端：路径 / 头部 / fail-closed ──────────────────────────────────

test('发货四个端点都挂在 /api/worker/shipment/** 下（工人可达面，无商家权限码）', () => {
  assert.equal(SHIPMENT_PREFIX, '/api/worker/shipment')
  const api = createApi({ fetchImpl: okFetch({}), storage: memoryStorage(LOGGED_IN) })
  for (const fn of ['recognizeShipment', 'packOrder', 'shipOrder', 'unpackOrder', 'readShipment']) {
    assert.equal(typeof api[fn], 'function', `客户端必须有 ${fn}`)
  }
  assert.equal(typeof api.requireMerchantPermissionCode, 'undefined', '工人端不得存在商家权限码通道')
})

test('请求带工人 session 头与幂等键；identity 仍不进 body', async () => {
  const seen = []
  const api = createApi({ fetchImpl: okFetch({ status: 'shipped' }, seen), storage: memoryStorage(LOGGED_IN) })
  await api.shipOrder('order-1', buildShipBody({ trackingNo: 'SF1', items: [] }), 'key-1')

  assert.equal(seen.length, 1)
  assert.equal(seen[0].url, '/api/worker/shipment/orders/order-1/ship')
  assert.equal(seen[0].init.headers[SESSION_HEADER], 'sess-1')
  assert.equal(seen[0].init.headers[CLIENT_REQUEST_ID_HEADER], 'key-1')
  const sent = JSON.parse(seen[0].init.body)
  assert.equal(sent.worker_id, undefined)
  assert.equal(sent.worker_name, undefined)
})

test('无 session ⇒ 发货 fail-closed：抛错且一个请求都不发', async () => {
  const seen = []
  const api = createApi({ fetchImpl: okFetch({}, seen), storage: memoryStorage() })
  await assert.rejects(() => api.shipOrder('order-1', buildShipBody({ trackingNo: 'SF1' }), 'k'),
    /工人身份/)
  assert.equal(seen.length, 0, '未登录不得发出任何请求')
})

test('撤销打包必须带理由（理由由页面采集，客户端不做默认值）', async () => {
  const seen = []
  const api = createApi({ fetchImpl: okFetch({ status: 'producing' }, seen), storage: memoryStorage(LOGGED_IN) })
  await api.unpackOrder('order-1', '装错单了，拆开重打', 'key-2')
  assert.equal(JSON.parse(seen[0].init.body).reason, '装错单了，拆开重打')
})
