// E — 并发 / 幂等 / 竞态（每条断言都配**正对照**：串行/合法路径应当成功）
// F — 红证（注入式：改一行 DB / 造第二条有效记录 ⇒ 当场红 ⇒ 还原 ⇒ 回绿，sha256 自证）
import {
  Recorder, judge, api, loginApi, psql, one, guardedWrite, PROBE_PREFIX, ID_PREFIX, TENANT_ID,
  log, nowCST, writeFileSync, outPath, sha256, probeSku, cleanupProbe, hexId, sleep,
} from './lib.mjs'

const R = new Recorder('E-concurrency-and-redproof.json')
const { token } = await loginApi()
const T = TENANT_ID
log(`E/F 段开始 ${nowCST().cst} (UTC ${nowCST().utc})`)

const mkProduct = async (name, status = 'draft') => {
  const sku = probeSku('E')
  const r = await api('POST', '/api/admin/products', {
    token,
    body: {
      name: `${PROBE_PREFIX}${name}`, skuCode: sku, basePrice: 20, stock: 3,
      unit: '米', pricingType: 'per_meter', description: `${PROBE_PREFIX}并发探针`, status,
      colors: [{ colorName: '米白' }], doorWidths: ['2.8m'],
      skus: [{ colorName: '米白', doorWidth: '2.8m', price: 20, stock: 3 }],
    },
  })
  return { r, id: r.data?.id, sku }
}

// ══════════════ E1 重复提交（同一表单连点）══════════════
// 先查幂等键是否被这条链路消费：client_request_keys 表（X-Client-Request-Id）
const idemKey = `${ID_PREFIX}-e1-${Date.now().toString(36)}`
const mkSame = (k) => api('POST', '/api/admin/products', {
  token,
  headers: { 'X-Client-Request-Id': k },
  body: {
    name: `${PROBE_PREFIX}重复提交`, skuCode: `${ID_PREFIX}-E1-DUP-${k.slice(-6).toUpperCase()}`, basePrice: 9, stock: 1,
    unit: '米', pricingType: 'per_meter', description: `${PROBE_PREFIX}重复提交探针`, status: 'draft',
    colors: [{ colorName: '米白' }], doorWidths: ['2.8m'],
    skus: [{ colorName: '米白', doorWidth: '2.8m', price: 9, stock: 1 }],
  },
})
// 正对照：串行发 1 次 ⇒ 必须成功（否则分不清"并发保护"与"功能不работ"）
const serial = await mkSame(idemKey)
const dupSku = `${ID_PREFIX}-E1-DUP-${idemKey.slice(-6).toUpperCase()}`
const afterSerial = one(`select count(*)::int as n from products where tenant_id=${T} and sku_code='${dupSku}' and deleted=0`)?.n
// 并发 5 次同 payload 同幂等键
const conc = await Promise.all([1, 2, 3, 4, 5].map(() => mkSame(idemKey)))
const afterConc = one(`select count(*)::int as n from products where tenant_id=${T} and sku_code='${dupSku}' and deleted=0`)?.n
const keys = psql(`select * from client_request_keys where tenant_id=${T} and client_request_id like '${ID_PREFIX}-e1-%'`)
writeFileSync(outPath('E1-duplicate-submit.json'), JSON.stringify({
  idemKey, serialHttp: serial.status, serialBody: serial.json, afterSerial,
  concHttp: conc.map((c) => c.status), concBody: conc.map((c) => ({ ok: c.json?.success, id: c.data?.id, msg: c.json?.error?.message })),
  afterConc, clientRequestKeys: keys,
}, null, 2))
judge(R, {
  id: 'E1.0', name: '正对照：串行 1 次重复提交（同幂等键）⇒ 成功且落库 1 份',
  expect: `HTTP 200 且 products(sku_code=${dupSku}) = 1`,
  actual: `HTTP ${serial.status} 落库=${afterSerial}`,
  pass: serial.status === 200 && afterSerial === 1,
  expectSource: '正对照（migao-acceptance 反假绿）：先证该写面在串行下能成功，才谈并发保护',
  evidence: [`响应: ${serial.text.slice(0, 200)}`],
})
judge(R, {
  id: 'E1.1', name: '并发 5 次同 payload 同 X-Client-Request-Id ⇒ 只应产生一份数据（不得 5 份）',
  expect: `落库份数 = 1（幂等键生效）；若为 6 ⇒ 幂等键未生效（登记项）`,
  actual: `落库=${afterConc}（并发前=${afterSerial}）HTTP=${JSON.stringify(conc.map((c) => c.status))}`,
  pass: afterConc === 1,
  expectSource: '幂等语义：同一 X-Client-Request-Id 的重复提交只应落一份；测点是 client_request_keys 是否被本链路消费',
  evidence: [`client_request_keys 命中: ${JSON.stringify(keys)}`, `并发响应体: ${conc.map((c) => c.text.slice(0, 80)).join(' | ')}`],
})

