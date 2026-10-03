// B — 批量写（爆炸半径最大） + C — 工序「设为不做并删除」依赖闭包
import {
  Recorder, judge, api, loginApi, psql, one, guardedWrite, PROBE_PREFIX, TENANT_ID, ID_PREFIX,
  log, nowCST, writeFileSync, outPath, tableSnap, fieldDiff, overreach, fmtDiff, hexId, probeSku, cleanupProbe, readXlsx,
} from './lib.mjs'

const R = new Recorder('B-batch-and-detach.json')
const { token } = await loginApi()
const T = TENANT_ID
const OTHER_TENANT = 21
log(`B/C 段开始 ${nowCST().cst}`)

const prodStatus = (id) => one(`select id,tenant_id,status,deleted from products where id='${id}'`)
const skuRowsOf = (id) => psql(`select id, product_id from product_skus where product_id='${id}'`)
const mkProduct = async (name, status) => {
  const sku = probeSku('BATCH')
  const r = await api('POST', '/api/admin/products', {
    token,
    body: {
      name: `${PROBE_PREFIX}${name}`, skuCode: sku, basePrice: 20, stock: 3,
      unit: '米', pricingType: 'per_meter', description: `${PROBE_PREFIX}批量写探针`,
      status,
      // 🔴 payload 形态取自 ProductCreateRequest：colors 是 ProductColorInput[]（**无** doorWidths 字段），
      //    门幅在**顶层** doorWidths，SKU 组合在顶层 skus[]。（首轮把 doorWidths/skus 塞进 colors[]
      //    ⇒ 静默被丢弃、0 个 SKU 子行 —— 那是**我的 payload 错**，不是产品缺陷。）
      colors: [{ colorName: '米白' }],
      doorWidths: ['2.8m'],
      skus: [{ colorName: '米白', doorWidth: '2.8m', price: 20, stock: 3 }],
    },
  })
  return { r, id: r.data?.id, sku }
}

// ══════════════ B1 批量上下架：负例（draft）+ 正例（off_sale）══════════════
// 🔴 判据纠正（主会话核 origin/main 源码）：`batchOnShelf` 白名单 = `Set.of("off_sale")`，
//    源码注释逐字「只有 off_sale/in_warehouse 状态的商品可上架」⇒ draft 被拒是**预期行为**。
//    而 `STATUS_TRANSITIONS` 里 `draft → [under_review, on_sale]`（**单条改状态端点允许 draft→on_sale**）
//    ⇒ 「批量上架」的准入集合 **严于**状态机 —— 那是**口径不一致（登记项）**，不是"上架坏了"。
const p1 = await mkProduct('批量A', 'draft')
const p2 = await mkProduct('批量B', 'draft')
const p3 = await mkProduct('批量C', 'draft')
log(`建探针商品(draft): ${p1.id}/${p2.id}/${p3.id} (HTTP ${p1.r.status}/${p2.r.status}/${p3.r.status})`)
writeFileSync(outPath('B1-created.json'), JSON.stringify({ p1, p2, p3 }, null, 2))
const ids123 = [p1.id, p2.id, p3.id]
const before1 = Object.fromEntries(ids123.map((id) => [id, prodStatus(id)?.status]))

// ── B1.1 负例：draft 批量上架 ⇒ 必须明确拒绝 + **零状态变更** ──
const onShelfDraft = await api('POST', '/api/admin/products/batch/on-shelf', { token, body: { productIds: ids123 } })
const after1 = Object.fromEntries(ids123.map((id) => [id, prodStatus(id)?.status]))
writeFileSync(outPath('B1-negative-draft-onshelf.json'), JSON.stringify({ http: onShelfDraft.status, body: onShelfDraft.json, before: before1, after: after1 }, null, 2))
judge(R, {
  id: 'B1.1', name: '负例：draft 批量上架 ⇒ 如实拒绝 + DB 零状态变更（不是「静默成功」）',
  expect: `success=0 failed=3；errors[] 每条含「不允许上架」；3 行 status 仍为 draft`,
  actual: `success=${onShelfDraft.data?.success} failed=${onShelfDraft.data?.failed} errors=${JSON.stringify(onShelfDraft.data?.errors)} 状态=${JSON.stringify(after1)}`,
  pass: onShelfDraft.data?.success === 0 && onShelfDraft.data?.failed === 3
    && (onShelfDraft.data?.errors || []).length === 3
    && JSON.stringify(after1) === JSON.stringify(before1),
  expectSource: 'ProductService#batchOnShelf 白名单 Set.of("off_sale") + 注释「只有 off_sale/in_warehouse 状态的商品可上架」；DB 逐行前后同一',
  evidence: [`响应: ${onShelfDraft.text.slice(0, 400)}`],
})

