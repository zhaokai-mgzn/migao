// 线② 破坏性写面 + 并发/幂等 —— 共享库（2026-10-03）
//
// 复用自 shipments-sweep/harness/lib.mjs（只读参考），补三件本线特有的事：
//   ① multipart 上传（`api()` 只发 JSON，本线 6 个上传端点全是 multipart）
//   ② 原生 XLSX 读/写（导入端点只吃 Excel —— `WorkbookFactory.create`；本机无 openpyxl / 不装依赖）
//   ③ 探针命名域 + 逐表残留计数（本线创建 商品/工序/文件 三类对象）
//
// 证据纪律（migao-acceptance）：
//   ① 期望一律本包独立算出（DB 读数 / 端点契约原文），**严禁**拿被测系统自己的读面当期望；
//   ② 写 SQL 必须带 `-- probe-ok`；探针命名域统一 `线②验收`；
//   ③ 时间一律 +08 口径；JSON 里 UTC 与 +08 同时留。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync, readdirSync, statSync } from 'node:fs'
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

/** 探针命名域：本包创建的一切对象都带此前缀（中文名域）+ `l2` 机器前缀（id 域）。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '线②验收'
/** 探针 id 的机器可判前缀：所有本包自建行 id 以 `l2` 开头（绝不碰别人的行）。 */
export const ID_PREFIX = 'l2'
export const IDEM_HEADER = 'X-Client-Request-Id'

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

