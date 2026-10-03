// 线③ —— 现状只读枚举（recon）。不改任何数据。
// 目标：把「面存在 / 不存在」「期望值从哪来」问清楚，再写断言。
import { loginApi, api, buildPoint, psql, one, log, OUT, TENANT_ID, nowCST, tsBoth } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const bp = buildPoint()
log(`构建点: ${bp.worktree} @ ${bp.sha} (${bp.commitTime}) pid=${bp.adminApiPid} start=${bp.adminApiStart} jvmTz=${bp.jvmTz}`)
writeFileSync(join(OUT, 'buildpoint.json'), JSON.stringify(bp, null, 2))

const { token } = await loginApi()
log(`登录 OK（租户 ${TENANT_ID}，${nowCST().cst}）`)

const probe = async (name, method, path, body) => {
  const r = await api(method, path, { token, body })
  const brief = JSON.stringify(r.data ?? r.json).slice(0, 600)
  log(`── ${name}: ${method} ${path} → HTTP ${r.status} ${brief}`)
  return r
}

// ── A. 财务 / 结算 / 发放 / 导出 ────────────────────────────────
log('═══ A. 计件收尾段（结算/发放/导出）面枚举 ═══')
await probe('finance summary', 'GET', '/api/admin/finance/summary')
await probe('finance txn page', 'GET', '/api/admin/finance/transactions?page=1&size=3')
await probe('finance reconciliation', 'GET', '/api/admin/finance/reconciliation?page=1&size=3')
for (const p of [
  '/api/admin/finance/settlements', '/api/admin/finance/payouts', '/api/admin/finance/export',
  '/api/admin/finance/transactions/export', '/api/admin/production/piecework/settlements',
  '/api/admin/production/piecework/export', '/api/admin/production/settlements',
  '/api/admin/production/payouts', '/api/admin/piecework/summary?period=2026-09',
]) await probe('探面', 'GET', p)

// ── B. 库存下游面枚举 ──────────────────────────────────────────
log('═══ B. 库存下游面枚举 ═══')
await probe('batch batches', 'GET', '/api/admin/batch-stock/batches?onlyAvailable=true')
await probe('batch distribution', 'GET', '/api/admin/batch-stock/distribution')
await probe('batch reconcile', 'GET', '/api/admin/batch-stock/reconcile')
await probe('batch candidates', 'GET', '/api/admin/batch-stock/candidates')
await probe('batch consumptions', 'GET', '/api/admin/batch-stock/consumptions?page=1&size=3')
await probe('saving-board', 'GET', '/api/admin/batch-stock/saving-board')
await probe('saving-trend', 'GET', '/api/admin/batch-stock/saving-trend')
await probe('remnant ledger', 'GET', '/api/admin/production/remnants')
await probe('remnant small-item-specs', 'GET', '/api/admin/production/remnants/small-item-specs')
await probe('remnant match', 'GET', '/api/admin/production/remnants/match')
await probe('stock ledger', 'GET', '/api/admin/stock-ledger?page=1&size=3')
await probe('batch-stock POST /', 'POST', '/api/admin/batch-stock', {})
await probe('batch-stock POST /stocktake(空)', 'POST', '/api/admin/batch-stock/stocktake', {})
await probe('inbound orders', 'GET', '/api/admin/inbound/orders?page=1&size=3')

// ── C. 看板 / 简报 / 时间口径 ──────────────────────────────────
log('═══ C. 看板/简报面枚举 ═══')
await probe('dashboard stats', 'GET', '/api/admin/dashboard/stats')
await probe('dashboard order-trend', 'GET', '/api/admin/dashboard/order-trend')
await probe('briefing today', 'GET', '/api/admin/briefing/today')
await probe('briefing snapshot', 'GET', '/api/admin/briefing/snapshot')

// ── 数据存量（期望来源的原料）──────────────────────────────────
log('═══ 存量读数（tenant 20）═══')
const stock = one(`select
  (select count(*) from products where tenant_id=${TENANT_ID} and deleted=0) products,
  (select count(*) from product_skus where tenant_id=${TENANT_ID}) skus,
  (select count(*) from product_skus where tenant_id=${TENANT_ID} and avg_cost is not null) skus_with_avg,
  (select count(*) from stock_batches where tenant_id=${TENANT_ID} and deleted=0) batches,
  (select count(*) from stock_batch_consumptions where tenant_id=${TENANT_ID} and deleted=0) consumptions,
  (select count(*) from stock_ledger_entries where tenant_id=${TENANT_ID} and deleted=0) ledger,
  (select count(*) from fabric_remnants where tenant_id=${TENANT_ID} and deleted=0) remnants,
  (select count(*) from inbound_orders where tenant_id=${TENANT_ID} and deleted=0) inbound,
  (select count(*) from finance_transactions where tenant_id=${TENANT_ID} and deleted=0) txns,
  (select count(*) from production_work_logs where tenant_id=${TENANT_ID} and deleted=0) worklogs,
  (select count(*) from daily_briefings where tenant_id=${TENANT_ID} and deleted=0) briefings,
  (select count(*) from orders where tenant_id=${TENANT_ID} and deleted=0) orders`)
log('存量: ' + JSON.stringify(stock))
writeFileSync(join(OUT, 'recon-stock.json'), JSON.stringify(stock, null, 2))

log('═══ ledger reason 分布 ═══')
const reasons = psql(`select reason, count(*) n, min(created_at) first_at, max(created_at) last_at
  from stock_ledger_entries where tenant_id=${TENANT_ID} and deleted=0 group by reason order by n desc`)
log(JSON.stringify(reasons))

log('═══ 存量 txn occurred_at 跨度（+08 口径）═══')
const span = one(`select count(*) n, min(occurred_at) mn, max(occurred_at) mx from finance_transactions where tenant_id=${TENANT_ID} and deleted=0`)
log(JSON.stringify(span) + '  → ' + JSON.stringify(tsBoth(span?.mn)))

log('═══ 简报 biz_date 分布 ═══')
log(JSON.stringify(psql(`select biz_date, verify_status, generated_at from daily_briefings where tenant_id=${TENANT_ID} and deleted=0 order by biz_date desc limit 8`)))

log('═══ 本包探针残留（应为 0）═══')
log(JSON.stringify(one(`select
  (select count(*) from orders where tenant_id=${TENANT_ID} and id like 'c3%') c3_orders,
  (select count(*) from finance_transactions where tenant_id=${TENANT_ID} and (order_no like 'c3%' or transaction_no like 'c3%' or remark like '%线③验收%')) c3_txns,
  (select count(*) from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no like 'c3%') c3_ledger`)))

log('recon 完成')
