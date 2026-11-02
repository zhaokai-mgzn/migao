// p0d-deployed-identity-probe.mjs — **部署镜像身份判别探针**（行为面，不问 Git 声明）
//
// 为什么要它：`#6219` 的修复（commit 24b7381d1）在 Git 上是 `ff655a06c`（**声明**的被测构建点）
// 的祖先，而实测 `GET /api/worker/production/cutting-height` 在「订单行 product_id 全空」时仍 **500**
// ⇒ **Git 声明与线上行为矛盾**。两种可能必须分开，不能靠猜：
//   (a) 线上镜像其实是**旧**的（deploy 声明与实际运行的容器不一致）；
//   (b) 镜像含修复、但还有**第二条**没修的 NPE 路径。
//
// 判别式（来自修复 diff 逐字）：旧代码那一行是
//     `row.put("brand",      item == null ? null : brands.get(item.getProductId()));`
//     `row.put("product_name", item == null ? null : item.getProductName());`
// 修复后是 `String productId = item == null ? null : item.getProductId();` + 三处 `productId == null ? null :`
// ⇒ **判别点**：`item` 为 NULL 时旧码在**取 `brand` 那一行**就抛（positionRow 里 `brand` 是
//   `product_name` 的**前一行**）⇒ **不可能**拿到 missing[] 形状的响应体；
//   修复后则两行都短路 ⇒ 必得 200 + `missing[]` 里点名该部位。
// ⇒ **单变量**：只改「订单行是否都存在且 product_id 为空」，看响应是 500 还是 200+missing[]。
import { writeFileSync } from 'node:fs'
import {
  apiWorker, log, nowCST, psql, one, guardedWrite, ensureWorkerSession, storePath, saveStore,
  buildFixture, cleanupFixture, TENANT_ID, outPath, writeFileSync as wf, readFileSync, existsSync,
  loginApi,
} from './lib.mjs'

const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(), 'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')
const out = { at: nowCST(), steps: [] }

// 夹具 A：正常（带真实 product_id）
const F = buildFixture({ tag: 'P0D', qty: '3.00' })
store.fixtures = { ...(store.fixtures ?? {}), P0D: F }
saveStore(store)

const fullRes = await apiWorker('GET', `/api/worker/production/cutting-height?token=${F.token}`, { sessionId: A.sessionId })
out.steps.push({ id: 'full-product-id', http: fullRes.status, keys: Object.keys(fullRes.json?.data ?? {}),
  positions0: fullRes.json?.data?.positions?.[0] ?? null, raw: JSON.stringify(fullRes.json).slice(0, 1200) })

// 单变量：把 product_id 置 NULL（订单行**仍存在** ⇒ 能走到 positionRow 的 item != null 分支）
guardedWrite(`-- probe-ok\nupdate order_items set product_id=null where tenant_id=${TENANT_ID} and id='${F.itemId}';`)
const nullRes = await apiWorker('GET', `/api/worker/production/cutting-height?token=${F.token}`, { sessionId: A.sessionId })
out.steps.push({ id: 'product-id-null', http: nullRes.status, keys: Object.keys(nullRes.json?.data ?? {}),
  errorCode: nullRes.json?.error?.code ?? null, errorMessage: nullRes.json?.error?.message ?? null,
  positions0: nullRes.json?.data?.positions?.[0] ?? null, missing: nullRes.json?.data?.missing ?? null,
  raw: JSON.stringify(nullRes.json).slice(0, 1500) })

// 判别（写死判别式，不猜）
const hasMissingShape = (r) => r.http === 200 && Array.isArray(r.missing)
out.verdict = {
  fixedCodeSignature: hasMissingShape({ http: nullRes.status, missing: nullRes.json?.data?.missing }),
  reading: nullRes.status === 500 && !hasMissingShape({ http: nullRes.status, missing: nullRes.json?.data?.missing })
    ? '线上在 item==null 时**仍抛**（取不到 missing[] 形状）⇒ 与「修复已部署」不相容 ⇒ 强烈指向**线上镜像是旧构**（判别式 = 若已含修复，product_name 那行的短路保证不抛 ⇒ 必得 200+missing[]）'
    : '线上呈现修复后的形状（200 + missing[]）⇒ (a) 不成立',
}
log(`P0d 全量(有 product_id): HTTP ${fullRes.status}`)
log(`P0d 单变量(product_id=NULL): HTTP ${nullRes.status} errorCode=${nullRes.json?.error?.code ?? '-'} keys=${JSON.stringify(Object.keys(nullRes.json?.data ?? {}))}`)
log(`P0d 判别: fixedSignature=${out.verdict.fixedCodeSignature}｜${out.verdict.reading}`)

// 收尾：把该行的 product_id 还原成「本租户任一真实商品」再删夹具（本探针自清）
const anyPid = one(`select id from products where tenant_id=${TENANT_ID} and deleted=0 and id like 'la%' limit 1`)?.id ?? null
if (anyPid) guardedWrite(`-- probe-ok\nupdate order_items set product_id='${anyPid}' where tenant_id=${TENANT_ID} and id='${F.itemId}';`)
cleanupFixture(F)
writeFileSync(outPath('P0d-deployed-identity.json'), JSON.stringify(out, null, 2))
process.exit(0)
