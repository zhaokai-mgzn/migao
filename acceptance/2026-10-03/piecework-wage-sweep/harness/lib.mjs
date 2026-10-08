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

// ────────────── 本轮（计件工资链）新增：decimal 语义 / 探针守卫 / 断言 ──────────────

/** 探针前缀（本轮全部自建对象的唯一命名域；绝不触碰他人创建的行）。 */
export const PROBE_PREFIX = process.env.PROBE_PREFIX || '工资验收'

/**
 * 金额/数量一律走 BigInt 分表示 —— 严禁浮点 `==`。
 * 接受 JSON 里的 number / string（"0.40" / "0.2" / "0.00"）与 null。
 * @returns {bigint|null} 以「分」为单位的整数（保留两位小数语义）
 */
export function cents(v) {
  if (v === null || v === undefined || v === '') return null
  const s = String(v).trim()
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(s)
  if (!m) throw new Error(`非十进制金额读数: ${JSON.stringify(v)}`)
  const sign = m[1] === '-' ? -1n : 1n
  const int = BigInt(m[2])
  const frac = (m[3] || '').padEnd(2, '0').slice(0, 2)
  return sign * (int * 100n + BigInt(frac))
}

/** 分 → 两位小数字符串（40n → "0.40"）。 */
export function fmt(c) {
  if (c === null || c === undefined) return 'null'
  const sign = c < 0n ? '-' : ''
  const a = c < 0n ? -c : c
  return `${sign}${a / 100n}.${String(a % 100n).padStart(2, '0')}`
}

/** decimal 语义相等（兼容 "0.2" ≡ "0.20" ≡ 0.2）。 */
export function moneyEq(a, b) { return cents(a) === cents(b) }

/** 独立性守卫：任何写/改操作前，目标必须命中探针命名域。 */
export function assertProbe(...vals) {
  const s = vals.filter((v) => v !== null && v !== undefined).join(' ')
  if (!s.includes(PROBE_PREFIX)) {
    throw new Error(`拒绝操作非探针对象（缺前缀「${PROBE_PREFIX}」）: ${s}`)
  }
}

/** 写 SQL 守卫：语句必须显式带 `-- probe-ok` 注释（人工审查痕迹），否则抛错。 */
export function guardedWrite(sql) {
  if (!/--\s*probe-ok/.test(sql)) throw new Error(`写 SQL 缺 -- probe-ok 标记: ${sql.slice(0, 120)}`)
  return psqlWrite(sql)
}

/**
 * 断言器：pass/fail 都带**期望来源**与**原始读数**（migao-acceptance：判定必须引证据）。
 * expectSource = 期望是怎么算出来的（禁止写「系统自己给的读数」）。
 */
export function judge(R, { id, name, expect, actual, pass, expectSource, evidence = [], detail }) {
  const d = detail || (pass ? `期望 ${expect} == 实测 ${actual}` : `期望 ${expect} ≠ 实测 ${actual}`)
  return pass
    ? R.pass(id, name, d, [`期望来源: ${expectSource}`, ...evidence])
    : R.fail(id, name, d, [`期望来源: ${expectSource}`, ...evidence])
}
