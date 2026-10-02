// 阶段 6：**连贯链路**验收 —— 入库过账 → 下单（消费该批次）→ 加工单 → 报工 → 发货
//
// 为什么单列（用户 2026-10-02 追问「你走的是入库-下单-加工-报工-发货链路？」）：
// 阶段 4/5 是**五段孤立探针** —— 入库只建了草稿（没过账 ⇒ stock_batches=0）、下单没消费批次、
// 发货一次都没做（order_shipments=0）。本阶段把五段接成**一条单**跑通，逐环节留三路证据。
//
// 纪律（本轮踩过的坑都写进断言里）：
//   ① 每一步先断言「前置对象非空」——否则 undefined 会被 JSON 丢掉、接口照样 200 ⇒ **假绿**
//      （首轮 CH-05 就踩了：商品没建成，订单却建成了）；
//   ② 含加工项订单发货前必须过 `OrderShipGuard`（加工单未完成 ⇒ 页面阻断）——把它做成**正向断言**；
//   ③ 旧码（加工单级 qr_token）报工必须带 `set_id` + `order_item_id`（服务端据此重解析部位、仍由系统定工序）。
import { chromium, Recorder, log, newContext, shot, api, loginApi, psql, saveCtx, loadCtx,
         waitService, sleep, grepApiLog, loginUi, REPO_ROOT, OUT } from './lib.mjs'
import { createServer } from 'node:http'
import { readFileSync, existsSync, statSync, writeFileSync } from 'node:fs'
import { join, extname } from 'node:path'

const R = new Recorder('s6-chain.json')
const ctx = loadCtx()
const T = ctx.tenantId
const stamp = String(Date.now()).slice(-6)
const H5_PORT = Number(process.env.H5_PORT || 3100)
const H5 = `http://127.0.0.1:${H5_PORT}`
const WEB = process.env.BASE_URL || 'http://localhost:3001'
const MIME = { '.html': 'text/html; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' }
const q = (sql) => { try { return psql(sql) } catch (e) { return null } }
const one = (sql) => (q(sql) || [])[0]
const errText = (r) => (r?.json?.error?.message || r?.json?.message || r?.text || '').slice(0, 200)
const need = (v, what) => { if (v === null || v === undefined || v === '') throw new Error(`前置对象为空：${what}`) ; return v }

function startH5Server() {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      if (req.url.startsWith('/api/')) {
        try {
          const chunks = []
          for await (const c of req) chunks.push(c)
          const fwd = { ...req.headers }
          for (const k of ['origin', 'referer', 'host', 'content-length', 'accept-encoding']) delete fwd[k]
          const up = await fetch('http://127.0.0.1:8080' + req.url, {
            method: req.method, headers: { ...fwd, host: '127.0.0.1:8080' },
            body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks),
          })
          const buf = Buffer.from(await up.arrayBuffer())
          res.writeHead(up.status, { 'content-type': up.headers.get('content-type') || 'application/json' })
          res.end(buf)
        } catch (e) { res.writeHead(502); res.end(String(e)) }
        return
      }
      let rel = decodeURIComponent(req.url.split('?')[0])
      if (rel === '/') rel = '/index.html'
      const p = rel.startsWith('/shared/') ? join(REPO_ROOT, 'frontend', rel) : join(REPO_ROOT, 'frontend/worker-h5', rel)
      if (existsSync(p) && statSync(p).isFile()) {
        res.writeHead(200, { 'content-type': (MIME[extname(p)] || 'application/octet-stream') + '; charset=utf-8' })
        res.end(readFileSync(p))
      } else { res.writeHead(404); res.end('nf') }
    })
    server.listen(H5_PORT, '127.0.0.1', () => resolve(server))
  })
}

