// 线A 工人端 + 小程序写面 sweep —— 共享库（2026-10-03 第三轮）
//
// 复制自 batch-writeface-sweep/harness/lib.mjs（铁律 8：复制后再改，不跨目录 import）。
// 本线新增：
//   ① 工人身份面：`POST /api/admin/workers` 建探针工人 + `POST /api/worker/login` 取 session
//      + `apiWorker()`（身份载体 = `X-Worker-Session-Id`，**不是** JWT）
//   ② 扫码闭环夹具：自建 加工单/套/订单行/工序实例/部位码（`la` 前缀），**不碰存量行**
//   ③ 存量不动自证：`ledgerHash()`（对租户 20 四张关键表做全行 sha256）
//   ④ 逐表残留计数扩到工人面新表
//
// 证据纪律（migao-acceptance）：
//   ① 期望一律本包独立算出（DB 读数 / 端点契约原文 / 源码符号），**严禁**拿被测系统读面当期望；
//   ② 写 SQL 必须带 `-- probe-ok`；探针命名域统一 `线A验收` / id 前缀 `la`；
//   ③ 时间一律 +08 口径；JSON 里 UTC 与 +08 同时留。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { deflateRawSync, inflateRawSync } from 'node:zlib'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const API = process.env.API_BASE || 'http://localhost:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const TENANT_ID = Number(process.env.TENANT_ID || 20)
export const ADMIN_PHONE = process.env.ADMIN_PHONE || '13870217889'
export const LIVE_WORKTREE = process.env.LIVE_WORKTREE || '/Users/guangzhen.zk/migao-wt/main-live'

/** 探针命名域：本包创建的一切对象都带此前缀（中文名域）+ `la` 机器前缀（id 域）。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '线A验收'
/** 探针 id 的机器可判前缀：所有本包自建行 id 以 `la` 开头（绝不碰别人的行）。 */
export const ID_PREFIX = 'la'
export const IDEM_HEADER = 'X-Client-Request-Id'
/** 工人 session 请求头（与 `WorkerSessionService.SESSION_HEADER` **逐字同名**）。 */
export const WORKER_HEADER = 'X-Worker-Session-Id'
/** 入库端点幂等头（`WorkerInboundController.IDEMPOTENCY_HEADER` **逐字同名**）。 */
export const IDEMPOTENCY_HEADER = 'Idempotency-Key'
/** 探针工人 PIN（**只用于本包自建工人**；存量工人的 PIN 不可知也不去重置）。 */
export const PROBE_PIN = process.env.PROBE_PIN || '246810'

mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${nowCST().cst} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

// ────────────────────────── 时间（+08 口径）──────────────────────────
// 🔴 本机时区 = Asia/Shanghai（issue #5352），但**进程 TZ 未必是**（实测本 harness 的 shell 令
//    `getTimezoneOffset()` 返回 0 ⇒ 直接用它会把 13:40 +08 读成 21:40）。⇒ 一律走 Intl 显式时区。
const CST_FMT = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})
export function nowCST() {
  const d = new Date()
  return { cst: `${CST_FMT.format(d).replace('T', ' ')} +08`, utc: d.toISOString() }
}

