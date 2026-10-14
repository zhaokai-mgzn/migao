// p9-cleanup —— 零残留自证：清理本包探针域 + 逐表计数 + 存量行零改动（sha256 前后对照）
// 用法：API_BASE=http://127.0.0.1:8080 node p9-cleanup.mjs
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { cleanupProbe, probeResidue, psql, one, sha256, outPath, log, nowCST, Recorder, TENANT_ID, PROBE_PREFIX } from './lib.mjs'

const R = new Recorder('B9-cleanup.json')

// ── 存量行快照（**非**本包探针域）—— 用内容 sha256 前后对照，证明「存量行零改动」──
// 🔴 修 #6938（类级病：**跨包写面未命名空间化**）：原判据只对「本包探针域」做豁免
//    （`remark not like '<PROBE_PREFIX>%'`），对**流水表**另有豁免，却**漏了 `orders`** ⇒
//    同租户的**并行包**（线① 工人/批量、线② 配置/计件）在同一窗口写入的订单被读成本线改动
//    ⇒ LB-Z-02 判红，而 added 的 2 行 `customer_name='工序验收客户077598'` **不是**本线命名域
//    （实测 2026-10-14 20:32:22 / 20:32:25 +08，见 2026-10-14 线③ REPORT §3-G2）。
//    修法与流水表同款口径：把**别线的命名域**一并排除（对 `orders.customer_name` / `remark` 两列都判），
//    并**逐条登记「排除了什么」**（归属可复核 ⇒ 排除不是障眼法）。
//    ⚠️ 覆盖面 = 下面这张**逐条登记**的清单（不是时间窗豁免：时间窗会把本线自己的真改动一起放过）。
//    清单外的外来命名域一律**判红并具名** ⇒ 出现新写面时当场可见、当场补登记（fail-loud，不静默）。
const FOREIGN_NAMESPACES = [
  '工序验收',   // 线①/线② 工序写面探针（2026-10-14 实测 max 44 行）
  '工资验收',   // 计件工资写面探针
  '设置验收',   // 配置写面探针
  '路线验收',   // 工艺路线写面探针
  '写面验收',   // 配置/写面横切探针
  '改价漂移',   // 改价漂移探针
  '红证',       // 红证注入探针（跨包共用词，非本线）
  '冒烟路线',   // smoke 路由探针
  'smoke-',     // smoke 客户（写面冒烟）
  '成品窗',     // smoke 商品「窗帘成品」，其订单随商品名
]
const stripProbes = () => {
  if (!PROBE_PREFIX) throw new Error('PROBE_PREFIX 为空 ⇒ 「非本包探针域」无法定义（fail-closed）')
  return `${PROBE_PREFIX}%`.replace(/'/g, "''")
}
const foreignPatterns = FOREIGN_NAMESPACES.map((p) => `${p}%`.replace(/'/g, "''"))
if (foreignPatterns.length === 0) throw new Error('FOREIGN_NAMESPACES 为空 ⇒ 跨包豁免清单被清空（fail-closed）')
// 🔴 `NOT <NULL>` 求值仍是 NULL ⇒ 三值逻辑会把「该列）为空」的行**整行丢掉**（实测：orders 参与对照数
//    被读成 0），所以两侧都用 coalesce 收敛成确定布尔（这是本次自查抓到的第二个装置缺陷）。
const likeAny = (col) => `coalesce(${col} LIKE ANY (ARRAY['${foreignPatterns.join("','")}']::text[]), false)`

function stockFingerprint() {
  const parts = []
  // orders：排除「本包探针域」+「已登记的别线命名域」（customer_name / remark 两列）
  parts.push(JSON.stringify(psql(`select id::text, status, refund_amount::text, actual_amount::text, deleted::text
                                  from orders where tenant_id=${TENANT_ID}
                                   and (remark is null or remark not like '${stripProbes()}')
                                   and not ${likeAny('customer_name')}
                                   and not ${likeAny('remark')}
                                  order by id`)))
  parts.push(JSON.stringify(psql(`select id, status, refund_amount::text, deleted::text
                                  from after_sales_tickets where tenant_id=${TENANT_ID} and (description is null or description not like '${stripProbes()}')
                                  order by id`)))
  // 归属自证：快照的**规模**（参与对照的行数）+ 被排除的别线命名域逐条计数（不是只看一个 sha）
  const attribution = psql(`select coalesce(customer_name,'(null)') as name, count(*)::int as n from orders
                             where tenant_id=${TENANT_ID} and (${FOREIGN_NAMESPACES.map((p) => `customer_name like '${p.replace(/'/g, "''")}%'`).join(' or ')})
                             group by 1 order by 2 desc`)
  // 空集守卫（#6938）：**参与对照的行数为 0 时，added/removed/changed 三项必然全 0 —— 那是恒等、不是证据**。
  const totalOrders = one(`select count(*)::int as n from orders where tenant_id=${TENANT_ID}`)?.n
  const totalTickets = one(`select count(*)::int as n from after_sales_tickets where tenant_id=${TENANT_ID}`)?.n
  const coverage = { orders: JSON.parse(parts[0]).length, tickets: JSON.parse(parts[1]).length, totalOrders, totalTickets }
  return { sha: sha256(parts.join('|')), sizes: parts.map((p) => p.length), parts, attribution, coverage }
}
/** 逐行 diff（orders / after_sales_tickets）—— 判据本体。 */
function rowDiffOf(before, after) {
  const diff = {}
  for (const [i, label] of [[0, 'orders'], [1, 'after_sales_tickets']]) {
    try {
      const bo = JSON.parse(before.parts[i]); const ao = JSON.parse(after.parts[i])
      const bm = new Map(bo.map((r) => [r.id, r])); const am = new Map(ao.map((r) => [r.id, r]))
      diff[label] = {
        added: [...am.keys()].filter((k) => !bm.has(k)),
        removed: [...bm.keys()].filter((k) => !am.has(k)),
        changed: [...am.keys()].filter((k) => bm.has(k) && JSON.stringify(bm.get(k)) !== JSON.stringify(am.get(k)))
          .map((k) => ({ id: k, before: bm.get(k), after: am.get(k) })),
      }
    } catch (e) { diff[label] = { error: e.message.slice(0, 120) } }
  }
  return diff
}
/** 逐条守卫：任一条为红 ⇒ LB-Z-02 判 fail；**空集**（任一张表在对照集里 0 行）⇒ 判 skip（恒等不是证据）。 */
function guardsOf(before, after, rowDiff) {
  const emptySet = before.coverage.orders === 0 || before.coverage.tickets === 0
  const emptyTables = [['orders', before.coverage.orders], ['after_sales_tickets', before.coverage.tickets]]
    .filter(([, n]) => n === 0).map(([t]) => t)
  const attrOf = (fp) => Object.fromEntries((fp.attribution ?? []).map((r) => [r.name, r.n]))
  const a0 = attrOf(before); const a1 = attrOf(after)
  const attrKeys = [...new Set([...Object.keys(a0), ...Object.keys(a1)])].sort()
  const attrChanged = attrKeys.filter((k) => (a0[k] ?? 0) !== (a1[k] ?? 0)).map((k) => ({ name: k, before: a0[k] ?? 0, after: a1[k] ?? 0 }))
  return {
    emptySet,
    emptyTables,
    rowDiffClean: ['orders', 'after_sales_tickets'].every((k) => rowDiff[k] && !rowDiff[k].error
      && rowDiff[k].added.length === 0 && rowDiff[k].removed.length === 0 && rowDiff[k].changed.length === 0),
    foreignAttrStable: attrChanged.length === 0,
    foreignAttrChanged: attrChanged,
    foreignRowTotal: Object.values(a1).reduce((a, b) => a + b, 0),
  }
}

// 🔴 「存量行零改动」的判据必须取**本段内紧邻的 before/after**：
//    实测教训 —— 用 p8 的历史快照与 p9 的现快照比，会读到**别的包**（线A，id 前缀 `laord…`）中途清理掉的
//    55 行 `orders` ⇒ added/removed 非空 ⇒ **假红**（那 55 行从来不属于本包）。跨包隔离铁律：外来变化必须归因。
const before = stockFingerprint()
const preCleanupResidue = probeResidue()
let cleanupError = null
try { cleanupProbe() } catch (e) { cleanupError = e.message }
const residue = probeResidue()
// 兜底：若仍有残留，再清一次并复读（清理器缺陷要**当场可见**，不静默）
let residue2 = residue
if (residue.total !== 0) {
  try { cleanupProbe() } catch (e) { cleanupError = (cleanupError || '') + ' | retry: ' + e.message }
  residue2 = probeResidue()
}
const post = stockFingerprint()
// 逐行差异（**可归因**）：这才是「存量行零改动」的**判据本体**（sha 只作粗指标，
// ⚠️ 实测过一次 sha 不等但逐行 diff 全 0 —— 差异来自**参与对照的部件本身**在两次运行间不同，
//   故判据落在**逐行 diff** 上：added/removed/changed 三项全空才算零改动）。
let rowDiff = null
if (before && Array.isArray(before.parts) && post && Array.isArray(post.parts)) rowDiff = rowDiffOf(before, post)
const guards = rowDiff ? guardsOf(before, post, rowDiff) : null
writeFileSync(outPath('B9-residue.json'), JSON.stringify({
  at: nowCST(), preCleanupResidue, residue, residue2, cleanupError,
  stockBeforeSha: before?.sha, stockAfterSha: post?.sha, rowDiff, guards,
  foreignNamespaces: FOREIGN_NAMESPACES,
  foreignAttribution: { before: before?.attribution, after: post?.attribution },
  coverage: { before: before?.coverage, after: post?.coverage },
  stockUnchanged: guards ? (guards.rowDiffClean && guards.foreignAttrStable) : null,
}, null, 2))

R.add('LB-Z-01', '零残留：本包探针域逐表计数 = 0',
  residue2.total === 0 ? 'pass' : 'fail',
  `清理前 ${preCleanupResidue.total} 行 → 清理后 ${residue2.total} 行；逐表=${JSON.stringify(residue2.counts)}`,
  [`清理器: 本包 lib.mjs 的 cleanupProbe()（**仅**本包命名域：订单 remark 前缀「${PROBE_PREFIX}」/ 工单 description 前缀 / 商品 name·sku_code 前缀 / 台账 product·sku 关联 / finance 经订单关联 / client_request_keys 的 lb- 前缀）`,
   `跨包隔离: 同时段线A 在同租户 20 写入（实测 38 行 remark=「线A验收扫码闭环夹具」）—— **按行内容归因**，本清理器绝不触及`,
   `清理报错（若有）: ${cleanupError || '无'}`,
   `原始读数: ${JSON.stringify({ preCleanupResidue, residue2 })}`])

// ── LB-Z-02（#6938 修：三态 + 空集守卫 + 归属守卫）──
const Z02_EVIDENCE = (rd, gd) => [
  `对照口径 = **本段内紧邻的前后两次**快照，且**只保留归属可判的行**：排除「本包探针域」+ 已登记的别线命名域 ${JSON.stringify(FOREIGN_NAMESPACES)}（orders 侧判 customer_name / remark 两列）`,
  `⚠️ 豁免**不是时间窗**：时间窗会把本线自己的真改动一起放过；本口径只按**命名空间**排除，本线探针行的任何改动照样判红`,
  `⚠️ 豁免覆盖面（可复核）: 清单只覆盖**已登记的写面**；清单外的外来命名域一律计入对照 ⇒ 判红并具名（出现新写面 ⇒ 当场可见、当场补登记，不静默放过）`,
  `参与对照的行数（orders/tickets）= ${gd ? `${before.coverage.orders}/${before.coverage.tickets}` : '?'}（租户内全量 orders=${gd ? before.coverage.totalOrders : '?'} / tickets=${gd ? before.coverage.totalTickets : '?'}）`,
  `别线命名域逐行归属计数（before → after）: ${JSON.stringify(before?.attribution)} → ${JSON.stringify(post?.attribution)}`,
  `逐行差异（可归因）: ${JSON.stringify(rd)}`,
  `粗指标（不作判据）: before sha=${String(before?.sha).slice(0, 16)}… / after sha=${String(post?.sha).slice(0, 16)}…`,
  `⚠️ 已知边界: stock_ledger_entries / finance_transactions 是**流水表、只增不减**，且同租户的**线A 并发包**也在写（实测两次对照之间 +28 行）⇒ 这两张表只登记行数读数，不参与断言`,
]
if (guards) {
  const counts = `orders: added=${rowDiff.orders.added.length} removed=${rowDiff.orders.removed.length} changed=${rowDiff.orders.changed.length}；after_sales_tickets: added=${rowDiff.after_sales_tickets.added.length} removed=${rowDiff.after_sales_tickets.removed.length} changed=${rowDiff.after_sales_tickets.changed.length}`
  if (guards.emptySet) {
    // 🔴 空集守卫：参与对照的行数为 0 时，added/removed/changed 三项**必然**全 0 —— 那是恒等，不是证据。
    //    宁可**如实 skip 并印出来**，也不把空集折算成 pass（migao-acceptance：空集无判别力）。
    R.skip('LB-Z-02', '存量行零改动（非本包探针域逐行 diff：orders / after_sales_tickets）',
      `**空集 ⇒ 无法判定**：排除本包探针域与已登记的别线命名域后，参与对照的行数为 0 的表 = ${JSON.stringify(guards.emptyTables)}` +
      `（租户内全量 orders=${before.coverage.totalOrders} / tickets=${before.coverage.totalTickets}；对照集 orders=${before.coverage.orders} / tickets=${before.coverage.tickets}）` +
      `⇒ 该表 added/removed/changed **必然**全 0，是恒等而非证据。本判据只在**每张表都非空**时才有判别力；` +
      `重启条件：该表出现归属本线（探针域内）或归属未登记的存量行时 —— 正常一轮含建单的 sweep 天然满足`)
    log('  ↳ LB-Z-02 判 skip（空集无判别力），逐条守卫与归属读数见 B9-residue.json::guards / ::foreignAttribution')
  } else {
    R.add('LB-Z-02', '存量行零改动（非本包探针域逐行 diff：orders / after_sales_tickets）',
      guards.rowDiffClean && guards.foreignAttrStable ? 'pass' : 'fail',
      `${counts}；别线命名域归属漂移=${guards.foreignAttrStable ? '无' : JSON.stringify(guards.foreignAttrChanged)}`,
      Z02_EVIDENCE(rowDiff, guards))
  }
} else {
  R.skip('LB-Z-02', '存量行零改动（非本包探针域逐行 diff）', '未取到 before/after 快照（stockFingerprint 失败）', [])
}

log(`p9 完成：${JSON.stringify(R.summary())}；残留=${residue2.total}`)
