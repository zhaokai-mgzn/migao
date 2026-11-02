// F — 红证台账（注入 ⇒ 红 ⇒ 还原 ⇒ 绿，sha256 内容指纹自证；禁用 mtime/size）
import {
  Recorder, judge, psql, one, guardedWrite, PROBE_PREFIX, ID_PREFIX, TENANT_ID,
  log, nowCST, writeFileSync, outPath, sha256, probeSku, cleanupProbe, hexId, api, loginApi,
} from './lib.mjs'

const R = new Recorder('F-redproof.json')
const { token } = await loginApi()
const T = TENANT_ID
log(`F 段开始 ${nowCST().cst} (UTC ${nowCST().utc})`)

const mkProduct = async (name, status = 'draft') => {
  const sku = probeSku('F')
  const r = await api('POST', '/api/admin/products', {
    token,
    body: {
      name: `${PROBE_PREFIX}${name}`, skuCode: sku, basePrice: 20, stock: 3, unit: '米', pricingType: 'per_meter',
      description: `${PROBE_PREFIX}红证探针`, status, colors: [{ colorName: '米白' }], doorWidths: ['2.8m'],
      skus: [{ colorName: '米白', doorWidth: '2.8m', price: 20, stock: 3 }],
    },
  })
  return { r, id: r.data?.id, sku }
}
const fp = (v) => sha256(typeof v === 'string' ? v : JSON.stringify(v))

// ══════════ F1 孤儿不变式：**注入被 DB 拒绝** ⇒ 该判据是结构性保证（无判别力），必须如实登记 ══════════
const orphanId = hexId('l2orph')
let f1Err = null
try {
  guardedWrite(`-- probe-ok
    insert into product_skus (tenant_id, product_id, color_id, door_width, price, stock, sku_code, sales_count, created_at, updated_at, color_name, avg_cost, cost_amount, latest_batch_no)
    values (${T}, '${orphanId}', null, '2.8m', 1, 1, '${ID_PREFIX}-ORPHAN-PROOF', 0, now(), now(), '${PROBE_PREFIX}孤儿', 0, 0, null);`)
} catch (e) { f1Err = String(e.message).match(/ERROR:[^\n]*/)?.[0] ?? String(e.message) }
const f1After = one(`select count(*)::int as n from product_skus where sku_code='${ID_PREFIX}-ORPHAN-PROOF'`)?.n
const fkList = psql(`select conrelid::regclass::text as child, a.attname as col from pg_constraint c join unnest(c.conkey) k(attnum) on true join pg_attribute a on a.attrelid=c.conrelid and a.attnum=k.attnum where c.contype='f' and c.confrelid='products'::regclass order by 1`)
writeFileSync(outPath('F1-orphan-injection-attempt.json'), JSON.stringify({
  attempt: 'insert 一条 product_id 不存在的 product_skus 行（真孤儿）',
  error: f1Err, rowsWithProofSkuAfter: f1After, fksToProducts: fkList,
}, null, 2))
judge(R, {
  id: 'F1', name: '红证①（**注入被拒**）：真孤儿无法注入 ⇒ 「孤儿扫描=0」是 DB 结构性保证、**无判别力**',
  expect: `注入应被 FK 拒绝（error 非空）且注入后仍无该行`,
  actual: `error=${f1Err ?? '（未被拒绝！）'}；注入后命中行数=${f1After}；指向 products 的 FK 数=${fkList.length}`,
  pass: !!f1Err && f1After === 0,
  expectSource: 'migao-acceptance 铁律 2 + 「关系式断言在空集上恒真」：判据自己要先接受"它有没有判别力"的检验',
  evidence: [
    `指向 products 的 ${fkList.length} 条 FK: ${fkList.map((x) => `${x.child}.${x.col}`).join(', ')}`,
    '⇒ 结论：B3.2 的「真孤儿=0」不是被测行为的结果而是**约束的结果** ⇒ 已改判 skip（见 REPORT §2/§7）',
  ],
})

// ══════════ F2 幂等判据可红性：注入第二条同货号商品 ══════════
const f2 = await mkProduct('红证F2', 'draft')
const cnt = () => one(`select count(*)::int as n from products where tenant_id=${T} and sku_code='${f2.sku}' and deleted=0`)?.n
const f2Green = cnt()
const dupId = hexId('l2dup')
guardedWrite(`-- probe-ok
  insert into products (id, tenant_id, name, base_price, stock, status, sku_code, created_at, updated_at, deleted, pricing_type, unit)
  values ('${dupId}', ${T}, '${PROBE_PREFIX}红证重复', 1, 1, 'draft', '${f2.sku}', now(), now(), 0, 'per_meter', '米');`)
