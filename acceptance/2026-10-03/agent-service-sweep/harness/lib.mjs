// 线① AI Agent 服务域 —— 独立验证包共享库（2026-10-03）
//
// 证据纪律（migao-acceptance）：
//  ① 每条判定带「期望来源」——期望由本包独立算出/由契约声明，禁止拿被测系统自己的读面当期望；
//  ② 写 SQL 必须带 `-- probe-ok`；探针命名域统一前缀 `线①验收`；
//  ③ 时间一律 +08；原始 UTC 读数同时标注换算；
//  ④ 只动自己前缀的对象；既有行改动逐条还原。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || '/Users/guangzhen.zk/ai native/migao'
/** 被测 ai-agent-service（本线自起，干净 origin/main 检出） */
export const AGENT = process.env.AGENT_BASE || 'http://127.0.0.1:8001'
/** 被测 admin-api（已在跑的 main-live 构建） */
export const ADMIN = process.env.ADMIN_BASE || 'http://127.0.0.1:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
export const TENANT_A = Number(process.env.TENANT_A || 20)
export const TENANT_B = Number(process.env.TENANT_B || 21)
export const ADMIN_PHONE = process.env.ADMIN_PHONE || '13870217889'
export const LIVE_WORKTREE = process.env.LIVE_WORKTREE || '/Users/guangzhen.zk/migao-wt/main-live'
/** 本线自起的干净检出（构建点自证对象） */
export const AGENT_WORKTREE = process.env.AGENT_WORKTREE || '/Users/guangzhen.zk/migao-wt/line1-agent'

/** 服务令牌（与 admin-api 的 SERVICE_TOKEN_SECRET 实测一致；取自 ai-agent-service/.env） */
export function serviceToken() {
  const env = readFileSync(join(AGENT_WORKTREE, 'backend/ai-agent-service/.env'), 'utf8')
  const m = env.match(/^SERVICE_TOKEN=(.*)$/m)
  if (!m) throw new Error('SERVICE_TOKEN 未在 .env 中找到')
  return m[1].trim().replace(/^"|"$/g, '')
}

/** 探针命名域：本包创建的一切对象都带这个前缀。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '线①验收'
export const PROBE_USER = (tag) => `probe_line1_${tag}`

mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${nowCST().cst} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

// ────────────────────────── 时间（+08 口径）──────────────────────────
/** ⚠️ 时区口径：一律用 **Asia/Shanghai 具名时区**格式化（本机 TZ=CST 但 Node 的 getTimezoneOffset 读数
 *  曾在本会话把 13:42 输出成 "21:42 +08" —— 双偏移的根源是"本地 getter + 手工偏移"混用。
 *  ⇒ 单一事实源 = Intl 具名时区，禁止再手工加减偏移。`utc` 字段始终可信。 */
const cstFmt = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})
export function nowCST() {
  const d = new Date()
  return { cst: `${cstFmt.format(d).replace('T', ' ')} +08`, utc: d.toISOString() }
}

/** 原始时间戳 → 标注 +08 换算的读数（RDS 给 +08、API JSON 给 Z）。 */
export function tsBoth(v) {
  if (v == null) return null
  const s = String(v)
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return { raw: s, note: '非时间戳' }
  const hasOffset = /[+-]\d{2}(?::?\d{2})?$/.test(s) && !s.endsWith('Z')
  let plus08
  if (hasOffset) {
    plus08 = s.replace('T', ' ').slice(0, 19) + ' (原文已带 +08 偏移，未再换算)'
  } else {
    const l = new Date(d.getTime() + 8 * 3600 * 1000)
    plus08 = l.toISOString().replace('T', ' ').slice(0, 19) + ' +08（由 UTC 换算）'
  }
  return { raw: s, plus08 }
}