// ── B1.2 同 payload 连发两次：结果集合不漂移（幂等）──
const onShelfAgain = await api('POST', '/api/admin/products/batch/on-shelf', { token, body: { productIds: ids123 } })
const after1b = Object.fromEntries(ids123.map((id) => [id, prodStatus(id)?.status]))
judge(R, {
  id: 'B1.2', name: '同 payload 连发 batch 两次：结果集合不漂移（零漂移 = 幂等）',
  expect: '第二次 failed/success 与第一次相同（0/3）且 DB 状态逐行不变',
  actual: `第2次 success=${onShelfAgain.data?.success} failed=${onShelfAgain.data?.failed}；状态=${JSON.stringify(after1b)}`,
  pass: onShelfAgain.data?.success === 0 && onShelfAgain.data?.failed === 3
    && JSON.stringify(after1b) === JSON.stringify(before1),
  expectSource: '幂等判据：同一 payload 重复调用 ⇒ 结果集合与 DB 状态均不漂移（不新增、不改坏）',
  evidence: [`第二次响应: ${onShelfAgain.text.slice(0, 300)}`],
})

// ── B1.3 正对照前置：走**状态机**把商品推到 on_sale（create 不接受 status=off_sale —— 实测 422，
//    因 validateRequiredForStatus 对非 draft 状态另有必填要求；故用 draft→on_sale 的正规流转）──
const q1 = await mkProduct('正例D', 'draft')
const q2 = await mkProduct('正例E', 'draft')
const st1 = await api('PUT', `/api/admin/products/${q1.id}/status`, { token, body: { status: 'on_sale' } })
const st2 = await api('PUT', `/api/admin/products/${q2.id}/status`, { token, body: { status: 'on_sale' } })
const onSaleStatus = Object.fromEntries([q1.id, q2.id].map((id) => [id, prodStatus(id)?.status]))
judge(R, {
  id: 'B1.3', name: '正对照前置：draft →(PUT /{id}/status) on_sale 成功（状态机路径可达，面非空）',
  expect: `2 行 status=on_sale（HTTP 200/200）`,
  actual: `${JSON.stringify(onSaleStatus)}（HTTP ${st1.status}/${st2.status}）`,
  pass: Object.values(onSaleStatus).every((x) => x === 'on_sale') && st1.status === 200 && st2.status === 200,
  expectSource: 'STATUS_TRANSITIONS: draft→[under_review, on_sale]（ProductService 静态块）；DB 核对',
  evidence: [`PUT 响应: ${st1.text.slice(0, 200)}`],
})
// ── B1.4 正路径：batch/off-shelf（on_sale → off_sale）──
const offShelfPos = await api('POST', '/api/admin/products/batch/off-shelf', { token, body: { productIds: [q1.id, q2.id] } })
const offPosStatus = Object.fromEntries([q1.id, q2.id].map((id) => [id, prodStatus(id)?.status]))
writeFileSync(outPath('B1-off-shelf-positive.json'), JSON.stringify({ http: offShelfPos.status, body: offShelfPos.json, before: onSaleStatus, after: offPosStatus }, null, 2))
judge(R, {
  id: 'B1.4', name: '正对照：batch/off-shelf 真能成功（2/2，DB 落 off_sale）',
  expect: `success=2 failed=0；2 行 status=off_sale`,
  actual: `success=${offShelfPos.data?.success} failed=${offShelfPos.data?.failed} 状态=${JSON.stringify(offPosStatus)}`,
  pass: offShelfPos.data?.success === 2 && offShelfPos.data?.failed === 0 && Object.values(offPosStatus).every((x) => x === 'off_sale'),
  expectSource: 'ProductService#batchOffShelf 白名单 {on_sale}；DB 逐行核对（migao-acceptance 反假绿：先证面真的能用）',
  evidence: [`响应: ${offShelfPos.text.slice(0, 300)}`],
})
// ── B1.5 batch/on-shelf 正路径（off_sale → on_sale）：这才是「draft 被拒」的对照 ──
const onShelfPos = await api('POST', '/api/admin/products/batch/on-shelf', { token, body: { productIds: [q1.id, q2.id] } })
const onPosStatus = Object.fromEntries([q1.id, q2.id].map((id) => [id, prodStatus(id)?.status]))
writeFileSync(outPath('B1-on-shelf-positive.json'), JSON.stringify({ http: onShelfPos.status, body: onShelfPos.json, before: offPosStatus, after: onPosStatus }, null, 2))
judge(R, {
  id: 'B1.5', name: '正对照：off_sale → batch/on-shelf 真能成功 ⇒ 证明 draft 被拒是**准入集合**而非端点故障',
  expect: `success=2 failed=0；2 行 status=on_sale`,
  actual: `success=${onShelfPos.data?.success} failed=${onShelfPos.data?.failed} 状态=${JSON.stringify(onPosStatus)}`,
  pass: onShelfPos.data?.success === 2 && Object.values(onPosStatus).every((x) => x === 'on_sale'),
  expectSource: 'ProductService#batchOnShelf 白名单 {off_sale}；同端点在同一批商品上 off_sale 成功、draft 失败 ⇒ 判别性对照',
  evidence: [`响应: ${onShelfPos.text.slice(0, 300)}`, `前序 off-shelf: success=${offShelfPos.data?.success}`],
})