const f2Red = cnt()
const f2FpRed = fp(psql(`select id, sku_code from products where id='${dupId}'`))
guardedWrite(`-- probe-ok delete from products where tenant_id=${T} and id='${dupId}';`)
const f2Back = cnt()
const f2FpRes = fp(psql(`select id from products where id='${dupId}'`))
writeFileSync(outPath('F2-idempotence-redproof.json'), JSON.stringify({
  green: f2Green, red: f2Red, restored: f2Back, injectedFingerprint: f2FpRed, restoredFingerprint: f2FpRes,
}, null, 2))
judge(R, {
  id: 'F2', name: '红证②：幂等判据（同货号商品数=1）**会红**（注入第二条同货号 ⇒ 2 ⇒ 清理 ⇒ 1），sha256 自证',
  expect: `1 → 注入后 2（判据当场红）→ 清理后 1`,
  actual: `green=${f2Green} red=${f2Red} restored=${f2Back}；注入行 sha256=${f2FpRed.slice(0, 16)}；还原后 sha256=${f2FpRes.slice(0, 16)}`,
  pass: f2Green === 1 && f2Red === 2 && f2Back === 1 && f2FpRed !== f2FpRes,
  expectSource: 'migao-acceptance 铁律 2：把被测行为改坏 ⇒ 判据必须红（否则是恒绿空断言）；指纹自证注入/还原真的生效',
  evidence: [`注入 SQL: insert into products(id='${dupId}', sku_code='${f2.sku}')`, `清理 SQL: delete from products where id='${dupId}'`],
})

// ══════════ F3 库存不得为负判据可红性（注入 ⇒ 红 ⇒ 还原 ⇒ 绿）══════════
const f3 = await mkProduct('红证F3', 'draft')
const putStock = (v) => api('PUT', `/api/admin/products/${f3.id}`, {
  token,
  body: {
    name: `${PROBE_PREFIX}红证F3`, skuCode: f3.sku, basePrice: 20, stock: v, unit: '米', pricingType: 'per_meter',
    description: `${PROBE_PREFIX}红证探针`, status: 'draft', colors: [{ colorName: '米白' }], doorWidths: ['2.8m'],
    skus: [{ colorName: '米白', doorWidth: '2.8m', price: 20, stock: v }],
  },
})
const stockRow = () => one(`select stock::text as s from products where id='${f3.id}'`)
await putStock(7)
const f3Green = stockRow()?.s
const f3FpGreen = fp(psql(`select id, stock::text as s from products where id='${f3.id}'`))
const f3Inj = await putStock(-5)
const f3Red = stockRow()?.s
const f3FpRed = fp(psql(`select id, stock::text as s from products where id='${f3.id}'`))
await putStock(7)
const f3Back = stockRow()?.s
writeFileSync(outPath('F3-stock-redproof.json'), JSON.stringify({
  green: f3Green, injectedHttp: f3Inj.status, red: f3Red, restored: f3Back, fpGreen: f3FpGreen, fpRed: f3FpRed,
}, null, 2))
judge(R, {
  id: 'F3', name: '红证③：库存不变式（stock ≥ 0）**会红**（注入 -5 ⇒ 变红 ⇒ 还原 7 ⇒ 回绿），sha256 自证',
  expect: `7（绿）→ 注入 -5 后读数为负（红）→ 还原 7（绿）`,
  actual: `green=${f3Green} → 注入(-5) HTTP ${f3Inj.status} 读数=${f3Red} → 还原=${f3Back}；指纹 ${f3FpGreen.slice(0, 12)} → ${f3FpRed.slice(0, 12)}`,
  pass: Number(f3Green) === 7 && Number(f3Red) < 0 && Number(f3Back) === 7 && f3FpGreen !== f3FpRed,
  expectSource: 'migao-acceptance 铁律 2：不变式判据必须能被违反它的状态判红（本注入**成功** ⇒ 同时证明 E2.1 是真缺陷而非空断言）',
  evidence: [`注入前 DB 指纹=${f3FpGreen}`, `注入后 DB 指纹=${f3FpRed}`],
})

// ══════════ F4 故意的失效控制项（必须红）══════════
judge(R, {
  id: 'F4', name: '故意的失效控制项（**必须红**）：断言 1 === 2 —— 证明 fail 桶可达、红证通道可用',
  expect: '1 === 2（**故意为假**）',
  actual: '1 === 2 为 false ⇒ 本条预期就是 fail',
  pass: false,
  expectSource: 'migao-acceptance 反假绿：保留一条**故意的失效控制项**（必须红）',
  evidence: ['本条**不计入缺陷**，仅作通道自证'],
})

try { cleanupProbe(); log('F 段探针对象已清理') } catch (e) { log(`清理失败: ${e.message.slice(0, 200)}`) }
log(`F 段结束，摘要 ${JSON.stringify(R.summary())}`)
process.exit(0)