export function tsBoth(v) {
  if (v == null) return null
  const s = String(v)
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return { raw: s, note: '非时间戳' }
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

// ────────────────────────── 构建点自证 ──────────────────────────
export function buildPoint(worktree = LIVE_WORKTREE) {
  const git = (args) => { try { return execFileSync('git', ['-C', worktree, ...args], { encoding: 'utf8' }).trim() } catch { return 'unknown' } }
  let procStart = 'unknown'
  let pid = 'unknown'
  try {
    pid = execFileSync('bash', ['-lc', `lsof -nP -iTCP:8080 -sTCP:LISTEN -t 2>/dev/null | head -1`], { encoding: 'utf8' }).trim()
    if (pid) procStart = execFileSync('bash', ['-lc', `ps -o lstart= -p ${pid}`], { encoding: 'utf8' }).trim()
  } catch { /* 非致命 */ }
  return {
    worktree, pid,
    sha: git(['rev-parse', '--short', 'HEAD']),
    shaFull: git(['rev-parse', 'HEAD']),
    subject: git(['log', '-1', '--format=%s']),
    commitTime: git(['log', '-1', '--format=%cI']),
    originMain: (() => { try { return execFileSync('git', ['-C', REPO_ROOT, 'rev-parse', '--short', 'origin/main'], { encoding: 'utf8' }).trim() } catch { return 'unknown' } })(),
    adminApiStart: procStart,
    observedAt: nowCST(),
  }
}

// ────────────────────────── 证据记录 ──────────────────────────
export class Recorder {
  constructor(file) { this.file = file; this.records = [] }
  add(id, name, status, detail, evidence = []) {
    const rec = { id, name, status, detail, evidence, at: nowCST().cst, atUtc: nowCST().utc }
    this.records.push(rec)
    const icon = status === 'pass' ? 'PASS' : status === 'fail' ? 'FAIL' : 'SKIP'
    log(`[${icon}] [${id}] ${name} — ${detail}`)
    this.dump()
    return rec
  }
  pass(id, name, detail, ev) { return this.add(id, name, 'pass', detail, ev) }
  fail(id, name, detail, ev) { return this.add(id, name, 'fail', detail, ev) }
  skip(id, name, detail) { return this.add(id, name, 'skip', detail, []) }
  dump() { writeFileSync(join(OUT, this.file), JSON.stringify({ records: this.records, summary: this.summary() }, null, 2)) }
  summary() {
    const c = (s) => this.records.filter((r) => r.status === s).length
    return { pass: c('pass'), fail: c('fail'), skip: c('skip'), total: this.records.length }
  }
}

/** 🔴 判据底座 fail-closed（主会话复核抓到的成片假绿）：**判过之前先证明取到了真值**。
 *  规则：`expect`/`actual` 里出现 `undefined` / `null` / `NaN` / 空字符串 ⇒ 默认**不允许判 pass**
 *  （那条判据等于什么都没测 —— 实测形态：`期望 undefined == undefined ⇒ pass`）。
 *  可空字段必须**显式声明**（`nullable: ['字段名']`）才放行，声明即契约：写清该字段为什么可空。
 *  @returns {string|null} 违规说明；null = 取值完好 */
export function valueGuard({ expect, actual, nullable = [] }) {
  if (nullable.length) return null
  const bad = []
  for (const [k, v] of [['expect', expect], ['actual', actual]]) {
    const t = String(v ?? '')
    if (v === undefined || v === null) bad.push(`${k}=${v}`)
    else if (t.includes('undefined') || t.includes('NaN') || t.trim() === '') bad.push(`${k} 含未取值: ${t.slice(0, 80)}`)
  }
  return bad.length ? bad.join('；') : null
}

/** 断言器：pass/fail **都**带「期望来源 + 原始读数」。 */
export function judge(R, { id, name, expect, actual, pass, expectSource, evidence = [], detail, nullable = [] }) {
  const guard = valueGuard({ expect, actual, nullable })
  const d = detail || (pass ? `期望 ${expect} == 实测 ${actual}` : `期望 ${expect} ≠ 实测 ${actual}`)
  const ev = [`期望来源: ${expectSource}`, `期望: ${expect}`, `实得: ${actual}`, ...evidence]
  if (pass && guard) {
    // 判过关但**没取到真值** ⇒ 一律记 fail（判据缺陷），并在读数里写明缺的是哪一项
    return R.fail(id, name, `判据缺陷（未取到真值，不许判 pass）：${guard}`, [...ev, `guard: ${guard}`])
  }
  return pass ? R.pass(id, name, d, ev) : R.fail(id, name, d, ev)
}

// ────────────────────────── HTTP ──────────────────────────
export async function api(method, path, { token, body, headers = {}, timeoutMs = 60000, raw = false } = {}) {
  const h = { ...headers }
  if (!raw) h['Content-Type'] = 'application/json'
  if (token) { h.Cookie = `access_token=${token}`; h.Authorization = `Bearer ${token}` }
  let res
  try {
    res = await fetch(API + path, {
      method, headers: h,
      body: body === undefined ? undefined : (raw ? body : JSON.stringify(body)),
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch (e) {
    return { status: 0, json: null, text: `FETCH_ERROR ${e.name}: ${e.message}`, ok: false, data: null, headers: {} }
  }
  const buf = Buffer.from(await res.arrayBuffer())
  const text = buf.toString('utf8')
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON（xlsx/二进制） */ }
  const hdrs = {}
  res.headers.forEach((v, k) => { hdrs[k] = v })
  return { status: res.status, json, text, ok: res.ok, data: json?.data, buf, headers: hdrs }
}

/** multipart/form-data 上传。files: [{field, filename, content(Buffer|string), type}] */
export async function upload(path, { token, files, fields = {}, method = 'POST', timeoutMs = 120000 }) {
  const fd = new FormData()
  for (const [k, v] of Object.entries(fields)) fd.append(k, v)
  for (const f of files) {
    const content = typeof f.content === 'string' ? Buffer.from(f.content, 'utf8') : f.content
    fd.append(f.field, new Blob([content], { type: f.type || 'application/octet-stream' }), f.filename)
  }
  const h = {}
  if (token) { h.Cookie = `access_token=${token}`; h.Authorization = `Bearer ${token}` }
  let res
  try {
    res = await fetch(API + path, { method, headers: h, body: fd, signal: AbortSignal.timeout(timeoutMs) })
  } catch (e) {
    return { status: 0, json: null, text: `FETCH_ERROR ${e.name}: ${e.message}`, ok: false, data: null }
  }
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON */ }
  return { status: res.status, json, text, ok: res.ok, data: json?.data }
}

/**
 * 管理员登录（短信链）。
 *
 * 🔴 为什么带重试 + 会话缓存：本机 :8080 **曾**以「未注入 `.env`」启动 ⇒ `sms.bypass-code` 为空
 * （主会话 16:15 的环境失误，16:23 已修）。这段重试不是绕过鉴权 —— 它只处理
 * 「60 秒防刷窗口内重登」这一**服务端自己定义**的形态（`SmsService.LIMIT_TTL_SECONDS`），
 * 并把拿到的 token 落到 `out/.session.json`（**只在验收目录**），避免每个分段重复登录。
 */
export async function loginApi(phone = ADMIN_PHONE, code = SMS_CODE) {
  const cache = join(OUT, '.session.json')
  try {
    const c = JSON.parse(readFileSync(cache, 'utf8'))
    if (c?.token) {
      const probe = await api('GET', '/api/auth/me', { token: c.token })
      if (probe.status === 200) return { token: c.token, raw: c.raw, cached: true }
    }
  } catch { /* 无缓存或已失效 ⇒ 重新登录 */ }
  let last = null
  for (let attempt = 0; attempt < 3; attempt++) {
    const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
    last = r
    if (r.json?.success) {
      const d = r.json.data
      const token = d.accessToken ?? d.access_token
      try { writeFileSync(cache, JSON.stringify({ token, raw: d, at: nowCST() }, null, 2)) } catch { /* 非致命 */ }
      return { token, raw: d, cached: false }
    }
    if (attempt < 2) await sleep(20000)
  }
  throw new Error(`登录失败 ${last?.status}: ${String(last?.text).slice(0, 300)}`)
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

export function psql(sql) {
  const c = pgConf()
  const out = execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
     '-c', `select coalesce(json_agg(row_to_json(t))::text,'[]') from (${sql}) t`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
  return JSON.parse(out.trim() || '[]')
}
export const one = (sql) => psql(sql)[0] ?? null

export function guardedWrite(sql) {
  if (!/--\s*probe-ok/.test(sql)) throw new Error(`写 SQL 缺 -- probe-ok 标记: ${sql.slice(0, 120)}`)
  const c = pgConf()
  return execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
}

export function assertProbe(...vals) {
  const s = vals.filter((v) => v !== null && v !== undefined).join(' ')
  if (!s.includes(PROBE_PREFIX)) throw new Error(`拒绝操作非探针对象（缺前缀「${PROBE_PREFIX}」）: ${s}`)
}

/** 内容指纹（红证注入/还原自证 —— 禁用 mtime/size，migao-dev-flow §19.1）。 */
export function sha256(s) {
  return execFileSync('shasum', ['-a', '256'], { input: typeof s === 'string' ? s : s, encoding: 'utf8' }).split(/\s+/)[0]
}

// ────────────────────────── decimal 语义（千分 milli，禁浮点 ==）──────────────────────────
export const SCALE = 1000n
export function cents(v) {
  if (typeof v === 'bigint') return v
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

// ────────────────────────── 字段级前后 diff ──────────────────────────
export function tableSnap(sqlWhitelist) {
  const snap = new Map()
  for (const { table, where, key = 'id' } of sqlWhitelist) {
    const rows = psql(`select * from ${table} where ${where}`)
    for (const r of rows) snap.set(`${table}|${r[key]}`, { table, row: r })
  }
  return snap
}
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
export function overreach(d, allowed) {
  const allow = new Set(allowed)
  return d.filter((x) => !allow.has(`${x.table}.${x.field}`) && !allow.has(`${x.table}.*`) && !allow.has(x.table))
}
export const fmtDiff = (d) => d.map((x) => `${x.table}.${x.field}: ${JSON.stringify(x.before)} → ${JSON.stringify(x.after)} [${x.kind}]`)

// ────────────────────────── 原生 XLSX（写 / 读）──────────────────────────
// 为什么自己写：导入端点吃 `WorkbookFactory.create`（xlsx），而本机 **无 openpyxl**、
// 本包**不装依赖**（最少代码阶梯）。xlsx = ZIP；POI 读 STORE(0) 与 DEFLATE(8) 均可。
function crc32(buf) {
  let c, crc = 0xFFFFFFFF
  for (let i = 0; i < buf.length; i++) {
    c = (crc ^ buf[i]) & 0xFF
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xEDB88320 : c >>> 1
    crc = (crc >>> 8) ^ c
  }
  return (crc ^ 0xFFFFFFFF) >>> 0
}
function zipStore(entries) {
  const locals = [], centrals = []
  let offset = 0
  for (const e of entries) {
    const name = Buffer.from(e.name, 'utf8')
    const data = Buffer.isBuffer(e.data) ? e.data : Buffer.from(e.data, 'utf8')
    const crc = crc32(data)
    const lh = Buffer.alloc(30)
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(0, 6)
    lh.writeUInt16LE(0, 8); lh.writeUInt16LE(0, 10); lh.writeUInt16LE(0, 12)
    lh.writeUInt32LE(crc, 14); lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(data.length, 22)
    lh.writeUInt16LE(name.length, 26); lh.writeUInt16LE(0, 28)
    locals.push(lh, name, data)
    const ch = Buffer.alloc(46)
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6)
    ch.writeUInt16LE(0, 8); ch.writeUInt16LE(0, 10); ch.writeUInt16LE(0, 12); ch.writeUInt16LE(0, 14)
    ch.writeUInt32LE(crc, 16); ch.writeUInt32LE(data.length, 20); ch.writeUInt32LE(data.length, 24)
    ch.writeUInt16LE(name.length, 28); ch.writeUInt32LE(offset, 42)
    centrals.push(ch, name)
    offset += lh.length + name.length + data.length
  }
  const cd = Buffer.concat(centrals)
  const eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(0x06054b50, 0); eocd.writeUInt16LE(entries.length, 8); eocd.writeUInt16LE(entries.length, 10)
  eocd.writeUInt32LE(cd.length, 12); eocd.writeUInt32LE(offset, 16)
  return Buffer.concat([...locals, cd, eocd])
}
/** 读 zip 条目 —— **从 central directory 解**。
 *  🔴 为什么不是自己解 local header：**Apache POI 写的是 streamed zip**（general-purpose flag bit 3
 *  置位 = data descriptor），local file header 里 size 字段**全是 0**，真实长度在 local header 之后的
 *  data descriptor 里 ⇒ 按 local header 解析会读出**空内容**（实测：导出档 5641 字节、9 个条目
 *  全部读成空 ⇒ A5 四条判据**假红** —— 「读器坏了」被读成「导出是空的」）。
 *  真值在 **central directory**（EOCD → 各条目的 offset/size 权威）。也不调系统 `unzip`：
 *  `unzip -Z1 -` 把 `-` 当文件名（实测吐出 usage 帮助文本、被当成条目名 ⇒ 同样假红）。 */
function zipEntries(buf) {
  let eocd = -1
  for (let i = buf.length - 22; i >= 0 && i > buf.length - 66000; i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break }
  }
  if (eocd < 0) return {}
  const count = buf.readUInt16LE(eocd + 10)
  let p = buf.readUInt32LE(eocd + 16)
  const out = {}
  for (let n = 0; n < count && p + 46 <= buf.length; n++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) break
    const method = buf.readUInt16LE(p + 10)
    const csize = buf.readUInt32LE(p + 20)
    const nlen = buf.readUInt16LE(p + 28)
    const elen = buf.readUInt16LE(p + 30)
    const clen = buf.readUInt16LE(p + 32)
    const lho = buf.readUInt32LE(p + 42)
    const name = buf.slice(p + 46, p + 46 + nlen).toString('utf8')
    // local header：从 lho 取纠缠的 name/extra 长度（local 的 name 长度可能与 central 不同）
    const lNlen = buf.readUInt16LE(lho + 26)
    const lElen = buf.readUInt16LE(lho + 28)
    const dataStart = lho + 30 + lNlen + lElen
    const raw = buf.slice(dataStart, dataStart + csize)
    try { out[name] = method === 8 ? inflateRawSync(raw) : raw } catch { out[name] = null }
    p += 46 + nlen + elen + clen
  }
  return out
}
const xmlEsc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const colName = (n) => { let s = ''; n++; while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26) } return s }

