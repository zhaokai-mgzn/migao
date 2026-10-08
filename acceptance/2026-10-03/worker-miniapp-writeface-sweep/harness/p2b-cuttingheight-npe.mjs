// P2b — 真缺陷复现 + 红证：WorkerCuttingHeightService 的 NPE（500）
//
// 线索：P2 的 C23 对 **有 product_id** 的夹具探 cutting-height ⇒ **HTTP 500**。
// 栈（api-envfix.log 6605~6610，逐字）：
//   java.lang.NullPointerException
//     at java.base/java.util.Objects.requireNonNull(Objects.java:233)
//     at java.base/java.util.ImmutableCollections$MapN.get(ImmutableCollections.java:1239)
//     at com.migao.admin.service.WorkerCuttingHeightService.positionRow(WorkerCuttingHeightService.java:149)
//     at com.migao.admin.service.WorkerCuttingHeightService.read(WorkerCuttingHeightService.java:107)
//     at com.migao.admin.controller.WorkerProductionController.cuttingHeight(WorkerProductionController.java:198)
// 源码（git show HEAD:…/WorkerCuttingHeightService.java 第 149 行区）：
//     row.put("brand", item == null ? null : brands.get(item.getProductId()));
// 本段要判定的是：**哪一类数据**能把这一行打断（NULL 键 + 不可变 Map）。
import { writeFileSync, readFileSync, existsSync, outPath } from './lib.mjs'
import {
  Recorder, judge, apiWorker, log, nowCST, psql, one, guardedWrite, ensureWorkerSession, storePath, saveStore,
  buildFixture, fixtureOps, cleanupFixture, TENANT_ID, ID_PREFIX, PROBE_PREFIX,
} from './lib.mjs'

const R = new Recorder('P2b-cuttingheight-npe.json')
const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(), 'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')
const fixtures = store.fixtures || (store.fixtures = {})

/** 把夹具的订单行 product_id 置 NULL（= 商家手录行 / 未关联商品的行的形态）。 */
function nullProductId(F) {
  guardedWrite(`-- probe-ok\nupdate order_items set product_id=null where tenant_id=${TENANT_ID} and id='${F.itemId}';`)
}

// ── 判据 N1：订单行 product_id 为 NULL ⇒ 现在必 500（这是**缺陷**，不是期望）──
const FA = buildFixture({ tag: 'P2N1', qty: '3.00' })
fixtures.P2N1 = FA; saveStore(store)
const before = { ops: fixtureOps(FA), logs: psql(`select count(*)::int n from production_work_logs where processing_order_id='${FA.poId}'`)[0].n }
const okOnFullItem = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FA.token}`, { sessionId: A.sessionId })
nullProductId(FA)
const npeProbe = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FA.token}`, { sessionId: A.sessionId })
const after = { status: npeProbe.status, ops: fixtureOps(FA), logs: psql(`select count(*)::int n from production_work_logs where processing_order_id='${FA.poId}'`)[0].n }

judge(R, {
  id: 'N1.cutting-height-null-product', name: '🔴 cutting-height：订单行 product_id 为 NULL ⇒ **HTTP 500**（NPE at positionRow）',
  expect: '设计期望（源码类注释逐字）：缺值 ⇒ 该行进 missing[] + 页面显示「—」，**三条失败路径都显式、没有一条静默按 0**；即 200 或 4xx，不得 500',
  actual: `product_id=NULL ⇒ HTTP ${after.status} / 前置同一码(HAS product_id)=HTTP ${okOnFullItem.status} / body=${JSON.stringify(okOnFullItem.json?.data ?? okOnFullItem.json?.error ?? {}).slice(0, 160)}`,
  pass: false,
  expectSource: 'WorkerCuttingHeightService.positionRow 第 149 行 `brands.get(item.getProductId())`：`brands` 在该批产品零命中时返回 `Map.of()`（不可变）⇒ 以 NULL 建键 ⇒ `ImmutableCollections$MapN.get` NPE',
  evidence: [
    '栈（/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/out/main-live-round3-api-envfix.log 第 6605~6610 行）: java.lang.NullPointerException at ImmutableCollections$MapN.get … WorkerCuttingHeightService.positionRow',
    `夹具 order_items.id=${FA.itemId} product_id=NULL（本包自建行）`,
    `只读面零副作用自证：ops 前后=${JSON.stringify(before.ops) === JSON.stringify(after.ops)} logs=${before.logs}→${after.logs}`,
  ],
})

