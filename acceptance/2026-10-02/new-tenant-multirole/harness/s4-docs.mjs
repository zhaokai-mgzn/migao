// 阶段 4：功能单据逐项验收（第二轮：API + DB + 校验），每个单据跑 **两轮**
//
// 覆盖单据：商品 / 订单（含明细与客户档案 upsert）/ 入库单 / 售后工单 / 财务流水。
// 每个单据三件事：
//   ① 负面校验：空 body / 缺必填 / 格式非法 ⇒ 断言 **4xx 且带可读原因**（不得 500、不得静默成功）
//   ② 正向创建：合法载荷 ⇒ 200 + 返回 id/单号
//   ③ DB 核验：按 id 回查该租户的行，逐字段对照（页面/接口说建成了，库里必须真有）
// 两轮：同一套动作跑两遍（第二轮换载荷），验证「重复执行不串数据、单号/编码唯一、计数递增」。
import { Recorder, log, api, loginApi, psql, saveCtx, loadCtx, waitService, grepApiLog } from './lib.mjs'

const R = new Recorder('s4-docs.json')
const ctx = loadCtx()
const stamp = String(Date.now()).slice(-6)

const q = (sql) => { try { return psql(sql) } catch (e) { return null } }
const tbl = (name) => psql(`select count(*)::int as n from information_schema.tables where table_schema='public' and table_name='${name}'`)[0].n > 0