/** 写一个最小可用 xlsx。rows: 二维数组，元素 string|number|null。headers 单独传入（可为 null = 无表头行）。 */
export function makeXlsx(headers, rows, sheetName = 'Sheet1') {
  const all = headers ? [headers, ...rows] : rows
  let sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>`
  all.forEach((row, r) => {
    sheet += `<row r="${r + 1}">`
    row.forEach((v, c) => {
      if (v === null || v === undefined || v === '') return
      const ref = `${colName(c)}${r + 1}`
      if (typeof v === 'number') sheet += `<c r="${ref}"><v>${v}</v></c>`
      else sheet += `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlEsc(v)}</t></is></c>`
    })
    sheet += '</row>'
  })
  sheet += '</sheetData></worksheet>'
  const files = [
    { name: '[Content_Types].xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>` },
    { name: '_rels/.rels', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>` },
    { name: 'xl/workbook.xml', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${xmlEsc(sheetName)}" sheetId="1" r:id="rId1"/></sheets></workbook>` },
    { name: 'xl/_rels/workbook.xml.rels', data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>` },
    { name: 'xl/worksheets/sheet1.xml', data: sheet },
  ]
  return zipStore(files)
}

/** 读 xlsx → { headers, rows, grid }（inlineStr + sharedStrings 都支持）。 */
export function readXlsx(buf) {
  const parts = zipEntries(buf)
  const names = Object.keys(parts)
  const shared = []
  if (parts['xl/sharedStrings.xml']) {
    const xml = parts['xl/sharedStrings.xml'].toString('utf8')
    for (const m of xml.matchAll(/<si>([\s\S]*?)<\/si>/g)) {
      shared.push([...m[1].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((x) => x[1]).join(''))
    }
  }
  const sheetName = names.find((k) => /^xl\/worksheets\/sheet\d+\.xml$/.test(k))
  if (!sheetName) return { headers: [], rows: [], grid: [], parts: names, error: '未定位到 worksheet（zip 条目: ' + names.join(',') + '）' }
  const xml = parts[sheetName].toString('utf8')
  const unesc = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&')
  const grid = []
  for (const rm of xml.matchAll(/<row[^>]*r="(\d+)"[^>]*>([\s\S]*?)<\/row>/g)) {
    const rIdx = Number(rm[1]) - 1
    const cells = []
    for (const cm of rm[2].matchAll(/<c r="([A-Z]+)\d+"([^>]*)>([\s\S]*?)<\/c>/g)) {
      const [, colRef, attrs, inner] = cm
      let ci = 0
      for (const ch of colRef) ci = ci * 26 + (ch.charCodeAt(0) - 64)
      ci -= 1
      const t = /t="([^"]+)"/.exec(attrs)?.[1]
      let val = null
      if (t === 'inlineStr') val = unesc([...inner.matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((x) => x[1]).join(''))
      else if (t === 's') { const idx = Number(/<v>([\s\S]*?)<\/v>/.exec(inner)?.[1]); val = shared[idx] ?? null }
      else if (t === 'str') val = unesc([...inner.matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((x) => x[1]).join(''))
      else val = unesc(/<v>([\s\S]*?)<\/v>/.exec(inner)?.[1] ?? '')
      cells[ci] = val
    }
    grid[rIdx] = cells
  }
  const clean = []
  for (let i = 0; i < grid.length; i++) clean[i] = (grid[i] || []).map((v) => (v === undefined ? '' : v))
  return { headers: clean[0] || [], rows: clean.slice(1), grid: clean, parts: names }
}

// ────────────────────────── 探针对象 ──────────────────────────
export const hexId = (prefix, len = 20) => prefix + Array.from({ length: len }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('')
/** 本包探针货号（机器可辨）。 */
export const probeSku = (tag) => `${ID_PREFIX.toUpperCase()}-${tag}-${Date.now().toString(36).toUpperCase()}`
export const idemKey = (tag, n = 0) => `${ID_PREFIX}-${tag}-${Date.now().toString(36)}-${n}`

// ══════════════════════════ 工人身份面（本线新增）══════════════════════════

/** 工人端请求：身份载体 = `X-Worker-Session-Id`（**不是** JWT；见 `WorkerSessionService.SESSION_HEADER`）。 */
export function apiWorker(method, path, { sessionId, tenantId = TENANT_ID, body, headers = {}, timeoutMs = 60000, raw = false } = {}) {
  const h = { ...headers }
  if (sessionId) h[WORKER_HEADER] = sessionId
  if (tenantId != null) h['X-Tenant-Id'] = String(tenantId)
  // raw:true = body 已是 JSON 字符串（**禁止**再 stringify —— 双重编码会让服务端报
  // 'Cannot construct instance ... from String value' ⇒ 400 BAD_REQUEST。实测踩过。）
  return api(method, path, { body, headers: h, timeoutMs, raw })
}

/** 预序列化 JSON body 的工人写调用（大整数 id 不能走 JS Number ⇒ 只能拼串后 raw 发送）。
 *  🔴 必须自带 `Content-Type: application/json`：`api(..., raw:true)` 故意不加该头，
 *  fetch 会默认发 `text/plain` ⇒ 服务端 415 UNSUPPORTED_MEDIA_TYPE（实测踩过两次）。 */
export const rawWorker = (path, sessionId, bodyStr, extraHeaders = {}, tenantId = TENANT_ID) =>
  apiWorker('POST', path, {
    sessionId, tenantId, body: bodyStr, raw: true,
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
  })

/** 工人登录（工号 + PIN）⇒ `{sessionId, workerId, workerName, raw}`。 */
export async function loginWorker(workerNo, pin = PROBE_PIN, tenantId = TENANT_ID, deviceLabel = '线A验收PAD') {
  const r = await api('POST', '/api/worker/login', {
    headers: { 'X-Tenant-Id': String(tenantId) },
    body: { workerNo, pin, deviceLabel, tenantId },
  })
  const d = r.json?.data
  if (!d?.session_id) throw new Error(`工人登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  return { sessionId: d.session_id, workerId: d.worker_id, workerName: d.worker_name, idleMinutes: d.idle_minutes, raw: d }
}