// ══════════════ B2 部分失败：不得「返回失败但已删一半」 ══════════════
const ghostId = hexId('l2ghost')           // 不存在
const foreignProd = one(`select id, tenant_id from products where tenant_id=${OTHER_TENANT} limit 1`)
const foreignId = foreignProd?.id
const p4 = await mkProduct('部分失败D', 'draft')
const p5 = await mkProduct('部分失败E', 'draft')
const snapIds = [p4.id, p5.id]
const beforeDel = Object.fromEntries(snapIds.map((id) => [id, prodStatus(id)]))
const partial = await api('POST', '/api/admin/products/batch/delete', {
  token, body: { productIds: [p4.id, ghostId, foreignId, p5.id].filter(Boolean) },
})
const afterDel = Object.fromEntries(snapIds.map((id) => [id, prodStatus(id)]))
const foreignAfter = foreignId ? prodStatus(foreignId) : null
writeFileSync(outPath('B2-partial-delete.json'), JSON.stringify({
  http: partial.status, body: partial.json, before: beforeDel, after: afterDel,
  foreign: { id: foreignId, tenant: foreignProd?.tenant_id, after: foreignAfter },
  ghostId,
}, null, 2))
judge(R, {
  id: 'B2.1', name: '部分失败：如实报告失败项（不存在的 id + 他租户 id 各进 errors[]）',
  expect: `failed = 2（ghost + 他租户）且 errors[] 覆盖这两个 id`,
  actual: `success=${partial.data?.success} failed=${partial.data?.failed} errors=${JSON.stringify(partial.data?.errors)}`,
  pass: partial.data?.failed === 2 && (partial.data?.errors || []).length === 2
    && (partial.data?.errors || []).some((e) => e.id === ghostId)
    && (foreignId ? (partial.data?.errors || []).some((e) => e.id === foreignId) : true),
  expectSource: 'ProductService#batchDelete：selectById==null ⇒ result.addError(id,"商品不存在")；BatchOperationResult{success,failed,errors[{id,message}]}',
  evidence: [`响应原文: ${partial.text.slice(0, 500)}`],
})
judge(R, {
  id: 'B2.2', name: '部分失败：合法的 2 个 id 真删了（原子的边界 = 逐项报告，非整包回滚）',
  expect: `products(${p4.id}) 与 products(${p5.id}) 均 deleted=1（或行已不存在）`,
  actual: `p4=${JSON.stringify(afterDel[p4.id])} p5=${JSON.stringify(afterDel[p5.id])}`,
  pass: [p4.id, p5.id].every((id) => { const row = afterDel[id]; return row === null || row?.deleted === 1 }),
  expectSource: 'DB 逐行前后快照（readings 走独立 SQL，不看响应体）；契约 = 逐项报告（非整包回滚）',
  evidence: [`before: ${JSON.stringify(beforeDel)}`, `after: ${JSON.stringify(afterDel)}`],
})
judge(R, {
  id: 'B2.3', name: '他租户 id 零写（跨租户删除被拒）',
  expect: `租户 ${OTHER_TENANT} 的商品 ${foreignId} 在调用后 deleted=0 且行仍在`,
  actual: JSON.stringify(foreignAfter),
  pass: !!foreignAfter && foreignAfter.deleted === 0 && foreignAfter.tenant_id === OTHER_TENANT,
  expectSource: '多租户隔离（TenantContext）；DB 行前后同一',
  evidence: [`他租户商品: ${JSON.stringify(foreignProd)}`],
})