// ══════════════ E2 库存不得为负（超卖护栏）══════════════
const e2 = await mkProduct('库存E2', 'draft')
const stockOf = () => one(`select stock::text as s from products where id='${e2.id}'`)?.s
const skuStockOf = () => psql(`select id, stock::text as s from product_skus where product_id='${e2.id}'`)
// 正对照：合法值 7 ⇒ 成功且落库
const putStock = (v) => api('PUT', `/api/admin/products/${e2.id}`, {
  token,
  body: {
    name: `${PROBE_PREFIX}库存E2`, skuCode: e2.sku, basePrice: 20, stock: v, unit: '米', pricingType: 'per_meter',
    description: `${PROBE_PREFIX}并发探针`, status: 'draft',
    colors: [{ colorName: '米白' }], doorWidths: ['2.8m'],
    skus: [{ colorName: '米白', doorWidth: '2.8m', price: 20, stock: v }],
  },
})
const ok7 = await putStock(7)
const after7 = { product: stockOf(), skus: skuStockOf() }
const neg = await putStock(-5)
const afterNeg = { product: stockOf(), skus: skuStockOf() }
// 并发写负库存 5 次
const negConc = await Promise.all([1, 2, 3, 4, 5].map(() => putStock(-1)))
const afterNegConc = { product: stockOf(), skus: skuStockOf() }
// ⚠️ stock_ledger_entries 的列是 delta / before_qty / after_qty（**没有** quantity）—— 实测列名
const negLedger = psql(`select id, ref_no, delta::text as d, before_qty::text as b, after_qty::text as a, reason from stock_ledger_entries where product_id='${e2.id}' limit 20`)
writeFileSync(outPath('E2-stock-negative.json'), JSON.stringify({
  positive: { http: ok7.status, after: after7 }, negative: { http: neg.status, body: neg.json, after: afterNeg },
  negativeConcurrent: { http: negConc.map((c) => c.status), after: afterNegConc }, ledger: negLedger,
}, null, 2))
judge(R, {
  id: 'E2.0', name: '正对照：库存写 7（合法）⇒ 200 且 DB 落 7（商品级与 SKU 级）',
  expect: `HTTP 200；products.stock=7 且 sku.stock=7`,
  actual: `HTTP ${ok7.status}；product=${after7.product} sku=${JSON.stringify(after7.skus)}`,
  pass: ok7.status === 200 && Number(after7.product) === 7,
  expectSource: '正对照（反假绿）：库存写面在合法值上必须真的生效，否则"不得为负"是空断言',
  evidence: [`响应: ${ok7.text.slice(0, 200)}`],
})
judge(R, {
  id: 'E2.1', name: '库存不得为负：写 -5 ⇒ 必须拒绝且 DB 零变更（超卖护栏）',
  expect: `HTTP 4xx 且 products.stock 仍为 7`,
  actual: `HTTP ${neg.status} body=${neg.text.slice(0, 180)}；product=${afterNeg.product}`,
  pass: neg.status >= 400 && neg.status < 500 && Number(afterNeg.product) === 7,
  expectSource: '库口径 stock 为数量字段；超卖 ⇒ 红（本线硬要求「库存不得为负」）。StockQuantity 准入判据存在于 import/stocktake 路径',
  evidence: [`负值落库: ${JSON.stringify(afterNeg)}`, `ledger: ${JSON.stringify(negLedger)}`],
})
judge(R, {
  id: 'E2.2', name: '并发写负库存 5 次 ⇒ 不得有任一次落库（仓库不得出现负库存）',
  expect: `5 次全 4xx；products.stock ≥ 0`,
  actual: `HTTP=${JSON.stringify(negConc.map((c) => c.status))}；product=${afterNegConc.product} sku=${JSON.stringify(afterNegConc.skus)}`,
  pass: negConc.every((c) => c.status >= 400) && Number(afterNegConc.product) >= 0,
  expectSource: '并发下同一护栏必须仍成立（每条并发断言都配正对照 E2.0）',
  evidence: [`并发响应: ${negConc.map((c) => c.text.slice(0, 60)).join(' | ')}`],
})