/** 会话缓存与重登（每个分段各自可独立跑：缓存有效则复用，失效则真登录一次）。 */
export function storePath() { return join(OUT, '.store.json') }
export function loadStore() {
  try { return JSON.parse(readFileSync(storePath(), 'utf8')) } catch { return {} }
}
export function saveStore(s) { writeFileSync(storePath(), JSON.stringify(s, null, 2)); return s }

/** 取一个**当前有效**的工人 session（缓存优先 ⇒ 真登录兜底）。 */
export async function ensureWorkerSession(store, tag = 'A', { deviceLabel = '线A验收PAD' } = {}) {
  const key = `worker${tag}`
  const w = store[key]
  if (!w?.workerNo) throw new Error(`store 里没有 worker${tag}（先跑 p1-auth）`)
  if (w.sessionId) {
    const probe = await apiWorker('GET', '/api/worker/me', { sessionId: w.sessionId })
    if (probe.status === 200) return w
  }
  const l = await loginWorker(w.workerNo, w.pin ?? PROBE_PIN, TENANT_ID, deviceLabel)
  w.sessionId = l.sessionId
  w.workerId = l.workerId ?? w.workerId
  w.workerName = l.workerName ?? w.workerName
  saveStore(store)
  return w
}

/** 建一个探针工人（**真实 API**：`POST /api/admin/workers`，权限码 employee:create）。 */
export async function createProbeWorker(token, { name, workerNo, pin = PROBE_PIN } = {}) {
  const suffix = String(Date.now()).slice(-6)
  const body = {
    workerNo: workerNo || `${ID_PREFIX.toUpperCase()}${suffix}`,
    name: name || `${PROBE_PREFIX}工人${suffix}`,
    pin,
  }
  const r = await api('POST', '/api/admin/workers', { token, body })
  if (r.status !== 200) {
    // 🔴 422 的**完整原因**在 error.details[] 里（只打外层会把业务校验当噪声丢掉）
    log(`建探针工人失败 HTTP ${r.status}: ${JSON.stringify(r.json?.error ?? r.text).slice(0, 500)}`)
  }
  return { status: r.status, workerId: r.json?.data?.id ?? null, body, raw: r }
}