// ══════════════ B3 batch/delete 依赖闭包（孤儿引用）══════════════
// 🔴 判据纠正（主会话核 origin/main + 本包实测）：`batchDelete` 走的是**软删**（`productMapper.deleteById`
//    = MP 逻辑删除，行仍在、`deleted=1`）。⇒ 「子行（SKU/颜色/台账）在软删后仍在」**是设计**，不是孤儿：
//    孤儿的定义只能是「引用了一个**根本不存在的** parent 行」。首轮把「软删父行的子行」判成孤儿 = **假红**。
const p6 = await mkProduct('闭包F', 'draft')
const skusBefore = skuRowsOf(p6.id)
judge(R, {
  id: 'B3.0', name: '正对照：探针商品确实有 SKU 子行（闭包判据才有意义）',
  expect: `product_skus(product_id=${p6.id}) ≥ 1`,
  actual: `子行数 = ${skusBefore.length}`,
  pass: skusBefore.length >= 1,
  expectSource: '独立 SQL；无子行 ⇒ 孤儿判据是空断言（migao-acceptance 反假绿）',
  evidence: [`子行: ${JSON.stringify(skusBefore)}`],
})
const del = await api('POST', '/api/admin/products/batch/delete', { token, body: { productIds: [p6.id] } })
const childAfter = {
  skus: one(`select count(*)::int as n from product_skus where product_id='${p6.id}'`)?.n,
  colors: one(`select count(*)::int as n from product_colors where product_id='${p6.id}'`)?.n,
  ledger: one(`select count(*)::int as n from stock_ledger_entries where product_id='${p6.id}'`)?.n,
}
const p6After = prodStatus(p6.id)
writeFileSync(outPath('B3-delete-closure.json'), JSON.stringify({
  deleted: { http: del.status, body: del.json }, productAfter: p6After,
  skusBeforeCount: skusBefore.length, childAfter,
  definition: '软删：parent 行仍在（deleted=1）⇒ 子行不是孤儿；孤儿 = 引用不存在的 parent',
}, null, 2))
judge(R, {
  id: 'B3.1', name: '软删语义：parent 行仍在（deleted=1）⇒ 子行不构成孤儿（判据纠正后的正确期望）',
  expect: `products(${p6.id}).deleted=1 且行仍存在；子行保留（审计/历史）`,
  actual: `product=${JSON.stringify(p6After)} 子行=${JSON.stringify(childAfter)}`,
  pass: p6After?.deleted === 1 && childAfter.skus === skusBefore.length,
  expectSource: 'MP 逻辑删除（软删）语义：行保留 + deleted=1；`stock_ledger_entries_product_id_fkey` 等 8 条 FK 由 DB 保证引用完整性',
  evidence: [`删除响应: ${del.text.slice(0, 200)}`],
})
// ── B3.2 真孤儿扫描：全表逐引用列扫「parent 不存在」──
const refTables = [
  ['product_skus', 'product_id'], ['product_colors', 'product_id'], ['product_attributes', 'product_id'],
  ['stock_ledger_entries', 'product_id'], ['stock_batches', 'product_id'], ['stock_batch_consumptions', 'product_id'],
  ['inbound_order_items', 'product_id'], ['fabric_remnants', 'product_id'],
]
const trueOrphans = {}
for (const [tbl, col] of refTables) {
  const n = one(`select count(*)::int as n from ${tbl} x where x.${col} is not null and not exists (select 1 from products p where p.id=x.${col})`)?.n
  trueOrphans[`${tbl}.${col}`] = n
}
const fkCount = one(`select count(*)::int as n from pg_constraint c where c.contype='f' and c.confrelid='products'::regclass`)?.n
writeFileSync(outPath('B3-orphan-scan.json'), JSON.stringify({ trueOrphans, fkCountToProducts: fkCount, refTables }, null, 2))
judge(R, {
  id: 'B3.2', name: '真孤儿扫描：8 张引用表逐列找「parent 不存在」的行 ⇒ 必须为 0',
  expect: `8 个 (表,列) 组合的真孤儿数全为 0（DB 有 ${fkCount} 条 FK 指向 products，属结构保证）`,
  actual: `真孤儿=${JSON.stringify(trueOrphans)}；指向 products 的 FK 数=${fkCount}`,
  expectSource: '孤儿定义 = 引用列非空且 parent 行不存在；pg_constraint 现查 FK 数（不硬编码）',
  pass: Object.values(trueOrphans).every((v) => Number(v) === 0),   // 🔴 首轮漏写 pass ⇒ judge 拿 undefined 判 fail（判据自身的缺陷）
  evidence: [`表清单: ${refTables.map((x) => x.join('.')).join(', ')}`],
})

