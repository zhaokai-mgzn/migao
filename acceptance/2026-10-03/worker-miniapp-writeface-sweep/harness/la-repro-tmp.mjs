import { buildFixture, apiWorker, ensureWorkerSession, storePath, saveStore, readFileSync, existsSync, psql, one, guardedWrite, TENANT_ID } from './lib.mjs'
const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(),'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')
const F = buildFixture({ tag: 'P2X', qty: '3.00' })
store.fixtures = store.fixtures || {}; store.fixtures.P2X = F; saveStore(store)
const row = one(`select id, product_id, (product_id is null) as pid_null, processing_info::text from order_items where id='${F.itemId}'`)
console.log('fixture item:', JSON.stringify(row))
console.log('set_id/set_no:', F.setId, F.poNo)
const cut = await apiWorker('GET', `/api/worker/production/cutting-height?token=${F.token}`, { sessionId: A.sessionId })
console.log('cutting-height (item.product_id 实时值):', cut.status, JSON.stringify(cut.json?.error ?? cut.json?.data ?? {}).slice(0,200))
// 把 product_id 置为真实商品
guardedWrite(`-- probe-ok\nupdate order_items set product_id=(select id from products where tenant_id=${TENANT_ID} and deleted=0 limit 1) where tenant_id=${TENANT_ID} and id='${F.itemId}';`)
const pid2 = one(`select product_id, (product_id is null) as pid_null from order_items where id='${F.itemId}'`)
const cut2 = await apiWorker('GET', `/api/worker/production/cutting-height?token=${F.token}`, { sessionId: A.sessionId })
console.log('after set real product:', JSON.stringify(pid2), '⇒', cut2.status)
// 该 order_item 删除（items 映射里没有这一行 ⇒ item=null ⇒ brand 走 null 分支）
guardedWrite(`-- probe-ok\nupdate order_items set deleted=1 where tenant_id=${TENANT_ID} and id='${F.itemId}';`)
const cut3 = await apiWorker('GET', `/api/worker/production/cutting-height?token=${F.token}`, { sessionId: A.sessionId })
console.log('after item 不存在:', cut3.status, JSON.stringify(cut3.json?.data?.positions ?? cut3.json?.error ?? {}).slice(0,220))
process.exit(0)