/** 探针工人档案查询（**只读**，直接读 DB：验证「API 建行的终态」，不拿 API 读面当期望）。 */
export const probeWorkerRow = (workerId) =>
  one(`select id, worker_no, nickname, role, status, tenant_id, (worker_no is not null) as is_worker, length(password_hash) as hash_len
         from users where id='${workerId}'`)

// ══════════════════════════ 扫码闭环夹具（本线新增）══════════════════════════
//
// 为什么要**自建**（而不是拿存量单报工）：铁律 5/6 —— 存量行零改动 + 与线B 跨包隔离。
// 夹具 = 自建 orders / processing_orders / processing_order_sets / order_items /
//        processing_position_operations / processing_set_part_tokens 六行，全部 `la` 前缀；
//        并**自建 orders 行**（不复用存量订单）⇒ `selectActiveByOrderId` 必命中本夹具那一张
//        （否则同一 order_id 下多张加工单会随机取一张，夹具不可复现）。

/** 从存量数据里挑一个「可参照」的工序实例（**只读**，只取字段形状，不碰该行）。 */
function pickOpTemplate() {
  const rows = psql(`select o.operation_name, o.group_name, o.unit, o.position_name, o.position_kind,
                            o.qty_source, o.unit_price, o.factor,
                            (select i.product_id from order_items i
                              where i.tenant_id=o.tenant_id and i.id=o.order_item_id and i.deleted=0
                              limit 1) as product_id
                       from processing_position_operations o
                      where o.tenant_id=${TENANT_ID} and o.deleted=0 and o.set_id is not null and o.qty>0
                        and o.status='pending' and o.done_qty < o.qty
                      order by o.created_at desc limit 1`)
  if (!rows.length) throw new Error('找不到可参照的工序实例（夹具无法搭建）')
  const t = rows[0]
  // 存量工序实例的 order_item_id 常指不到 order_items 行（实测多行如此）⇒ 模板给不出 product_id。
  // 夹具必须带**真实 product_id**（否则 WorkerCuttingHeightService.brands() 走 Map.of() 分支，
  // 那是另一条缺陷路径，会把别的判据染红）⇒ 兜底取一个本租户真实商品。
  if (!t.product_id) {
    t.product_id = psql(`select id from products where tenant_id=${TENANT_ID} and deleted=0 order by created_at desc limit 1`)[0]?.id ?? null
  }
  return t
}