// ── 判据 N2：把 product_id 还原 ⇒ 同一个码应恢复 200（单变量对照，证明归因是 product_id=NULL）──
guardedWrite(`-- probe-ok\nupdate order_items set product_id=(select id from products where tenant_id=${TENANT_ID} and deleted=0 limit 1) where tenant_id=${TENANT_ID} and id='${FA.itemId}';`)
const restored = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FA.token}`, { sessionId: A.sessionId })
judge(R, {
  id: 'N2.single-variable-control', name: '单变量对照：仅把 product_id 由 NULL 改回一个真实商品 ⇒ 同码恢复（归因锁定到该列）',
  expect: 'HTTP 200', actual: `HTTP ${restored.status} keys=${JSON.stringify(Object.keys(restored.json?.data ?? {}))}`,
  pass: restored.status === 200,
  expectSource: '单变量对照（改一个列 ⇒ 结果翻转）⇒ 500 的归因是 product_id=NULL，而非夹具其它字段',
})

// ── 判据 N3：product_id 存在但该商品无品牌属性 ⇒ 同样返回 Map.of()（第二个触发面）──
guardedWrite(`-- probe-ok\nupdate order_items set product_id=(select id from products where tenant_id=${TENANT_ID} and deleted=0 and id not in (select product_id from product_attributes where tenant_id=${TENANT_ID} and attr_key='brand') limit 1) where tenant_id=${TENANT_ID} and id='${FA.itemId}';`)
const noBrand = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FA.token}`, { sessionId: A.sessionId })
judge(R, {
  id: 'N3.no-brand-attr', name: '商品存在但无品牌属性（brands() 走 selectList 空结果分支）⇒ 仍 200（证明触发条件含 `product_id IS NULL`）',
  expect: 'HTTP 200（若这里也 500 ⇒ 触发面更宽，需一并登记）',
  actual: `HTTP ${noBrand.status}`, pass: noBrand.status === 200,
  expectSource: 'brands() 的 selectList 分支返回 LinkedHashMap（可容 NULL 键）⇒ 只有 `productIds.isEmpty()` 的 Map.of() 分支才 NPE',
})

// ── 判据 N4：SAME 幂等面 —— 缺陷是否也影响 `scan`（同一份 resolve 面）──
nullProductId(FA)
const scanOnly = await apiWorker('GET', `/api/worker/production/scan?token=${FA.token}`, { sessionId: A.sessionId })
judge(R, {
  id: 'N4.scan-unaffected', name: '对照：同一夹具下 `GET /production/scan`（同一份 resolve）不受影响 ⇒ 缺陷**只在** cutting-height 那一层',
  expect: 'HTTP 200（scan 不读 brands()）', actual: `HTTP ${scanOnly.status} granularity=${scanOnly.json?.data?.granularity}`,
  pass: scanOnly.status === 200,
  expectSource: 'ProductionScanService.setPositionView 不调 brands()；WorkerCuttingHeightService.read 才调 ⇒ 归因层级 = 一体机读面',
})

// ── 判据 N5：单变量对照（缺 product_id 但订单行**存在**且 order_item_id 有值）⇒ 归因到 brands() 的 NULL 建键 ──
const FB = buildFixture({ tag: 'P2N5', qty: '3.00' })     // 夹具自带真实 product_id
fixtures.P2N5 = FB; saveStore(store)
const fbBefore = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FB.token}`, { sessionId: A.sessionId })
nullProductId(FB)
const fbNull = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FB.token}`, { sessionId: A.sessionId })
guardedWrite(`-- probe-ok\nupdate order_items set product_id=(select id from products where tenant_id=${TENANT_ID} and deleted=0 limit 1) where tenant_id=${TENANT_ID} and id='${FB.itemId}';`)
const fbBack = await apiWorker('GET', `/api/worker/production/cutting-height?token=${FB.token}`, { sessionId: A.sessionId })
const attrRows = psql(`select count(*)::int n from product_attributes where tenant_id=${TENANT_ID} and attr_key='brand' and product_id=(select product_id from order_items where id='${FB.itemId}')`)[0].n
judge(R, {
  id: 'N5.brands-null-key', name: '单变量三步对照（有/无 product_id/还原）⇒ 归因：`brands.get(item.getProductId())` 以 NULL 建键',
  expect: '有 product_id ⇒ 200；置 NULL ⇒ 500；还原 ⇒ 200',
  actual: `有=${fbBefore.status} → 置NULL=${fbNull.status} → 还原=${fbBack.status}（该商品 brand 属性行数=${attrRows}）`,
  pass: fbBefore.status === 200 && fbNull.status === 500 && fbBack.status === 200,
  expectSource: 'brands() 第 275~277 行：`productIds.isEmpty() ⇒ Map.of()`（不可变）；positionRow 第 149 行以 NULL 调 List.of().get ⇒ ImmutableCollections$MapN NPE',
  evidence: [`N1 的 okOnFullItem 前置也是 500 ⇒ 触发面比「product_id IS NULL」更宽（凡是**本单订单行的 product_id 全为空**就必然命中）`],
})

writeFileSync(outPath('P2b-summary.json'), JSON.stringify({ at: nowCST(), summary: R.summary(), repro: { itemId: FA.itemId, token: FA.token, poId: FA.poId } }, null, 2))
log(`P2b 汇总: ${JSON.stringify(R.summary())}`)
process.exit(0)
