// 发货单 / 仓储链 —— 功能级验证共享库（产线 ①，2026-10-03）
//
// 证据纪律（migao-acceptance）：
//  ① 每条判定必须带**期望来源**——期望一律由本包独立算出（订单量 − 已发合计），
//     🔴 严禁把被测系统自己的读面当期望（上一批 D1 就是靠这条藏住的）；
//  ② 写 SQL 必须带 `-- probe-ok`（人工审查痕迹）；探针命名域统一 `发货验收`；
//  ③ 时间一律 +08 口径（原始 JSON 若为 UTC 则标注换算）。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const API = process.env.API_BASE || 'http://localhost:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const TENANT_ID = Number(process.env.TENANT_ID || 20)
export const ADMIN_PHONE = process.env.ADMIN_PHONE || '13870217889'
export const LIVE_WORKTREE = process.env.LIVE_WORKTREE || '/Users/guangzhen.zk/migao-wt/main-live'
/** 探针 id 的**机器可判前缀**（必须落在 `[0-9a-fA-F-]+` 内）。
 *  🔴 为什么不是中文前缀：`OrderController` 的写端点路由带正则约束
 *  `@PutMapping("/{id:[0-9a-fA-F-]+}/status")`（OrderController.java:239）——
 *  非十六进制 id 会在**路由层**就 404，**根本进不到状态机** ⇒ 拿它测"非法流转被拒"是
 *  **空断言**（实测踩过：T2/T3/T5 三条全 404，测的是路由不是状态机）。 */
export const HEX = '0123456789abcdef'
export function hexId(prefix, len = 20) {
  let s = ''
  for (let i = 0; i < len; i++) s += HEX[Math.floor(Math.random() * 16)]
  return prefix + s
}

/** 探针命名域：本包创建的一切对象都带这个前缀；绝不触碰别人创建的行。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '发货验收'
/** 探针工人（本包自建，PIN 已知）。 */
export const PROBE_WORKER = { workerNo: 'WFS20261003', pin: '246810', name: `${PROBE_PREFIX}工人` }
export const SESSION_HEADER = 'X-Worker-Session-Id'
export const IDEM_HEADER = 'X-Client-Request-Id'

mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${nowCST().cst} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

// ────────────────────────── 时间（+08 口径）──────────────────────────
export function nowCST() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const off = -d.getTimezoneOffset()
  const l = new Date(d.getTime() + off * 60000)
  return {
    cst: `${l.getFullYear()}-${p(l.getMonth() + 1)}-${p(l.getDate())} ${p(l.getHours())}:${p(l.getMinutes())}:${p(l.getSeconds())} +08`,
    utc: d.toISOString(),
  }
}

/** 原始时间戳 → 标注 +08 换算的口径串。
 *  ⚠️ 两种来源格式：RDS/psql 给 `2026-10-03T10:36:12.583762+08:00`（**已带 +08**），
 *  API JSON 给 `...Z`（UTC）。带显式偏移的一律按其自身偏移换算 —— 否则会把 +08 再 +8（实测踩过）。 */
export function tsBoth(v) {
  if (v == null) return null
  const s = String(v)
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return { raw: s, note: '非时间戳' }
  // ⚠️ `toISOString()` 是 **UTC** 口径 —— 不能用它再叠加偏移（实测会把 +08 读数再 −8h）。
  // 有显式偏移 ⇒ 原文即 +08 本地墙钟；只有 Z/无偏移 ⇒ 用 UTC 墙钟 + 8h 换算。
  // 变体：`+08`（无分）也算显式偏移（psql 输出实测两种都给过）
  const hasOffset = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/.test(s) && !s.endsWith('Z')
  let plus08
  if (hasOffset) {
    plus08 = s.replace('T', ' ').slice(0, 19) + ' (原文偏移=本地墙钟，未再换算)'
  } else {
    const l = new Date(d.getTime() + 8 * 3600 * 1000)
    plus08 = l.toISOString().replace('T', ' ').slice(0, 19) + ' +08（由 UTC 换算）'
  }
  return { raw: s, plus08 }
}

// ────────────────────────── 构建点自证（"已合并未必已部署"）──────────────────────────
export function buildPoint(worktree = LIVE_WORKTREE) {
  const git = (args) => { try { return execFileSync('git', ['-C', worktree, ...args], { encoding: 'utf8' }).trim() } catch { return 'unknown' } }
  const sha = git(['rev-parse', '--short', 'HEAD'])
  const shaFull = git(['rev-parse', 'HEAD'])
  const subject = git(['log', '-1', '--format=%s'])
  const commitTime = git(['log', '-1', '--format=%cI'])
  // 运行中的 admin-api 进程启动时刻（活环境测量窗口，migao-acceptance v1.9）
  let procStart = 'unknown'
  try {
    const pid = execFileSync('bash', ['-lc',
      `lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null | head -1`], { encoding: 'utf8' }).trim()
    if (pid) {
      procStart = execFileSync('bash', ['-lc', `ps -o lstart= -p ${pid}`], { encoding: 'utf8' }).trim()
    }
  } catch { /* 非致命 */ }
  return { worktree, sha, shaFull, subject, commitTime, adminApiStart: procStart, observedAt: nowCST() }
}

