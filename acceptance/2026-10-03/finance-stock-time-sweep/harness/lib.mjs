// 线③ 财务/库存下游 + 账期时间口径 —— 功能级验证共享库（2026-10-03）
//
// 证据纪律（migao-acceptance）：
//  ① 每条判定必须带**期望来源**——期望一律由本包独立算出（SQL 自己重算），
//     🔴 严禁把被测系统自己的读面当期望；
//  ② 写 SQL 必须带 `-- probe-ok`（人工审查痕迹）；探针命名域统一 `线③验收`，
//     机器可判前缀统一 `c3`（hex/ASCII 安全，避开他人 `fa/fb/fsp/fsw/...` 命名空间）；
//  ③ 时间一律 +08 口径（原始 JSON 若为 UTC 则标注换算）；
//  ④ 只读参考 shipments-sweep/harness/lib.mjs 的骨架，**不写它的 out/**。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const API = process.env.API_BASE || 'http://localhost:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const TENANT_ID = Number(process.env.TENANT_ID || 20)
export const ADMIN_PHONE = process.env.ADMIN_PHONE || '13870217889'
export const LIVE_WORKTREE = process.env.LIVE_WORKTREE || '/Users/guangzhen.zk/migao-wt/main-live'

/** 探针命名域：本包创建的一切对象都带这个前缀；绝不触碰别人创建的行。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '线③验收'
/** 机器可判 id 前缀（hex/ASCII 安全）：避开他包 `fa*`（发货）、`fb*`（加工单）等。 */
export const HEX = '0123456789abcdef'
export function hexId(prefix, len = 20) {
  let s = ''
  for (let i = 0; i < len; i++) s += HEX[Math.floor(Math.random() * 16)]
  return prefix + s
}
/** 本包机器可判探针 id 前缀（**只此一组**，便于残留计数与自清）。 */
export const C3 = {
  order: 'c3',        // c3 + 20 hex
  item: 'c4',         // c4 + 20 hex
  po: 'c5',           // c5 + 20 hex
  txn: 'c3t',         // 流水号域（finance_transactions.order_no / transaction_no 用）
}
export const REF_NO = (tag) => `c3ref${tag}`

mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${nowCST().cst} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

// ────────────────────────── 时间（+08 口径）──────────────────────────
/**
 * 🔴 已修 harness bug（2026-10-03，本包 v2）：原实现 `off = -d.getTimezoneOffset()` 后
 * `new Date(d.getTime()+off*60000)` 再取**本地 getter** ⇒ **同一偏移被加两次**（本机 offset=-480
 * ⇒ +8h 双重换算），实测 `cst` 比真实 +08 墙钟**快 8 小时**（且与同结构里的 `utc` 字段自相矛盾）。
 * 现行实现用 **显式时区** `Asia/Shanghai`（Intl，方案 B）—— 跨机不再依赖 TZ 环境变量，
 * 从根上排除「本地 getter + 手动偏移」这种双重换算。
 */
const CST_FMT = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', hour12: false,
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit',
})
/** 真实 +08 墙钟串（不带标签）。 */
export const cstWall = (d = new Date()) => CST_FMT.format(d).replace('T', ' ')
export function nowCST() {
  const d = new Date()
  return { cst: `${cstWall(d)} +08`, utc: d.toISOString() }
}
/** 自检：nowCST() 必须与 SQL `now() at time zone 'Asia/Shanghai'` 一致（见 verify-time.mjs）。 */

/**
 * 原始时间戳 → {raw, plus08}。带显式偏移 ⇒ 原文即本地墙钟（**不再换算**）；
 * 只有 Z/无偏移 ⇒ 用 UTC 墙钟 +8h 换算。两种来源格式都覆盖：
 * RDS/psql 给 `...+08:00`，API JSON 给 `...Z`。
 */
