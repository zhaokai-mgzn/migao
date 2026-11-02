// 加工派单 + 工序设置/路线 全覆盖验收 —— 共享库
//
// 证据纪律（migao-acceptance）：每条记录必须带可复核的证据引用
// （API 请求 + HTTP 读数 + SQL 原文），禁止只写「正常/符合预期」。
import { appendFileSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))

export const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
export const API = process.env.API_BASE || 'http://localhost:8080'
export const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
export const SMS_CODE = process.env.SMS_CODE || '123456'

mkdirSync(OUT, { recursive: true })

export function log(msg) {
  const line = `${new Date().toISOString()} ${msg}`
  console.log(line)
  appendFileSync(join(OUT, 'run.log'), line + '\n')
}

export function sha(ref = 'HEAD') {
  try {
    return execFileSync('git', ['-C', REPO_ROOT, 'rev-parse', '--short', ref], { encoding: 'utf8' }).trim()
  } catch { return 'unknown' }
}

// ────────────────────────── 证据记录 ──────────────────────────
export class Recorder {
  constructor(file) {
    this.file = file
    this.records = []
  }
  add(id, name, status, detail, evidence = []) {
    const rec = { id, name, status, detail, evidence, at: new Date().toISOString() }
    this.records.push(rec)
    const icon = status === 'pass' ? '✅' : status === 'fail' ? '❌' : '⏭️'
    log(`${icon} [${id}] ${name} — ${detail}`)
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

// ────────────────────────── HTTP ──────────────────────────
export async function api(method, path, { token, body, headers = {} } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers }
  if (token) { h.Cookie = `access_token=${token}`; h.Authorization = `Bearer ${token}` }
  const res = await fetch(API + path, {
    method, headers: h,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON */ }
  return { status: res.status, json, text, ok: res.ok }
}

export async function loginApi(phone, code = SMS_CODE) {
  const r = await api('POST', '/api/auth/sms/login', { body: { phone, code } })
  if (!r.json?.success) throw new Error(`登录失败 ${r.status}: ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { token: d.accessToken ?? d.access_token, raw: d }
}

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

/** 写 SQL（仅验收自建数据的清理 / 断言前后的定点定值）。 */
export function psqlWrite(sql) {
  const c = pgConf()
  return execFileSync('psql',
    ['-h', c.host, '-p', c.port, '-U', c.user, '-d', c.db, '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
    { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export async function waitService(tries = 20) {
  for (let i = 0; i < tries; i++) {
    try { const r = await api('GET', '/actuator/health'); if (r.status < 500) return true } catch { /* retry */ }
    await sleep(1500)
  }
  return false
}