// ────────────────────────── 证据记录 ──────────────────────────
export class Recorder {
  constructor(file) {
    this.file = file
    this.records = []
  }
  add(id, name, status, detail, evidence = []) {
    const rec = { id, name, status, detail, evidence, at: nowCST().cst }
    this.records.push(rec)
    const icon = status === 'pass' ? 'PASS' : status === 'fail' ? 'FAIL' : 'SKIP'
    log(`[${icon}] [${id}] ${name} — ${detail}`)
    this.dump()
    return rec
  }
  pass(id, name, detail, ev) { return this.add(id, name, 'pass', detail, ev) }
  fail(id, name, detail, ev) { return this.add(id, name, 'fail', detail, ev) }
  skip(id, name, detail) { return this.add(id, name, 'skip', detail, []) }
  dump() { writeFileSync(join(OUT, this.file), JSON.stringify(this.records, null, 2)) }
  summary() {
    const c = (s) => this.records.filter((r) => r.status === s).length
    return { pass: c('pass'), fail: c('fail'), skip: c('skip'), total: this.records.length }
  }
}

/**
 * 断言器：pass/fail **都**带「期望来源 + 原始读数」。
 * expectSource 必须写清期望是怎么独立算出来的（禁止「系统自己给的读面」）。
 */
export function judge(R, { id, name, expect, actual, pass, expectSource, evidence = [], detail }) {
  const d = detail || (pass ? `期望 ${expect} == 实测 ${actual}` : `期望 ${expect} ≠ 实测 ${actual}`)
  return pass
    ? R.pass(id, name, d, [`期望来源: ${expectSource}`, ...evidence])
    : R.fail(id, name, d, [`期望来源: ${expectSource}`, ...evidence])
}

// ────────────────────────── HTTP ──────────────────────────
export async function api(method, path, { token, body, headers = {}, timeoutMs = 60000 } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers }
  if (token) { h.Cookie = `access_token=${token}`; h.Authorization = `Bearer ${token}` }
  let res
  try {
    res = await fetch(API + path, {
      method, headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (e) {
    return { status: 0, json: null, text: `FETCH_ERROR ${e.name}: ${e.message}`, ok: false, data: null }
  }
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON */ }
  return { status: res.status, json, text, ok: res.ok, data: json?.data }
}

export async function loginApi(phone = ADMIN_PHONE, code = SMS_CODE) {
  const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, raw: d }
}