/** 断言器：pass/fail **都**带「期望来源 + 原始读数」。 */
export function judge(R, { id, name, expect, actual, pass, expectSource, evidence = [], detail }) {
  const d = detail || (pass ? `期望 ${expect} == 实测 ${actual}` : `期望 ${expect} ≠ 实测 ${actual}`)
  const ev = [`期望来源: ${expectSource}`, `期望: ${expect}`, `实得: ${actual}`, ...evidence]
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

export async function loginApi(phone = ADMIN_PHONE, code = SMS_CODE) {
  const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, raw: d }
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
/** 本包探针货号（导入幂等键 = (tenant, 货号)，全库唯一 —— 必须机器可辨）。 */
export const probeSku = (tag) => `${ID_PREFIX.toUpperCase()}-${tag}-${Date.now().toString(36).toUpperCase()}`

/** 建一个探针商品（走**真实 API**，不用 SQL —— 测的是写面本身）。 */
export async function createProduct(token, { name, skuCode, price = 10, stock = 5, status, colors } = {}) {
  const body = {
    name: name || `${PROBE_PREFIX}商品${Date.now().toString().slice(-6)}`,
    skuCode: skuCode || probeSku('P'),
    basePrice: price, price, stock,
    unit: '米', pricingType: 'per_meter',
    description: `${PROBE_PREFIX}（线②销毁性写面探针，用后自清）`,
    colors: colors || [],
  }
  if (status) body.status = status
  const r = await api('POST', '/api/admin/products', { token, body })
  return r
}
export async function deleteProductSoft(token, id) {
  return api('DELETE', `/api/admin/products/${id}`, { token })
}

/** 本包探针对象在全库的存活计数（**只读**；机器读数）。 */
export function probeResidue() {
  const q = psql
  const counts = {
    products: q(`select id from products where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    productsByName: q(`select id from products where tenant_id=${TENANT_ID} and name like '${PROBE_PREFIX}%'`).length,
    productSkus: q(`select id from product_skus where tenant_id=${TENANT_ID} and product_id like '${ID_PREFIX}%'`).length,
    productColors: q(`select id from product_colors where tenant_id=${TENANT_ID} and product_id like '${ID_PREFIX}%'`).length,
    productAttrs: q(`select id from product_attributes where tenant_id=${TENANT_ID} and product_id like '${ID_PREFIX}%'`).length,
    operations: q(`select id from production_operations where tenant_id=${TENANT_ID} and id like '${ID_PREFIX}%'`).length,
    // ⚠️ 该表**无** operation_id 列（按 logical_name 寻址）—— 实测列名（首轮此处报错被误当 dangling）
    opPositions: q(`select id from production_operation_positions where tenant_id=${TENANT_ID} and logical_name like '${PROBE_PREFIX}%'`).length,
    opPositionsByName: q(`select id from production_operation_positions where tenant_id=${TENANT_ID} and logical_name like '${PROBE_PREFIX}%'`).length,
    opPriceVersions: q(`select id from production_operation_price_versions where tenant_id=${TENANT_ID} and operation_id like '${ID_PREFIX}%'`).length,
    routeTemplates: q(`select id from production_route_templates where tenant_id=${TENANT_ID} and name like '${PROBE_PREFIX}%'`).length,
    routeRules: q(`select id from production_route_rules where tenant_id=${TENANT_ID} and operation like '${PROBE_PREFIX}%'`).length,
    ledger: q(`select id from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no like '${ID_PREFIX}%'`).length,
    ledgerByProduct: q(`select id from stock_ledger_entries where tenant_id=${TENANT_ID} and product_id like '${ID_PREFIX}%'`).length,
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  return { counts, total }
}

/** 本包探针**商品**的判定域：id `l2%` ∪ name `${PROBE_PREFIX}%` ∪ sku_code `L2-%`。
 *  🔴 API 建的商品 id 是**随机 32 位 hex**（没有 l2 前缀）⇒ 只按 id 前缀清会漏（实测：清理由此失败，
 *  并被 `stock_ledger_entries_product_id_fkey` 当场拦下 —— 那是**清理器**的缺陷，不是产品缺陷）。 */
const PRODUCT_SCOPE = `select id from products where tenant_id=${'${T}'} and (id like '${ID_PREFIX}%' or name like '${PROBE_PREFIX}%' or sku_code like '${ID_PREFIX.toUpperCase()}-%')`

/** 清掉本包全部探针数据（硬删，**仅**本包命名域；子行先删，FK 顺序即安全顺序）。 */
export function cleanupProbe() {
  const T = TENANT_ID
  const w = (sql) => guardedWrite(`-- probe-ok\n${sql}`)
  const scope = `select id from products where tenant_id=${T} and (id like '${ID_PREFIX}%' or name like '${PROBE_PREFIX}%' or sku_code like '${ID_PREFIX.toUpperCase()}-%')`
  const opScope = `select id from production_operations where tenant_id=${T} and (id like '${ID_PREFIX}%' or name like '${PROBE_PREFIX}%')`
  w(`delete from stock_batch_consumptions where product_id in (${scope});`)
  w(`delete from stock_batches where product_id in (${scope});`)
  w(`delete from stock_ledger_entries where product_id in (${scope}) or (tenant_id=${T} and ref_no like '${ID_PREFIX}%');`)
  w(`delete from fabric_remnants where product_id in (${scope});`)
  w(`delete from inbound_order_items where product_id in (${scope});`)
  w(`delete from product_skus where product_id in (${scope});`)
  w(`delete from product_colors where product_id in (${scope});`)
  w(`delete from product_attributes where product_id in (${scope});`)
  w(`delete from products where id in (${scope});`)
  // ⚠️ production_operation_positions **没有** operation_id 列（按 logical_name 寻址）—— 实测列名
  w(`delete from production_operation_positions where tenant_id=${T} and logical_name like '${PROBE_PREFIX}%';`)
  w(`delete from production_operation_price_versions where operation_id in (${opScope});`)
  w(`delete from production_operations where id in (${opScope});`)
  w(`delete from production_route_rules where tenant_id=${T} and (operation like '${PROBE_PREFIX}%' or after_operation like '${PROBE_PREFIX}%');`)
  w(`delete from production_route_templates where tenant_id=${T} and name like '${PROBE_PREFIX}%';`)
}
export const idemKey = (tag, n = 0) => `${ID_PREFIX}-${tag}-${Date.now().toString(36)}-${n}`

/** 本地落盘目录（LocalFileStorageService 的 uploads/）—— 用于「不落盘」判据。
 *  ⚠️ 探针**不写**这里；只读列举 + 内容指纹比对。 */
export function uploadsDir(worktree = LIVE_WORKTREE) {
  const candidates = [
    join(worktree, 'backend/admin-api/uploads'),
    join(REPO_ROOT, 'backend/admin-api/uploads'),
  ]
  for (const c of candidates) { try { if (statSync(c).isDirectory()) return c } catch { /* 不存在 */ } }
  return null
}
export function listFilesRec(dir, rel = '') {
  const out = []
  let ents = []
  try { ents = readdirSync(dir, { withFileTypes: true }) } catch { return out }
  for (const e of ents) {
    const p = join(dir, e.name)
    const r = rel ? `${rel}/${e.name}` : e.name
    if (e.isDirectory()) out.push(...listFilesRec(p, r))
    else out.push({ rel: r, path: p, size: statSync(p).size })
  }
  return out
}

export { writeFileSync, readFileSync, deflateRawSync, inflateRawSync }
export const outPath = (f) => join(OUT, f)