/** 建一套自建扫码闭环夹具，返回夹具台账。 */
export function buildFixture({ tag = 'A', qty = '12.30', opCount = 1 } = {}) {
  const t = pickOpTemplate()
  const uniq = `${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`
  const raw = `${ID_PREFIX}${uniq}`.padEnd(32, 'f').slice(0, 32)
  const F = {
    tag, qty, uniq,
    orderId: `${ID_PREFIX}ord${uniq}`,
    orderNo: `${ID_PREFIX.toUpperCase()}-ORD-${uniq.toUpperCase()}`,
    poId: `${ID_PREFIX}po${uniq}`,
    poNo: `${ID_PREFIX.toUpperCase()}-JG-${uniq.toUpperCase()}`,
    setId: `${ID_PREFIX}set${uniq}`,
    itemId: `${ID_PREFIX}itm${uniq}`,
    token: raw,
  }
  F.langId = `${ID_PREFIX}lab${uniq}`
  const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)
  w(`insert into orders (id, tenant_id, order_no, customer_name, status, total_amount, is_urgent, remark, created_by_name)
     values ('${F.orderId}', ${TENANT_ID}, '${F.orderNo}', '${PROBE_PREFIX}客户', 'confirmed', 0, false, '${PROBE_PREFIX}扫码闭环夹具', '${PROBE_PREFIX}');`)
  w(`insert into processing_orders (id, tenant_id, order_id, processing_order_no, status, items_snapshot, remark)
     values ('${F.poId}', ${TENANT_ID}, '${F.orderId}', '${F.poNo}', 'generated', '[]'::jsonb, '${PROBE_PREFIX}夹具');`)
  w(`insert into processing_order_sets (id, tenant_id, processing_order_id, set_index, set_no, position_item_ids)
     values ('${F.setId}', ${TENANT_ID}, '${F.poId}', 1, '${F.poNo}-001', '["${F.itemId}"]'::jsonb);`)
  // 🔴 夹具订单行要带**真实的 product_id**：否则 `WorkerCuttingHeightService.brands()` 走 `Map.of()` 分支
  // ⇒ `brands.get(null)` NPE ⇒ 500（那是**产品缺陷**，不该混进「正常夹具」里把别的判据染红）。
  w(`insert into order_items (id, tenant_id, order_id, product_id, product_name, quantity, width, height, craft, curtain_type, processing_info)
     values ('${F.itemId}', ${TENANT_ID}, '${F.orderId}', ${t.product_id ? `'${t.product_id}'` : 'null'}, '${PROBE_PREFIX}布', 1, 3.0, 2.5, '${PROBE_PREFIX}工艺', '布帘',
             '{"componentRole":"主布","panels":2}'::jsonb);`)
  const opIds = []
  for (let i = 0; i < opCount; i++) {
    const opId = opCount === 1 ? `${ID_PREFIX}op${uniq}` : `${ID_PREFIX}op${uniq}_${i}`
    w(`insert into processing_position_operations
         (id, tenant_id, processing_order_id, position_name, position_kind, order_item_id, seq,
          operation_name, group_name, unit, qty, qty_source, unit_price, factor, status, done_qty, set_id, set_no)
       values ('${opId}', ${TENANT_ID}, '${F.poId}', '${t.position_name}', '${t.position_kind}', '${F.itemId}', ${i + 1},
               '${t.operation_name}', ${t.group_name ? `'${t.group_name}'` : 'null'}, ${t.unit ? `'${t.unit}'` : 'null'},
               ${qty}, ${t.qty_source ? `'${t.qty_source}'` : 'null'}, ${t.unit_price ?? 'null'}, ${t.factor ?? 1}, 'pending', 0,
               '${F.setId}', '${F.poNo}-001');`)
    opIds.push(opId)
  }
  F.opIds = opIds
  F.opId = opIds[0]
  w(`insert into processing_set_part_tokens (id, tenant_id, processing_order_id, set_id, order_item_id, position_kind, token)
     values ('${F.langId}', ${TENANT_ID}, '${F.poId}', '${F.setId}', '${F.itemId}', '${t.position_kind}', '${F.token}');`)
  return F
}