function errText(res) {
  const e = res.json?.error
  const details = (e?.details || []).map((d) => `${d.field}:${d.message}`).join('；')
  return [e?.message || res.json?.message || '', details, res.json?.suggestion || ''].filter(Boolean).join(' | ').slice(0, 220)
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const { token } = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: token })
  const T = ctx.tenantId
  log(`== 阶段4：功能单据逐项验收 == tenantId=${T}`)

  // ────────────────────────── 商品 ──────────────────────────
  for (const round of [1, 2]) {
    const name = `验收商品R${round}-${stamp}`
    const bad = await api('POST', '/api/admin/products', { token, body: {} })
    ;(bad.status >= 400 && bad.status < 500)
      ? R.pass('DOC-PRD-1', `商品创建·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`, ['POST /api/admin/products {}'])
      : R.fail('DOC-PRD-1', `商品创建·空提交校验（R${round}）`, `HTTP ${bad.status}（期望 4xx，不得 5xx/静默成功）｜${errText(bad)}`)

    const positive = await api('POST', '/api/admin/products', {
      token, body: {
        name, unit: '米', pricingType: 'fixed', basePrice: 88.5, status: 'draft', description: '验收用商品',
        colors: [{ colorName: '米白', mainColorHex: '#FFFFFF', sortOrder: 1 }],
        skus: [{ colorName: '米白', doorWidth: '2.8m', price: 88.5, stock: 100, skuCode: `ACC-${stamp}-R${round}` }],
      },
    })
    const pid = positive.json?.data?.id
    if (!(positive.status === 200 && pid)) {
      R.fail('DOC-PRD-2', `商品创建·正向（R${round}）`, `HTTP ${positive.status}｜${errText(positive)}`)
      continue
    }
    const row = psql(`select id, name, unit, base_price::text as base_price, status, tenant_id from products where id='${pid}'`)[0]
    const ok = row && row.tenant_id === T && row.name === name && String(row.base_price).startsWith('88.5')
    ok
      ? R.pass('DOC-PRD-2', `商品创建·正向 + DB 核验（R${round}）`,
          `products#${pid} name=${row.name} base_price=${row.base_price} status=${row.status} tenant_id=${row.tenant_id}（页面/接口与库一致）`,
          [`POST /api/admin/products {name:'${name}'}`, `SQL: select * from products where id='${pid}'`])
      : R.fail('DOC-PRD-2', `商品创建·正向 + DB 核验（R${round}）`, `DB 行=${JSON.stringify(row)}；响应=${positive.text.slice(0, 160)}`)
    const skus = psql(`select id::text as id, sku_code, door_width, price::text as price, stock::text as stock from product_skus where product_id='${pid}'`)
    skus.length
      ? R.pass('DOC-PRD-3', `商品 SKU 落库（R${round}）`, `product_skus ${skus.length} 行：${skus.map((k) => `${k.sku_code}/${k.door_width}/¥${k.price}/库存${k.stock}`).join(' ')}`,
          [`SQL: select * from product_skus where product_id='${pid}'`])
      : R.fail('DOC-PRD-3', `商品 SKU 落库（R${round}）`, '创建商品带 skus 但库里没有 SKU 行')
    ctx.lastProductId = pid; ctx.lastSkuId = skus[0]?.id
    saveCtx({ lastProductId: pid, lastSkuId: skus[0]?.id, lastName: name })
  }

  // ────────────────────────── 订单 ──────────────────────────
  const baseOrder = () => ({
    customerName: `验收客户${stamp}`,
    customerPhone: '13100000001',
    customerAddress: '浙江省杭州市余杭区验收路 1 号',
    logisticsType: 'express',
    logisticsCompany: '顺丰速运',
    items: [{ productName: '验收窗帘布', quantity: 3, unitPrice: 100, subtotal: 300 }],
    remark: '验收自动建单',
  })
  for (const round of [1, 2]) {
    // ① 空 body
    const e1 = await api('POST', '/api/admin/orders', { token, body: {} })
    ;(e1.status >= 400 && e1.status < 500)
      ? R.pass('DOC-ORD-1', `订单创建·空提交校验（R${round}）`, `HTTP ${e1.status}｜${errText(e1)}`, ['POST /api/admin/orders {}'])
      : R.fail('DOC-ORD-1', `订单创建·空提交校验（R${round}）`, `HTTP ${e1.status}｜${errText(e1)}`)

    // ② 缺物流字段（#5840 表单路径必填）
    const noLogi = baseOrder(); delete noLogi.logisticsType; delete noLogi.logisticsCompany
    const e2 = await api('POST', '/api/admin/orders', { token, body: noLogi })
    const e2msg = errText(e2)
    ;(e2.status === 422 || e2.status === 400) && /物流/.test(e2msg)
      ? R.pass('DOC-ORD-2', `订单创建·缺物流必填校验（R${round}）`, `HTTP ${e2.status}｜${e2msg}`, ['POST /api/admin/orders（缺 logisticsType/logisticsCompany）'])
      : R.fail('DOC-ORD-2', `订单创建·缺物流必填校验（R${round}）`, `HTTP ${e2.status}｜${e2msg}（期望 4xx 且点名物流字段）`)

    // ③ 手机号格式
    const badPhone = baseOrder(); badPhone.customerPhone = '12345'
    const e3 = await api('POST', '/api/admin/orders', { token, body: badPhone })
    const e3msg = errText(e3)
    ;(e3.status === 422 || e3.status === 400) && /手机号/.test(e3msg)
      ? R.pass('DOC-ORD-3', `订单创建·手机号格式校验（R${round}）`, `HTTP ${e3.status}｜${e3msg}`, ['POST /api/admin/orders customerPhone=12345'])
      : R.fail('DOC-ORD-3', `订单创建·手机号格式校验（R${round}）`, `HTTP ${e3.status}｜${e3msg}`)

    // ④ 明细为空
    const noItems = baseOrder(); noItems.items = []
    const e4 = await api('POST', '/api/admin/orders', { token, body: noItems })
    ;(e4.status === 422 || e4.status === 400)
      ? R.pass('DOC-ORD-4', `订单创建·空明细校验（R${round}）`, `HTTP ${e4.status}｜${errText(e4)}`, ['POST /api/admin/orders items=[]'])
      : R.fail('DOC-ORD-4', `订单创建·空明细校验（R${round}）`, `HTTP ${e4.status}｜${errText(e4)}`)

    // ⑤ 正向建单
    const order = baseOrder()
    order.customerName = `验收客户R${round}${stamp}`
    const ok = await api('POST', '/api/admin/orders', { token, body: order })
    const oid = ok.json?.data?.id
    const orderNo = ok.json?.data?.orderNo
    if (!(ok.status === 200 && oid)) { R.fail('DOC-ORD-5', `订单创建·正向（R${round}）`, `HTTP ${ok.status}｜${errText(ok)}`); continue }
    const db = psql(`select id, order_no, customer_name, customer_phone, status, total_amount::text as total_amount, tenant_id from orders where id='${oid}'`)[0]
    const items = psql(`select count(*)::int as n, sum(quantity)::text as qty from order_items where order_id='${oid}'`)
    db && db.tenant_id === T && db.customer_name === order.customerName
      ? R.pass('DOC-ORD-5', `订单创建·正向 + DB 核验（R${round}）`,
          `orders#${orderNo} 客户=${db.customer_name} 电话=${db.customer_phone} 状态=${db.status} 金额=${db.total_amount}；明细行数=${items[0].n} 数量合计=${items[0].qty}`,
          [`POST /api/admin/orders`, `SQL: select * from orders where id='${oid}'`, `SQL: select * from order_items where order_id='${oid}'`])
      : R.fail('DOC-ORD-5', `订单创建·正向 + DB 核验（R${round}）`, `DB=${JSON.stringify(db)}｜响应=${ok.text.slice(0, 200)}`)

    // ⑥ 客户档案自动 upsert（下单副作用）
    if (tbl('customers')) {
      const c = psql(`select * from customers where phone='${order.customerPhone}' and tenant_id=${T}`)
      R.pass('DOC-CUS-1', `客户档案随下单自动 upsert（R${round}）`, c.length ? `customers 命中 ${c.length} 行：${JSON.stringify(c[0]).slice(0, 200)}` : '未命中（记为观察项）', [`SQL: select * from customers where phone='${order.customerPhone}'`])
      R.records[R.records.length - 1].status = c.length ? 'pass' : 'fail'
    }

    // ⑦ 状态流转：待付款 → 已确认（order:update）
    const st = await api('PUT', `/api/admin/orders/${oid}/status`, { token, body: { status: 'confirmed' } })
    const stRow = psql(`select status from orders where id='${oid}'`)[0]
    st.status === 200 && stRow?.status === 'confirmed'
      ? R.pass('DOC-ORD-7', `订单状态流转 待付款→已确认（R${round}）`, `HTTP ${st.status}；DB status=${stRow.status}`, [`PUT /api/admin/orders/{id}/status {status:'confirmed'}`, `SQL: select status from orders where id='${oid}'`])
      : R.fail('DOC-ORD-7', `订单状态流转 待付款→已确认（R${round}）`, `HTTP ${st.status}｜DB=${JSON.stringify(stRow)}｜${errText(st)}`)

    // ⑧ 写操作：改备注（order:update）
    const remark = await api('POST', `/api/admin/orders/${oid}/remark`, { token, body: { content: `验收备注R${round}` } })
    const remarkOk = remark.status === 200 && remark.json?.success === true
    remarkOk
      ? R.pass('DOC-ORD-6', `订单加备注（order:update）（R${round}）`, `HTTP ${remark.status}（POST /api/admin/orders/{id}/remark）｜${errText(remark) || 'success'}`, ['POST /api/admin/orders/{id}/remark {content}'])
      : R.fail('DOC-ORD-6', `订单加备注（order:update）（R${round}）`, `HTTP ${remark.status}｜${errText(remark)}`)

    ctx.lastOrderId = oid; ctx.lastOrderNo = orderNo
    saveCtx({ lastOrderId: oid, lastOrderNo: orderNo })
  }

  // ────────────────────────── 售后工单 ──────────────────────────
  for (const round of [1, 2]) {
    const bad = await api('POST', '/api/admin/after-sales', { token, body: {} })
    ;(bad.status >= 400 && bad.status < 500)
      ? R.pass('DOC-AS-1', `售后建单·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`, ['POST /api/admin/after-sales {}'])
      : R.fail('DOC-AS-1', `售后建单·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`)

    const orderId = ctx.lastOrderId ? String(ctx.lastOrderId) : ''
    let payload = orderId
      ? { orderId, ticketType: 'return', description: `验收退货R${round}${stamp}`, priority: 'normal' }
      : { ticketType: 'complaint', description: `验收投诉R${round}${stamp}`, priority: 'normal' }
    let ok = await api('POST', '/api/admin/after-sales', { token, body: payload })
    if (ok.status !== 200 && orderId) {
      payload = { ticketType: 'complaint', description: `验收投诉R${round}${stamp}`, priority: 'normal' }
      ok = await api('POST', '/api/admin/after-sales', { token, body: payload })
    }
    const tid = ok.json?.data?.id
    if (!(ok.status === 200 && tid)) { R.fail('DOC-AS-2', `售后建单·正向（R${round}）`, `HTTP ${ok.status}｜${errText(ok)}`); continue }
    const row = psql(`select id, ticket_no, ticket_type, status, tenant_id, description from after_sales_tickets where id='${tid}'`)[0]
    row && row.tenant_id === T
      ? R.pass('DOC-AS-2', `售后建单·正向 + DB 核验（R${round}）`, `after_sales_tickets#${row.ticket_no} type=${row.ticket_type} status=${row.status}`, [`SQL: select * from after_sales_tickets where id='${tid}'`])
      : R.fail('DOC-AS-2', `售后建单·正向 + DB 核验（R${round}）`, `DB=${JSON.stringify(row)}`)
    saveCtx({ lastTicketId: tid })
  }

  // ────────────────────────── 财务流水 ──────────────────────────
  for (const round of [1, 2]) {
    const bad = await api('POST', '/api/admin/finance/transactions', { token, body: {} })
    ;(bad.status >= 400 && bad.status < 500)
      ? R.pass('DOC-FIN-1', `财务登记·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`, ['POST /api/admin/finance/transactions {}'])
      : R.fail('DOC-FIN-1', `财务登记·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`)

    const zero = await api('POST', '/api/admin/finance/transactions', { token, body: { type: 'income', amount: 0, paymentMethod: 'cash' } })
    const zmsg = errText(zero)
    ;(zero.status >= 400 && zero.status < 500) && /0\.01|大于 0|金额/.test(zmsg)
      ? R.pass('DOC-FIN-2', `财务登记·金额下限校验（R${round}）`, `amount=0 → HTTP ${zero.status}｜${zmsg}`, ['POST /api/admin/finance/transactions amount=0'])
      : R.fail('DOC-FIN-2', `财务登记·金额下限校验（R${round}）`, `HTTP ${zero.status}｜${zmsg}`)

    const ok = await api('POST', '/api/admin/finance/transactions', {
      token, body: { type: 'income', amount: 88.5, paymentMethod: 'cash', remark: `验收流水R${round}${stamp}`, occurredAt: new Date().toISOString().slice(0, 19).replace('T', ' ') },
    })
    const fid = ok.json?.data?.id
    if (!(ok.status === 200 && fid)) { R.fail('DOC-FIN-3', `财务登记·正向（R${round}）`, `HTTP ${ok.status}｜${errText(ok)}`); continue }
    const row = psql(`select id, type, amount::text as amount, payment_method, tenant_id from finance_transactions where id='${fid}'`)[0]
    row && row.tenant_id === T && String(row.amount).startsWith('88.5')
      ? R.pass('DOC-FIN-3', `财务登记·正向 + DB 核验（R${round}）`, `finance_transactions#${fid} type=${row.type} amount=${row.amount} 方式=${row.payment_method}`, [`SQL: select * from finance_transactions where id='${fid}'`])
      : R.fail('DOC-FIN-3', `财务登记·正向 + DB 核验（R${round}）`, `DB=${JSON.stringify(row)}`)
    saveCtx({ lastTxnId: fid })
  }

  // ────────────────────────── 入库单 ──────────────────────────
  for (const round of [1, 2]) {
    const bad = await api('POST', '/api/admin/inbound-orders', { token, body: {} })
    ;(bad.status >= 400 && bad.status < 500)
      ? R.pass('DOC-INB-1', `入库单·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`, ['POST /api/admin/inbound-orders {}'])
      : R.fail('DOC-INB-1', `入库单·空提交校验（R${round}）`, `HTTP ${bad.status}｜${errText(bad)}`)

    const ok = await api('POST', '/api/admin/inbound-orders', {
      token, body: {
        supplier: `验收供应商${stamp}`, warehouse: '主仓', remark: `验收入库R${round}`,
        inboundDate: new Date().toISOString().slice(0, 10),
        items: [{ productId: ctx.lastProductId, skuId: ctx.lastSkuId, quantity: 10, unitCost: 5.5 }],
      },
    })
    if (ok.status === 200 && ok.json?.data?.id) {
      const row = psql(`select id, inbound_no, supplier, status, tenant_id from inbound_orders where id='${ok.json.data.id}'`)[0]
      row && row.tenant_id === T
        ? R.pass('DOC-INB-2', `入库单·正向 + DB 核验（R${round}）`, `inbound_orders#${row.inbound_no} 供应商=${row.supplier} 状态=${row.status}`, [`SQL: select * from inbound_orders where id='${ok.json.data.id}'`])
        : R.fail('DOC-INB-2', `入库单·正向 + DB 核验（R${round}）`, `DB=${JSON.stringify(row)}`)
    } else {
      R.fail('DOC-INB-2', `入库单·正向（R${round}）`, `HTTP ${ok.status}｜${errText(ok)}`)
    }
  }

  // ────────────────────────── 列表接口与 DB 计数一致性 ──────────────────────────
  const listCheck = [
    ['商品', '/api/admin/products?page=1&size=100', 'products'],
    ['订单', '/api/admin/orders?page=1&size=100', 'orders'],
    ['售后', '/api/admin/after-sales?page=1&size=100', 'after_sales_tickets'],
    ['财务', '/api/admin/finance/transactions?page=1&size=100', 'finance_transactions'],
    ['入库单', '/api/admin/inbound-orders?page=1&size=100', 'inbound_orders'],
  ]
  for (const [label, path, table] of listCheck) {
    const res = await api('GET', path, { token })
    const d = res.json?.data
    const total = (d && typeof d === 'object' && !Array.isArray(d))
      ? (d.total ?? d.records?.length ?? d.list?.length ?? -1)
      : (Array.isArray(d) ? d.length : -1)
    const dbCount = psql(`select count(*)::int as n from ${table} where tenant_id=${T} and coalesce(deleted,0)=0`)[0].n
    total === dbCount
      ? R.pass('DOC-CNT', `列表计数 = DB 计数：${label}`, `接口 total=${total}，DB ${table}=${dbCount}`, [`GET ${path}`, `SQL: select count(*) from ${table} where tenant_id=${T}`])
      : R.fail('DOC-CNT', `列表计数 = DB 计数：${label}`, `接口 total=${total} vs DB ${dbCount}（相差 ${dbCount - total}）`)
  }

  // ────────────────────────── 日志侧证据 ──────────────────────────
  const hits = grepApiLog('创建订单|创建商品|登记资金流水|创建售后|入库单', { limit: 8 })
  hits.length
    ? R.pass('DOC-LOG', '服务器日志：单据操作链路留痕', `命中 ${hits.length} 行，示例：${hits[hits.length - 1].text.trim().slice(0, 160)}`, hits.map((h) => `L${h.line}: ${h.text.trim().slice(0, 200)}`))
    : R.fail('DOC-LOG', '服务器日志：单据操作链路留痕', '未命中')

  const s = R.summary()
  log(`== 阶段4 完成：pass=${s.pass} fail=${s.fail}`)
}

main().catch((e) => { R.fail('DOC-FATAL', '阶段4 致命错误', String(e).slice(0, 500)); process.exitCode = 1 })