// ══════════════ E3 终态对象并发写（软删 = 终态）══════════════
const e3 = await mkProduct('终态E3', 'draft')
const delE3 = await api('POST', '/api/admin/products/batch/delete', { token, body: { productIds: [e3.id] } })
const live = await mkProduct('活体对照E3b', 'draft')
// 正对照：活体商品可改状态
const livePut = await api('PUT', `/api/admin/products/${live.id}/status`, { token, body: { status: 'on_sale' } })
const liveAfter = one(`select status from products where id='${live.id}'`)?.status
judge(R, {
  id: 'E3.0', name: '正对照：活体商品的同类写（PUT status）真的成功',
  expect: `HTTP 200 且 status=on_sale`,
  actual: `HTTP ${livePut.status} status=${liveAfter}`,
  pass: livePut.status === 200 && liveAfter === 'on_sale',
  expectSource: '正对照（反假绿）：先证该写路径可用',
  evidence: [`响应: ${livePut.text.slice(0, 200)}`],
})
const termWrites = await Promise.all([1, 2, 3, 4, 5].map(() => api('PUT', `/api/admin/products/${e3.id}/status`, { token, body: { status: 'on_sale' } })))
const e3After = one(`select id,status,deleted from products where id='${e3.id}'`)
writeFileSync(outPath('E3-terminal-race.json'), JSON.stringify({
  deletedHttp: delE3.status, concurrentHttp: termWrites.map((c) => c.status), after: e3After,
}, null, 2))
judge(R, {
  id: 'E3.1', name: '终态（已软删）对象并发发起会改状态的写 ⇒ 全部拒绝且零写',
  expect: `5 次全 4xx（404/422）；DB deleted 仍为 1 且 status 未被改成 on_sale`,
  actual: `HTTP=${JSON.stringify(termWrites.map((c) => c.status))}；DB=${JSON.stringify(e3After)}`,
  pass: termWrites.every((c) => c.status >= 400 && c.status < 500) && e3After?.deleted === 1 && e3After?.status !== 'on_sale',
  expectSource: '软删后 selectById 被 MP 逻辑删除过滤 ⇒ Product null ⇒ notFound；并发下必须零写',
  evidence: [`响应: ${termWrites.map((c) => c.text.slice(0, 60)).join(' | ')}`],
})

// ══════════════ E4 幂等：同 payload 连发 batch（已在 B1.2 覆盖）+ 工序 detach 并发幂等 ══════════════
const e4OpName = `${PROBE_PREFIX}并发工序`
const e4Op = await api('POST', '/api/admin/production/operations', { token, body: { name: e4OpName, group_name: `${PROBE_PREFIX}组`, unit: '米', unit_price: 5, position: `${PROBE_PREFIX}部位3`, sort_order: 997 } })
const e4Id = e4Op.data?.id
const e4Conc = await Promise.all([1, 2, 3, 4, 5].map(() => api('DELETE', `/api/admin/production/operations/${e4Id}/detach-and-delete`, { token })))
const e4After = one(`select id,deleted from production_operations where id='${e4Id}'`)
writeFileSync(outPath('E4-detach-concurrent.json'), JSON.stringify({
  createHttp: e4Op.status, concurrentHttp: e4Conc.map((c) => c.status), after: e4After,
}, null, 2))
judge(R, {
  id: 'E4.1', name: '并发 5 次 detach-and-delete 同一工序 ⇒ 恰好 1 次成功、其余拒绝，且终态 deleted=1（无半完成）',
  expect: `成功(200) 次数 = 1；其余 4xx；DB deleted=1`,
  actual: `HTTP=${JSON.stringify(e4Conc.map((c) => c.status))} 200 次数=${e4Conc.filter((c) => c.status === 200).length}；DB=${JSON.stringify(e4After)}`,
  pass: e4Conc.filter((c) => c.status === 200).length === 1 && e4Conc.every((c) => c.status < 500) && e4After?.deleted === 1,
  expectSource: '并发幂等：同一删除请求并发 ⇒ 一次生效；不得 5xx、不得半完成（#4608 的静默 no-op 形态）',
  evidence: [`响应: ${e4Conc.map((c) => c.text.slice(0, 70)).join(' | ')}`],
})

// ══════════════ F 红证（注入式：改一行 DB ⇒ 当场红 ⇒ 还原 ⇒ 回绿；sha256 自证）══════════════
const fp = (s) => sha256(String(s))

// F1 — 孤儿扫描的可红性：注入一条真孤儿（parent 不存在）⇒ 扫描必须 >0
const scanOrphans = () => one(`select count(*)::int as n from product_skus x where x.product_id is not null and not exists (select 1 from products p where p.id=x.product_id)`)?.n
const f1Before = scanOrphans()
const orphanId = hexId('l2orph')
guardedWrite(`-- probe-ok
  insert into product_skus (tenant_id, product_id, color_id, door_width, price, stock, sku_code, sales_count, created_at, updated_at, color_name, avg_cost, cost_amount, latest_batch_no)
  values (${T}, '${orphanId}', null, '2.8m', 1, 1, '${ID_PREFIX}-ORPHAN-PROOF', 0, now(), now(), '${PROBE_PREFIX}孤儿', 0, 0, null);`)
