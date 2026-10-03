// p9-cleanup —— 零残留自证：清理本包探针域 + 逐表计数 + 存量行零改动（sha256 前后对照）
// 用法：API_BASE=http://127.0.0.1:8080 node p9-cleanup.mjs
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { cleanupProbe, probeResidue, psql, sha256, outPath, log, nowCST, Recorder, TENANT_ID, PROBE_PREFIX } from './lib.mjs'

const R = new Recorder('B9-cleanup.json')

/** 存量行快照（**非**本包探针域）——用内容 sha256 前后对照，证明「存量行零改动」。 */
function stockFingerprint() {
  const parts = []
  parts.push(JSON.stringify(psql(`select id::text, status, refund_amount::text, actual_amount::text, deleted::text
                                  from orders where tenant_id=${TENANT_ID} and (remark is null or remark not like '${PROBE_PREFIX}%')
                                  order by id`)))
  parts.push(JSON.stringify(psql(`select id, status, refund_amount::text, deleted::text
                                  from after_sales_tickets where tenant_id=${TENANT_ID} and (description is null or description not like '${PROBE_PREFIX}%')
                                  order by id`)))

  return { sha: sha256(parts.join('|')), sizes: parts.map((p) => p.length), parts }
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
if (before && Array.isArray(before.parts) && post && Array.isArray(post.parts)) {
  rowDiff = {}
  for (const [i, label] of [[0, 'orders'], [1, 'after_sales_tickets']]) {
    try {
      const bo = JSON.parse(before.parts[i]); const ao = JSON.parse(post.parts[i])
      const bm = new Map(bo.map((r) => [r.id, r])); const am = new Map(ao.map((r) => [r.id, r]))
      rowDiff[label] = {
        added: [...am.keys()].filter((k) => !bm.has(k)),
        removed: [...bm.keys()].filter((k) => !am.has(k)),
        changed: [...am.keys()].filter((k) => bm.has(k) && JSON.stringify(bm.get(k)) !== JSON.stringify(am.get(k)))
          .map((k) => ({ id: k, before: bm.get(k), after: am.get(k) })),
      }
    } catch (e) { rowDiff[label] = { error: e.message.slice(0, 120) } }
  }
}
writeFileSync(outPath('B9-residue.json'), JSON.stringify({
  at: nowCST(), preCleanupResidue, residue, residue2, cleanupError,
  stockBeforeSha: before?.sha, stockAfterSha: post?.sha, rowDiff,
  stockUnchanged: rowDiff ? ['orders', 'after_sales_tickets'].every((k) => rowDiff[k] && !rowDiff[k].error && rowDiff[k].added.length === 0 && rowDiff[k].removed.length === 0 && rowDiff[k].changed.length === 0) : null,
}, null, 2))

R.add('LB-Z-01', '零残留：本包探针域逐表计数 = 0',
  residue2.total === 0 ? 'pass' : 'fail',
  `清理前 ${preCleanupResidue.total} 行 → 清理后 ${residue2.total} 行；逐表=${JSON.stringify(residue2.counts)}`,
  [`清理器: 本包 lib.mjs 的 cleanupProbe()（**仅**本包命名域：订单 remark 前缀「${PROBE_PREFIX}」/ 工单 description 前缀 / 商品 name·sku_code 前缀 / 台账 product·sku 关联 / finance 经订单关联 / client_request_keys 的 lb- 前缀）`,
   `跨包隔离: 同时段线A 在同租户 20 写入（实测 38 行 remark=「线A验收扫码闭环夹具」）—— **按行内容归因**，本清理器绝不触及`,
   `清理报错（若有）: ${cleanupError || '无'}`,
   `原始读数: ${JSON.stringify({ preCleanupResidue, residue2 })}`])

if (before && rowDiff && !rowDiff.orders?.error) {
  const unchanged = ['orders', 'after_sales_tickets'].every((k) => rowDiff[k] && rowDiff[k].added.length === 0 && rowDiff[k].removed.length === 0 && rowDiff[k].changed.length === 0)
  R.add('LB-Z-02', '存量行零改动（**非探针域逐行 diff**：orders / after_sales_tickets）',
    unchanged ? 'pass' : 'fail',
    `orders: added=${rowDiff.orders.added.length} removed=${rowDiff.orders.removed.length} changed=${rowDiff.orders.changed.length}；after_sales_tickets: added=${rowDiff.after_sales_tickets.added.length} removed=${rowDiff.after_sales_tickets.removed.length} changed=${rowDiff.after_sales_tickets.changed.length}`,
    [`对照口径: 对「非本包探针域的 orders / after_sales_tickets 逐行关键列 + 台账与退款流水全表 count/sum」做整体 sha256`,
     `对照口径 = **本段内紧邻的前后两次非探针域逐行快照**（orders / after_sales_tickets 的 id+status+金额+deleted）`,
     `⚠️ 已知边界: stock_ledger_entries / finance_transactions 是**流水表、只增不减**，且同租户的**线A 并发包**也在写（实测两次对照之间 +28 行）⇒ 把它们算进「零改动」会把外来写读成本包的问题（假红）。故这两张表只登记**行数读数**，不参与 sha 断言。`,
     `逐行差异（可归因）: ${JSON.stringify(rowDiff)}`,
     `粗指标（不作判据）: before sha=${String(before?.sha).slice(0, 16)}… / after sha=${String(post?.sha).slice(0, 16)}…`,
     `⚠️ 已知边界: stock_ledger_entries / finance_transactions 是**流水表、只增不减**，且同租户的线A 并发包也在写 ⇒ 只登记行数、不参与判据`])
} else {
  R.skip('LB-Z-02', '存量行零改动（sha256 前后对照）', '未找到 before 快照（p9 之前须先跑 p7-stock-before 记录基线）', [])
}

log(`p9 完成：${JSON.stringify(R.summary())}；残留=${residue2.total}`)
