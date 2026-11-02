// 线③ 自建共享工装：并发发射（barrier 对齐）+ 判别性读数 + 探针对象纪律
import { api, psql, log, OUT } from './lib.mjs'
import { PROBE } from './config.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

/** 单请求：记录发出/收到时刻（毫秒，相对 t0），供「真交错窗口」判别性读数用 */
export function timedApi(method, path, opts, t0) {
  const sentAt = Date.now() - t0
  return api(method, path, opts).then((r) => ({ ...r, sentAt, recvAt: Date.now() - t0 }))
}

/**
 * 并发发射 N 个请求（同一 microtask 门控 ⇒ barrier 对齐）。
 * @param {number} n
 * @param {(i:number)=>Promise<any>} fn
 * @param {number} t0
 */
export async function fanOut(n, fn, t0) {
  let gate
  const p = new Promise((r) => { gate = r })
  const jobs = []
  for (let i = 0; i < n; i++) jobs.push((async () => { await gate; return fn(i) })())
  await new Promise((r) => setImmediate(r))   // 让所有 job 挂到 gate 上
  gate()
  const out = await Promise.all(jobs)
  return out
}

/** 交错窗口读数：把一批带 sentAt/recvAt 的响应换算成「重叠了多少对」 */
export function overlapStats(resps) {
  const spans = resps.map((r) => [r.sentAt, r.recvAt]).sort((a, b) => a[0] - b[0])
  let pairs = 0
  for (let i = 0; i < spans.length; i++) for (let j = i + 1; j < spans.length; j++) if (spans[j][0] < spans[i][1]) pairs++
  const first = spans[0], last = spans[spans.length - 1]
  return {
    requests: spans.length,
    overlappedPairs: pairs,
    // 判别性读数：从第一个请求发出到最后一个请求发出之间的跨度（越小 = 越接近真同时）
    issueSpanMs: last ? last[0] - first[0] : null,
    wallMs: last ? last[1] - first[0] : null,
    spans: spans.slice(0, 12),
  }
}

export function counts(resps, pred = (r) => r.status === 200) {
  const ok = resps.filter(pred).length
  return { total: resps.length, ok, notOk: resps.length - ok }
}

/** 写档（证据落盘），统一放 OUT 目录 */
export function save(name, obj) {
  writeFileSync(join(OUT, name), JSON.stringify(obj, null, 2))
  return name
}

/** 探针对象纪律：拒绝非探针对象的写操作 */
export function assertProbeName(name) {
  if (!String(name).includes(PROBE)) throw new Error(`非探针对象，拒绝写：${name}`)
}

// ⚠️ bigint 精度（本机实测）：product_skus.id 是雪花 bigint（19 位）> 2^53 ⇒ 必须全程**字符串**传递，
// Number()/JSON.parse 会把 ...360002 变成 ...360000（500 差值级）⇒ 产品侧「SKU 不属于该商品」422。
export const skuIdsByCode = (tenantId, codePrefix = PROBE.toUpperCase()) =>
  psql(`select id::text as id, product_id, sku_code, stock::text as stock from product_skus where tenant_id=${tenantId} and upper(sku_code) like '${codePrefix}%' order by id`).map((r) => ({
    id: String(r.id), product_id: r.product_id, sku_code: r.sku_code, stock: r.stock,
  }))

export const ledgerRows = (tenantId, skuId) =>
  psql(`select id, sku_id::text as sku_id, delta::text as delta, before_qty::text as before_qty, after_qty::text as after_qty, reason, ref_no, note, created_at
        from stock_ledger_entries where tenant_id=${tenantId} and sku_id=${skuId} order by id`)

export const skuStock = (tenantId, skuId) =>
  psql(`select id::text as id, stock::text as stock from product_skus where tenant_id=${tenantId} and id=${skuId}`)[0] ?? null

export const inboundRow = (tenantId, id) =>
  psql(`select id, inbound_no, status, posted_at, cancelled_at from inbound_orders where tenant_id=${tenantId} and id='${id}'`)[0] ?? null

export const batchRows = (tenantId, skuId) =>
  psql(`select id, batch_no, sku_id::text as sku_id, quantity::text as quantity from stock_batches where tenant_id=${tenantId} and sku_id=${skuId} order by id`)

export const consumptionRows = (tenantId, skuId) =>
  psql(`select id, batch_id, delta::text as delta, before_qty::text as before_qty, after_qty::text as after_qty, reason, stocktake_run_id
        from stock_batch_consumptions where tenant_id=${tenantId} and sku_id=${skuId} order by id`)

/** ledger 链一致性：按 before→after 首尾相接（本线命名空间内，按 sku 过滤） */
export function chainCheck(rows) {
  const bad = []
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1], cur = rows[i]
    if (Number(cur.before_qty) !== Number(prev.after_qty)) bad.push({ at: cur.id, prevAfter: prev.after_qty, curBefore: cur.before_qty })
    if (Number(cur.before_qty) + Number(cur.delta) !== Number(cur.after_qty)) bad.push({ at: cur.id, arith: `${cur.before_qty}+${cur.delta}!=${cur.after_qty}` })
  }
  return bad
}

/** 按 product_id 取探针 SKU（建品应答给的是 product id；sku_code 形态随夹具变，故按 id 直查） */
export const skuByProduct = (tenantId, productId) =>
  psql(`select id::text as id, product_id, sku_code, stock::text as stock from product_skus where tenant_id=${tenantId} and product_id='${productId}' order by id limit 1`)[0] ?? null

/**
 * 原生写执行器（**不**走 lib.mjs::psql 的 `select ... from (<sql>) t` 包装 —— 那个包装只适合只读查询，
 * 把 DELETE/UPDATE 塞进子查询会被 PG 拒绝）。返回受影响行数（解析 psql 的 `DELETE n` 标记）。
 */
import { execFileSync } from 'node:child_process'
import { readFileSync as _readFileSync } from 'node:fs'
import { join as _join } from 'node:path'
import { REPO_ROOT as _REPO_ROOT } from './lib.mjs'
export function execSql(sql) {
  const env = _readFileSync(_join(_REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const g = (k) => (env.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  try {
    const out = execFileSync('psql', ['-h', g('RDS_HOST'), '-p', g('RDS_PORT'), '-U', g('RDS_USER'), '-d', g('RDS_DB'),
      '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
      { env: { ...process.env, PGPASSWORD: g('RDS_PASSWORD') }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
    const m = out.match(/(?:DELETE|UPDATE|INSERT)\s+(\d+)/)
    return { ok: true, rows: m ? Number(m[1]) : (out.trim() ? 0 : 0), out: out.trim().slice(0, 200) }
  } catch (e) {
    return { ok: false, rows: 0, error: String(e.stderr || e.message).split('\n').slice(0, 2).join(' ').slice(0, 200) }
  }
}