export async function workerLogin() {
  const r = await api('POST', '/api/worker/login', {
    body: { workerNo: PROBE_WORKER.workerNo, pin: PROBE_WORKER.pin, tenantId: TENANT_ID, deviceLabel: `${PROBE_PREFIX}探针设备` },
  })
  if (!r.json?.success) throw new Error(`工人登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  return r.json.data.session_id
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ────────────────────────── DB（psql 直连云 dev 库）──────────────────────────
let _pgConf = null
function pgConf() {
  if (_pgConf) return _pgConf
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  _pgConf = { host: get('RDS_HOST'), port: get('RDS_PORT'), user: get('RDS_USER'), db: get('RDS_DB'), password: get('RDS_PASSWORD') }
  return _pgConf
}

/** 只读 SQL：包成一行 json_agg ⇒ 输出即 JS 对象数组。 */
export function psql(sql) {
  const c = pgConf()
  const out = execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
     '-c', `select coalesce(json_agg(row_to_json(t))::text,'[]') from (${sql}) t`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
  return JSON.parse(out.trim() || '[]')
}
export const one = (sql) => psql(sql)[0] ?? null

/** 写 SQL 守卫：语句必须显式带 `-- probe-ok`（人工审查痕迹），否则抛错。 */
export function guardedWrite(sql) {
  if (!/--\s*probe-ok/.test(sql)) throw new Error(`写 SQL 缺 -- probe-ok 标记: ${sql.slice(0, 120)}`)
  const c = pgConf()
  return execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
}

/** 独立性守卫：任何写操作前，目标必须命中探针命名域。 */
export function assertProbe(...vals) {
  const s = vals.filter((v) => v !== null && v !== undefined).join(' ')
  if (!s.includes(PROBE_PREFIX)) {
    throw new Error(`拒绝操作非探针对象（缺前缀「${PROBE_PREFIX}」）: ${s}`)
  }
}

// ────────────────────────── decimal 语义 ──────────────────────────
/**
 * 数量/金额一律走 BigInt **千分**（milli）表示 —— 严禁浮点 `==`。
 * 为什么是千分不是分：`order_shipment_items.shipped_quantity` 是 unbounded `numeric`，
 * 实测能落 `0.001` ⇒ 用「分」会把 0.001 与 0 判成相等（假绿）。三位覆盖米/套/件的现实精度。
 */
export const SCALE = 1000n
export function cents(v) {
  if (typeof v === 'bigint') return v          // 已是 milli 表示（幂等，防"双重换算"假红）
  if (v === null || v === undefined || v === '') return null
  const s = String(v).trim()
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(s)
  if (!m) throw new Error(`非十进制读数: ${JSON.stringify(v)}`)
  const sign = m[1] === '-' ? -1n : 1n
  const frac = (m[3] || '').padEnd(3, '0').slice(0, 3)
  return sign * (BigInt(m[2]) * SCALE + BigInt(frac))
}
export function fmtQty(c) {
  if (c === null || c === undefined) return 'null'
  const sign = c < 0n ? '-' : ''
  const a = c < 0n ? -c : c
  return `${sign}${a / SCALE}.${String(a % SCALE).padStart(3, '0')}`
}
export const qtyEq = (a, b) => cents(a) === cents(b)

// ────────────────────────── 字段级前后 diff（写后等价性）──────────────────────────
/**
 * 行集快照：{ `${table}|${key}` → rowObject }。
 * 允许变化集 = payload 键 ∪ 显式声明的审计/派生态（时间戳、id、order_no、shipment_no、updated_at…）。
 */
export function tableSnap(sqlWhitelist) {
  const snap = new Map()
  for (const { table, where, key = 'id' } of sqlWhitelist) {
    const rows = psql(`select * from ${table} where ${where}`)
    for (const r of rows) snap.set(`${table}|${r[key]}`, { table, row: r })
  }
  return snap
}

/** 字段级 diff → [{table, key, field, before, after, kind}]；kind ∈ field | added-row | removed-row。 */
export function fieldDiff(before, after) {
  const out = []
  for (const [k, b] of before) {
    const a = after.get(k)
    if (!a) { out.push({ table: b.table, key: k, field: '*', before: 'ROW_EXISTS', after: 'ROW_MISSING', kind: 'removed-row' }); continue }
    for (const f of new Set([...Object.keys(b.row), ...Object.keys(a.row)])) {
      const bv = JSON.stringify(b.row[f] ?? null)
      const av = JSON.stringify(a.row[f] ?? null)
      if (bv !== av) out.push({ table: b.table, key: k, field: f, before: b.row[f] ?? null, after: a.row[f] ?? null, kind: 'field' })
    }
  }
  for (const [k, a] of after) {
    if (!before.has(k)) out.push({ table: a.table, key: k, field: '*', before: 'ROW_MISSING', after: 'ROW_ADDED', kind: 'added-row' })
  }
  return out.sort((x, y) => (x.table + x.key + x.field).localeCompare(y.table + y.key + y.field))
}

/** 越界判定：返回不在 allowed 里的 diff 条目（多一处即红）。 */
export function overreach(d, allowed) {
  const allow = new Set(allowed)
  return d.filter((x) => !allow.has(`${x.table}.${x.field}`) && !allow.has(`${x.table}.*`) && !allow.has(x.table))
}
export const fmtDiff = (d) => d.map((x) => `${x.table}.${x.field}: ${JSON.stringify(x.before)} → ${JSON.stringify(x.after)} [${x.kind}]`)

// ────────────────────────── 探针对象：建 / 清 ──────────────────────────
/** 一个探针订单的完整夹具（**自建**，不依赖库里的存量行）。 */
export function createProbeOrder({ tag, status = 'confirmed', items, customer }) {
  const cust = customer || `${PROBE_PREFIX}客户-${tag}`
  assertProbe(cust)   // 守卫对象 = 真正落库的客户名（带探针前缀），不是内部标签
  const orderId = hexId('fa')
  const orderNo = `FS${Date.now().toString().slice(-9)}${Math.floor(Math.random() * 90 + 10)}`

  guardedWrite(`-- probe-ok
    insert into orders (id, tenant_id, order_no, customer_name, customer_phone, status, total_amount, actual_amount, created_at, updated_at, deleted, is_urgent)
    values ('${orderId}', ${TENANT_ID}, '${orderNo}', '${cust}', '13900000000', '${status}', 0, 0, now(), now(), 0, false);`)
  const created = []
  for (const it of items) {
    const itemId = hexId('fb')
    guardedWrite(`-- probe-ok
      insert into order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, subtotal, created_at, updated_at, deleted)
      values ('${itemId}', ${TENANT_ID}, '${orderId}', null, '${it.name}', ${it.qty}, 10, 0, now(), now(), 0);`)
    created.push({ itemId, ...it })
  }
  return { orderId, orderNo, tag, items: created, customer: cust }
}

/**
 * 补一张**已完成**加工单（为「含加工项订单必须完成加工单才可发货」提供正对照夹具，
 * 以及让 production /print 面可达 —— 该面按 order_id 找加工单，找不到就 404）。
 */
export function addProcessingOrder(orderId, { status = 'completed', snapshot = '[]' } = {}) {
  // 守卫对象 = 探针订单 id 的**机器可判前缀**（`fsprobe`）；中文命名域在客户名上（见 createProbeOrder）
  if (!String(orderId).startsWith('fa')) {
    throw new Error(`拒绝为宿主数据补加工单（不是本包探针订单）: ${orderId}`)
  }
  const id = hexId('fc')
  const no = `JG${Date.now().toString().slice(-9)}${Math.floor(Math.random() * 90 + 10)}`
  guardedWrite(`-- probe-ok
    insert into processing_orders (id, tenant_id, order_id, processing_order_no, status, items_snapshot, created_at, updated_at, deleted)
    values ('${id}', ${TENANT_ID}, '${orderId}', '${no}', '${status}', '${snapshot}'::jsonb, now(), now(), 0);`)
  return { id, processingOrderNo: no }
}

/** 本包探针对象在库里的存活计数（**只读**，机器读数）。 */
export function probeResidue() {
  const q = (sql) => psql(sql)
  const orderIds = q(`select id from orders where tenant_id=${TENANT_ID} and id like 'fa%'`).map((r) => r.id)
  const shipIds = q(`select id from order_shipments where tenant_id=${TENANT_ID} and order_id like 'fa%'`).map((r) => r.id)
  const counts = {
    orders: orderIds.length,
    orderItems: q(`select id from order_items where tenant_id=${TENANT_ID} and order_id like 'fa%'`).length,
    shipments: shipIds.length,
    shipmentItems: q(`select id from order_shipment_items where tenant_id=${TENANT_ID} and order_id like 'fa%'`).length,
    logistics: q(`select id from order_logistics where tenant_id=${TENANT_ID} and order_id like 'fa%'`).length,
    clientRequestKeys: q(`select id from client_request_keys where tenant_id=${TENANT_ID} and client_request_id like 'fsp-%'`).length,
    stockLedger: q(`select id from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no like 'fsp%'`).length,
    processingOrders: q(`select id from processing_orders where tenant_id=${TENANT_ID} and order_id like 'fa%'`).length,
    probeWorkers: q(`select id from users where tenant_id=${TENANT_ID} and worker_no='${PROBE_WORKER.workerNo}'`).length,
    workerSessions: q(`select id from worker_sessions where tenant_id=${TENANT_ID} and worker_id in (select id from users where tenant_id=${TENANT_ID} and worker_no='${PROBE_WORKER.workerNo}')`).length,
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  return { counts, total, orderIds: orderIds.length, shipIds: shipIds.length }
}

/** 清掉本包全部探针数据（硬删，仅探针命名域）。 */
export function cleanupProbe() {
  const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)
  w(`delete from processing_orders where tenant_id=${TENANT_ID} and order_id like 'fa%';`)
  w(`delete from order_shipment_items where tenant_id=${TENANT_ID} and order_id like 'fa%';`)
  w(`delete from order_shipments where tenant_id=${TENANT_ID} and order_id like 'fa%';`)
  w(`delete from order_logistics where tenant_id=${TENANT_ID} and order_id like 'fa%';`)
  w(`delete from order_items where tenant_id=${TENANT_ID} and order_id like 'fa%';`)
  w(`delete from orders where tenant_id=${TENANT_ID} and id like 'fa%';`)
  w(`delete from client_request_keys where tenant_id=${TENANT_ID} and client_request_id like 'fsp-%';`)
  w(`delete from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no like 'fsp%';`)
  w(`delete from worker_sessions where tenant_id=${TENANT_ID} and worker_id in (select id from users where tenant_id=${TENANT_ID} and worker_no='${PROBE_WORKER.workerNo}');`)
  w(`delete from users where tenant_id=${TENANT_ID} and worker_no='${PROBE_WORKER.workerNo}';`)
}

export const idemKey = (tag, n = 0) => `fsp-${tag}-${Date.now().toString(36)}-${n}`