/** 按需给夹具注入第二道**同 seq** 工序（红证：`OPERATION_AMBIGUOUS` 必须在**写库之前**拒绝）。 */
export function fixtureDupSeq(F) {
  const t = pickOpTemplate()
  const dup = `${ID_PREFIX}dup${F.tag}${Date.now().toString(36)}`
  guardedWrite(`-- probe-ok
insert into processing_position_operations
  (id, tenant_id, processing_order_id, position_name, position_kind, order_item_id, seq,
   operation_name, group_name, unit, qty, qty_source, unit_price, factor, status, done_qty, set_id, set_no)
values ('${dup}', ${TENANT_ID}, '${F.poId}', '${t.position_name}', '${t.position_kind}', '${F.itemId}', 1,
        '${t.operation_name}（同序）', ${t.group_name ? `'${t.group_name}'` : 'null'}, ${t.unit ? `'${t.unit}'` : 'null'},
        ${F.qty}, ${t.qty_source ? `'${t.qty_source}'` : 'null'}, ${t.unit_price ?? 'null'}, ${t.factor ?? 1}, 'pending', 0,
        '${F.setId}', '${F.poNo}-001');`)
  F.dupOpId = dup
  return dup
}

/** 夹具实测读数（**独立算**：期望值不取自被测读面）。 */
export const fixtureOps = (F) =>
  psql(`select id, seq, status, done_qty::text, qty::text, worker_id, worker_name, position_name,
               (done_at is not null) as has_done_at,
               (started_at is not null) as has_started_at,
               (started_at at time zone 'Asia/Shanghai')::text as started_at_cst,
               (done_at at time zone 'Asia/Shanghai')::text as done_at_cst
          from processing_position_operations
         where tenant_id=${TENANT_ID} and processing_order_id='${F.poId}' and deleted=0
         order by seq, id`)

export const workLogs = (F) =>
  psql(`select id, operation_id, operation_name, worker_id, worker_name, qty::text, qualified_qty::text,
               work_type, unit_price::text, factor::text, work_date::text,
               (created_at at time zone 'Asia/Shanghai')::text as created_at_cst
          from production_work_logs
         where tenant_id=${TENANT_ID} and processing_order_id='${F.poId}' and deleted=0
         order by created_at, id`)

export const reportAudits = (F) =>
  psql(`select id, work_log_id, operation_id, worker_id, worker_name, worker_session_id, identity_source
          from worker_report_audits
         where tenant_id=${TENANT_ID} and processing_order_id='${F.poId}' and deleted=0`)

/** 存量行**零改动**自证：关键表全行 sha256（前后对照；mtime/size 不算数，§19.1）。 */
export const LEDGER_TABLES = [
  'orders', 'processing_orders', 'processing_position_operations', 'processing_set_part_tokens',
  'production_work_logs', 'worker_report_audits', 'users', 'worker_sessions', 'inbound_labels', 'client_request_keys',
]
export function ledgerHash({ excludeProbe = false } = {}) {
  // excludeProbe=true ⇒ **只对存量行**取指纹（把本包 `la` 命名域的行排除在外）。
  // 🔴 为什么必须有这个口径：全表指纹在「清理后」必然变（我自己删掉了探针行）⇒ 那是**预期变化**，
  //    不构成「存量被改」。存量零改动命题 = 排除探针域后逐字节相同（且**逐表行数也要相同**）。
  const parts = []
  for (const t of LEDGER_TABLES) {
    const probeFilter = excludeProbe ? ` and coalesce(id::text,'') not like '${ID_PREFIX}%'` : ''
    const rows = psql(`select md5(string_agg(x, E'\\n' order by x)) as h, count(*)::int as n from
      (select (t.*)::text as x from ${t} t where t.tenant_id=${TENANT_ID}${probeFilter}) t`)
    parts.push(`${t}=${rows[0]?.h ?? 'EMPTY'}#${rows[0]?.n ?? 0}`)
  }
  return { hash: sha256(parts.join('|')), parts, excludeProbe }
}

/** 全库关键表行数（只读；用于「清理前后」对照 —— 不只盯探针域）。 */
export function tableCounts() {
  const q = (sql) => one(sql)?.n ?? null
  return {
    orders: q(`select count(*)::int n from orders where tenant_id=${TENANT_ID}`),
    processingOrders: q(`select count(*)::int n from processing_orders where tenant_id=${TENANT_ID}`),
    positionOps: q(`select count(*)::int n from processing_position_operations where tenant_id=${TENANT_ID}`),
    partTokens: q(`select count(*)::int n from processing_set_part_tokens where tenant_id=${TENANT_ID}`),
    workLogs: q(`select count(*)::int n from production_work_logs where tenant_id=${TENANT_ID}`),
    users: q(`select count(*)::int n from users where tenant_id=${TENANT_ID}`),
    inboundOrders: q(`select count(*)::int n from inbound_orders where tenant_id=${TENANT_ID}`),
    inboundLabels: q(`select count(*)::int n from inbound_labels where tenant_id=${TENANT_ID}`),
  }
}