// ────────────────────────── 构建点自证 ──────────────────────────
function git(worktree, args) {
  try { return execFileSync('git', ['-C', worktree, ...args], { encoding: 'utf8' }).trim() } catch { return 'unknown' }
}
export function buildPoint(worktree = AGENT_WORKTREE, port = 8001) {
  let procStart = 'unknown'
  try {
    const pid = execFileSync('bash', ['-lc', `lsof -nP -iTCP:${port} -sTCP:LISTEN -t 2>/dev/null | head -1`], { encoding: 'utf8' }).trim()
    if (pid) procStart = execFileSync('bash', ['-lc', `ps -o lstart= -p ${pid}`], { encoding: 'utf8' }).trim()
  } catch { /* 非致命 */ }
  return {
    worktree, port,
    sha: git(worktree, ['rev-parse', '--short', 'HEAD']),
    shaFull: git(worktree, ['rev-parse', 'HEAD']),
    subject: git(worktree, ['log', '-1', '--format=%s']),
    commitTime: git(worktree, ['log', '-1', '--format=%cI']),
    dirty: git(worktree, ['status', '--porcelain']),
    procStart,
    observedAt: nowCST().cst,
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
  dump() { writeFileSync(join(OUT, this.file), JSON.stringify(this.records, null, 2)) }
  summary() {
    const c = (s) => this.records.filter((r) => r.status === s).length
    return { file: this.file, pass: c('pass'), fail: c('fail'), skip: c('skip'), total: this.records.length }
  }
}

/** 断言器：pass/fail 都带「期望来源 + 原始读数」。 */
export function judge(R, { id, name, expect, actual, pass, expectSource, evidence = [], detail }) {
  const d = detail || (pass ? `期望 ${expect} == 实测 ${actual}` : `期望 ${expect} ≠ 实测 ${actual}`)
  const ev = [`期望来源: ${expectSource}`, `HTTP/读数: ${JSON.stringify(actual)}`, ...evidence]
  return pass ? R.pass(id, name, d, ev) : R.fail(id, name, d, ev)
}

// ────────────────────────── HTTP ──────────────────────────
async function http(base, method, path, { token, body, headers = {}, timeoutMs = 60000, cookieAuth = true } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers }
  if (token) {
    h.Authorization = `Bearer ${token}`
    if (cookieAuth) h.Cookie = `access_token=${token}`
  }
  let res
  try {
    res = await fetch(base + path, {
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

/** 打 ai-agent-service(:8001) */
export const agentApi = (method, path, opts) => http(AGENT, method, path, opts)
/** 打 admin-api(:8080) */
export const adminApi = (method, path, opts) => http(ADMIN, method, path, opts)

/** 内部服务调用：X-Service-Token + X-Tenant-Id */
export const internalCall = (method, path, { tenantId, body, headers = {}, token } = {}) =>
  agentApi(method, path, {
    token,
    body,
    headers: { 'X-Service-Token': token || serviceToken(), ...(tenantId != null ? { 'X-Tenant-Id': String(tenantId) } : {}), ...headers },
  })

export async function adminLogin(phone = ADMIN_PHONE, code = SMS_CODE) {
  const r = await adminApi('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`admin 登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, raw: d }
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ────────────────────────── JWT 铸造（RS256，与 .env 公钥同对）──────────────────────────
/** 用 ~/migao-keys/jwt-private.pem 签一枚 JWT（与 ai-agent-service 的 JWT_PUBLIC_KEY 配对）。
 *  实现走 `mint_jwt.py`（PyJWT）—— 唯一事实源，见该文件 docstring（Node 侧手工 openssl 拼签名实测假红）。 */
export function mintJwt({ userId, tenantId, role = 'admin', permissions = ['*'], identityType = 'account', ttlSec = 3600, aud = 'migao', keyFile = process.env.JWT_PRIVATE_KEY || `${process.env.HOME}/migao-keys/jwt-private.pem`, overrideClaims = null }) {
  const now = Math.floor(Date.now() / 1000)
  const payload = overrideClaims || {
    userId, tenantId, identityType, role, permissions, aud, iat: now, exp: now + ttlSec,
  }
  const py = process.env.PYTHON_BIN || join(AGENT_WORKTREE, 'backend/ai-agent-service/.venv/bin/python')
  return execFileSync(py, [join(HERE, 'mint_jwt.py'), keyFile], { input: JSON.stringify(payload), encoding: 'utf8' }).trim()
}

/** 已过期 JWT（exp 在过去、iat 更早）——用于「过期 token 必须拒」的正向夹具。 */
export function mintExpiredJwt(opts = {}) {
  const now = Math.floor(Date.now() / 1000)
  return mintJwt({ ...opts, overrideClaims: {
    userId: opts.userId || 'probe_expired', tenantId: opts.tenantId ?? TENANT_A, identityType: 'account',
    role: 'admin', permissions: ['*'], aud: 'migao', iat: now - 7200, exp: now - 3600,
  } })
}

/** 用「另一把」RSA 私钥签的 JWT（签名错）——期望拒。私钥现场生成、不落盘（`-` ⇒ 生成态）。 */
export function mintForeignSignedJwt(opts = {}) {
  const now = Math.floor(Date.now() / 1000)
  return mintJwt({ ...opts, keyFile: '-', overrideClaims: {
    userId: 'probe_line1_foreign', tenantId: TENANT_A, identityType: 'account', role: 'admin',
    permissions: ['*'], aud: 'migao', iat: now, exp: now + 3600,
  } })
}

// ────────────────────────── DB（psql 直连云 dev 库）──────────────────────────
let _pgConf = null
function pgConf() {
  if (_pgConf) return _pgConf
  const envFile = readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
  const get = (k) => (envFile.match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
  _pgConf = { host: get('RDS_HOST'), port: get('RDS_PORT'), user: get('RDS_USER'), db: get('RDS_DB'), password: get('RDS_PASSWORD') }
  if (!_pgConf.host) throw new Error('admin-api/.env 缺 RDS_HOST')
  return _pgConf
}

/** 只读 SQL：包成一行 json_agg ⇒ 输出即对象数组。 */
export function psql(sql) {
  const c = pgConf()
  const out = execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
     '-c', `select coalesce(json_agg(row_to_json(t))::text,'[]') from (${sql}) t`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
  return JSON.parse(out.trim() || '[]')
}
export const one = (sql) => psql(sql)[0] ?? null

/** 写 SQL 守卫：语句必须显式带 `-- probe-ok`。 */
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
  if (!s.includes(PROBE_PREFIX)) throw new Error(`拒绝操作非探针对象（缺前缀「${PROBE_PREFIX}」）: ${s}`)
}

/** 行内容指纹（写前/写后自证用）。 */
export function sha256(s) {
  return execFileSync('bash', ['-lc', `printf '%s' "$0" | shasum -a 256 | cut -d' ' -f1`, String(s)], { encoding: 'utf8' }).trim()
}
export function fileSha256(p) {
  try { return execFileSync('bash', ['-lc', `shasum -a 256 "${p}" | cut -d' ' -f1`], { encoding: 'utf8' }).trim() } catch { return 'unknown' }
}

/** 会话探针：探针命名域内的会话 id 前缀（机器可判）。 */
export const probeSessionId = (tag) => `l1probe-${tag}-${Date.now().toString(36)}`

/** 本包探针对象的存活计数（只读、机器读数）。 */
export function probeResidue() {
  const sid = `select id from sessions where customer_id like 'probe_line1_%'`
  const aid = `select id from agent_sessions where customer_id like 'probe_line1_%'`
  const counts = {
    sessions: psql(`${sid}`).length,
    sessionMessages: psql(`select id from session_messages where session_id in (${sid})`).length,
    agentSessions: psql(`${aid}`).length,
    knowledgeCards: psql(`select id from knowledge_cards where title like '${PROBE_PREFIX}%'`).length,
    knowledgeCandidates: psql(`select id from knowledge_candidates where suggested_title like '${PROBE_PREFIX}%'`).length,
  }
  return { counts, total: Object.values(counts).reduce((a, b) => a + b, 0) }
}