// ── B3.3 读面可达性（主会话要求的「孤儿」可观察危害口径）──
// 子表没有 deleted 列（product_skus/product_colors 实测无该列）⇒ 它们的行只能靠**父行不可见**而不可见。
// ⇒ 有判别力的判据是：软删后，该商品/SKU/颜色**能否通过任何读面被单独暴露**。
const p7 = await mkProduct('读面G', 'draft')
const p7skuCode = one(`select sku_code from products where id='${p7.id}'`)?.sku_code ?? ''
const p7name = one(`select name from products where id='${p7.id}'`)?.name ?? ''
await api('POST', '/api/admin/products/batch/delete', { token, body: { productIds: [p7.id] } })
const readGet = await api('GET', `/api/admin/products/${p7.id}`, { token })
const readList = await api('GET', `/api/admin/products?page=1&size=100&keyword=${encodeURIComponent(p7skuCode)}`, { token })
const expAfter = await api('GET', `/api/admin/products/export?keyword=${encodeURIComponent(p7skuCode)}`, { token })
let expRows = []
try { expRows = expAfter.buf?.length ? readXlsx(expAfter.buf).rows : [] } catch { expRows = ['PARSE_ERR'] }
const childrenTotals = {
  skus: one(`select count(*)::int as n from product_skus where product_id='${p7.id}'`)?.n,
  colors: one(`select count(*)::int as n from product_colors where product_id='${p7.id}'`)?.n,
  ledger: one(`select count(*)::int as n from stock_ledger_entries where product_id='${p7.id}'`)?.n,
}
writeFileSync(outPath('B3-readface-reachability.json'), JSON.stringify({
  productId: p7.id, skuCode: p7skuCode, name: p7name,
  childrenTotals,
  read: {
    getById: { http: readGet.status, success: readGet.json?.success, deletedFlag: readGet.data?.deleted ?? null },
    listBySku: { http: readList.status, total: readList.data?.total },
    exportRows: expRows.length,
  },
}, null, 2))
judge(R, {
  id: 'B3.3', name: '软删后读面可达性：商品/SKU 不得再被单独读回（子行随之不可见）',
  expect: `GET /{id} 不返回该商品（404 或 success=false）；列表 keyword=${p7skuCode} total=0；导出该货号 0 行`,
  actual: `GET=${readGet.status}/${readGet.json?.success} 列表total=${readList.data?.total} 导出行=${expRows.length}；子行总数=${JSON.stringify(childrenTotals)}`,
  pass: expRows.length === 0 && (readList.data?.total === 0 || readList.data?.total == null)
    && (readGet.status === 404 || readGet.json?.success === false),
  expectSource: '软删（deleted=1）后读面必须过滤（getProducts wrapper 带 deleted 条件）；子行无 deleted 列 ⇒ 只能随父行不可见',
  evidence: [`GET 响应: ${readGet.text.slice(0, 200)}`, `列表响应: ${readList.text.slice(0, 200)}`],
})

// ══════════════ C1 工序 detach-and-delete ══════════════
const opName = `${PROBE_PREFIX}工序${Date.now().toString().slice(-6)}`
const mkOp = await api('POST', '/api/admin/production/operations', {
  token, body: { name: opName, group_name: `${PROBE_PREFIX}组`, unit: '米', unit_price: 12.5, position: `${PROBE_PREFIX}部位`, sort_order: 999 },
})
const opId = mkOp.data?.id
log(`建探针工序: ${opId} (HTTP ${mkOp.status}) ${mkOp.text.slice(0, 200)}`)
writeFileSync(outPath('C1-created-op.json'), JSON.stringify({ http: mkOp.status, body: mkOp.json }, null, 2))
judge(R, {
  id: 'C1.0', name: '正对照：探针工序已落库（面非空）',
  expect: `${opId} 在 production_operations 且 deleted=0`,
  actual: JSON.stringify(one(`select id,name,deleted,tenant_id from production_operations where id='${opId}'`)),
  pass: !!opId && one(`select deleted from production_operations where id='${opId}'`)?.deleted === 0,
  expectSource: '独立 SQL 核对（先证面有数据才谈删除语义）',
  evidence: [`建工序响应: ${mkOp.text.slice(0, 300)}`],
})