/** 幂等键行（`client_request_keys.response_payload` 快照 = 「同键回放」的物证）。 */
export const idemRow = (key) =>
  one(`select tenant_id, client_request_id, endpoint, (response_payload is not null) as has_snapshot,
               (created_at at time zone 'Asia/Shanghai')::text as created_at_cst
          from client_request_keys where tenant_id=${TENANT_ID} and client_request_id='${key}'`)

/** 清掉单个夹具（**逐表硬删**，顺序 = FK 顺序）。 */
export function cleanupFixture(F) {
  const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)
  const po = `'${F.poId}'`
  w(`delete from worker_report_audits where tenant_id=${TENANT_ID} and processing_order_id=${po};`)
  w(`delete from production_work_logs where tenant_id=${TENANT_ID} and processing_order_id=${po};`)
  w(`delete from processing_position_operations where tenant_id=${TENANT_ID} and processing_order_id=${po};`)
  w(`delete from processing_set_part_tokens where processing_order_id=${po};`)
  w(`delete from processing_order_sets where processing_order_id=${po};`)
  w(`delete from order_items where tenant_id=${TENANT_ID} and order_id='${F.orderId}';`)
  w(`delete from processing_orders where tenant_id=${TENANT_ID} and id=${po};`)
  w(`delete from orders where tenant_id=${TENANT_ID} and id='${F.orderId}';`)
}

// ══════════════════════════ 探针残留（工人面版）══════════════════════════

/** 本包探针对象在全库的存活计数（**只读**；机器读数，终态必须 total=0）。 */
export function probeResidue() {
  const q = psql
  const counts = {
    probeUsers: q(`select id from users where tenant_id=${TENANT_ID} and (id like '${ID_PREFIX}%' or worker_no like '${ID_PREFIX.toUpperCase()}%')`).length,
    probeSessions: q(`select id from worker_sessions where tenant_id=${TENANT_ID} and (worker_id like '${ID_PREFIX}%' or worker_no like '${ID_PREFIX.toUpperCase()}%')`).length,
    probeOrders: q(`select id from orders where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    probeProcessingOrders: q(`select id from processing_orders where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    probeSets: q(`select id from processing_order_sets where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    probeItems: q(`select id from order_items where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    probePositionOps: q(`select id from processing_position_operations where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    probePartTokens: q(`select id from processing_set_part_tokens where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    probeWorkLogs: q(`select id from production_work_logs where tenant_id=${TENANT_ID} and processing_order_id like '${ID_PREFIX}%'`).length,
    probeAudits: q(`select id from worker_report_audits where tenant_id=${TENANT_ID} and processing_order_id like '${ID_PREFIX}%'`).length,
    probeIdemKeys: q(`select id from client_request_keys where tenant_id=${TENANT_ID} and client_request_id like '${ID_PREFIX}-%'`).length,
    probeInboundItems: q(`select id from inbound_order_items where tenant_id=${TENANT_ID} and inbound_order_id like '${ID_PREFIX}%'`).length,
    probeInboundLabels: q(`select id from inbound_labels where tenant_id=${TENANT_ID} and inbound_order_id like '${ID_PREFIX}%'`).length,
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  return { counts, total }
}

/** 清掉本包**全部**探针数据（硬删，**仅**本包命名域；子行先删，FK 顺序即安全顺序）。 */
export function cleanupProbe() {
  const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)
  const probePo = `select id from processing_orders where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`
  const probeOrder = `select id from orders where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`
  const probeInbound = `select id from inbound_orders where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`
  w(`delete from inbound_labels where inbound_order_id in (${probeInbound});`)
  w(`delete from inbound_order_items where inbound_order_id in (${probeInbound});`)
  w(`delete from inbound_orders where id in (${probeInbound});`)
  w(`delete from worker_report_audits where tenant_id=${TENANT_ID} and processing_order_id in (${probePo});`)
  w(`delete from production_work_logs where tenant_id=${TENANT_ID} and processing_order_id in (${probePo});`)
  w(`delete from processing_position_operations where tenant_id=${TENANT_ID} and processing_order_id in (${probePo});`)
  w(`delete from processing_set_part_tokens where processing_order_id in (${probePo});`)
  w(`delete from processing_order_sets where processing_order_id in (${probePo});`)
  w(`delete from order_items where order_id in (${probeOrder});`)
  w(`delete from processing_orders where id in (${probePo});`)
  w(`delete from orders where id in (${probeOrder});`)
  w(`delete from worker_sessions where tenant_id=${TENANT_ID} and (worker_id like '${ID_PREFIX}%' or worker_no like '${ID_PREFIX.toUpperCase()}%');`)
  w(`delete from users where tenant_id=${TENANT_ID} and (id like '${ID_PREFIX}%' or worker_no like '${ID_PREFIX.toUpperCase()}%');`)
  w(`delete from client_request_keys where tenant_id=${TENANT_ID} and client_request_id like '${ID_PREFIX}-%';`)
}

export { writeFileSync, readFileSync, existsSync, mkdirSync, deflateRawSync, inflateRawSync }
export const outPath = (f) => join(OUT, f)
