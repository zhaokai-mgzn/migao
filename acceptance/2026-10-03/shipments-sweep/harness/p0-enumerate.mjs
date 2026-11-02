// p0-enumerate.mjs —— 链路枚举（**先枚举，别猜**）
// 产物: out/surface.json —— 每一跳（端点 / 表 / 字段 / 状态取值 / 前端页面）
import { writeFileSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { API, OUT, REPO_ROOT, LIVE_WORKTREE, TENANT_ID, psql, log, nowCST } from './lib.mjs'

const src = (p) => join(LIVE_WORKTREE, p)
const sh = (cmd, args) => { try { return execFileSync(cmd, args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }) } catch (e) { return String(e.stdout || '') } }

// ── ① 端点（OpenAPI 真值面）──────────────────────────────
const docs = JSON.parse(await (await fetch(API + '/v3/api-docs')).text())
const KW = /ship|deliver|logistic|warehouse|stock|inventory|export|print|发货|出库|仓储|打包|入库/i
const endpoints = []
for (const [p, v] of Object.entries(docs.paths || {})) {
  const blob = JSON.stringify(v)
  if (!(KW.test(p) || KW.test(blob))) continue
  for (const m of ['get', 'post', 'put', 'patch', 'delete']) {
    if (!v[m]) continue
    const op = v[m]
    endpoints.push({
      method: m.toUpperCase(),
      path: p,
      summary: op.summary || '',
      requestBodyKeys: op.requestBody
        ? Object.keys(op.requestBody.content?.['application/json']?.schema?.properties || {})
        : [],
      responses: Object.keys(op.responses || {}),
    })
  }
}
endpoints.sort((a, b) => (a.path + a.method).localeCompare(b.path + b.method))

// ── ② 发货链相关 Java 源（代码级跳点）────────────────────────
const javaFiles = sh('bash', ['-lc',
  `cd ${JSON.stringify(src('backend/admin-api/src/main/java/com/migao/admin'))} && grep -rl 'order_shipments\\|OrderShipment\\|worker/shipment' --include=*.java . | sort`],
).trim().split('\n').filter(Boolean)

const javaHits = {}
for (const f of javaFiles) {
  const abs = join(src('backend/admin-api/src/main/java/com/migao/admin'), f)
  const txt = readFileSync(abs, 'utf8')
  javaHits[f] = {
    lines: txt.split('\n').length,
    mappings: (txt.match(/@(Get|Post|Put|Patch|Delete)Mapping\([^)]*\)/g) || []),
    transitions: /STATUS_TRANSITIONS/.test(txt),
  }
}

// ── ③ DB 表 / 列 / 唯一约束 ──────────────────────────────
const TABLES = ['orders', 'order_items', 'order_shipments', 'order_shipment_items', 'order_logistics',
  'stock_ledger_entries', 'stock_batches', 'inbound_orders', 'client_request_keys', 'users', 'worker_sessions']
const tables = {}
for (const t of TABLES) {
  tables[t] = {
    columns: psql(`select column_name, data_type, is_nullable from information_schema.columns where table_name='${t}' order by ordinal_position`),
    uniqueIndexes: psql(`select indexname, indexdef from pg_indexes where tablename='${t}' and indexdef like '%UNIQUE%'`),
  }
}

// ── ④ 前端页面（发货相关）────────────────────────────────
const uiFiles = sh('bash', ['-lc',
  `cd ${JSON.stringify(src('frontend/admin-web/src'))} && grep -rl '发货\\|shipment\\|Shipment' --include=*.tsx app components 2>/dev/null | sort`],
).trim().split('\n').filter(Boolean)

// ── ⑤ 状态机（从唯一实现点逐字取）──────────────────────────
const transSrc = readFileSync(src('backend/admin-api/src/main/java/com/migao/admin/service/OrderStatusTransitions.java'), 'utf8')
const transBlock = (transSrc.match(/STATUS_TRANSITIONS = Map\.of\(([\s\S]*?)\);/) || [])[1] || ''
const transitions = {}
for (const m of transBlock.matchAll(/"(\w+)",\s*Set\.of\(([^)]*)\)/g)) {
  transitions[m[1]] = [...m[2].matchAll(/"(\w+)"/g)].map((x) => x[1])
}

// ── ⑥ 发货写面的可发状态 / 结算口径（从服务端逐字取）──────────
const svcSrc = readFileSync(src('backend/admin-api/src/main/java/com/migao/admin/service/OrderShipmentService.java'), 'utf8')
const shippableFrom = ((svcSrc.match(/SHIPPABLE_FROM = List\.of\(([^)]*)\)/) || [])[1] || '')
  .match(/"(\w+)"/g)?.map((s) => s.replace(/"/g, '')) || []

const surface = {
  enumeratedAt: nowCST(),
  tenantId: TENANT_ID,
  openapiPaths: Object.keys(docs.paths || {}).length,
  endpoints,
  javaFiles: javaHits,
  tables,
  uiFiles,
  statusMachine: { transitions, shippableFrom, packedIsItsOwnState: 'packed' in transitions },
  notes: [
    '发货有两个写入口：工人面 POST /api/worker/shipment/orders/{orderId}/ship（记实发明细）与商家/生产面 POST /api/admin/production/orders/{orderId}/ship（只记物流+流转状态，不写 order_shipment_items）',
    '发货单实体只有两张表：order_shipments（单据头）+ order_shipment_items（逐行实发）',
    '唯一约束：order_shipments 只有 (tenant_id, client_request_id) WHERE client_request_id IS NOT NULL AND deleted=0；order_shipment_items 无任何唯一约束',
  ],
}
writeFileSync(join(OUT, 'surface.json'), JSON.stringify(surface, null, 2))
log(`[p0] 枚举完成：endpoints=${endpoints.length} javaFiles=${Object.keys(javaHits).length} uiFiles=${uiFiles.length} tables=${TABLES.length}`)
log(`[p0] 状态机转移: ${JSON.stringify(transitions)}`)
log(`[p0] 可发货起始态: ${JSON.stringify(shippableFrom)}`)
console.log(JSON.stringify({
  endpoints: endpoints.map((e) => `${e.method} ${e.path}`),
  uiFiles, transitions, shippableFrom,
  shipItemsUnique: tables.order_shipment_items.uniqueIndexes.map((x) => x.indexname),
  shipUnique: tables.order_shipments.uniqueIndexes.map((x) => x.indexname),
}, null, 1))