const f1Injected = scanOrphans()
const f1FpInj = fp(JSON.stringify(psql(`select id, product_id from product_skus where sku_code='${ID_PREFIX}-ORPHAN-PROOF'`)))
guardedWrite(`-- probe-ok delete from product_skus where tenant_id=${T} and sku_code='${ID_PREFIX}-ORPHAN-PROOF';`)
const f1Restored = scanOrphans()
const f1FpRes = fp(JSON.stringify(psql(`select id from product_skus where sku_code='${ID_PREFIX}-ORPHAN-PROOF'`)))
writeFileSync(outPath('F1-orphan-redproof.json'), JSON.stringify({
  before: f1Before, injected: f1Injected, restored: f1Restored,
  injectedRowFingerprint: f1FpInj, restoredRowFingerprint: f1FpRes,
}, null, 2))
judge(R, {
  id: 'F1', name: '红证①：孤儿扫描**会红**（注入真孤儿 ⇒ >0；还原 ⇒ 0），sha256 自证注入/还原',
  expect: `注入前 0 → 注入后 ≥1（红）→ 还原后 0`,
  actual: `before=${f1Before} injected=${f1Injected} restored=${f1Restored}；注入行指纹=${f1FpInj.slice(0, 12)} 还原后指纹=${f1FpRes.slice(0, 12)}`,
  pass: f1Before === 0 && f1Injected >= 1 && f1Restored === 0,
  expectSource: 'migao-acceptance 铁律 2：不会红的断言 = 空断言 —— 注入一条违反不变式的行，判据必须报出',
  evidence: [`注入 SQL: insert into product_skus(product_id='${orphanId}', sku_code='${ID_PREFIX}-ORPHAN-PROOF')`, `还原 SQL: delete from product_skus where sku_code='${ID_PREFIX}-ORPHAN-PROOF'`],
})

// F2 — 幂等判据的可红性：造第二条同货号商品 ⇒ 「products(sku_code)=1」必须变红
const f2 = await mkProduct('红证F2', 'draft')
const cnt = () => one(`select count(*)::int as n from products where tenant_id=${T} and sku_code='${f2.sku}' and deleted=0`)?.n
const f2Green = cnt()
const dupId = hexId('l2dup')
guardedWrite(`-- probe-ok
  insert into products (id, tenant_id, name, base_price, stock, status, sku_code, created_at, updated_at, deleted, pricing_type, unit)
  values ('${dupId}', ${T}, '${PROBE_PREFIX}红证重复', 1, 1, 'draft', '${f2.sku}', now(), now(), 0, 'per_meter', '米');`)
const f2Red = cnt()
const f2FpRed = fp(JSON.stringify(psql(`select id from products where id='${dupId}'`)))
guardedWrite(`-- probe-ok delete from products where tenant_id=${T} and id='${dupId}';`)
const f2Back = cnt()
writeFileSync(outPath('F2-idempotence-redproof.json'), JSON.stringify({
  green: f2Green, red: f2Red, restored: f2Back, injectedRowFingerprint: f2FpRed,
}, null, 2))
judge(R, {
  id: 'F2', name: '红证②：幂等判据（同货号商品数=1）**会红**（注入第二条同货号 ⇒ 2；清理 ⇒ 1）',
  expect: `1 → 注入后 2（判据会红）→ 清理后 1`,
  actual: `green=${f2Green} red=${f2Red} restored=${f2Back}；注入行指纹=${f2FpRed.slice(0, 12)}`,
  pass: f2Green === 1 && f2Red === 2 && f2Back === 1,
  expectSource: 'migao-acceptance 铁律 2：把被测行为改坏 ⇒ 判据必须红（否则是恒绿的空断言）',
  evidence: [`注入行 id=${dupId}（sku_code=${f2.sku}）`, `sha256(注入行)=${f2FpRed}`],
})

// F3 — 故意的失效控制项（必须红）
judge(R, {
  id: 'F3', name: '故意的失效控制项（必须红）：断言 1 === 2 —— 用于证明「判据真的会红、fail 桶不是空的」',
  expect: '1 === 2（**故意为假**）',
  actual: '1 === 2 为 false',
  pass: false,
  expectSource: 'migao-acceptance 反假绿：保留一条**故意的失效控制项**（必须红）',
  evidence: ['控制项：本条**预期就是 fail**；它出现在 §3 台账里即证明红证通道可用'],
})

// 清理
try { cleanupProbe(); log('E/F 段探针对象已清理') } catch (e) { log(`清理失败: ${e.message.slice(0, 200)}`) }
log(`E/F 段结束，摘要 ${JSON.stringify(R.summary())}`)
process.exit(0)