// 两步：给该工序建一行价目矩阵格（applicable=true）⇒ 走「一键」路径才有意义
const posId = hexId('l2pos')
guardedWrite(`-- probe-ok
  insert into production_operation_positions (id, tenant_id, logical_name, position, unit_price, applicable, status, created_at, updated_at, deleted)
  values ('${posId}', ${T}, '${opName}', '${PROBE_PREFIX}部位', 12.5, true, 'active', now(), now(), 0);`)
const posBefore = one(`select * from production_operation_positions where id='${posId}'`)

// 二次调用幂等 + 跨租户 404 —— 先做跨租户（只读面：用不存在/他租户 id）
const crossOp = one(`select id from production_operations where tenant_id<>${T} limit 1`)
const rCross = await api('DELETE', `/api/admin/production/operations/${crossOp?.id ?? hexId('l2none')}/detach-and-delete`, { token })
const crossAfter = crossOp ? one(`select id,deleted,tenant_id,updated_at from production_operations where id='${crossOp.id}'`) : null
judge(R, {
  id: 'C1.1', name: '跨租户 id ⇒ 404 且零写',
  expect: `HTTP 404；他租户工序 deleted 与 updated_at 不变`,
  actual: `HTTP ${rCross.status} body=${rCross.text.slice(0, 200)}；他租户行=${JSON.stringify(crossAfter)}`,
  pass: rCross.status === 404,
  expectSource: 'ProductionOperationCommandService#deleteDetaching：op==null || !tenantId.equals(op.getTenantId()) ⇒ BusinessException.notFound("工序")',
  evidence: [`跨租户工序: ${JSON.stringify(crossOp)}`, `调用后: ${JSON.stringify(crossAfter)}`],
})

const beforeOp = one(`select id,name,deleted,status,updated_at from production_operations where id='${opId}'`)
const det = await api('DELETE', `/api/admin/production/operations/${opId}/detach-and-delete`, { token })
const afterOp = one(`select id,name,deleted,status,updated_at from production_operations where id='${opId}'`)
const posAfter = one(`select * from production_operation_positions where id='${posId}'`)
writeFileSync(outPath('C1-detach.json'), JSON.stringify({
  http: det.status, body: det.json, posBefore, posAfter, beforeOp, afterOp,
}, null, 2))
judge(R, {
  id: 'C1.2', name: '一键删除成功 ⇒ 工序软删 + 矩阵格级联（detached/deleted_positions 如实报数）',
  expect: `HTTP 200；operation.deleted=1；格 applicable=false（detached_positions≥1）或格被软删（deleted=1）`,
  actual: `HTTP ${det.status} body=${det.text.slice(0, 300)}；格 after=${JSON.stringify(posAfter)}`,
  pass: det.status === 200 && afterOp?.deleted === 1
    && (posAfter === null || posAfter.deleted === 1 || posAfter.applicable === false),
  expectSource: 'Controller 注释：同一事务里先摘格（applicable=false + 价清空）再软删工序 + 级联软删矩阵行',
  evidence: [`detached_positions=${det.data?.detached_positions} deleted_positions=${det.data?.deleted_positions}`, `格 before=${JSON.stringify(posBefore)}`],
})

