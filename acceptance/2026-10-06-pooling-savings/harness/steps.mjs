// 2026-10-06 智能派单省料验证 · 共享步骤库
//
// 只做四件事，全部走**真实 admin-api + 真库**：
//   ① 造探针对象（商品 / SKU / 入库批次）
//   ② 造订单（可并排的窄窗几何）并确认收款
//   ③ 读待派池 / 成批预览 / 派单
//   ④ 读回批次消耗台账（省料读数）
import { api, psql, psqlWrite, PROBE, TENANT_ID } from './lib.mjs'

export const T = TENANT_ID

export async function login() {
  const { loginApi } = await import('./lib.mjs')
  const { token } = await loginApi(process.env.ADMIN_PHONE || '13800138000')
  return token
}

const err = (r) => (r?.json?.error?.message || r?.json?.message || r?.text || '').slice(0, 300)

/** 探针商品 + SKU（门幅 2.8）+ 入库批次（过账），返回 {productId, skuId, skuCode, batchNo} */
export async function setupProbe(token, { stamp, meters = 4000, unitCost = 40 } = {}) {
  const skuCode = `${PROBE}-${stamp}`
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE}类${stamp}`, sortOrder: 1 } })
  const categoryId = cat.json?.data?.id
  if (!categoryId) throw new Error(`分类创建失败 HTTP ${cat.status} ${err(cat)}`)
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PROBE}布${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 68, status: 'on_sale',
      categoryId,
      colors: [{ colorName: '验收白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '验收白', doorWidth: '2.8m', price: 68, stock: 0, skuCode }],
    },
  })
  const productId = prod.json?.data?.id
  if (!productId) throw new Error(`商品创建失败 HTTP ${prod.status} ${err(prod)}`)
  const skuRow = psql(`select id::text as id from product_skus where tenant_id=${T} and sku_code='${skuCode}'`)[0]
  if (!skuRow) throw new Error(`SKU 未落库：${skuCode}`)

  const inb = await api('POST', '/api/admin/inbound-orders', {
    token, body: {
      supplier: `${PROBE}供应商${stamp}`, warehouse: '主仓',
      inboundDate: new Date().toISOString().slice(0, 10), remark: `${PROBE}入库${stamp}`,
      items: [{ productId, skuId: skuRow.id, quantity: meters, unitCost, dyeLot: `DYE-${stamp}` }],
    },
  })
  const inboundId = inb.json?.data?.id
  if (!inboundId) throw new Error(`入库单创建失败 HTTP ${inb.status} ${err(inb)}`)
  const post = await api('PATCH', `/api/admin/inbound-orders/${inboundId}`, { token, body: { action: 'post' } })
  if (!(post.status === 200 && post.json?.success)) throw new Error(`入库过账失败 HTTP ${post.status} ${err(post)}`)
  const batch = psql(`select batch_no, quantity::text as qty from stock_batches where tenant_id=${T} and sku_id=${skuRow.id} order by id desc limit 1`)[0]

  return { productId, skuId: skuRow.id, skuCode, inboundId, batchNo: batch?.batch_no, batchQty: batch?.qty }
}

/**
 * 造 1 张订单（可并排窄窗几何）并确认收款。
 *
 * 几何（#5142 类注释的「定宽买高 P=1 窄窗互补」受益场景）：
 *   窗宽 0.7 × 褶倍 2 = 1.4 米 ≤ 门幅 2.8 ⇒ 1 幅；窗高 1.1 + 卷边 0.3 = 1.4 米
 *   ⇒ 每行占门幅 1.4 米、沿卷长 1.4 米、公式米数 1.4 米
 *   ⇒ 两行（两扇窄窗）并排 = 1 行 / 领 1.4 米，逐单分开 = 2 行 / 2.8 米
 */
export async function createOrder(token, { productId, skuId, skuCode, seq, idx = 0, qty = 1.4, width = 0.7, height = 1.1, panels = 1, urgent = false, requiredDeliveryDate = null }) {
  const body = {
    customerName: `${PROBE}客${seq}`, customerPhone: `133${String(10000000 + Number(idx)).slice(-8)}`,
    customerAddress: `${PROBE}地址 ${seq} 号`, logisticsType: 'express', logisticsCompany: '顺丰速运',
    isUrgent: urgent,
    ...(requiredDeliveryDate ? { requiredDeliveryDate } : {}),
    items: [{
      productId: String(productId), skuId: String(skuId), productName: `${PROBE}布${seq}`,
      quantity: qty, unitPrice: 68, subtotal: Number((qty * 68).toFixed(2)),
      width, height,
      processingInfo: {
        sku: skuCode, skuCode, colorName: '验收白', doorWidth: '2.8', unit: '米',
        sellingMethod: 'bulk_cut', curtainType: '布帘', craft: '韩褶',
        cuttingMode: '定宽买高', panels, height, fabric_meters: qty, fullness: 2,
        processingItems: [{ id: 'pi1', name: '锁边', quantity: qty, unit: '米' }],
      },
    }],
  }
  const r = await api('POST', '/api/admin/orders', { token, body })
  const id = r.json?.data?.id
  if (!id) throw new Error(`建单失败 HTTP ${r.status} ${err(r)}`)
  const pay = await api('PUT', `/api/admin/orders/${id}/payment`, { token })
  if (!(pay.status === 200 && pay.json?.success)) throw new Error(`确认收款失败 HTTP ${pay.status} ${err(pay)}`)
  const row = psql(`select o.id::text as id, o.order_no, o.status, oi.id::text as item_id
                    from orders o join order_items oi on oi.order_id=o.id
                    where o.id='${id}' and o.tenant_id=${T}`)[0]
  return { orderId: String(id), orderNo: row?.order_no, status: row?.status, itemId: row?.item_id }
}

/** 指派行（orderId + itemId，batchNo 留空 ⇒ 由 assignmentRule 自动补位） */
export const assign = (orders, rule = 'fifo') => ({
  batches: orders.map((o) => ({ orderId: o.orderId, itemId: o.itemId })),
  assignmentRule: rule,
})

/** 批次消耗台账读数（逐行带两个米数口径） */
export function consumptions(where = 'true') {
  return psql(`select c.id, c.order_item_id, c.batch_no, c.delta::text as delta,
                      c.formula_meters::text as formula, c.planned_meters::text as planned,
                      (c.formula_meters - c.planned_meters)::text as saved, c.unit_cost::text as unit_cost
               from stock_batch_consumptions c where c.tenant_id=${T} and ${where} order by c.id`)
}

export function ordersByNoPrefix(prefix) {
  return psql(`select o.id::text as order_id, o.order_no, o.status, oi.id::text as item_id
               from orders o join order_items oi on oi.order_id=o.id
               where o.tenant_id=${T} and o.customer_name like '${prefix}%' order by o.id`)
}

/** 清理：删掉本轮探针造出来的全部对象（按前缀）。顺序即安全顺序（先子后父，FK 实测）。 */
export function cleanup(prefix) {
  const ORD = `select id from orders where tenant_id=${T} and customer_name like '${prefix}%'`;
  const ITEM = `select oi.id from order_items oi join orders o on o.id=oi.order_id
                where o.tenant_id=${T} and o.customer_name like '${prefix}%'`;
  const PO = `select po.id from processing_orders po join orders o on o.id=po.order_id
              where o.tenant_id=${T} and o.customer_name like '${prefix}%'`;
  const SKU = `select id from product_skus where tenant_id=${T} and sku_code like '${prefix}%'`;
  const BATCH = `select id from stock_batches where tenant_id=${T} and sku_code like '${prefix}%'`;
  const INB = `select id from inbound_orders where tenant_id=${T} and remark like '${prefix}%'`;
  return psqlWrite(`begin;
    delete from worker_report_audits where processing_order_id in (${PO});
    delete from production_work_logs where processing_order_id in (${PO});
    delete from production_instance_repricing_logs where processing_order_id in (${PO});
    delete from processing_set_part_tokens where processing_order_id in (${PO});
    delete from processing_order_sets where processing_order_id in (${PO});
    delete from processing_position_operations where processing_order_id in (${PO});
    delete from stock_batch_consumptions where order_item_id in (select id::text from order_items where id in (${ITEM}));
    delete from fabric_remnants where source_batch_id in (${BATCH});
    delete from processing_orders where order_id in (${ORD});
    delete from order_logistics where order_id in (${ORD});
    delete from stock_ledger_entries where ref_no in (select order_no from orders where id in (${ORD}));
    delete from order_items where order_id in (${ORD});
    delete from orders where id in (${ORD});
    delete from stock_ledger_entries where sku_id in (${SKU});
    delete from inbound_order_items where inbound_order_id in (${INB});
    delete from stock_batches where id in (${BATCH});
    delete from inbound_orders where id in (${INB});
    delete from product_skus where id in (${SKU});
    delete from products where tenant_id=${T} and name like '${prefix}%';
    delete from categories where tenant_id=${T} and name like '${prefix}%';
    commit;`)
}

/**
 * 「配置的工艺路线」期望工序序列（**结构判据**，供 300 单工序比对用）。
 *
 * 规则（与本仓 `ProductionRouteRule` 的语义逐条对应）：
 *   · 起点 = 租户**默认路线模板**的 `mainline`（逻辑工序名）；
 *   · 命中规则（按 `priority, id` 升序）：`craft` ⇒ `trigger_value == 本单 craft`；
 *     `option` ⇒ ∈ `specialOptions`；`processing_item` ⇒ ∈ 加工项名；`position` 列非空 ⇒ 按部位限定；
 *   · `action='insert'` ⇒ 插到锚点 `after_operation` 的**后面**（锚点找不到 ⇒ 追加末尾）；目标已存在 ⇒ 取代（先删后插）；
 *   · `action='remove'` ⇒ 删除该逻辑工序。
 * ⚠️ 逐字口径的权威判据不在这里，而在 `service/ProductionRouteParityTest` +
 *    `RoutingModelFixture::DEPOSITIONED_ROUTINGS`（9 组合冻结快照逐字对比）。本函数只做**结构**比对。
 */
export function expectedRoute(mainline, rules, { craft, specialOptions = [], processingItems = [], position = null }) {
  let seq = [...mainline]
  const matched = rules.filter((r) => {
    if (r.trigger_kind === 'craft') return r.trigger_value === craft
    if (r.trigger_kind === 'option') return specialOptions.includes(r.trigger_value)
    if (r.trigger_kind === 'processing_item') return processingItems.includes(r.trigger_value)
    if (r.trigger_kind === 'position') return r.position === position
    return false
  }).filter((r) => !r.position || r.position === position)
  for (const r of matched) {
    if (r.action === 'remove') { seq = seq.filter((x) => x !== r.operation); continue }
    if (r.action !== 'insert') continue
    const at = r.after_operation ? seq.indexOf(r.after_operation) : -1
    seq = seq.filter((x) => x !== r.operation)
    const pos = r.after_operation ? seq.indexOf(r.after_operation) : -1
    if (r.after_operation && pos >= 0) seq.splice(pos + 1, 0, r.operation)
    else seq.push(r.operation)
    void at
  }
  return seq
}

/** 变体名 → 逻辑工序名（本租户工序库实测形态：`精裁-布` / `布三边` / `布帘车被`） */
export const logicalOperation = (n) => n.replace(/^(布帘|布|纱)/, '').replace(/-(布|纱)$/, '')
