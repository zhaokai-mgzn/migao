// W4 的**判别性对照**：同一业务序列改成顺序执行 ⇒ 第二单必须被库存校验拒掉（4xx）
// 判据：顺序执行下 stock 10 - 8 = 2 < 8 ⇒ 第二单 4xx；并发下（W4）两单都 200 且库存钳 0 ⇒ 证明 W4 测的确实是并发窗口
import { api, loginApi, one, log, OUT } from './lib.mjs'
import { skuByProduct, skuStock, ledgerRows } from './lib2.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
const T_A = 25, STAMP = '20261004010446'
const rnd = () => Math.random().toString(36).slice(2, 8)
const a = await loginApi('13800138000'); const TOK = a.token
const nm = `race-sweep-CTL-${STAMP}-${rnd()}`
const mk = await api('POST', '/api/admin/products', { token: TOK, body: { name: nm, skuCode: `RCTL${rnd()}`.slice(0, 20), unit: '米',
  pricingType: 'per_meter', basePrice: 10.0, status: 'draft', stock: 10, colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] } })
if (mk.status !== 200) { log(`对照夹具建品失败 ${mk.status} ${mk.text.slice(0, 160)}`); writeFileSync(join(OUT, 'control-seq-oversell.json'), JSON.stringify({ ok: false, mk: mk.text.slice(0, 200) }, null, 2)); process.exit(0) }
const sku = skuByProduct(T_A, mk.json.data.id)
const before = skuStock(T_A, sku.id)
const mkOrder = async (tag) => {
  const r = await api('POST', '/api/admin/agent/orders', { token: TOK, body: {
    customerName: `race-sweep-ctl-${tag}`, customerPhone: '13900000000', customerAddress: 'race-sweep-addr',
    logisticsType: 'express', logisticsCompany: 'race-sweep-log', remark: `race-sweep-ctl-${tag}-${STAMP}-${rnd()}`,
    items: [{ productId: sku.product_id, productName: sku.sku_code, quantity: '8.0', unitPrice: 10.0, subtotal: '80.0',
              processingInfo: { skuId: String(sku.id), skuCode: sku.sku_code } }] } })
  return { id: r.json?.data?.id, no: r.json?.data?.orderNo, status: r.status }
}
const o1 = await mkOrder('a'), o2 = await mkOrder('b')
const p1 = await api('PUT', `/api/admin/orders/${o1.id}/payment`, { token: TOK })
const mid = skuStock(T_A, sku.id)
const p2 = await api('PUT', `/api/admin/orders/${o2.id}/payment`, { token: TOK })
const after = skuStock(T_A, sku.id)
const led = ledgerRows(T_A, sku.id)
const ev = { skuId: sku.id, skuCode: sku.sku_code, stockBefore: before.stock, afterFirstPayment: mid.stock, stockAfter: after.stock,
  pay1: { status: p1.status, body: p1.text.slice(0, 160) }, pay2: { status: p2.status, body: p2.text.slice(0, 220) },
  orderNos: [o1.no, o2.no], ledger: led.map((r) => ({ id: r.id, delta: r.delta, before: r.before_qty, after: r.after_qty, ref_no: r.ref_no })),
  judge: '顺序执行 ⇒ 第二单必须 4xx（库存 2 < 8）；这与 W4 并发下的 [200,200] 构成判别性对照' }
writeFileSync(join(OUT, 'control-seq-oversell.json'), JSON.stringify(ev, null, 2))
log(`W4 顺序对照：库存 ${before.stock}→(首单后)${mid.stock}→${after.stock}；pay1=${p1.status} pay2=${p2.status}（第二单应 4xx）`)