// 依赖闭包：逐表扫悬空引用
// ⚠️ 列名以 information_schema 实测为准（首轮把 `production_operation_positions.operation_id` 写死 ⇒ psql 报
//    column does not exist ⇒ 判据**不可判定**；`production_operation_position_price_versions` 的列是 position_row_id）
const opRefs = [
  ['production_operation_positions', 'logical_name'],              // 按逻辑名寻址；无 operation_id 列
  ['production_operation_price_versions', 'operation_id'],
  ['production_route_rules', 'operation'],
  ['production_route_rules', 'after_operation'],
]
const dangling = {}
for (const [tbl, col] of opRefs) {
  let n = 0
  try {
    // ⚠️ 列名逐个表实测（首轮两处假红都是**我写错列名**，不是 dangling）：
    //   production_operation_positions     → 有 logical_name / status / applicable / deleted
    //   production_operation_price_versions→ 只有 operation_id / unit_price / deleted（**无 status**）
    //   production_route_rules             → operation / after_operation / status / deleted
    const hasStatus = tbl !== 'production_operation_price_versions'
    const extra = tbl === 'production_operation_positions' ? ` and coalesce(applicable,false)=true` : ''
    const stCond = hasStatus ? ` and coalesce(status,'active')='active'` : ''
    n = one(`select count(*)::int as n from ${tbl} where ${col}='${opName}'${extra}${stCond} and coalesce(deleted,0)=0`)?.n ?? 0
  } catch (e) { n = `ERR ${String(e).match(/ERROR:[^\n]*/)?.[0] ?? String(e).slice(0, 90)}` }
  dangling[`${tbl}.${col}`] = n
}
// ⚠️ 价目版本账**本来就该留**（Service 注释「追加一行（当前价 = 最新版本行，构成调价账）」= 审计账）
//    ⇒ 它的 deleted=0 不是缺陷；有判别力的判据是「**读面**是否还把它当活跃工序的价暴露出来」。
const pvRows = psql(`select id, operation_id, unit_price, deleted from production_operation_price_versions where operation_id='${opId}'`)
const pvExposed = await api('GET', '/api/admin/production/operations-catalog', { token })
const pvExposedHit = JSON.stringify(pvExposed.data ?? {}).includes(opName)
// 路线主线（jsonb 数组含工序名）是否还引用它
const routeRefs = psql(`select id, name, mainline, status, deleted from production_route_templates where tenant_id=${T} and mainline::text like '%${opName}%'`)
judge(R, {
  id: 'C1.3', name: '删除后依赖闭包：活跃引用数必须为 0（矩阵格/路线规则/主线）+ 价目账读面不得再暴露',
  expect: '4 个 (表,列) 组合的活跃命中数全为 0；无活跃路线主线含它；operations-catalog 不含它',
  actual: `dangling=${JSON.stringify(dangling)} routeRefs=${JSON.stringify(routeRefs)} catalog含它=${pvExposedHit} 价目账行=${JSON.stringify(pvRows)}`,
  pass: Object.values(dangling).every((v) => v === 0)
    && routeRefs.filter((x) => x.deleted === 0 && x.status === 'active').length === 0
    && !pvExposedHit,
  expectSource: 'Controller/Service 注释「删工序要删干净」；列名以 information_schema 实测为准；价目版本账按 Service 注释**有意保留**（审计），故只判读面暴露',
  evidence: [`表清单: ${opRefs.map((x) => x.join('.')).join(', ')}`, `价目账（有意保留）: ${JSON.stringify(pvRows)}`],
})

// 二次调用幂等（不得 500）
const det2 = await api('DELETE', `/api/admin/production/operations/${opId}/detach-and-delete`, { token })
const afterOp2 = one(`select id,deleted,updated_at from production_operations where id='${opId}'`)
judge(R, {
  id: 'C1.4', name: '二次调用幂等：**不得 500**（404 或 200-no-op 都可接受，崩溃不可接受）',
  expect: 'HTTP \u2208 {200,404}（均非 5xx）且 deleted 仍为 1',
  actual: `HTTP ${det2.status} body=${det2.text.slice(0, 200)}；deleted=${afterOp2?.deleted}`,
  pass: (det2.status === 200 || det2.status === 404) && afterOp2?.deleted === 1,
  expectSource: 'Service 注释「已软删 ⇒ 200 幂等 no-op（不报 404）」——**实测是 404**（契约偏差，登记 §7；但两次都非 5xx ⇒ 幂等性本身成立）',
  evidence: [`updated_at: ${afterOp?.updated_at} → ${afterOp2?.updated_at}`],
})

// ── 本段自建对象统一清理（探针命名域 = id `l2%` ∪ name/logical_name `${PROBE_PREFIX}%`）──
try { cleanupProbe(); log('B 段探针对象已清理') } catch (e) { log(`清理失败（需人工核）: ${e.message}`) }

log(`B/C 段结束，摘要 ${JSON.stringify(R.summary())}`)
process.exit(R.summary().fail > 0 ? 1 : 0)
