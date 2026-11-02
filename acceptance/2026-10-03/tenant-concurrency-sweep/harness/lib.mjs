// 线④ 并发 × 跨租户串号 + ai-agent-service(:8001) 租户链路 —— 共享库
// 证据纪律（migao-acceptance）：每条记录带可复核证据（请求 + HTTP 读数 + SQL 原文）。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const API = process.env.API_BASE || 'http://localhost:8080'
export const AGENT = process.env.AGENT_BASE || 'http://localhost:8001'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'
mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${new Date().toISOString()} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

export class Recorder {
  constructor(file) { this.file = file; this.records = [] }
  add(id, name, status, detail, evidence = []) {
    const rec = { id, name, status, detail, evidence, at: new Date().toISOString() }
    this.records.push(rec)
    const icon = status === 'pass' ? '✅' : status === 'fail' ? '❌' : '⏭️'
    log(`${icon} [${id}] ${name} — ${detail}`)
    this.dump(); return rec
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

const envFile = () => readFileSync(join(REPO_ROOT, 'backend/admin-api/.env'), 'utf8')
const envGet = (k) => (envFile().match(new RegExp(`^${k}=(.*)$`, 'm')) || [])[1]
export const SERVICE_TOKEN = envGet('SERVICE_TOKEN_SECRET')

export async function api(method, path, { token, body, headers = {}, base = API, raw = false, timeoutMs = 30000 } = {}) {
  const h = { ...headers }
  if (!raw) h['Content-Type'] = 'application/json'
  if (token) { h.Cookie = `access_token=${token}`; h.Authorization = `Bearer ${token}` }
  const ac = new AbortController()
  const t = setTimeout(() => ac.abort(), timeoutMs)
  const t0 = Date.now()
  try {
    const res = await fetch(base + path, { method, headers: h, body: body === undefined ? undefined : (raw ? body : JSON.stringify(body)), signal: ac.signal })
    const text = await res.text()
    let json = null
    try { json = JSON.parse(text) } catch { /* 非 JSON */ }
    return { status: res.status, json, text, ok: res.ok, ms: Date.now() - t0 }
  } catch (e) {
    return { status: 0, json: null, text: `NETERR:${e.name}:${e.message}`, ok: false, ms: Date.now() - t0 }
  } finally { clearTimeout(t) }
}

export async function loginApi(phone, code = SMS_CODE) {
  const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`登录失败 ${phone} ${r.status}: ${r.text.slice(0, 200)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, user: d.user, raw: d }
}

// ── DB（只读 psql 直连云 dev RDS）──
let _pg = null
function pgConf() {
  if (_pg) return _pg
  _pg = { host: envGet('RDS_HOST'), port: envGet('RDS_PORT'), user: envGet('RDS_USER'), db: envGet('RDS_DB'), password: envGet('RDS_PASSWORD') }
  return _pg
}
export function psql(sql) {
  const c = pgConf()
  const out = execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1',
      '-c', `select coalesce(json_agg(row_to_json(t))::text,'[]') from (${sql}) t`],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  return JSON.parse(out.trim() || '[]')
}
export const one = (sql) => psql(sql)[0] ?? null
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ── 本地伪造 JWT（仅用 admin-api/.env 里的 JWT_PRIVATE_KEY 自签，用于「租户链」判据的可判别夹具）──
// 纪律：不落盘、不外发、只打本机 :8001/:8080；断言里必须与「真 token」正对照。
import { createSign } from 'node:crypto'
export function forgeJwt(claims = {}, ttlSec = 3600) {
  const pem = (envGet('JWT_PRIVATE_KEY') || '').replace(/\\n/g, '\n')
  if (!pem.includes('BEGIN')) throw new Error('JWT_PRIVATE_KEY 不可用 ⇒ 无法伪造夹具')
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url')
  const now = Math.floor(Date.now() / 1000)
  const payload = { aud: ['migao'], tokenType: 'access', iat: now, exp: now + ttlSec, jti: `probe-${now}-${Math.random().toString(36).slice(2, 8)}`, ...claims }
  const head = b64({ alg: 'RS256' })
  const body = b64(payload)
  const signer = createSign('RSA-SHA256')
  signer.update(`${head}.${body}`)
  return `${head}.${body}.${signer.sign(pem).toString('base64url')}`
}