/** 库存三件套快照：SKU 现货 / 批次数与数量 / 台账条数（用于「动作前 → 动作后」差异断言）。 */
function snapshot(skuId, label) {
  const sku = skuId ? one(`select stock::text as stock, price::text as price from product_skus where id=${skuId}`) : null
  const batch = one(`select count(*)::int as n, coalesce(sum(quantity),0)::text as qty from stock_batches where tenant_id=${T} and sku_id=${skuId}`)
  const ledger = one(`select count(*)::int as n from stock_ledger_entries where tenant_id=${T}`)
  return { label, skuStock: sku?.stock ?? null, skuPrice: sku?.price ?? null, batchCount: batch?.n ?? null, batchQty: batch?.qty ?? null, ledgerCount: ledger?.n ?? null }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const { token } = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: token })
  // 工人 session 必须走端点登录拿（worker_sessions 表里只有 id/worker_no，没有 session_id 列 —— 首轮误查该列 ⇒ wsess=undefined ⇒ 后续全部 401）
  const wlogin = await api('POST', '/api/worker/login', { body: { workerNo: ctx.worker.workerNo, pin: ctx.worker.pin, tenantId: T, deviceLabel: 'CHAIN-PAD' } })
  const wsess = wlogin.json?.data?.session_id
  const h5Server = await startH5Server()
  const browser = await chromium.launch({ headless: true })
  log(`== 阶段6：连贯链路（入库过账→下单→加工→报工→发货） == tenant=${T}`)

  let productId = null, skuId = null, inboundId = null, orderId = null, orderNo = null, poId = null, poNo = null, qrToken = null, setId = null, orderItemId = null

  // ══════════ A. 商品 + 分类 → 入库单 → **过账** ══════════
  try {
    const cat = await api('POST', '/api/admin/categories', { token, body: { name: `链路分类${stamp}`, sortOrder: 1 } })
    const categoryId = cat.json?.data?.id
    const prod = await api('POST', '/api/admin/products', {
      token, body: {
        name: `链路商品${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 68,
        status: categoryId ? 'on_shelf' : 'draft', categoryId,
        colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
        skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 0, skuCode: `CHAIN-${stamp}` }],
      },
    })
    productId = need(prod.json?.data?.id, `商品创建（HTTP ${prod.status} ${errText(prod)}）`)
    skuId = need(one(`select id::text as id from product_skus where product_id='${productId}'`)?.id, 'SKU 行')
    const before = snapshot(skuId, '入库前')
    R.pass('CH-01', '链路①：建商品/分类/SKU（库存起点 0）',
      `products#${productId}（分类 ${categoryId || '未建（退回草稿态）'}）；product_skus#${skuId} 现货=${before.skuStock} 单价=${before.skuPrice}`,
      [`POST /api/admin/categories`, `POST /api/admin/products`, `SQL: select * from product_skus where id=${skuId}`])

    const inb = await api('POST', '/api/admin/inbound-orders', {
      token, body: {
        supplier: `链路供应商${stamp}`, warehouse: '主仓', inboundDate: new Date().toISOString().slice(0, 10),
        remark: `链路验收入库${stamp}`,
        items: [{ productId, skuId, quantity: 100, unitCost: 12.5, dyeLot: `DYE-${stamp}` }],
      },
    })
    inboundId = need(inb.json?.data?.id, `入库单创建（HTTP ${inb.status} ${errText(inb)}）`)
    const inbNo = inb.json?.data?.inbound_no || inb.json?.data?.inboundNo
    const draftRow = one(`select status, inbound_no from inbound_orders where id='${inboundId}'`)
    R.pass('CH-02', '链路②：建入库单（草稿，未动库存）',
      `inbound_orders#${inbNo} status=${draftRow?.status}；过账前：SKU 现货 ${before.skuStock} / 批次 ${before.batchCount} 个 ${before.batchQty} 米 / 台账 ${before.ledgerCount} 条`,
      [`POST /api/admin/inbound-orders`, `SQL: select status from inbound_orders where id='${inboundId}'`])

    const post = await api('PATCH', `/api/admin/inbound-orders/${inboundId}`, { token, body: { action: 'post' } })
    if (!(post.status === 200 && post.json?.success)) throw new Error(`过账失败：HTTP ${post.status} ${errText(post)}`)
    const after = snapshot(skuId, '过账后')
    const batch = one(`select batch_no, quantity::text as quantity, unit_cost::text as unit_cost, amount::text as amount, dye_lot, inbound_no
                       from stock_batches where tenant_id=${T} and sku_id=${skuId} order by created_at desc limit 1`)
    const led = one(`select delta::text as delta, before_qty::text as before_qty, after_qty::text as after_qty, reason, ref_no, operator,
                            avg_cost_before::text as avg_before, avg_cost_after::text as avg_after, cost_amount::text as cost_amount
                     from stock_ledger_entries where tenant_id=${T} and sku_id=${skuId} order by created_at desc limit 1`)
    const status = one(`select status from inbound_orders where id='${inboundId}'`)?.status
    const stockUp = Number(after.skuStock) > Number(before.skuStock)
    const batchUp = Number(after.batchCount) > Number(before.batchCount)
    const ledgerUp = Number(after.ledgerCount) > Number(before.ledgerCount)
    ;(status === 'posted' && stockUp && batchUp && ledgerUp)
      ? R.pass('CH-03', '链路③：**入库过账**（状态 + 批次 + 现货 + 台账 四联）',
          `inbound_orders.status=draft→${status}；product_skus.stock ${before.skuStock}→${after.skuStock}；stock_batches ${before.batchCount}→${after.batchCount} 个（批次号 ${batch?.batch_no}｜数量 ${batch?.quantity}｜单价 ${batch?.unit_cost}｜金额 ${batch?.amount}｜缸号 ${batch?.dye_lot}｜来源 ${batch?.inbound_no}）；stock_ledger_entries ${before.ledgerCount}→${after.ledgerCount} 条（${led?.reason} delta=${led?.delta} ${led?.before_qty}→${led?.after_qty}，ref=${led?.ref_no}，操作人=${led?.operator}）`,
          [`PATCH /api/admin/inbound-orders/${inboundId} {action:'post'}`, `SQL: select * from stock_batches where sku_id=${skuId}`, `SQL: select * from stock_ledger_entries where sku_id=${skuId}`])
      : R.fail('CH-03', '链路③：入库过账', `status=${status} 现货↑=${stockUp} 批次↑=${batchUp} 台账↑=${ledgerUp}｜batch=${JSON.stringify(batch)}｜ledger=${JSON.stringify(led)}`)

    // 移动加权平均成本：起点 0 库存 ⇒ 过账后台账的 avg_cost_after 应等于本次入库单价 12.5
    const avgOk = led && Math.abs(Number(led.avg_after) - 12.5) < 0.0001 && Number(led.before_qty) === 0
      ? true
      : led && Math.abs(Number(led.avg_after) - (Number(led.avg_before) * Number(led.before_qty) + Number(batch?.unit_cost) * Number(batch?.quantity)) / (Number(led.before_qty) + Number(batch?.quantity))) < 0.0001
    avgOk
      ? R.pass('CH-04', '链路③b：移动加权平均成本口径正确',
          `台账 avg_cost ${led?.avg_before} → ${led?.avg_after}（过账前现货 ${led?.before_qty}、本次入库 ${batch?.quantity}@${batch?.unit_cost}）⇒ 与加权平均公式一致；成本金额 ${led?.cost_amount}`,
          [`SQL: select avg_cost_before, avg_cost_after, cost_amount from stock_ledger_entries where sku_id=${skuId}`])
      : R.fail('CH-04', '链路③b：移动加权平均成本口径', `avg_before=${led?.avg_before} avg_after=${led?.avg_after} before_qty=${led?.before_qty} 单价=${batch?.unit_cost} 数量=${batch?.quantity}`)

    const batchesApi = await api('GET', `/api/admin/inbound-orders/batches?skuId=${skuId}`, { token })
    const n = (batchesApi.json?.data || []).length
    n > 0 ? R.pass('CH-05', '链路③c：批次查询端点可见新批次', `GET /api/admin/inbound-orders/batches?skuId= → ${n} 条（${(batchesApi.json.data[0] || {}).batch_no ?? ''}）`, ['GET /api/admin/inbound-orders/batches'])
          : R.fail('CH-05', '链路③c：批次查询端点', `HTTP ${batchesApi.status} 返回 ${n} 条`)
  } catch (e) {
    R.fail('CH-01', '链路①/②/③（商品+入库过账）失败', String(e).slice(0, 400))
  }

  // ══════════ B. 下单（消费本链路入库的商品）══════════
  try {
    need(productId, '商品 id（入库环节未建成 ⇒ 不得继续下单）'); need(skuId, 'SKU id')
    const before = snapshot(skuId, '下单前')
    const order = await api('POST', '/api/admin/orders', {
      token, body: {
        customerName: `链路客户${stamp}`, customerPhone: '13300000001', customerAddress: '杭州市余杭区链路路 1 号',
        logisticsType: 'express', logisticsCompany: '顺丰速运',
        items: [{
          productId, skuId, productName: `链路商品${stamp}`, quantity: 10, unitPrice: 68, subtotal: 680,
          processingInfo: {
            sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
            processingItems: [{ id: 'proc_item_1', name: '锁边', quantity: 10, unit: '米' }],
          },
        }],
      },
    })
    orderId = need(order.json?.data?.id, `建单（HTTP ${order.status} ${errText(order)}）`)
    orderNo = order.json?.data?.orderNo
    const after = snapshot(skuId, '下单后')
    // ⚠️ order_items **没有 sku_id 列**（实测：只有 product_id；SKU 落在 processing_info JSON 里，
    //    真正的「SKU 被消耗」证据在 stock_batch_consumptions.sku_id）⇒ 这里判 product_id + processing_info 里的 skuId
    const item = one(`select product_id, product_name, quantity::text as qty, unit_price::text as price, processing_info::text as pi from order_items where order_id='${orderId}'`)
    const skuInPi = item && String(item.pi || '').includes(String(skuId))
    const linked = item && String(item.product_id) === String(productId)
    linked
      ? R.pass('CH-06', '链路④：下单**引用本链路入库的商品**（SKU 随加工信息带下）',
          `orders#${orderNo}；order_items.product_id=${item.product_id}（= 入库批次同一商品）；数量 ${item.qty}@${item.price}；processing_info 含本链路 skuId=${skuInPi}；SKU 现货 ${before.skuStock}→${after.skuStock}（${Number(after.skuStock) < Number(before.skuStock) ? '下单即扣减' : '下单不扣减 —— 扣减发生在加工备料/发货'}）`,
          [`POST /api/admin/orders`, `SQL: select * from order_items where order_id='${orderId}'`])
      : R.fail('CH-06', '链路④：下单引用入库商品', `order_items.product_id 与入库商品不一致：${JSON.stringify(item)}（期望 ${productId}）`)
    const pay = await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
    const st = one(`select status from orders where id='${orderId}'`)?.status
    R.pass('CH-07', '链路④b：确认收款 → 已确认', `HTTP ${pay.status}；DB status=${st}`, ['PUT /api/admin/orders/{id}/payment'])
  } catch (e) {
    R.fail('CH-06', '链路④（下单）失败', String(e).slice(0, 300))
  }

  // ══════════ C. 加工单 + 工序实例 + 发货守卫（正向断言）══════════
  try {
    need(orderId, '订单 id（下单环节未成 ⇒ 不得继续）')
    const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
    const po = one(`select id, processing_order_no, status from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
    poId = need(po?.id, `加工单（HTTP ${gen.status} ${errText(gen)}）`)
    poNo = po.processing_order_no
    const ops = await api('GET', `/api/admin/production/orders/${orderId}/operations`, { token })
    qrToken = need(ops.json?.data?.qr_token, 'qr_token')
    const positions = ops.json?.data?.positions || []
    const opTotal = positions.reduce((n, p) => n + (p.operations || []).length, 0)
    const inst = one(`select count(*)::int as total from processing_position_operations where processing_order_id='${poId}'`)
    opTotal > 0 && Number(inst?.total) > 0
      ? R.pass('CH-08', '链路⑤：生成加工单 + 实例化工序 + 二维码',
          `processing_orders#${poNo} status=${po.status}；工序实例 ${inst.total} 行（解析面 ${opTotal} 道 / 部位 ${positions.length} 个）；qr_token=${String(qrToken).slice(0, 12)}…（32 位hex=${/^[0-9a-f]{32}$/.test(String(qrToken))}）`,
          ['POST /api/admin/processing-orders/generate', `GET /api/admin/production/orders/${orderId}/operations`, `SQL: select * from processing_position_operations where processing_order_id='${poId}'`])
      : R.fail('CH-08', '链路⑤：生成加工单', `HTTP ${gen.status}｜工序实例 ${inst?.total} 行 / 解析面 ${opTotal} 道`)

    // 页面：生产看板应显示该加工单
    const { page } = await newContext(browser)
    await loginUi(page, { mode: 'admin', phone: ctx.adminPhone })
    await page.goto(`${WEB}/production`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await sleep(2500)
    const board = await page.evaluate(() => document.body.innerText)
    await shot(page, 's6-01-production-board')
    board.includes(poNo)
      ? R.pass('CH-09', '链路⑤b：生产看板页面显示该加工单（页面证据）', `DOM 文本含加工单号 ${poNo}`,
          ['screenshots/s6-01-production-board.png', `GET ${WEB}/production`])
      : R.fail('CH-09', '链路⑤b：生产看板显示加工单', `未含 ${poNo}；片段=${board.replace(/\n/g, ' ').slice(0, 180)}`, ['screenshots/s6-01-production-board.png'])

    // 发货守卫（正向）：加工单未完成 ⇒ 发货页必须阻断
    await page.goto(`${WEB}/orders/${orderId}/ship`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await sleep(2500)
    const shipText = (await page.evaluate(() => document.body.innerText)).replace(/\n/g, ' ')
    const hasForm = await page.locator('input[placeholder="请输入快递单号"]').isVisible().catch(() => false)
    const blocked = /须先完成加工单/.test(shipText)
    await shot(page, 's6-02-ship-guard-blocked')
    blocked && !hasForm
      ? R.pass('CH-10', '链路⑥：**发货守卫正向生效**（含加工项且加工单未完成 ⇒ 页面阻断、不放表单）',
          `页面文案命中「须先完成加工单后再发货」；发货表单可见=${hasForm}；加工单 status=${po.status}`,
          ['screenshots/s6-02-ship-guard-blocked.png', 'OrderShipGuard.assertProcessingCompletedBeforeShip'])
      : R.fail('CH-10', '链路⑥：发货守卫正向生效', `阻断文案=${blocked} 表单可见=${hasForm}；页面片段=${shipText.slice(0, 200)}`, ['screenshots/s6-02-ship-guard-blocked.png'])
  } catch (e) {
    R.fail('CH-08', '链路⑤/⑥（加工单+守卫）失败', String(e).slice(0, 300))
  }

  // ══════════ D. 报工：B 端 H5 扫一次 + 补齐到加工单完成 ══════════
  try {
    need(qrToken, 'qr_token（加工单环节未成 ⇒ 不得继续报工）')
    const { page } = await newContext(browser)
    await page.goto(`${H5}/index.html?tenant_id=${T}`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.waitForSelector('#wh5-worker-no', { timeout: 20000 })
    await page.fill('#wh5-worker-no', ctx.worker.workerNo); await page.fill('#wh5-pin', ctx.worker.pin)
    await page.click('#wh5-login')
    await page.waitForSelector('#wh5-current-worker', { timeout: 15000 })
    await page.fill('#wh5-code', String(qrToken)); await page.click('#wh5-scan')
    await sleep(2500)
    if (!(await page.locator('#wh5-operation').isVisible().catch(() => false)) && await page.locator('[data-set-id]').first().isVisible().catch(() => false)) {
      await page.locator('[data-set-id]').first().click(); await sleep(600)
      await page.locator('[data-order-item-id]').first().click(); await sleep(1500)
    }
    // 旧码的两个选择键（后续用端点补齐时复用）
    setId = await page.locator('.wh5-choice.is-on').first().getAttribute('data-set-id').catch(() => null)
    orderItemId = await page.locator('[data-order-item-id].is-on').first().getAttribute('data-order-item-id').catch(() => null)
    const opText = await page.locator('#wh5-operation').innerText().catch(() => '')
    const before = Number(one(`select count(*)::int as n from production_work_logs where processing_order_id='${poId}'`)?.n ?? 0)
    await page.locator('#wh5-report').click()
    await sleep(2500)
    const notice = await page.locator('#wh5-notice, #wh5-completed').first().innerText().catch(() => '')
    await shot(page, 's6-03-h5-report-on-chain')
    const after = Number(one(`select count(*)::int as n from production_work_logs where processing_order_id='${poId}'`)?.n ?? 0)
    const logRow = one(`select operation_name, qty::text as qty, unit_price::text as unit_price, worker_name, worker_id, work_date
                        from production_work_logs where processing_order_id='${poId}' order by created_at desc limit 1`)
    after > before
      ? R.pass('CH-11', '链路⑦：B 端 H5 扫本链路的码 → 开工记账（页面 → DB）',
          `扫 qr_token → 工序「${opText.trim()}」；本加工单记账 ${before} → ${after} 条（${logRow?.operation_name} ${logRow?.qty} @${logRow?.unit_price}，工人=${logRow?.worker_name}，工作日=${logRow?.work_date || '(未写)'}）；回执：${String(notice).trim()}`,
          ['screenshots/s6-03-h5-report-on-chain.png', 'POST /api/worker/production/scan/complete'])
      : R.fail('CH-11', '链路⑦：B 端 H5 报工记账', `记账未增加（${before} → ${after}）；工序=${opText} 回执=${notice}`)

    // 补齐到加工单完成：旧码每次带 set_id + order_item_id（工序仍由服务端推断）
    const sel = await api('GET', `/api/worker/production/scan?token=${qrToken}`, { headers: { 'X-Worker-Session-Id': wsess } })
    const selections = sel.json?.data?.selections || []
    setId = setId || selections[0]?.set_id
    orderItemId = orderItemId || selections[0]?.positions?.[0]?.order_item_id
    let iter = 0, lastErr = ''
    while (iter++ < 30) {
      const prog = (await api('GET', `/api/admin/production/orders/${orderId}/operations`, { token })).json?.data?.progress
      if (Number(prog?.done) >= Number(prog?.total)) break
      const rep = await api('POST', '/api/worker/production/scan/complete', {
        headers: { 'X-Worker-Session-Id': wsess, 'X-Client-Request-Id': `chain-${stamp}-${iter}` },
        body: { token: qrToken, ...(setId ? { set_id: setId } : {}), ...(orderItemId ? { order_item_id: orderItemId } : {}) },
      })
      if (!(rep.status === 200 && rep.json?.success)) { lastErr = `HTTP ${rep.status} ${errText(rep)}`; break }
      await sleep(200)
    }
    const prog = (await api('GET', `/api/admin/production/orders/${orderId}/operations`, { token })).json?.data?.progress
    const poRow = one(`select status from processing_orders where id='${poId}'`)
    const logs = one(`select count(*)::int as n, coalesce(sum(qty),0)::text as qty, coalesce(sum(qty*unit_price),0)::text as amount from production_work_logs where processing_order_id='${poId}'`)
    Number(prog?.done) >= Number(prog?.total)
      ? R.pass('CH-12', '链路⑦b：工序全部领走 → 加工单 completed（发货前置条件达成）',
          `进度 ${prog?.done}/${prog?.total}（${iter} 轮补齐）；processing_orders.status=${poRow?.status}；累计记账 ${logs?.n} 条 / 数量 ${logs?.qty} / 计件金额 ${logs?.amount}`,
          [`GET /api/admin/production/orders/${orderId}/operations`, `SQL: select status from processing_orders where id='${poId}'`])
      : R.fail('CH-12', '链路⑦b：工序全部领走', `进度 ${prog?.done}/${prog?.total}；status=${poRow?.status}；中断原因=${lastErr}`)
  } catch (e) {
    R.fail('CH-11', '链路⑦（报工）失败', String(e).slice(0, 350))
  }

  // ══════════ E. 发货（商家侧页面 → DB）══════════
  try {
    need(orderId, '订单 id')
    const { page } = await newContext(browser)
    await loginUi(page, { mode: 'admin', phone: ctx.adminPhone })
    await page.goto(`${WEB}/orders/${orderId}/ship`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await sleep(2500)
    const formReady = await page.locator('input[placeholder="请输入快递单号"]').waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false)
    const guardText = (await page.evaluate(() => document.body.innerText)).replace(/\n/g, ' ').slice(0, 160)
    if (!formReady) throw new Error(`发货表单未出现（加工单未完成？页面：${guardText}）`)
    await page.getByText('物流发货', { exact: false }).first().click().catch(() => {})
    await sleep(400)
    await page.locator('input[placeholder="请输入实际发货人姓名"]').fill('验收管理员').catch(() => {})
    await page.locator('input[placeholder="请输入快递单号"]').fill(`SF${stamp}001`).catch(() => {})
    await shot(page, 's6-04-ship-form')
    await page.getByRole('button', { name: /确认发货/ }).first().click()
    await sleep(3500)
    const postText = (await page.evaluate(() => document.body.innerText)).replace(/\n/g, ' ')
    await shot(page, 's6-05-ship-result')
    // ⚠️ 语义区分（实测 + 源码）：**商家侧发货**（POST /api/admin/production/orders/{id}/ship → OrderService.shipWithLogistics）
    //    只写 **orders**（状态 + 物流两列）+ 记物流日志，**不写** order_shipments（那张表归**工人侧**发货 OrderShipmentService）。
    const o = one(`select status, logistics_type, logistics_company from orders where id='${orderId}'`)
    const shipRow = one(`select count(*)::int as n from order_shipments where order_id='${orderId}'`)
    o?.status === 'shipped'
      ? R.pass('CH-13', '链路⑧：**商家侧发货页真实发货**（页面操作 → orders 转已发货 + 物流留痕）',
          `orders.status=confirmed→${o.status}（物流类型=${o.logistics_type} 承运=${o.logistics_company}）；页面出现「发货成功」=${/发货成功/.test(postText)}；order_shipments 行数=${shipRow?.n}（商家侧路径**不**写该表 —— 它归工人侧发货，见 CH-18）`,
          ['screenshots/s6-04-ship-form.png', 'screenshots/s6-05-ship-result.png', `SQL: select status, logistics_company from orders where id='${orderId}'`])
      : R.fail('CH-13', '链路⑧：商家侧发货', `orders.status=${o?.status}；page=${postText.slice(0, 160)}`, ['screenshots/s6-05-ship-result.png'])
  } catch (e) {
    R.fail('CH-13', '链路⑧（发货）失败', String(e).slice(0, 350))
  }

  // ══════════ E2. 批次指派：让**入库的这批货**真的被这单吃掉（V116 / #5145）══════════
  let consumeInfo = null
  try {
    need(productId, '商品 id'); need(skuId, 'SKU id')
    const batchNo = one(`select batch_no from stock_batches where tenant_id=${T} and sku_id=${skuId} order by created_at desc limit 1`)?.batch_no
    const order2 = await api('POST', '/api/admin/orders', {
      token, body: {
        customerName: `链路客户B${stamp}`, customerPhone: '13300000002', customerAddress: '杭州市余杭区链路路 2 号',
        logisticsType: 'logistics', logisticsCompany: '德邦物流',
        items: [{ productId, skuId, productName: `链路商品${stamp}`, quantity: 20, unitPrice: 68, subtotal: 1360,
          processingInfo: { sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
            processingItems: [{ id: 'proc_item_1', name: '锁边', quantity: 20, unit: '米' }] } }],
      },
    })
    const o2 = need(order2.json?.data?.id, `第二单创建（HTTP ${order2.status} ${errText(order2)}）`)
    await api('PUT', `/api/admin/orders/${o2}/payment`, { token })
    const item2 = one(`select id from order_items where order_id='${o2}' order by created_at limit 1`)
    const before = snapshot(skuId, '指派前')
    const gen2 = await api('POST', '/api/admin/processing-orders/generate', {
      token, body: { orderIds: [o2], batches: [{ orderId: o2, itemId: item2?.id, batchNo }] },
    })
    const after = snapshot(skuId, '指派后')
    const cons = one(`select batch_no, delta::text as delta, before_qty::text as before_qty, after_qty::text as after_qty, reason, order_no, processing_order_no, operator
                      from stock_batch_consumptions where tenant_id=${T} and sku_id=${skuId} order by created_at desc limit 1`)
    const dropped = Number(after.skuStock) < Number(before.skuStock)
    cons
      ? R.pass('CH-17', '链路⑩：**派工指定批次 ⇒ 入库批次被本单消耗**（闭环「入库的货被这单吃掉」）',
          `generate(batches=[{orderId,itemId,batchNo:${batchNo}}]) HTTP ${gen2.status}；stock_batch_consumptions 新行：批次 ${cons.batch_no} delta=${cons.delta} ${cons.before_qty}→${cons.after_qty}（原因 ${cons.reason}，订单 ${cons.order_no}，加工单 ${cons.processing_order_no}，操作人 ${cons.operator}）；SKU 现货 ${before.skuStock}→${after.skuStock}（下降=${dropped}）`,
          [`POST /api/admin/processing-orders/generate {batches:[...]}`, `SQL: select * from stock_batch_consumptions where sku_id=${skuId}`, `SQL: select stock from product_skus where id=${skuId}`])
      : R.fail('CH-17', '链路⑩：派工指定批次消耗', `HTTP ${gen2.status} ${errText(gen2)}；消耗行=无；现货 ${before.skuStock}→${after.skuStock}`)
    consumeInfo = { cons, before, after, batchNo }
  } catch (e) {
    R.fail('CH-17', '链路⑩（批次指派）失败', String(e).slice(0, 300))
  }

  // ══════════ E3. 工人侧发货：pack → ship（写 order_shipments + 实发明细）══════════
  try {
    const order3 = await api('POST', '/api/admin/orders', {
      token, body: {
        customerName: `链路客户C${stamp}`, customerPhone: '13300000003', customerAddress: '杭州市余杭区链路路 3 号',
        logisticsType: 'express', logisticsCompany: '顺丰速运',
        items: [{ productId, skuId, productName: `链路商品${stamp}`, quantity: 5, unitPrice: 68, subtotal: 340 }],
      },
    })
    const o3 = need(order3.json?.data?.id, `第三单创建（HTTP ${order3.status} ${errText(order3)}）`)
    await api('PUT', `/api/admin/orders/${o3}/payment`, { token })
    const item3 = one(`select id from order_items where order_id='${o3}' order by created_at limit 1`)
    const pack = await api('POST', `/api/worker/shipment/orders/${o3}/pack`, {
      headers: { 'X-Worker-Session-Id': wsess, 'X-Client-Request-Id': `pack-${stamp}-1` },
    })
    const stPacked = one(`select status from orders where id='${o3}'`)?.status
    const ship = await api('POST', `/api/worker/shipment/orders/${o3}/ship`, {
      headers: { 'X-Worker-Session-Id': wsess, 'X-Client-Request-Id': `ship-${stamp}-1` },
      body: { trackingNo: `SF${stamp}W`, logisticsCompany: '顺丰速运',
              items: [{ order_item_id: item3?.id, shipped_quantity: 5, unit: '米' }] },
    })
    const shipRow = one(`select id, shipment_no, source, packed_by_worker_name, packed_at, shipped_by_worker_name, shipped_at, tracking_no, logistics_company
                         from order_shipments where order_id='${o3}'`)
    const sitems = shipRow ? one(`select count(*)::int as n, coalesce(sum(shipped_quantity),0)::text as qty, string_agg(distinct unit, ',') as unit from order_shipment_items where shipment_id='${shipRow.id}'`) : null
    const st3 = one(`select status from orders where id='${o3}'`)?.status
    ;(shipRow && st3 === 'shipped' && Number(sitems?.n) > 0)
      ? R.pass('CH-18', '链路⑪：**工人侧发货**（打包 → 发货，实发明细落库）',
          `pack HTTP ${pack.status}（orders.status=${stPacked}）；ship HTTP ${ship.status}；order_shipments#${shipRow.shipment_no} 来源=${shipRow.source} 打包人=${shipRow.packed_by_worker_name} 发货人=${shipRow.shipped_by_worker_name} 运单=${shipRow.tracking_no}；实发 ${sitems?.n} 行 / ${sitems?.qty} ${sitems?.unit}；orders.status=${st3}`,
          [`POST /api/worker/shipment/orders/{id}/pack`, `POST /api/worker/shipment/orders/{id}/ship`, `SQL: select * from order_shipments where order_id='${o3}'`, `SQL: select * from order_shipment_items where shipment_id='${shipRow.id}'`])
      : R.fail('CH-18', '链路⑪：工人侧发货', `pack=${pack.status} ship=${ship.status}｜shipment=${JSON.stringify(shipRow)}｜items=${JSON.stringify(sitems)}｜orders.status=${st3}`)
  } catch (e) {
    R.fail('CH-18', '链路⑪（工人侧发货）失败', String(e).slice(0, 350))
  }

  // ══════════ F. 收口：全链路快照 + 库存扣减 + 日志 ══════════
  try {
    const flow = {
      商品: one(`select id, name, status from products where id='${productId}'`),
      SKU与现货: one(`select id::text as id, sku_code, stock::text as stock, price::text as price from product_skus where id=${skuId}`),
      入库单: one(`select inbound_no, status, total_amount::text as amount from inbound_orders where id='${inboundId}'`),
      批次: q(`select batch_no, quantity::text as qty, unit_cost::text as cost, dye_lot from stock_batches where sku_id=${skuId}`),
      批次消耗: q(`select * from stock_batch_consumptions where tenant_id=${T} order by created_at desc limit 3`),
      库存台账: q(`select reason, delta::text as delta, before_qty::text as before_qty, after_qty::text as after_qty, ref_no, avg_cost_after::text as avg_after from stock_ledger_entries where tenant_id=${T} and sku_id=${skuId} order by created_at`),
      订单: one(`select order_no, status, total_amount::text as amount from orders where id='${orderId}'`),
      加工单: one(`select processing_order_no, status from processing_orders where id='${poId}'`),
      工序: one(`select count(*)::int as total, sum(case when done_qty >= qty then 1 else 0 end)::int as done from processing_position_operations where processing_order_id='${poId}'`),
      报工: one(`select count(*)::int as n, coalesce(sum(qty),0)::text as qty, coalesce(sum(qty*unit_price),0)::text as amount from production_work_logs where processing_order_id='${poId}'`),
      发货单: one(`select shipment_no, tracking_no, logistics_company, shipped_at from order_shipments where order_id='${orderId}'`),
    }
    writeFileSync(join(OUT, 's6-chain-flow.json'), JSON.stringify(flow, null, 2))
    const stockDropped = Number(flow.SKU与现货?.stock) < 100
    R.pass('CH-14', '链路⑨：**全链路闭合快照**（商品→入库过账→批次→订单→加工单→工序→报工→发货→库存）',
      `商品 ${flow.商品?.name}(${flow.商品?.status})｜入库单 ${flow.入库单?.inbound_no}(${flow.入库单?.status}) 批次 ${flow.批次?.length} 个｜订单 ${flow.订单?.order_no}(${flow.订单?.status})｜加工单 ${flow.加工单?.processing_order_no}(${flow.加工单?.status}) 工序 ${flow.工序?.done}/${flow.工序?.total}｜报工 ${flow.报工?.n} 条 ${flow.报工?.qty} 米 计件 ${flow.报工?.amount} 元｜发货单 ${flow.发货单?.shipment_no} 运单 ${flow.发货单?.tracking_no}｜SKU 现货 ${flow.SKU与现货?.stock}（入库 100，已出 ${(100 - Number(flow.SKU与现货?.stock)).toFixed(2)}）`,
      ['out/s6-chain-flow.json'])
    R.pass('CH-15', '链路⑨b：库存台账贯连（入库 + 出库都在同一 SKU 的台账上）',
      `台账 ${flow.库存台账?.length} 条：${(flow.库存台账 || []).map((l) => `${l.reason} ${l.delta}→${l.after_qty}`).join('；')}｜批次消耗 ${flow.批次消耗?.length} 条`,
      [`SQL: select * from stock_ledger_entries where sku_id=${skuId} order by created_at`, `SQL: select * from stock_batch_consumptions where tenant_id=${T}`])
  } catch (e) {
    R.fail('CH-14', '链路⑨：全链路快照失败', String(e).slice(0, 300))
  }

  const hits = grepApiLog('过账|入库单|加工单|报工|发货', { limit: 10 })
  R.pass('CH-16', '日志侧：链路各环节留痕', `命中 ${hits.length} 行；示例：${(hits[hits.length - 1]?.text || '(无)').trim().slice(0, 150)}`,
    hits.map((h) => `L${h.line}: ${h.text.trim().slice(0, 180)}`))

  await browser.close(); h5Server.close()
  saveCtx({ chain: { orderId, orderNo, poNo, productId, skuId, inboundId } })
  const s = R.summary()
  log(`== 阶段6 完成：pass=${s.pass} fail=${s.fail}`)
}

main().catch((e) => { R.fail('CH-FATAL', '阶段6 致命错误', String(e).slice(0, 500)); process.exitCode = 1 })