export function tsBoth(v) {
  if (v == null) return null
  const s = String(v)
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return { raw: s, note: '非时间戳' }
  const hasOffset = /(?:[+-]\d{2}(?::?\d{2})?)$/.test(s)
  let plus08
  if (hasOffset) {
    plus08 = s.replace('T', ' ').slice(0, 19) + ' (原文偏移=本地墙钟，未再换算)'
  } else {
    // 无偏移/Z ⇒ 用显式时区换算（与 nowCST 同源，不再手算 +8h）
    plus08 = cstWall(d) + ' +08（由 UTC 换算）'
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
  let procStart = 'unknown'
  let pid = null
  try {
    pid = execFileSync('bash', ['-lc',
      `lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null | head -1`], { encoding: 'utf8' }).trim()
    if (pid) procStart = execFileSync('bash', ['-lc', `ps -o lstart= -p ${pid}`], { encoding: 'utf8' }).trim()
  } catch { /* 非致命 */ }
  let jvmTz = 'unknown'
  try {
    if (pid) jvmTz = (execFileSync('bash', ['-lc',
      `jcmd ${pid} VM.system_properties 2>/dev/null | grep -E '^user.timezone=' || true`],
      { encoding: 'utf8' }).trim()) || 'unknown'
  } catch { /* 非致命 */ }
  return { worktree, sha, shaFull, subject, commitTime, adminApiPid: pid, adminApiStart: procStart, jvmTz, observedAt: nowCST() }
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

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ────────────────────────── DB（psql 直连云 dev 库）──────────────────────────
// 连接串：优先 env DATABASE_URL，其次 backend/admin-api/.env 的 RDS_* 字段。
let _pg = null
function pgConf() {
  if (_pg) return _pg
  if (process.env.DATABASE_URL) {
    const u = new URL(process.env.DATABASE_URL)
    _pg = { url: process.env.DATABASE_URL, host: u.hostname, port: u.port, user: decodeURIComponent(u.username), db: u.pathname.slice(1), password: decodeURIComponent(u.password) }
    return _pg
  }
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  _pg = { host: get('RDS_HOST'), port: get('RDS_PORT'), user: get('RDS_USER'), db: get('RDS_DB'), password: get('RDS_PASSWORD') }
  return _pg
}

/** psql 原始调用（-t -A，不带 json 包装），返回行数组（每行一个字符串）。 */
export function psqlRaw(sql, { tuples = false } = {}) {
  const c = pgConf()
  const args = ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1']
  if (tuples) args.push('-F', '\u0001')
  args.push('-c', sql)
  const out = execFileSync('/opt/homebrew/bin/psql', args,
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  return out.split('\n').filter((l) => l.length > 0)
}

/** 只读 SQL：包成一行 json_agg ⇒ 输出即 JS 对象数组。
 *  🔴 子查询别名用 `__q`（**不是 `t`**）：实测踩过 —— 若内部 SQL 把某列也命名为 `t`，
 *  PG 会优先把它解析成**列**而非行类型 ⇒ `function row_to_json(text) does not exist`。
 *  用 `__q` 让「列名与包装别名撞车」在内层根本不可能发生（类级固化，而非逐个改列名）。 */
export function psql(sql) {
  const out = psqlRaw(`select coalesce(json_agg(row_to_json(__q))::text,'[]') from (${sql}) __q`)
  return JSON.parse(out.join('\n').trim() || '[]')
}
export const one = (sql) => psql(sql)[0] ?? null

/** 写 SQL 守卫：语句必须显式带 `-- probe-ok`（人工审查痕迹），否则抛错。 */
export function guardedWrite(sql) {
  assertProbeSql(sql)
  const c = pgConf()
  return execFileSync('/opt/homebrew/bin/psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
}

/**
 * 写 SQL 守卫（双重）：
 *  ① 必须带 `-- probe-ok`；
 *  ② **必须命中本包探针命名域**（`c3`/`c4`/`c5` 机器前缀 或 中文 `线③验收`）——
 *     防止误改既有行（跨包隔离纪律 ③：非自己的行不改）。
 *  例外：显式声明 `-- probe-ok restore` 的**还原**语句（id 精确到本包探针行）。
 */
export function assertProbeSql(sql) {
  if (!/--\s*probe-ok/.test(sql)) throw new Error(`写 SQL 缺 -- probe-ok 标记: ${sql.slice(0, 160)}`)
  if (!/c3|c4|c5|线③验收/.test(sql)) {
    throw new Error(`写 SQL 未命中本包探针命名域（c3/c4/c5/线③验收）: ${sql.slice(0, 160)}`)
  }
}

// ────────────────────────── 内容指纹（红证自证）──────────────────────────
export const sha256 = (s) => createHash('sha256').update(s, 'utf8').digest('hex')
/** 行指纹：稳定键序序列化后的 sha256（注入/还原前后比对，**禁用 mtime/size**）。 */
export function rowFingerprint(rows) {
  const canon = rows
    .map((r) => JSON.stringify(Object.keys(r).sort().reduce((a, k) => ((a[k] = r[k]), a), {})))
    .sort()
    .join('\n')
  return { sha256: sha256(canon), n: rows.length }
}

// ────────────────────────── decimal 语义（禁浮点 ==）──────────────────────────
// 金额/数量一律走 BigInt。**两位**（分）用于金额，**四位**用于均价（numeric(12,4)）。
export const S2 = 100n
export const S4 = 10000n
export function dec(v, scale) {
  if (v === null || v === undefined || v === '') return null
  const s = String(v).trim()
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(s)
  if (!m) throw new Error(`非十进制读数: ${JSON.stringify(v)}`)
  const sign = m[1] === '-' ? -1n : 1n
  const frac = (m[3] || '').padEnd(Number(scale === S2 ? 2 : 4), '0').slice(0, Number(scale === S2 ? 2 : 4))
  return sign * (BigInt(m[2]) * scale + BigInt(frac))
}
export const money2 = (v) => dec(v, S2)          // 分
export const qty4 = (v) => dec(v, S4)            // 万分位（numeric(12,4)/numeric(16,4)）
export function fmt(v, scale) {
  if (v === null || v === undefined) return 'null'
  const s = scale === S2 ? 2 : 4
  const sign = v < 0n ? '-' : ''
  const a = v < 0n ? -v : v
  const base = scale === S2 ? S2 : S4
  return `${sign}${a / base}.${String(a % base).padStart(s, '0')}`
}

/**
 * HALF_UP 四舍五入到 n 位（Java BigDecimal HALF_UP 的整数版）——
 * 独立重算**必须**用它，不得用 JS 浮点 toFixed（0.005 会 banker's 偏）。
 * 入参/出参皆为「已按目标精度放大的整数」。
 */
export function halfUpDiv(numer, denom, keepScale) {
  // 求 round(numer/denom × 10^keepScale) 的 HALF_UP。numer/denom 皆为整数。
  const neg = (numer < 0n) !== (denom < 0n)
  const n = numer < 0n ? -numer : numer
  const d = denom < 0n ? -denom : denom
  const pow = 10n ** BigInt(keepScale)
  const scaled = n * pow
  const q = scaled / d
  const r = scaled % d
  const rounded = (r * 2n >= d) ? q + 1n : q
  return neg ? -rounded : rounded
}

/** 移动加权平均（独立重算，口径抄自 InboundOrderService.movingAverage）：
 *  未记单价(/unitCost null) ⇒ 保持 beforeAvg；before_qty<=0 或 beforeAvg null ⇒ unitCost；
 *  否则 (before_qty*before_avg + in_qty*unit_cost)/(before_qty+in_qty)，HALF_UP 保留 4 位。 */
export function movingAverage(beforeQty, beforeAvg, quantity, unitCost) {
  if (unitCost === null || unitCost === undefined) return beforeAvg === undefined ? null : beforeAvg
  const bq = beforeQty === null || beforeQty === undefined ? 0n : qty4(beforeQty)
  const uc = qty4(unitCost)
  if (bq <= 0n || beforeAvg === null || beforeAvg === undefined) return uc
  const ba = qty4(beforeAvg)
  const iq = quantity === null || quantity === undefined ? 0n : qty4(quantity)
  // 分母/分子皆已 ×10^4 ⇒ 直接整数运算后 HALF_UP 到 4 位
  const numer = ba * bq + uc * iq      // 单位: 10^-8 量级
  const denom = bq + iq                // 单位: 10^-4
  // 需要 round(numer/denom / 10^4) ⇒ halfUpDiv(numer, denom*10^4, 4)
  return halfUpDiv(numer, denom * S4, 4) * 1n === undefined ? null : halfUpDiv(numer, denom * S4, 4)
}

// ────────────────────────── 前后快照（存量零改动自证）──────────────────────────
export function snapTables(specs) {
  const snap = new Map()
  for (const { table, where, key = 'id' } of specs) {
    const rows = psql(`select * from ${table} where ${where}`)
    for (const r of rows) snap.set(`${table}|${r[key]}`, { table, row: r })
  }
  return snap
}
export function fieldDiff(before, after) {
  const out = []
  for (const [k, b] of before) {
    const a = after.get(k)
    if (!a) { out.push({ key: k, field: '*', before: 'ROW_EXISTS', after: 'ROW_MISSING', kind: 'removed-row' }); continue }
    for (const f of new Set([...Object.keys(b.row), ...Object.keys(a.row)])) {
      const bv = JSON.stringify(b.row[f] ?? null)
      const av = JSON.stringify(a.row[f] ?? null)
      if (bv !== av) out.push({ key: k, field: f, before: b.row[f] ?? null, after: a.row[f] ?? null, kind: 'field' })
    }
  }
  for (const [k, a] of after) {
    if (!before.has(k)) out.push({ key: k, field: '*', before: 'ROW_MISSING', after: 'ROW_ADDED', kind: 'added-row' })
  }
  return out
}

export function listOut() {
  return readdirSync(OUT)
}
